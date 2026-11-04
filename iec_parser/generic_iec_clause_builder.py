"""Build generic clause model trees from structural parser blocks."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence

from iec_parser.generic_iec_kb_models import (
    Clause,
    ClauseType,
    ParentRelationship,
    RelationshipType,
    SourceReference,
)
from iec_parser.generic_iec_structural_parser import StructuralBlock


class GenericIECClauseBuilder:
    """Convert ordered structural clause blocks into nested Clause models."""

    _CLAUSE_BLOCK_TYPES = {"CLAUSE", "SUBCLAUSE"}

    def build(self, blocks: Sequence[StructuralBlock]) -> List[Clause]:
        """Return top-level clauses with all child clauses nested exactly once."""

        if blocks is None:
            raise TypeError("blocks must be a sequence of StructuralBlock objects")
        if isinstance(blocks, (str, bytes)):
            raise TypeError("blocks must be a sequence of StructuralBlock objects")

        clause_blocks = self._filter_clause_blocks(blocks)
        if not clause_blocks:
            return []
        self._validate_unique_ids(clause_blocks)

        ordered_blocks = sorted(clause_blocks, key=lambda block: block.source_order)
        blocks_by_id = {block.block_id: block for block in ordered_blocks}
        resolved_parents = {
            block.block_id: self._resolve_parent(block, blocks_by_id)
            for block in ordered_blocks
        }
        clauses = {
            block.block_id: self._create_clause(
                block, resolved_parents[block.block_id]
            )
            for block in ordered_blocks
        }

        top_level: List[Clause] = []
        for block in ordered_blocks:
            clause = clauses[block.block_id]
            parent_id = resolved_parents[block.block_id]
            if parent_id is None:
                top_level.append(clause)
            else:
                clauses[parent_id].children.append(clause)
        return top_level

    @classmethod
    def build_from_blocks(cls, blocks: Sequence[StructuralBlock]) -> List[Clause]:
        """Convenience API for building without retaining a builder instance."""

        return cls().build(blocks)

    def _filter_clause_blocks(
        self, blocks: Sequence[StructuralBlock]
    ) -> List[StructuralBlock]:
        filtered: List[StructuralBlock] = []
        for block in blocks:
            if not isinstance(block, StructuralBlock):
                raise TypeError("Every input item must be a StructuralBlock")
            if block.block_type in self._CLAUSE_BLOCK_TYPES:
                filtered.append(block)
        return filtered

    @staticmethod
    def _validate_unique_ids(blocks: Sequence[StructuralBlock]) -> None:
        seen = set()
        for block in blocks:
            if not isinstance(block.block_id, str) or not block.block_id.strip():
                raise ValueError("Clause structural blocks must have a non-empty block_id")
            if block.block_id in seen:
                raise ValueError(f"Duplicate clause ID in structural input: {block.block_id}")
            seen.add(block.block_id)

    def _resolve_parent(
        self,
        block: StructuralBlock,
        blocks_by_id: Dict[str, StructuralBlock],
    ) -> Optional[str]:
        supplied_parent = block.parent_id
        if supplied_parent and self._is_valid_parent(
            supplied_parent, block, blocks_by_id
        ):
            return supplied_parent

        components = block.block_id.split(".")
        while len(components) > 1:
            components.pop()
            candidate = ".".join(components)
            if self._is_valid_parent(candidate, block, blocks_by_id):
                return candidate
        return None

    @staticmethod
    def _is_valid_parent(
        parent_id: str,
        child: StructuralBlock,
        blocks_by_id: Dict[str, StructuralBlock],
    ) -> bool:
        parent = blocks_by_id.get(parent_id)
        return bool(
            parent
            and child.block_id.startswith(f"{parent_id}.")
            and parent.source_order < child.source_order
        )

    def _create_clause(
        self, block: StructuralBlock, parent_id: Optional[str]
    ) -> Clause:
        return Clause(
            clause_id=block.block_id,
            title=block.title,
            clause_type=self._detect_clause_type(block),
            source=SourceReference(
                page_start=block.page_start,
                page_end=block.page_end,
                raw_text=block.raw_text,
            ),
            relationship_to_parent=ParentRelationship(
                type=RelationshipType.NONE,
                parent_clause_id=parent_id,
            ),
        )

    @staticmethod
    def _detect_clause_type(block: StructuralBlock) -> ClauseType:
        title = (block.title or "").strip()
        if re.fullmatch(r"void", title, re.IGNORECASE):
            return ClauseType.VOID
        explicit_text = f"{title}\n{block.raw_text[:300]}"
        if re.search(r"\(\s*informative\s*\)", explicit_text, re.IGNORECASE):
            return ClauseType.INFORMATIVE
        return ClauseType.NORMATIVE
