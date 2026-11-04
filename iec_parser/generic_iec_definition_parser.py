"""Source-backed extraction of definitions from structural definition context."""

from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

from iec_parser.generic_iec_kb_models import (
    Definition, DocumentType, ParentRelationship, RelationshipType,
    SourceReference, StandardDocument,
)
from iec_parser.generic_iec_structural_parser import StructuralBlock


class GenericIECDefinitionParser:
    """Convert only DEFINITION-context structural text into Definition models."""

    _ID_LINE_RE = re.compile(
        r"^(?P<id>\d+(?:\.\d+)+)(?:\s+(?P<operation>Replacement|Addition|Modification)\s*:?)?$",
        re.IGNORECASE,
    )
    _SECTION_TERM_RE = re.compile(r"^(?:terms? and )?definitions?(?: relating to\b|$)", re.IGNORECASE)
    _OPERATION_MAP = {
        "replacement": RelationshipType.REPLACEMENT,
        "addition": RelationshipType.ADDITION,
        "modification": RelationshipType.MODIFICATION,
    }

    def parse(
        self, document: StandardDocument, blocks: Sequence[StructuralBlock]
    ) -> List[Definition]:
        """Return ordered definitions without changing document or structural blocks."""

        if not isinstance(document, StandardDocument):
            raise TypeError("document must be a StandardDocument")
        if blocks is None or isinstance(blocks, (str, bytes)):
            raise TypeError("blocks must be a sequence of StructuralBlock objects")
        if any(not isinstance(block, StructuralBlock) for block in blocks):
            raise TypeError("blocks must contain StructuralBlock objects")

        definitions: List[Definition] = []
        seen = set()
        for block in sorted(blocks, key=lambda item: item.source_order):
            if block.semantic_context != "DEFINITION":
                continue
            for item in self._extract_block(document, block):
                if item.clause_id in seen:
                    continue
                seen.add(item.clause_id)
                definitions.append(item)
        return definitions

    def _extract_block(
        self, document: StandardDocument, block: StructuralBlock
    ) -> List[Definition]:
        lines = [self._clean(line) for line in block.raw_text.splitlines()]
        candidates: List[Tuple[int, str, Optional[str]]] = []
        for index, line in enumerate(lines):
            match = self._ID_LINE_RE.fullmatch(line)
            if match:
                candidates.append((index, match.group("id"), match.group("operation")))

        output: List[Definition] = []
        for position, (start, definition_id, operation) in enumerate(candidates):
            stop = candidates[position + 1][0] if position + 1 < len(candidates) else len(lines)
            content = [line for line in lines[start + 1:stop] if line]
            if not content:
                continue
            term = content[0].strip(" :")
            if not term or self._SECTION_TERM_RE.match(term):
                continue
            body_lines = self._without_note_paragraphs(content[1:])
            body = "\n".join(body_lines).strip()
            if not body:
                continue
            relationship_type = self._relationship_type(document, operation)
            raw_slice = "\n".join(lines[start:stop]).strip()
            output.append(Definition(
                term=term,
                definition=body,
                clause_id=definition_id,
                source=SourceReference(
                    page_start=block.page_start,
                    page_end=block.page_end,
                    raw_text=raw_slice,
                ),
                relationship_to_parent=ParentRelationship(
                    type=relationship_type,
                    parent_clause_id=(
                        definition_id if relationship_type is not RelationshipType.NONE else None
                    ),
                    notes=(f"Explicit definition {operation.lower()} operation."
                           if operation else None),
                ),
            ))
        return output

    def _relationship_type(
        self, document: StandardDocument, operation: Optional[str]
    ) -> RelationshipType:
        if document.document_type is not DocumentType.PART_2 or not operation:
            return RelationshipType.NONE
        return self._OPERATION_MAP.get(operation.casefold(), RelationshipType.UNRESOLVED)

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _without_note_paragraphs(lines: Sequence[str]) -> List[str]:
        """Remove NOTE paragraphs while retaining definition text that follows."""

        output: List[str] = []
        in_note = False
        for line in lines:
            if re.match(r"^NOTE(?:\s+\d+)?\b", line, re.IGNORECASE):
                in_note = True
                continue
            if in_note:
                # PDF line wrapping makes note continuation lines begin with a
                # lowercase word. A new sentence/list marker resumes the body.
                first = next((character for character in line if character.isalpha()), "")
                if first and first.islower():
                    continue
                in_note = False
            output.append(line)
        return output


__all__ = ["GenericIECDefinitionParser"]
