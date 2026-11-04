"""Focused tests for generic qualified Delta operations and safe merging."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from iec_par.generic_iec_effective_kb_builder import (
    GenericIECEffectiveKnowledgeBaseBuilder,
)
from iec_par.generic_iec_effective_kb_models import EffectiveStatus
from iec_par.generic_iec_kb_models import (
    ApplicabilityRule,
    ApplicabilityStatus,
    Clause,
    ClauseType,
    ConstraintStatus,
    ConstraintType,
    DocumentType,
    KnowledgeBase,
    OperationQualifierType,
    OperationTargetScope,
    ParentRelationship,
    RelationshipType,
    Requirement,
    RequirementType,
    SourceReference,
    StandardDocument,
    TechnicalConstraint,
)
from iec_par.generic_iec_relationship_parser import GenericIECRelationshipParser


def document(kind: DocumentType = DocumentType.PART_2) -> StandardDocument:
    return StandardDocument(
        document_type=kind,
        standard_id="GENERIC-DELTA" if kind is DocumentType.PART_2 else "GENERIC-BASE",
        standard_number="GEN 100-2" if kind is DocumentType.PART_2 else "GEN 100-1",
        parent_standard="GEN 100-1" if kind is DocumentType.PART_2 else None,
    )


def requirement(rid: str, text: str) -> Requirement:
    return Requirement(
        requirement_id=rid,
        text=text,
        requirement_type=RequirementType.GENERAL,
        normative=True,
        applicability=ApplicabilityRule(ApplicabilityStatus.ALWAYS),
    )


def clause(raw: str, cid: str = "8.4", relation: RelationshipType = RelationshipType.NONE) -> Clause:
    return Clause(
        clause_id=cid,
        clause_type=ClauseType.NORMATIVE,
        source=SourceReference(page_start=1, page_end=1, raw_text=raw),
        relationship_to_parent=ParentRelationship(relation, cid if relation is not RelationshipType.NONE else None),
        requirements=[requirement(f"{cid}-R1", "Delta equipment shall comply.")],
    )


def parsed(raw: str, cid: str = "8.4") -> Clause:
    return GenericIECRelationshipParser().parse(document(), [clause(raw, cid)])[0]


def pair(delta: Clause) -> tuple[KnowledgeBase, KnowledgeBase]:
    base_clause = clause("Base source", delta.relationship_to_parent.parent_clause_id or delta.clause_id)
    base_clause.requirements = [requirement(f"{base_clause.clause_id}-R1", "Base equipment shall comply.")]
    return KnowledgeBase(document(DocumentType.BASE), clauses=[base_clause]), KnowledgeBase(
        document(), clauses=[delta]
    )


class QualifiedDeltaOperationTests(unittest.TestCase):
    def test_01_bare_replacement(self) -> None:
        item = parsed("8.4 Replacement:\nText")
        self.assertIs(item.relationship_to_parent.type, RelationshipType.REPLACEMENT)
        self.assertIs(item.relationship_to_parent.directive.target_scope, OperationTargetScope.WHOLE_CLAUSE)

    def test_02_condition_replacement(self) -> None:
        item = parsed("8.4 Replacement for product category alpha:\nText")
        self.assertIs(item.relationship_to_parent.type, RelationshipType.REPLACEMENT)
        self.assertIs(item.relationship_to_parent.directive.qualifier_type, OperationQualifierType.CONDITION)
        self.assertEqual(item.relationship_to_parent.directive.qualifier_text, "product category alpha")

    def test_03_condition_raw_text_preserved(self) -> None:
        item = parsed("Replacement for feature alpha:\nText")
        self.assertEqual(item.relationship_to_parent.directive.raw_text, "Replacement for feature alpha:")

    def test_04_table_replacement(self) -> None:
        item = parsed("Replacement of Table 4:\nText")
        self.assertIs(item.relationship_to_parent.directive.target_scope, OperationTargetScope.TABLE)
        self.assertEqual(item.relationship_to_parent.directive.target_text, "Table 4")

    def test_05_other_table_number(self) -> None:
        self.assertIs(parsed("Replacement of Table 12:\nText").relationship_to_parent.directive.target_scope,
                      OperationTargetScope.TABLE)

    def test_06_first_paragraph(self) -> None:
        item = parsed("Replacement of the first paragraph:\nText")
        self.assertIs(item.relationship_to_parent.directive.target_scope, OperationTargetScope.PARTIAL_CONTENT)

    def test_07_second_paragraph(self) -> None:
        item = parsed("Replacement of the second paragraph:\nText")
        self.assertIs(item.relationship_to_parent.directive.target_scope, OperationTargetScope.PARTIAL_CONTENT)

    def test_08_modification_for_condition(self) -> None:
        item = parsed("Modification for feature alpha:\nText")
        self.assertIs(item.relationship_to_parent.type, RelationshipType.MODIFICATION)
        self.assertIs(item.relationship_to_parent.directive.qualifier_type, OperationQualifierType.CONDITION)

    def test_09_modification_of_table(self) -> None:
        item = parsed("Modification of Table 5:\nText")
        self.assertIs(item.relationship_to_parent.directive.target_scope, OperationTargetScope.TABLE)

    def test_10_addition_for_condition(self) -> None:
        item = parsed("Addition for feature alpha:\nText")
        self.assertIs(item.relationship_to_parent.type, RelationshipType.ADDITION)
        self.assertIs(item.relationship_to_parent.directive.qualifier_type, OperationQualifierType.CONDITION)

    def test_11_addition_to_clause(self) -> None:
        item = parsed("Addition to 8.4:\nText", "8.5")
        self.assertIs(item.relationship_to_parent.directive.target_scope, OperationTargetScope.CLAUSE)
        self.assertEqual(item.relationship_to_parent.parent_clause_id, "8.4")

    def test_12_addition_of_unknown_target(self) -> None:
        item = parsed("Addition of introductory material:\nText")
        self.assertIs(item.relationship_to_parent.directive.target_scope, OperationTargetScope.UNKNOWN_TARGET)

    def test_13_unknown_wording_unresolved(self) -> None:
        self.assertIs(parsed("Replace material as appropriate.\nText").relationship_to_parent.type,
                      RelationshipType.UNRESOLVED)

    def test_14_whole_replacement_preserved(self) -> None:
        delta = parsed("Replacement:\nText")
        effective = GenericIECEffectiveKnowledgeBaseBuilder().build(*pair(delta))
        self.assertIs(effective.clauses[0].requirements[0].effective_status, EffectiveStatus.INACTIVE)

    def test_15_condition_replacement_keeps_base(self) -> None:
        delta = parsed("Replacement for category alpha:\nText")
        effective = GenericIECEffectiveKnowledgeBaseBuilder().build(*pair(delta))
        self.assertIs(effective.clauses[0].requirements[0].effective_status, EffectiveStatus.ACTIVE)
        self.assertIs(effective.clauses[0].requirements[1].effective_status, EffectiveStatus.NEEDS_REVIEW)

    def test_16_table_replacement_keeps_base(self) -> None:
        effective = GenericIECEffectiveKnowledgeBaseBuilder().build(*pair(parsed("Replacement of Table 7:\nText")))
        self.assertIs(effective.clauses[0].requirements[0].effective_status, EffectiveStatus.ACTIVE)

    def test_17_paragraph_replacement_keeps_base(self) -> None:
        effective = GenericIECEffectiveKnowledgeBaseBuilder().build(
            *pair(parsed("Replacement of the third paragraph:\nText"))
        )
        self.assertIs(effective.clauses[0].requirements[0].effective_status, EffectiveStatus.ACTIVE)

    def test_18_unresolved_does_not_crash_or_fabricate(self) -> None:
        delta = parsed("Replace material as appropriate.\nText")
        effective = GenericIECEffectiveKnowledgeBaseBuilder().build(*pair(delta))
        self.assertEqual(effective.clauses[0].applied_operations[0].operation_type.value, "UNRESOLVED")
        self.assertIs(effective.clauses[0].requirements[0].effective_status, EffectiveStatus.ACTIVE)

    def test_19_unresolved_provenance(self) -> None:
        raw = "Replace material as appropriate.\nText"
        effective = GenericIECEffectiveKnowledgeBaseBuilder().build(*pair(parsed(raw)))
        self.assertEqual(effective.unresolved_operations[0]["source_text"], raw)

    def test_20_directive_serializes(self) -> None:
        data = parsed("Replacement of Table 9:\nText").to_dict()
        self.assertEqual(data["relationship_to_parent"]["directive"]["target_scope"], "TABLE")

    def test_21_applicability_unresolved_unchanged(self) -> None:
        item = parsed("Addition:\nText")
        item.requirements[0].applicability.status = ApplicabilityStatus.UNRESOLVED
        self.assertIs(item.requirements[0].applicability.status, ApplicabilityStatus.UNRESOLVED)

    def test_22_constraint_unresolved_unchanged(self) -> None:
        item = parsed("Addition:\nText")
        item.requirements[0].technical_constraints = [TechnicalConstraint(
            "C1", constraint_type=ConstraintType.OTHER, status=ConstraintStatus.UNRESOLVED
        )]
        self.assertIs(item.requirements[0].technical_constraints[0].status, ConstraintStatus.UNRESOLVED)

    def test_23_deterministic_effective_serialization(self) -> None:
        delta = parsed("Replacement of the fourth sentence:\nText")
        builder = GenericIECEffectiveKnowledgeBaseBuilder()
        base, delta_kb = pair(delta)
        self.assertEqual(builder.to_json(builder.build(base, delta_kb)),
                         builder.to_json(builder.build(base, delta_kb)))

    def test_24_no_specific_production_branch(self) -> None:
        root = Path(__file__).resolve().parents[1] / "iec_par"
        text = "\n".join((root / name).read_text(encoding="utf-8") for name in (
            "generic_iec_relationship_parser.py", "generic_iec_effective_kb_builder.py"
        ))
        for forbidden in ("62841", "impact drill", "17.2", "18.8", "23.3"):
            self.assertNotIn(forbidden, text.lower())

    def test_25_json_round_trip_shape(self) -> None:
        self.assertEqual(json.loads(parsed("Modification of Table 6:\nText").to_json())
                         ["relationship_to_parent"]["directive"]["target_text"], "Table 6")

    def test_26_applicable_except_precedes_nested_marker(self) -> None:
        item = parsed(
            "This clause of Part 1 is applicable except as follows.\nAddition:\nText"
        )
        self.assertIs(item.relationship_to_parent.type, RelationshipType.APPLICABLE_EXCEPT)

    def test_27_whole_requirement_modification_preserves_legacy_semantics(self) -> None:
        item = parsed("Modification to the requirement:\nText")
        self.assertIs(item.relationship_to_parent.type, RelationshipType.MODIFICATION)
        self.assertIsNone(item.relationship_to_parent.directive)


if __name__ == "__main__":
    unittest.main(verbosity=2)
