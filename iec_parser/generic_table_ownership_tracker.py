"""Persistent deterministic ownership state for document tables."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class TableOwnershipState:
    """Immutable snapshot of the currently open table, if any."""

    active: bool = False
    source_table_id: Optional[str] = None
    internal_ownership_id: Optional[str] = None
    table_title: Optional[str] = None
    start_page: Optional[int] = None
    current_page: Optional[int] = None
    last_table_block_type: Optional[str] = None
    recent_column_pattern: Optional[Tuple[str, ...]] = None
    repeated_header_signature: Optional[str] = None
    continuation_confidence: float = 0.0
    rows_seen: int = 0
    interruption_count: int = 0
    start_source_order: Optional[int] = None
    last_source_order: Optional[int] = None
    anchor_clause_id: Optional[str] = None


@dataclass(frozen=True)
class TableOwnershipDecision:
    """Ownership result for one classified source block."""

    table_owned: bool
    source_table_id: Optional[str]
    internal_ownership_id: Optional[str]
    continuation_confidence: float
    reasons: Tuple[str, ...]
    state: TableOwnershipState


class GenericTableOwnershipTracker:
    """Track table ownership across pages and harmless layout interruptions."""

    _CONTINUED = re.compile(
        r"\b(?:continued|continuation|concluded|cont\.?)(?:\s|\)|$)", re.IGNORECASE
    )
    _TOKEN = re.compile(r"[A-Za-z]+|\d+(?:[.,]\d+)?|[%°µΩ]+")

    def __init__(self) -> None:
        self._state = TableOwnershipState()
        self._sequence = 0
        self._history: Dict[str, TableOwnershipState] = {}

    @property
    def state(self) -> TableOwnershipState:
        """Return the current immutable state snapshot."""

        return self._state

    def open_table(
        self,
        *,
        source_table_id: Optional[str],
        table_title: Optional[str],
        page: int,
        source_order: int,
        anchor_clause_id: Optional[str],
        raw_label: str,
    ) -> TableOwnershipDecision:
        """Open a new source table or continue a repeated label for the open table."""

        normalized_id = source_table_id.upper() if source_table_id else None
        same_source = bool(
            self._state.active
            and normalized_id
            and normalized_id == self._state.source_table_id
        )
        continued_label = bool(self._CONTINUED.search(raw_label))
        historical = self._history.get(normalized_id or "")
        if same_source:
            self._state = replace(
                self._state,
                current_page=page,
                last_table_block_type="TABLE_TITLE",
                continuation_confidence=1.0,
                last_source_order=source_order,
            )
            reasons = (
                "explicit continued-table label"
                if continued_label else "repeated source table label",
                "source table identifier matches",
            )
        elif continued_label and historical is not None:
            self._state = replace(
                historical,
                active=True,
                current_page=page,
                last_table_block_type="TABLE_TITLE",
                continuation_confidence=1.0,
                last_source_order=source_order,
            )
            reasons = (
                "explicit continued-table label resumes prior ownership",
                "source table identifier matches prior ownership",
            )
        else:
            self._sequence += 1
            internal = f"TABLE_OWNERSHIP_{self._sequence}"
            self._state = TableOwnershipState(
                active=True,
                source_table_id=normalized_id,
                internal_ownership_id=internal,
                table_title=table_title,
                start_page=page,
                current_page=page,
                last_table_block_type="TABLE_TITLE",
                continuation_confidence=1.0,
                start_source_order=source_order,
                last_source_order=source_order,
                anchor_clause_id=anchor_clause_id,
            )
            reasons = (
                "recognized table title starts ownership",
                "new table replaces prior ownership" if same_source is False else "new table context",
            )
        if normalized_id:
            self._history[normalized_id] = self._state
        return self._decision(True, reasons)

    def own_block(
        self,
        *,
        block_type: str,
        raw_text: str,
        page: int,
        source_order: int,
        row_candidate: bool = False,
        header_candidate: bool = False,
        layout_interruption: bool = False,
    ) -> TableOwnershipDecision:
        """Attach a compatible block to the open table without page-based expiry."""

        if not self._state.active:
            return self._decision(False, ("no active table ownership",))
        page_transition = page != self._state.current_page
        signature = self.header_signature(raw_text) if header_candidate else None
        repeated = bool(
            signature
            and self._state.repeated_header_signature
            and signature == self._state.repeated_header_signature
        )
        rows = self._state.rows_seen + (1 if row_candidate else 0)
        interruptions = self._state.interruption_count + (1 if layout_interruption else 0)
        confidence = 0.72
        reasons = ["active table ownership persists"]
        if page_transition:
            reasons.append("page transition does not terminate table")
            confidence += 0.06
        if repeated:
            reasons.append("repeated table-header signature")
            confidence = max(confidence, 0.96)
        elif header_candidate:
            reasons.append("compatible table header")
            confidence = max(confidence, 0.9)
        if row_candidate:
            reasons.append("compatible row or cell shape")
            confidence = max(confidence, 0.9)
        if layout_interruption:
            reasons.append("layout header/footer interruption retained")
            confidence = max(confidence, 0.78)
        if block_type == "TABLE_CONTINUATION":
            reasons.append("wrapped or sparse continuation text")
        pattern = self.column_pattern(raw_text) if row_candidate or header_candidate else self._state.recent_column_pattern
        self._state = replace(
            self._state,
            current_page=page,
            last_table_block_type=block_type,
            recent_column_pattern=pattern,
            repeated_header_signature=signature or self._state.repeated_header_signature,
            continuation_confidence=min(confidence, 1.0),
            rows_seen=rows,
            interruption_count=interruptions,
            last_source_order=source_order,
        )
        if self._state.source_table_id:
            self._history[self._state.source_table_id] = self._state
        return self._decision(True, tuple(reasons))

    def close(self, *, reason: str) -> TableOwnershipDecision:
        """Close ownership only for an independently supported transition."""

        prior = self._state
        if prior.source_table_id:
            self._history[prior.source_table_id] = prior
        self._state = TableOwnershipState()
        return TableOwnershipDecision(
            table_owned=False,
            source_table_id=prior.source_table_id,
            internal_ownership_id=prior.internal_ownership_id,
            continuation_confidence=1.0,
            reasons=(reason,),
            state=self._state,
        )

    def unowned(self, *, reason: str) -> TableOwnershipDecision:
        """Return a public non-owning decision without mutating state."""

        return self._decision(False, (reason,))

    def _decision(
        self, table_owned: bool, reasons: Tuple[str, ...]
    ) -> TableOwnershipDecision:
        return TableOwnershipDecision(
            table_owned=table_owned,
            source_table_id=self._state.source_table_id,
            internal_ownership_id=self._state.internal_ownership_id,
            continuation_confidence=self._state.continuation_confidence,
            reasons=reasons,
            state=self._state,
        )

    @classmethod
    def header_signature(cls, value: str) -> Optional[str]:
        """Return a stable generic signature for a possible repeated header."""

        tokens = [token.casefold() for token in cls._TOKEN.findall(value)]
        alphabetic = [token for token in tokens if token.isalpha()]
        return "|".join(alphabetic) if len(alphabetic) >= 2 else None

    @classmethod
    def column_pattern(cls, value: str) -> Tuple[str, ...]:
        """Return a coarse non-semantic token-shape pattern for continuation checks."""

        pattern = []
        for token in cls._TOKEN.findall(value):
            if re.fullmatch(r"\d+(?:[.,]\d+)?", token):
                kind = "NUMBER"
            elif token.isalpha():
                kind = "TEXT"
            else:
                kind = "SYMBOL"
            if not pattern or pattern[-1] != kind:
                pattern.append(kind)
        return tuple(pattern[:8])
