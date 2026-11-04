"""Deterministic, context-aware classification of document text blocks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence, Tuple

from iec_parser.generic_table_ownership_tracker import (
    GenericTableOwnershipTracker,
)


class DocumentBlockType(str, Enum):
    """Semantic ownership classes used before structural object creation."""

    CLAUSE_HEADING = "CLAUSE_HEADING"
    ANNEX_HEADING = "ANNEX_HEADING"
    DEFINITION_ENTRY = "DEFINITION_ENTRY"
    TABLE_TITLE = "TABLE_TITLE"
    TABLE_HEADER = "TABLE_HEADER"
    TABLE_ROW = "TABLE_ROW"
    TABLE_CONTINUATION = "TABLE_CONTINUATION"
    LIST_ITEM = "LIST_ITEM"
    NOTE = "NOTE"
    PARAGRAPH = "PARAGRAPH"
    HEADER_FOOTER = "HEADER_FOOTER"
    SECTION_HEADING = "SECTION_HEADING"
    FIGURE_TITLE = "FIGURE_TITLE"
    FORMULA = "FORMULA"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SourceTextBlock:
    """One source-preserving line supplied to the block classifier."""

    raw_text: str
    page: int
    source_order: int


@dataclass(frozen=True)
class ClassifiedDocumentBlock:
    """A source block plus deterministic classification evidence."""

    raw_text: str
    normalized_text: str
    page: int
    source_order: int
    candidate_numeric_identifier: Optional[str]
    block_type: DocumentBlockType
    confidence: float
    reasons: Tuple[str, ...] = field(default_factory=tuple)
    table_context_active: bool = False
    owning_table_id: Optional[str] = None
    table_row_candidate: bool = False
    table_header_candidate: bool = False
    structural_heading_candidate: bool = False
    internal_table_ownership_id: Optional[str] = None
    ownership_confidence: float = 0.0
    ownership_reasons: Tuple[str, ...] = field(default_factory=tuple)
    owning_table_anchor_id: Optional[str] = None


class GenericDocumentBlockClassifier:
    """Classify ordered document lines using structural and neighboring context."""

    _CLAUSE = re.compile(
        r"^(?P<id>(?:[A-Z]{1,3}\.)?\d+(?:\.\d+)*)"
        r"(?:\s+(?P<title>\S.*))?$",
        re.IGNORECASE,
    )
    _TABLE = re.compile(
        r"^Table\s+(?P<id>(?:[A-Z]{1,3}\.)?\d+)"
        r"(?:\s*(?:[-:–—]\s*|[a-z]\s*[-:–—]\s*|"
        r"\((?:continued|continuation|concluded|cont\.?)\)\s*)"
        r"(?P<title>.*))?$",
        re.IGNORECASE,
    )
    _ANNEX = re.compile(
        r"^Annex\s+(?P<id>[A-Z]{1,3})(?:\s*[-:–—].*)?$", re.IGNORECASE
    )
    _FIGURE = re.compile(r"^Figure\s+(?:[A-Z]{1,3}\.)?\d+\b", re.IGNORECASE)
    _NOTE = re.compile(r"^NOTE(?:\s+\d+)?(?:\s|$)", re.IGNORECASE)
    _LIST = re.compile(r"^(?:[-–—•]|\([a-z0-9]+\)|[a-z]\))\s+", re.IGNORECASE)
    _PAGE_CHROME = re.compile(
        r"^(?:Page\s+\d+(?:\s+of\s+\d+)?|[-–—]\s*\d+\s*[-–—])$",
        re.IGNORECASE,
    )
    _UNIT_CELL = re.compile(
        r"^(?:[<>≤≥=±~]?\s*)?\d+(?:[.,]\d+)?\s*"
        r"(?:%|°?C|K|V|A|W|Hz|mm|cm|m|kg|g|N|Pa|h|s|Nm|MΩ)\b",
        re.IGNORECASE,
    )
    _UNIT_ONLY = re.compile(
        r"^(?:%|°?C|K|V|A|W|Hz|mm|cm|m|kg|g|N|Pa|h|s|Nm|MΩ)\s*[;,.]?$",
        re.IGNORECASE,
    )
    _UNIT_LEADING_TEXT = re.compile(
        r"^(?:V|W|Hz|mm|cm|m|kg|g|J|N|Pa|K|C|°C|IRHD|%)"
        r"(?:\b|\s|[,;:])",
        re.IGNORECASE,
    )
    _COLUMN_WORDS = {
        "item", "no", "number", "code", "type", "value", "values", "unit",
        "characteristic", "subclause", "requirement", "test", "result", "remark",
        "verdict", "description", "parameter", "condition", "minimum", "maximum",
    }
    _BODY_GRAMMAR = re.compile(
        r"\b(?:shall|must|should|is|are|may|can|will|has|have|compliance|"
        r"when|where|if|for|the|this|these|those)\b",
        re.IGNORECASE,
    )
    _DEFINITION_GRAMMAR = re.compile(
        r"\b(?:term|definition|means|defined\s+as|for\s+the\s+purposes?\s+of)\b",
        re.IGNORECASE,
    )

    def classify(
        self, blocks: Sequence[SourceTextBlock]
    ) -> List[ClassifiedDocumentBlock]:
        """Classify all blocks while retaining table ownership state."""

        normalized = [self._normalize(block.raw_text) for block in blocks]
        output: List[ClassifiedDocumentBlock] = []
        ownership = GenericTableOwnershipTracker()
        known_clause_ids: set[str] = set()
        last_top_level: Optional[int] = None
        definition_context = False
        most_recent_clause_id: Optional[str] = None
        table_anchor_clause_id: Optional[str] = None

        for index, block in enumerate(blocks):
            text = normalized[index]
            previous = self._neighbor(normalized, index, -1)
            following = self._neighbor(normalized, index, 1)
            following_second = self._neighbor(normalized, index, 2)
            table = self._TABLE.fullmatch(text)
            candidate = self._CLAUSE.fullmatch(text)
            candidate_id = candidate.group("id") if candidate else None
            title = (candidate.group("title") or "").strip() if candidate else ""
            reasons: List[str] = []
            block_type = DocumentBlockType.UNKNOWN
            confidence = 0.25
            table_was_active = ownership.state.active
            active_table_id = ownership.state.source_table_id
            structural_heading = False
            table_row = False
            table_header = False

            if not text:
                block_type = DocumentBlockType.UNKNOWN
                confidence = 1.0
                reasons.append("empty source block")
            elif table:
                block_type = DocumentBlockType.TABLE_TITLE
                confidence = 1.0
                reasons.append("recognized table title grammar")
                ownership_decision = ownership.open_table(
                    source_table_id=table.group("id"),
                    table_title=(table.group("title") or "").strip() or None,
                    page=block.page,
                    source_order=block.source_order,
                    anchor_clause_id=most_recent_clause_id,
                    raw_label=text,
                )
                table_anchor_clause_id = ownership.state.anchor_clause_id
                active_table_id = ownership.state.source_table_id
            elif annex_match := self._ANNEX.fullmatch(text):
                ownership_decision = ownership.close(reason="annex heading terminates table ownership")
                active_table_id = None
                most_recent_clause_id = annex_match.group("id").upper()
                definition_context = False
                block_type = DocumentBlockType.ANNEX_HEADING
                confidence = 1.0
                structural_heading = True
                reasons.append("recognized annex heading grammar")
            elif self._FIGURE.match(text):
                block_type = DocumentBlockType.FIGURE_TITLE
                confidence = 0.98
                reasons.append("recognized figure title grammar")
            elif self._NOTE.match(text):
                block_type = DocumentBlockType.NOTE
                confidence = 0.98
                reasons.append("recognized note grammar")
            elif self._LIST.match(text):
                block_type = DocumentBlockType.LIST_ITEM
                confidence = 0.9
                reasons.append("recognized list-item grammar")
            elif self._PAGE_CHROME.fullmatch(text):
                block_type = DocumentBlockType.HEADER_FOOTER
                confidence = 0.95
                reasons.append("recognized page chrome")
            elif active_table_id and self._looks_like_table_header(text):
                block_type = DocumentBlockType.TABLE_HEADER
                confidence = 0.9
                table_header = True
                reasons.append("column-label vocabulary inside active table")
            elif candidate:
                table_anchor_clause_id = ownership.state.anchor_clause_id
                level = candidate_id.count(".") + 1
                next_body = following_second if not title else following
                definition_candidate = bool(
                    level > 1
                    and definition_context
                    and self._looks_like_definition(title or following, next_body)
                )
                structural_following = next_body if not title else following
                following_match = self._CLAUSE.fullmatch(structural_following)
                following_section_sequence = self._section_sequence_support(
                    normalized, index, candidate_id
                )
                following_prose_sequence = self._prose_sequence_support(
                    normalized, index
                )
                next_structural_transition = bool(
                    self._ANNEX.fullmatch(structural_following)
                    or (
                        level == 1
                        and following_match
                        and (
                            (
                                "." not in following_match.group("id")
                                and int(following_match.group("id")) == int(candidate_id) + 1
                            )
                            or (
                                following_match.group("id").startswith(candidate_id + ".")
                                and following_section_sequence
                            )
                        )
                    )
                )
                positive_heading = self._positive_heading_evidence(
                    candidate_id=candidate_id,
                    title=title or following,
                    level=level,
                    known_clause_ids=known_clause_ids,
                    last_top_level=last_top_level,
                    following_text=next_body,
                    split_line=not bool(title),
                    require_strong_evidence=active_table_id is not None,
                    definition_candidate=definition_candidate,
                    next_structural_transition=next_structural_transition,
                    table_anchor_clause_id=table_anchor_clause_id,
                    following_section_sequence=following_section_sequence,
                    following_prose_sequence=following_prose_sequence,
                )
                if active_table_id and not positive_heading:
                    block_type = DocumentBlockType.TABLE_ROW
                    confidence = 0.92
                    table_row = True
                    reasons.extend((
                        "numeric identifier occurs inside active table",
                        "insufficient independent heading evidence",
                    ))
                elif positive_heading:
                    ownership_decision = ownership.close(
                        reason="strong independent clause heading terminates table ownership"
                    )
                    active_table_id = None
                    structural_heading = True
                    block_type = (
                        DocumentBlockType.DEFINITION_ENTRY
                        if definition_candidate
                        else DocumentBlockType.CLAUSE_HEADING
                    )
                    confidence = 0.9 if table_was_active else 0.96
                    reasons.extend(positive_heading)
                    known_clause_ids.add(candidate_id)
                    if level == 1:
                        number = int(candidate_id)
                        if last_top_level is None or number == last_top_level + 1:
                            last_top_level = number
                            most_recent_clause_id = candidate_id
                        definition_context = bool(re.search(
                            r"\b(?:terms?(?:\s+and\s+definitions?)?|definitions?)\b",
                            title or following,
                            re.IGNORECASE,
                        ))
                    else:
                        most_recent_clause_id = candidate_id
                elif active_table_id:
                    block_type = DocumentBlockType.TABLE_ROW
                    confidence = 0.9
                    table_row = True
                    reasons.append("clause-shaped value retained by table ownership")
                else:
                    block_type = DocumentBlockType.UNKNOWN
                    confidence = 0.55
                    reasons.append("numeric candidate lacks positive structural evidence")
            elif active_table_id and (self._UNIT_CELL.match(text) or self._row_shape(text, previous, following)):
                block_type = DocumentBlockType.TABLE_ROW
                confidence = 0.85
                table_row = True
                reasons.append("cell-like content inside active table")
            elif active_table_id:
                block_type = DocumentBlockType.TABLE_CONTINUATION
                confidence = 0.7
                reasons.append("source remains owned by active table")
            elif self._UNIT_CELL.match(text):
                block_type = DocumentBlockType.UNKNOWN
                confidence = 0.8
                reasons.append("standalone unit-bearing value")
            else:
                block_type = DocumentBlockType.PARAGRAPH
                confidence = 0.7
                reasons.append("prose without structural heading evidence")

            if "ownership_decision" not in locals():
                if ownership.state.active and block_type is not DocumentBlockType.TABLE_TITLE:
                    ownership_decision = ownership.own_block(
                        block_type=block_type.value,
                        raw_text=text,
                        page=block.page,
                        source_order=block.source_order,
                        row_candidate=table_row,
                        header_candidate=table_header,
                        layout_interruption=block_type is DocumentBlockType.HEADER_FOOTER,
                    )
                else:
                    ownership_decision = ownership.unowned(reason="block is not table-owned")

            output.append(ClassifiedDocumentBlock(
                raw_text=block.raw_text,
                normalized_text=text,
                page=block.page,
                source_order=block.source_order,
                candidate_numeric_identifier=candidate_id,
                block_type=block_type,
                confidence=confidence,
                reasons=tuple(reasons),
                table_context_active=table_was_active or table is not None,
                owning_table_id=(
                    ownership_decision.source_table_id
                    if ownership_decision.table_owned else None
                ),
                table_row_candidate=table_row,
                table_header_candidate=table_header,
                structural_heading_candidate=structural_heading,
                internal_table_ownership_id=(
                    ownership_decision.internal_ownership_id
                    if ownership_decision.table_owned else None
                ),
                ownership_confidence=ownership_decision.continuation_confidence,
                ownership_reasons=ownership_decision.reasons,
                owning_table_anchor_id=(
                    ownership_decision.state.anchor_clause_id
                    if ownership_decision.table_owned else None
                ),
            ))
            del ownership_decision
        return output

    def _positive_heading_evidence(
        self,
        *,
        candidate_id: str,
        title: str,
        level: int,
        known_clause_ids: set[str],
        last_top_level: Optional[int],
        following_text: str,
        split_line: bool,
        require_strong_evidence: bool,
        definition_candidate: bool,
        next_structural_transition: bool,
        table_anchor_clause_id: Optional[str],
        following_section_sequence: bool,
        following_prose_sequence: bool,
    ) -> List[str]:
        reasons: List[str] = []
        clean_title = self._normalize(title)
        wrapped_lowercase = bool(
            split_line and self._looks_like_body(following_text)
            and re.search(r"[a-z]", clean_title)
        )
        if not self._heading_like_title(clean_title) and not definition_candidate and not wrapped_lowercase:
            return reasons
        if level == 1:
            number = int(candidate_id)
            if last_top_level is None or number == last_top_level + 1:
                reasons.append("top-level hierarchy continuity")
        else:
            components = candidate_id.split(".")
            if any(".".join(components[:size]) in known_clause_ids for size in range(len(components) - 1, 0, -1)):
                reasons.append("existing ancestor supports hierarchy")
            elif not known_clause_ids:
                reasons.append("self-contained nested heading sequence")
        if self._looks_like_body(following_text):
            reasons.append("following prose supports section transition")
        title_words = len(re.findall(r"[A-Za-z]+", clean_title))
        top_continuous = "top-level hierarchy continuity" in reasons
        if not split_line and (
            not require_strong_evidence
            or level > 1 or top_continuous or last_top_level is None
            or (title_words >= 2 and self._looks_like_body(following_text))
        ):
            reasons.append("inline heading title")
        if split_line and (
            self._heading_like_title(clean_title) or definition_candidate or wrapped_lowercase
        ):
            reasons.append("split-line heading title")
        if re.search(r"\b(?:shall|must|is\s+required\s+to|are\s+required\s+to)\b", clean_title, re.IGNORECASE):
            reasons.append("normative heading text")
        if re.search(
            r"\bthis\s+(?:subclause|clause|section)\s+is\s+"
            r"(?:not\s+)?(?:applicable|void)\b",
            clean_title,
            re.IGNORECASE,
        ):
            reasons.append("structural status declaration")
        # Within a table, hierarchy alone is insufficient: require prose after
        # the heading or a substantial inline title plus a continuous parent.
        if definition_candidate:
            reasons.append("definition grammar in definition context")
        if next_structural_transition:
            reasons.append("following structural transition supports heading")
        if not require_strong_evidence and reasons:
            return reasons
        if require_strong_evidence:
            transition = (
                "following prose supports section transition" in reasons
                or "following structural transition supports heading" in reasons
                or "normative heading text" in reasons
                or "structural status declaration" in reasons
                or following_section_sequence
                or following_prose_sequence
            )
            if level == 1:
                if (
                    transition
                    and table_anchor_clause_id is not None
                    and "top-level hierarchy continuity" in reasons
                ):
                    return reasons
            elif table_anchor_clause_id:
                candidate_parts = candidate_id.split(".")
                anchor_parts = table_anchor_clause_id.split(".")
                same_lineage = candidate_parts[0] == anchor_parts[0]
                forward = self._identifier_order(candidate_parts) > self._identifier_order(anchor_parts)
                if transition and same_lineage and forward:
                    reasons.append("table-anchor lineage continuity")
                    return reasons
        return []

    @classmethod
    def _heading_like_title(cls, text: str) -> bool:
        if not text or len(text) > 240 or re.search(r"\.{2,}", text):
            return False
        if (
            cls._UNIT_CELL.match(text)
            or cls._UNIT_ONLY.fullmatch(text)
            or cls._UNIT_LEADING_TEXT.match(text)
            or re.fullmatch(r"\d+(?:[.,/]\d+)*", text)
        ):
            return False
        first_alpha = next((char for char in text if char.isalpha()), "")
        return bool(first_alpha and first_alpha.isupper())

    @classmethod
    def _looks_like_body(cls, text: str) -> bool:
        value = cls._normalize(text)
        return bool(
            len(value) >= 18
            and (cls._BODY_GRAMMAR.search(value) or re.search(r"[.;:]$", value))
            and not cls._looks_like_table_header(value)
        )

    @classmethod
    def _looks_like_definition(cls, title: str, following: str) -> bool:
        return bool(cls._DEFINITION_GRAMMAR.search(f"{title} {following}"))

    @classmethod
    def _looks_like_table_header(cls, text: str) -> bool:
        words = {word.casefold() for word in re.findall(r"[A-Za-z]+", text)}
        return bool(
            len(text) <= 120
            and not re.search(
                r"\b(?:shall|must|should|may|can|will|has|have|is|are|was|were)\b",
                text,
                re.IGNORECASE,
            )
            and len(words & cls._COLUMN_WORDS) >= 2
        )

    @classmethod
    def _row_shape(cls, text: str, previous: str, following: str) -> bool:
        compact = len(text) <= 80
        neighboring_cells = bool(
            cls._UNIT_CELL.match(previous) or cls._UNIT_CELL.match(following)
            or re.fullmatch(r"[A-Z0-9./()[\]-]{1,18}", previous)
            or re.fullmatch(r"[A-Z0-9./()[\]-]{1,18}", following)
        )
        return compact and neighboring_cells

    @classmethod
    def _section_sequence_support(
        cls, values: Sequence[str], index: int, candidate_id: str
    ) -> bool:
        """Find a short nested-heading sequence followed by normative prose."""

        nested_seen = False
        for value in [item for item in values[index + 1:index + 14] if item]:
            match = cls._CLAUSE.fullmatch(value)
            if match and match.group("id").startswith(candidate_id + "."):
                nested_seen = True
                continue
            if nested_seen and cls._looks_like_body(value):
                return True
            if nested_seen and match and not match.group("id").startswith(candidate_id + "."):
                return False
        return False

    @classmethod
    def _prose_sequence_support(cls, values: Sequence[str], index: int) -> bool:
        """Find nearby wrapped normative prose before another structural candidate."""

        fragments: List[str] = []
        for value in [item for item in values[index + 1:index + 12] if item]:
            if cls._TABLE.fullmatch(value) or cls._ANNEX.fullmatch(value):
                return False
            if cls._CLAUSE.fullmatch(value):
                return False
            fragments.append(value)
            combined = " ".join(fragments)
            if re.search(
                r"\b(?:shall|must|is\s+required\s+to|are\s+required\s+to)\b",
                combined,
                re.IGNORECASE,
            ):
                return True
        return False

    @staticmethod
    def _neighbor(values: Sequence[str], index: int, direction: int) -> str:
        cursor = index + direction
        inspected = 0
        while 0 <= cursor < len(values) and inspected < 4:
            if values[cursor]:
                return values[cursor]
            cursor += direction
            inspected += 1
        return ""

    @staticmethod
    def _normalize(text: str) -> str:
        value = text.translate(str.maketrans({"–": "-", "—": "-", "−": "-"}))
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _identifier_order(parts: Sequence[str]) -> Tuple[Tuple[int, object], ...]:
        """Return a deterministic order key for numeric or annex-prefixed IDs."""

        return tuple(
            (0, int(part)) if part.isdigit() else (1, part.casefold())
            for part in parts
        )
