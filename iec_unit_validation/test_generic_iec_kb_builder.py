"""Tests for generic IEC KnowledgeBase assembly."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from iec_par.generic_iec_kb_builder import GenericIECKnowledgeBaseBuilder
from iec_par.generic_iec_kb_models import (
    ApplicabilityRule,
    ApplicabilityStatus,
    Clause,
    ClauseType,
    ConstraintStatus,
    ConstraintType,
    DocumentType,
    ParentRelationship,
    RelationshipType,
    Requirement,
    RequirementType,
    SourceReference,
    StandardDocument,
    TechnicalConstraint,
)
from iec_par.generic_iec_structural_parser import StructuralBlock


class StubState:
    document: StandardDocument
    blocks: list[StructuralBlock]
    clauses: list[Clause]


class StubDocumentParser:
    def __init__(self, path: Path) -> None:
        self.path = path

    def parse(self) -> StandardDocument:
        return copy.deepcopy(StubState.document)


class StubStructuralParser:
    def __init__(self, path: Path) -> None:
        self.path = path

    def parse(self) -> list[StructuralBlock]:
        return copy.deepcopy(StubState.blocks)


class StubClauseBuilder:
    def build(self, blocks: list[StructuralBlock]) -> list[Clause]:
        return copy.deepcopy(StubState.clauses)


class AnnexAwareStubClauseBuilder:
    def build(self, blocks: list[StructuralBlock]) -> list[Clause]:
        if blocks and blocks[0].semantic_context == "ANNEX":
            return [make_clause(blocks[0].block_id)]
        return copy.deepcopy(StubState.clauses)


class StubRequirementParser:
    def parse(self, clauses: list[Clause], blocks: list[StructuralBlock]) -> list[Clause]:
        return copy.deepcopy(clauses)


class StubRelationshipParser:
    def parse(self, document, clauses, blocks):
        return copy.deepcopy(clauses)


class StubApplicabilityExtractor:
    def parse(self, clauses):
        return copy.deepcopy(clauses)


class StubApplicabilityNormalizer:
    def __init__(self, registry) -> None:
        self.registry = registry

    def parse(self, clauses):
        return copy.deepcopy(clauses)


class StubConstraintExtractor:
    def parse(self, clauses):
        return copy.deepcopy(clauses)


def make_requirement(requirement_id: str = "7-R1") -> Requirement:
    return Requirement(
        requirement_id=requirement_id,
        text="For class II appliances, the opening shall not exceed 50 mm.",
        requirement_type=RequirementType.LIMIT,
        normative=True,
        condition_text="For class II appliances",
        applicability=ApplicabilityRule(
            status=ApplicabilityStatus.RESOLVED,
            condition_text="For class II appliances",
            logic={"field": "protection_class", "operator": "equals", "value": "CLASS_II"},
        ),
        technical_constraints=[TechnicalConstraint(
            constraint_id=f"{requirement_id}-C1",
            parameter="opening_distance",
            operator="less_than_or_equal",
            value=50,
            unit="mm",
            unit_normalized="mm",
            raw_text="shall not exceed 50 mm",
            constraint_type=ConstraintType.DISTANCE_LIMIT,
            status=ConstraintStatus.RESOLVED,
            source_requirement_id=requirement_id,
        )],
    )


def make_clause(
    clause_id: str = "7",
    relationship: RelationshipType = RelationshipType.NONE,
    children: list[Clause] | None = None,
) -> Clause:
    return Clause(
        clause_id=clause_id,
        title="Protection",
        clause_type=ClauseType.NORMATIVE,
        source=SourceReference(page_start=4, page_end=5, raw_text="7 Protection\nSource text"),
        relationship_to_parent=ParentRelationship(type=relationship, parent_clause_id=clause_id),
        requirements=[make_requirement(f"{clause_id}-R1")],
        children=list(children or []),
    )


def structural_blocks() -> list[StructuralBlock]:
    return [
        StructuralBlock("CLAUSE", "7", "Protection", 1, None, 4, 5,
                        "7 Protection\nSource text", 0),
        StructuralBlock("ANNEX", "A", "Test details (normative)", 1, None, 20, 20,
                        "Annex A\n(normative)\nAnnex source", 1, "ANNEX"),
        StructuralBlock("OTHER", "A.1", "Annex detail", 2, "A", 21, 21,
                        "A.1 Annex detail", 2, "ANNEX"),
        StructuralBlock("TABLE", "1", "Limits Ω", 1, None, 8, 8,
                        "Table 1 – Limits Ω", 3, "TABLE"),
        StructuralBlock("DEFINITION_SECTION", "3", "Terms and definitions", 1, None,
                        3, 3, "3 Terms and definitions\nterm definition", 4, "DEFINITION"),
    ]


class TestGenericIECKnowledgeBaseBuilder(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.pdf = Path(self.temp.name) / "standard.pdf"
        self.pdf.write_bytes(b"stub pdf")
        StubState.document = StandardDocument(
            standard_id="IEC 12345-1:2020", standard_number="IEC 12345-1",
            edition="1", year=2020, document_type=DocumentType.BASE,
        )
        StubState.blocks = structural_blocks()
        StubState.clauses = [make_clause()]
        self.builder = GenericIECKnowledgeBaseBuilder(
            document_parser_cls=StubDocumentParser,
            structural_parser_cls=StubStructuralParser,
            clause_builder_cls=StubClauseBuilder,
            requirement_parser_cls=StubRequirementParser,
            relationship_parser_cls=StubRelationshipParser,
            applicability_extractor_cls=StubApplicabilityExtractor,
            applicability_normalizer_cls=StubApplicabilityNormalizer,
            constraint_extractor_cls=StubConstraintExtractor,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def delta(self) -> None:
        StubState.document = StandardDocument(
            standard_id="IEC 12345-2-7:2021", standard_number="IEC 12345-2-7",
            edition="2", year=2021, part_number="2-7",
            document_type=DocumentType.PART_2, parent_standard="IEC 12345-1",
        )
        StubState.clauses = [make_clause("7", RelationshipType.APPLICABLE_EXCEPT)]

    def test_01_build_simple_base_kb(self) -> None:
        self.assertIs(self.builder.build(self.pdf).document.document_type, DocumentType.BASE)

    def test_02_base_relationships_remain_none(self) -> None:
        self.assertIs(self.builder.build_base_kb(self.pdf).clauses[0].relationship_to_parent.type,
                      RelationshipType.NONE)

    def test_03_build_part_2_delta_kb(self) -> None:
        self.delta()
        self.assertIs(self.builder.build(self.pdf).document.document_type, DocumentType.PART_2)

    def test_04_part_2_relationship_preserved(self) -> None:
        self.delta()
        self.assertIs(self.builder.build_delta_kb(self.pdf).clauses[0].relationship_to_parent.type,
                      RelationshipType.APPLICABLE_EXCEPT)

    def test_05_applicability_logic_preserved(self) -> None:
        kb = self.builder.build(self.pdf)
        self.assertEqual(kb.clauses[0].requirements[0].applicability.logic,
                         StubState.clauses[0].requirements[0].applicability.logic)

    def test_06_technical_constraints_preserved(self) -> None:
        self.assertEqual(self.builder.get_summary(self.builder.build(self.pdf))["technical_constraints"], 1)

    def test_07_requirement_text_unchanged(self) -> None:
        kb = self.builder.build(self.pdf)
        self.assertEqual(kb.clauses[0].requirements[0].text, StubState.clauses[0].requirements[0].text)

    def test_08_condition_text_unchanged(self) -> None:
        kb = self.builder.build(self.pdf)
        self.assertEqual(kb.clauses[0].requirements[0].condition_text, "For class II appliances")

    def test_09_hierarchy_preserved(self) -> None:
        StubState.clauses = [make_clause(children=[make_clause("7.1")])]
        self.assertEqual(self.builder.build(self.pdf).clauses[0].children[0].clause_id, "7.1")

    def test_10_clause_ids_preserved(self) -> None:
        self.assertEqual(self.builder.build(self.pdf).clauses[0].clause_id, "7")

    def test_11_requirement_ids_preserved(self) -> None:
        self.assertEqual(self.builder.build(self.pdf).clauses[0].requirements[0].requirement_id, "7-R1")

    def test_12_annex_is_preserved(self) -> None:
        annex = self.builder.build(self.pdf).annexes[0]
        self.assertEqual((annex.annex_id, annex.normative, annex.source.page_end), ("A", True, 21))
        self.assertIn("A.1 Annex detail", annex.source.raw_text)

    def test_13_table_is_converted(self) -> None:
        table = self.builder.build(self.pdf).tables[0]
        self.assertEqual((table.table_id, table.title, table.structured_data),
                         ("1", "Limits Ω", None))

    def test_14_definition_not_made_requirement(self) -> None:
        kb = self.builder.build(self.pdf)
        self.assertEqual(kb.definitions, [])
        container = next(clause for clause in kb.clauses if clause.clause_id == "3")
        self.assertEqual(container.requirements, [])

    def test_15_serialization_works(self) -> None:
        self.assertEqual(json.loads(self.builder.to_json(self.builder.build(self.pdf)))["schema_version"], "1.0")

    def test_16_enums_serialize_as_values(self) -> None:
        data = json.loads(self.builder.to_json(self.builder.build(self.pdf)))
        self.assertEqual(data["document"]["document_type"], "BASE")

    def test_17_unicode_serialization(self) -> None:
        serialized = self.builder.to_json(self.builder.build(self.pdf))
        self.assertIn("Ω", serialized)
        self.assertNotIn("\\u03a9", serialized.lower())

    def test_18_deterministic_build_serialization(self) -> None:
        first = self.builder.to_json(self.builder.build(self.pdf))
        second = self.builder.to_json(self.builder.build(self.pdf))
        self.assertEqual(first, second)

    def test_19_same_kb_serialized_twice_identically(self) -> None:
        kb = self.builder.build(self.pdf)
        self.assertEqual(self.builder.to_json(kb), self.builder.to_json(kb))

    def test_20_base_filename(self) -> None:
        self.assertEqual(self.builder.generate_output_filename(self.builder.build(self.pdf)),
                         "IEC_12345_1_2020_base_kb.json")

    def test_21_delta_filename(self) -> None:
        self.delta()
        self.assertEqual(self.builder.generate_output_filename(self.builder.build(self.pdf)),
                         "IEC_12345_2_7_2021_delta_kb.json")

    def test_22_missing_file_error(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.builder.build(Path(self.temp.name) / "missing.pdf")

    def test_23_build_base_rejects_part_2(self) -> None:
        self.delta()
        with self.assertRaises(ValueError):
            self.builder.build_base_kb(self.pdf)

    def test_24_build_delta_rejects_base(self) -> None:
        with self.assertRaises(ValueError):
            self.builder.build_delta_kb(self.pdf)

    def test_25_constraint_source_requirement_validation(self) -> None:
        StubState.clauses[0].requirements[0].technical_constraints[0].source_requirement_id = "wrong"
        with self.assertRaises(ValueError):
            self.builder.build(self.pdf)

    def test_26_duplicate_requirements_rejected(self) -> None:
        StubState.clauses[0].requirements.append(copy.deepcopy(StubState.clauses[0].requirements[0]))
        with self.assertRaises(ValueError):
            self.builder.build(self.pdf)

    def test_27_duplicate_clauses_rejected(self) -> None:
        StubState.clauses.append(make_clause("7"))
        with self.assertRaises(ValueError):
            self.builder.build(self.pdf)

    def test_28_no_part_1_part_2_merge(self) -> None:
        self.delta()
        kb = self.builder.build_delta_kb(self.pdf)
        self.assertEqual([item.clause_id for item in kb.clauses], ["7", "3"])
        self.assertEqual(kb.clauses[1].requirements, [])

    def test_29_input_file_untouched(self) -> None:
        before = self.pdf.read_bytes()
        self.builder.build(self.pdf)
        self.assertEqual(self.pdf.read_bytes(), before)

    def test_30_pipeline_inputs_are_not_mutated(self) -> None:
        original = copy.deepcopy(StubState.clauses)
        kb = self.builder.build(self.pdf)
        kb.clauses[0].title = "Changed"
        self.assertEqual(StubState.clauses, original)

    def test_31_annex_requirements_are_enriched_without_main_clause_duplication(self) -> None:
        StubState.blocks.insert(
            2,
            StructuralBlock("SUBCLAUSE", "A.1", "Annex limit", 2, "A", 21, 21,
                            "A.1 Annex limit", 2, "ANNEX"),
        )
        builder = GenericIECKnowledgeBaseBuilder(
            document_parser_cls=StubDocumentParser,
            structural_parser_cls=StubStructuralParser,
            clause_builder_cls=AnnexAwareStubClauseBuilder,
            requirement_parser_cls=StubRequirementParser,
            relationship_parser_cls=StubRelationshipParser,
            applicability_extractor_cls=StubApplicabilityExtractor,
            applicability_normalizer_cls=StubApplicabilityNormalizer,
            constraint_extractor_cls=StubConstraintExtractor,
        )
        kb = builder.build(self.pdf)
        self.assertEqual(kb.annexes[0].requirements[0].requirement_id, "A.1-R1")
        self.assertNotIn("A.1", [item.clause_id for item in kb.clauses])


if __name__ == "__main__":
    unittest.main(verbosity=2)
