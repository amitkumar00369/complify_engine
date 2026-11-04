"""Conservative source-supported recovery of missing structural parents."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ParentRecoveryEvidence:
    """Auditable evidence used to recover one hierarchy-only container."""

    parent_id: str
    child_ids: Tuple[str, ...]
    evidence_types: Tuple[str, ...]
    source_page: int
    source_order: int
    semantic_context: str


class GenericStructuralParentResolver:
    """Recover only parents supported by source context and hierarchy evidence."""

    _DEFINITION_GRAMMAR = re.compile(
        r"\b(?:terms?(?:\s+and\s+definitions?)?|definitions?)\b", re.IGNORECASE
    )

    def __init__(self) -> None:
        self.recovery_evidence: Tuple[ParentRecoveryEvidence, ...] = ()

    def resolve(self, blocks: Sequence[Any]) -> List[Any]:
        """Return validated blocks with conservative recovered containers inserted."""

        if blocks is None or isinstance(blocks, (str, bytes)):
            raise TypeError("blocks must be a sequence of structural blocks")
        ordered = sorted(list(blocks), key=lambda item: item.source_order)
        self._validate_unique_ids(ordered)
        self._validate_acyclic(ordered)

        existing = {block.block_id: block for block in ordered}
        hierarchy = [
            block for block in ordered
            if block.block_type in {"CLAUSE", "SUBCLAUSE", "DEFINITION_SECTION", "ANNEX"}
        ]
        candidates: Dict[str, List[Any]] = {}
        for child in hierarchy:
            parent_id = self._immediate_parent_id(child.block_id)
            if parent_id and parent_id not in existing:
                candidates.setdefault(parent_id, []).append(child)

        recovered: List[Any] = []
        evidence_items: List[ParentRecoveryEvidence] = []
        for parent_id, children in sorted(
            candidates.items(), key=lambda item: min(child.source_order for child in item[1])
        ):
            evidence = self._recovery_evidence(parent_id, children, ordered, existing)
            if evidence is None:
                continue
            first = min(children, key=lambda item: item.source_order)
            parent_parent = self._nearest_existing_parent(parent_id, existing)
            recovered.append(first.__class__(
                block_type=("CLAUSE" if "." not in parent_id else "SUBCLAUSE"),
                block_id=parent_id,
                title=None,
                level=parent_id.count(".") + 1,
                parent_id=parent_parent,
                page_start=evidence.source_page,
                page_end=evidence.source_page,
                raw_text="",
                source_order=evidence.source_order,
                semantic_context=evidence.semantic_context,
                structural_origin="RECOVERED_FROM_SOURCE_HIERARCHY",
                source_supported=True,
                normative_text_fabricated=False,
                recovery_evidence=evidence.evidence_types,
            ))
            evidence_items.append(evidence)
            existing[parent_id] = recovered[-1]

        recovered_ids = {block.block_id for block in recovered}
        reparented = [
            replace(block, parent_id=self._immediate_parent_id(block.block_id))
            if (
                block.block_type in {"CLAUSE", "SUBCLAUSE", "DEFINITION_SECTION"}
                and self._immediate_parent_id(block.block_id) in recovered_ids
            )
            else block
            for block in ordered
        ]
        combined = reparented + recovered
        combined.sort(key=lambda item: (
            item.source_order,
            0 if item.structural_origin == "RECOVERED_FROM_SOURCE_HIERARCHY" else 1,
            item.level,
            item.block_id,
        ))
        # Source order is a stable sequence, not a copied child ordinal.
        combined = [replace(block, source_order=index) for index, block in enumerate(combined)]
        self.recovery_evidence = tuple(evidence_items)
        self._validate_unique_ids(combined)
        self._validate_acyclic(combined)
        return combined

    def _recovery_evidence(
        self,
        parent_id: str,
        children: Sequence[Any],
        ordered: Sequence[Any],
        existing: Dict[str, Any],
    ) -> Optional[ParentRecoveryEvidence]:
        children = sorted(children, key=lambda item: item.source_order)
        first = children[0]
        evidence: List[str] = []
        if self._explicit_heading_in_source(parent_id, ordered, first.source_order):
            evidence.append("EXPLICIT_PARENT_HEADING_IN_SOURCE")

        consecutive = len(children) >= 2 and all(
            right.source_order - left.source_order <= 2
            for left, right in zip(children, children[1:])
        )
        ancestor = self._nearest_existing_parent(parent_id, existing)
        definition_context = all(child.semantic_context == "DEFINITION" for child in children)
        definition_grammar = any(
            self._DEFINITION_GRAMMAR.search(child.title or "") for child in children
        )
        if consecutive and ancestor:
            evidence.append("MULTIPLE_CONSECUTIVE_CHILDREN_WITH_EXISTING_ANCESTOR")
        if consecutive and definition_context and definition_grammar:
            evidence.append("DEFINITION_SECTION_GRAMMAR_AND_CONSECUTIVE_CHILDREN")
        if consecutive and "." not in parent_id and self._bounded_by_top_level(parent_id, children, ordered):
            evidence.append("SOURCE_ORDERED_TOP_LEVEL_BOUNDARY")

        if not evidence:
            return None
        contexts = {child.semantic_context for child in children}
        if len(contexts) != 1:
            return None
        return ParentRecoveryEvidence(
            parent_id=parent_id,
            child_ids=tuple(child.block_id for child in children),
            evidence_types=tuple(evidence),
            source_page=first.page_start,
            source_order=first.source_order,
            semantic_context=first.semantic_context,
        )

    @staticmethod
    def _explicit_heading_in_source(
        parent_id: str, ordered: Sequence[Any], child_order: int
    ) -> bool:
        pattern = re.compile(
            rf"(?m)^\s*{re.escape(parent_id)}(?:\s+[A-Za-z][^\n]*)?\s*$"
        )
        nearby = [
            block.raw_text for block in ordered
            if abs(block.source_order - child_order) <= 2 and block.raw_text
        ]
        return bool(pattern.search("\n".join(nearby)))

    @staticmethod
    def _bounded_by_top_level(
        parent_id: str, children: Sequence[Any], ordered: Sequence[Any]
    ) -> bool:
        if not parent_id.isdigit():
            return False
        number = int(parent_id)
        start = min(child.source_order for child in children)
        stop = max(child.source_order for child in children)
        before = any(
            block.block_id == str(number - 1) and block.source_order < start
            for block in ordered
        )
        after = any(
            block.block_id == str(number + 1) and block.source_order > stop
            for block in ordered
        )
        return before and after

    @staticmethod
    def _immediate_parent_id(block_id: str) -> Optional[str]:
        return block_id.rsplit(".", 1)[0] if "." in block_id else None

    @classmethod
    def _nearest_existing_parent(
        cls, block_id: str, existing: Dict[str, Any]
    ) -> Optional[str]:
        candidate = cls._immediate_parent_id(block_id)
        while candidate:
            if candidate in existing:
                return candidate
            candidate = cls._immediate_parent_id(candidate)
        return None

    @staticmethod
    def _validate_unique_ids(blocks: Sequence[Any]) -> None:
        seen = set()
        for block in blocks:
            if block.block_type == "TABLE":
                continue
            key = (block.semantic_context, block.block_id)
            if key in seen:
                raise ValueError(f"Duplicate structural parent ID: {block.block_id}")
            seen.add(key)

    @staticmethod
    def _validate_acyclic(blocks: Sequence[Any]) -> None:
        parents = {
            block.block_id: block.parent_id for block in blocks
            if block.block_type in {"CLAUSE", "SUBCLAUSE", "DEFINITION_SECTION"}
        }
        for start in parents:
            seen = set()
            current: Optional[str] = start
            while current in parents:
                if current in seen:
                    raise ValueError(f"Structural hierarchy cycle detected at {current}")
                seen.add(current)
                current = parents[current]


__all__ = ["GenericStructuralParentResolver", "ParentRecoveryEvidence"]
