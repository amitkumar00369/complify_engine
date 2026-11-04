"""Semantic Part 2 relationship classification for generic IEC clauses."""

from __future__ import annotations

import copy
import re
from typing import List, Optional, Sequence, Tuple

from iec_parser.generic_iec_kb_models import (
    Clause,
    DeltaOperationDirective,
    DocumentType,
    OperationQualifierType,
    OperationTargetScope,
    ParentRelationship,
    RelationshipType,
    StandardDocument,
)
from iec_parser.generic_iec_structural_parser import StructuralBlock


class GenericIECRelationshipParser:
    """Classify explicit Part 2 delta wording without applying the delta."""

    _NOT_APPLICABLE_RE = re.compile(
        r"\bthis\s+(?:sub)?clause(?:\s+of\s+Part\s+1)?\s+is\s+not\s+applicable\b|"
        r"(?:^|\n)\s*(?:(?:[A-Z]{1,3}\.)?\d+(?:\.\d+)*\s+)?Not\s+applicable\s*\.?(?=\s*(?:\n|$))",
        re.IGNORECASE,
    )
    _APPLICABLE_EXCEPT_RE = re.compile(
        r"\b(?:this\s+clause\s+of\s+Part\s+1\s+is\s+)?"
        r"applicable\s+except\s+as\s+follows\b",
        re.IGNORECASE,
    )
    _APPLICABLE_RE = re.compile(
        r"\bthis\s+clause\s+of\s+Part\s+1\s+is\s+applicable\b",
        re.IGNORECASE,
    )
    _REPLACEMENT_RE = re.compile(
        r"(?:^|\n)\s*(?:(?:[A-Z]{1,3}\.)?\d+(?:\.\d+)*\s+)?Replacement\s*:|"
        r"\bthis\s+clause\s+of\s+Part\s+1\s+is\s+replaced\s+by\s+the\s+following\b|"
        r"\breplace\s+the\s+(?:text|requirement|clause)\s+by\s+the\s+following\b",
        re.IGNORECASE,
    )
    _DIRECTIVE_RE = re.compile(
        r"(?:^|\n)\s*(?:(?:[A-Z]{1,3}\.)?\d+(?:\.\d+)*\s+)?"
        r"(?P<operation>Addition|Modification|Replacement)"
        r"(?:\s+(?P<preposition>for|of|to)\s+(?P<qualifier>[^:\n]+?))?\s*:"
        r"(?=\s*(?:\n|$))",
        re.IGNORECASE,
    )
    _MODIFICATION_RE = re.compile(
        r"(?:^|\n)\s*(?:(?:[A-Z]{1,3}\.)?\d+(?:\.\d+)*\s+)?Modification(?:\s+to\s+the\s+requirement)?\s*:|"
        r"\breplace\s+[‘'\"].+?[’'\"]\s+by\s+[‘'\"]",
        re.IGNORECASE,
    )
    _WHOLE_REQUIREMENT_MODIFICATION_RE = re.compile(
        r"(?:^|\n)\s*(?:(?:[A-Z]{1,3}\.)?\d+(?:\.\d+)*\s+)?Modification\s+to\s+the\s+requirement\s*:",
        re.IGNORECASE,
    )
    _ADDITION_MARKER_RE = re.compile(
        r"(?:^|\n)\s*(?:(?:[A-Z]{1,3}\.)?\d+(?:\.\d+)*\s+)?Addition\s*:",
        re.IGNORECASE,
    )
    _EXPLICIT_NEW_RE = re.compile(
        r"\b(?:additional\s+(?:sub)?clause|add\s+the\s+following|add\s*:)\b",
        re.IGNORECASE,
    )
    _ALTERATION_HINT_RE = re.compile(
        r"\bPart\s+1\b|"
        r"(?:^|\n)\s*(?:\d+(?:\.\d+)*\s+)?"
        r"(?:addition|modification|replacement|replace|add)\b",
        re.IGNORECASE,
    )

    def parse(
        self,
        document: StandardDocument,
        clauses: Sequence[Clause],
        structural_blocks: Optional[Sequence[StructuralBlock]] = None,
    ) -> List[Clause]:
        """Return a deep copy with semantic Part 2 relationships populated."""

        if not isinstance(document, StandardDocument):
            raise TypeError("document must be a StandardDocument")
        if clauses is None or isinstance(clauses, (str, bytes)):
            raise TypeError("clauses must be a sequence of Clause objects")
        if any(not isinstance(clause, Clause) for clause in clauses):
            raise TypeError("Every input item must be a Clause")
        if structural_blocks is not None and (
            isinstance(structural_blocks, (str, bytes))
            or any(not isinstance(block, StructuralBlock) for block in structural_blocks)
        ):
            raise TypeError("structural_blocks must contain StructuralBlock objects")

        copied = copy.deepcopy(list(clauses))
        if document.document_type is not DocumentType.PART_2:
            return copied
        for clause in copied:
            self._apply_recursive(clause)
        return copied

    def _apply_recursive(self, clause: Clause) -> None:
        structural_parent = clause.relationship_to_parent.parent_clause_id
        relationship_type, evidence, directive = self._detect_relationship(
            clause.clause_id, clause.source.raw_text or ""
        )
        target, target_note = self._resolve_parent_clause_id(
            clause.clause_id, relationship_type
        )
        if (
            directive
            and directive.target_scope is OperationTargetScope.CLAUSE
            and directive.target_text
        ):
            target = directive.target_text
            target_note = "Targeted to the explicit clause identifier in the directive."
        notes = self._build_notes(
            evidence, target_note, structural_parent, target, relationship_type
        )
        clause.relationship_to_parent = ParentRelationship(
            type=relationship_type,
            parent_clause_id=(
                target if relationship_type is not RelationshipType.NONE else structural_parent
            ),
            notes=notes,
            directive=directive,
        )
        for child in clause.children:
            self._apply_recursive(child)

    def _detect_relationship(
        self, clause_id: str, raw_text: str
    ) -> Tuple[RelationshipType, Optional[str], Optional[DeltaOperationDirective]]:
        relationship_text = re.split(
            r"\n\s*(?:Annexes|Bibliography)\s*\n",
            raw_text,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        if self._NOT_APPLICABLE_RE.search(relationship_text):
            return RelationshipType.NOT_APPLICABLE, "Explicit not-applicable wording.", None
        if self._APPLICABLE_EXCEPT_RE.search(relationship_text):
            return (
                RelationshipType.APPLICABLE_EXCEPT,
                "Explicit Part 1 applicable-except wording.",
                None,
            )
        if self._WHOLE_REQUIREMENT_MODIFICATION_RE.search(relationship_text):
            return RelationshipType.MODIFICATION, "Explicit modification wording.", None
        directive_match = self._DIRECTIVE_RE.search(relationship_text)
        if directive_match:
            operation = RelationshipType[directive_match.group("operation").upper()]
            directive = self._directive_from_match(directive_match)
            return operation, f"Explicit {operation.value.lower()} directive.", directive
        if self._REPLACEMENT_RE.search(relationship_text):
            return RelationshipType.REPLACEMENT, "Explicit replacement wording.", None
        if self._MODIFICATION_RE.search(relationship_text):
            return RelationshipType.MODIFICATION, "Explicit modification wording.", None
        if self._ADDITION_MARKER_RE.search(relationship_text):
            return RelationshipType.ADDITION, "Explicit addition marker.", None
        if self._APPLICABLE_RE.search(relationship_text):
            return RelationshipType.APPLICABLE, "Explicit Part 1 applicable wording.", None
        if self._EXPLICIT_NEW_RE.search(relationship_text):
            if self._has_product_specific_suffix(clause_id):
                return (
                    RelationshipType.NEW_REQUIREMENT,
                    "Explicit new-clause wording with a product-specific subclause identifier.",
                    None,
                )
            return RelationshipType.ADDITION, "Explicit add/additional wording.", None
        if self._ALTERATION_HINT_RE.search(relationship_text):
            return (
                RelationshipType.UNRESOLVED,
                "Part 1 alteration wording is present but its operation is ambiguous.",
                None,
            )
        return RelationshipType.NONE, None, None

    @staticmethod
    def _directive_from_match(match: re.Match[str]) -> DeltaOperationDirective:
        """Build a generic directive without resolving product applicability."""

        raw_text = match.group(0).strip()
        preposition = (match.group("preposition") or "").lower() or None
        qualifier = (match.group("qualifier") or "").strip() or None
        if preposition == "for":
            return DeltaOperationDirective(
                raw_text=raw_text,
                qualifier_type=OperationQualifierType.CONDITION,
                qualifier_text=qualifier,
                target_scope=OperationTargetScope.WHOLE_CLAUSE,
                preposition=preposition,
            )
        if qualifier:
            normalized = re.sub(r"\s+", " ", qualifier).strip()
            if re.match(r"^table\s+\S+", normalized, re.IGNORECASE):
                scope = OperationTargetScope.TABLE
            elif re.match(
                r"^(?:the\s+)?(?:first|second|third|fourth|fifth|last|\d+(?:st|nd|rd|th)?)\s+"
                r"(?:paragraph|sentence|item)\b",
                normalized,
                re.IGNORECASE,
            ):
                scope = OperationTargetScope.PARTIAL_CONTENT
            elif re.fullmatch(r"\d+(?:\.\d+)*", normalized):
                scope = OperationTargetScope.CLAUSE
            else:
                scope = OperationTargetScope.UNKNOWN_TARGET
            return DeltaOperationDirective(
                raw_text=raw_text,
                qualifier_type=OperationQualifierType.TARGET,
                qualifier_text=normalized,
                target_scope=scope,
                target_text=normalized,
                preposition=preposition,
            )
        return DeltaOperationDirective(raw_text=raw_text)

    @staticmethod
    def _has_product_specific_suffix(clause_id: str) -> bool:
        parts = clause_id.split(".")
        return len(parts) > 1 and parts[-1].isdigit() and int(parts[-1]) >= 101

    def _resolve_parent_clause_id(
        self, clause_id: str, relationship_type: RelationshipType
    ) -> Tuple[Optional[str], Optional[str]]:
        if relationship_type is RelationshipType.NONE:
            return None, None
        if not re.fullmatch(r"(?:[A-Z]{1,3}\.)?\d+(?:\.\d+)*", clause_id, re.IGNORECASE):
            return None, "No reliable numeric Part 1 target could be resolved."
        if relationship_type is RelationshipType.NEW_REQUIREMENT:
            components = clause_id.split(".")
            if len(components) < 2:
                return None, "A new-clause parent target could not be resolved."
            return ".".join(components[:-1]), "Targeted to the nearest base-clause ancestor."
        return clause_id, "Targeted to the matching Part 1 clause identifier."

    @staticmethod
    def _build_notes(
        evidence: Optional[str],
        target_note: Optional[str],
        structural_parent: Optional[str],
        target: Optional[str],
        relationship_type: RelationshipType,
    ) -> Optional[str]:
        if relationship_type is RelationshipType.NONE:
            return None
        parts = [part for part in (evidence, target_note) if part]
        if structural_parent and structural_parent != target:
            parts.append(f"Structural parent retained as context: {structural_parent}.")
        if relationship_type is RelationshipType.UNRESOLVED:
            parts.append("Manual relationship review is required.")
        return " ".join(parts) or None
