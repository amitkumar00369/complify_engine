"""Step 31M-C tests for conservative structural parent recovery."""

from __future__ import annotations

import unittest
from pathlib import Path

from iec_par.generic_iec_kb_builder import GenericIECKnowledgeBaseBuilder
from iec_par.generic_iec_structural_parser import (
    GenericIECStructuralParser,
    StructuralBlock,
)
from iec_par.generic_structural_parent_resolver import (
    GenericStructuralParentResolver,
)


ROOT = Path(__file__).resolve().parents[1]


def block(
    block_id: str,
    order: int,
    *,
    block_type: str = "SUBCLAUSE",
    parent_id: str | None = None,
    title: str | None = "Heading",
    context: str = "MAIN_CLAUSE",
    raw_text: str | None = None,
) -> StructuralBlock:
    return StructuralBlock(
        block_type=block_type,
        block_id=block_id,
        title=title,
        level=block_id.count(".") + 1,
        parent_id=parent_id,
        page_start=order + 1,
        page_end=order + 1,
        raw_text=raw_text if raw_text is not None else f"{block_id} {title or ''}".strip(),
        source_order=order,
        semantic_context=context,
    )


class GenericStructuralParentRecoveryTests(unittest.TestCase):
    def resolve(self, *blocks: StructuralBlock):
        return GenericStructuralParentResolver().resolve(blocks)

    def test_01_explicit_parent_and_child(self):
        result = self.resolve(block("5", 0, block_type="CLAUSE"), block("5.1", 1, parent_id="5"))
        self.assertEqual([item.block_id for item in result], ["5", "5.1"])

    def test_02_missing_source_proven_parent_recovered(self):
        result = self.resolve(
            block("5", 0, block_type="CLAUSE"),
            block("5.2.1", 1, raw_text="5.2 Parent heading\n5.2.1 Child"),
        )
        recovered = next(item for item in result if item.block_id == "5.2")
        self.assertEqual(recovered.structural_origin, "RECOVERED_FROM_SOURCE_HIERARCHY")

    def test_03_child_alone_does_not_always_create_parent(self):
        result = self.resolve(block("5.2.1", 0))
        self.assertNotIn("5.2", [item.block_id for item in result])

    def test_04_multiple_children_support_parent_recovery(self):
        result = self.resolve(
            block("5", 0, block_type="CLAUSE"), block("5.2.1", 1), block("5.2.2", 2)
        )
        self.assertIn("5.2", [item.block_id for item in result])

    def test_05_definition_parent_recovery(self):
        result = self.resolve(
            block("2", 0, block_type="CLAUSE"),
            block("3.1", 1, block_type="DEFINITION_SECTION", context="DEFINITION", title="General terms and definitions"),
            block("3.2", 2, block_type="DEFINITION_SECTION", context="DEFINITION", title="Definitions relating to voltage"),
            block("4", 3, block_type="CLAUSE"),
        )
        parent = next(item for item in result if item.block_id == "3")
        self.assertEqual(parent.semantic_context, "DEFINITION")

    def test_06_definition_ordering(self):
        kb = GenericIECKnowledgeBaseBuilder().build_base_kb(ROOT / "RawData/IEC 61058 .pdf")
        ids = [item.clause_id for item in kb.definitions]
        self.assertEqual(ids, sorted(ids, key=lambda value: tuple(map(int, value.split(".")))))

    def test_07_no_requirement_fabrication(self):
        kb = GenericIECKnowledgeBaseBuilder().build_base_kb(ROOT / "RawData/IEC 61058 .pdf")
        parent = next(item for item in kb.clauses if item.clause_id == "3")
        self.assertEqual(parent.requirements, [])

    def test_08_missing_intermediate_parent(self):
        result = self.resolve(
            block("5", 0, block_type="CLAUSE"), block("5.2.1", 1), block("5.2.2", 2)
        )
        parent = next(item for item in result if item.block_id == "5.2")
        self.assertEqual(parent.parent_id, "5")
        children = [item for item in result if item.block_id.startswith("5.2.")]
        self.assertTrue(all(item.parent_id == "5.2" for item in children))

    def test_09_ambiguous_intermediate_parent_not_recovered(self):
        result = self.resolve(block("8.4.1", 0), block("8.4.2", 4))
        self.assertNotIn("8.4", [item.block_id for item in result])

    def test_10_annex_parent_recovery(self):
        result = self.resolve(
            block("A", 0, block_type="ANNEX", context="ANNEX"),
            block("A.3.1", 1, context="ANNEX"), block("A.3.2", 2, context="ANNEX"),
        )
        self.assertIn("A.3", [item.block_id for item in result])

    def test_11_normative_informative_annex_preservation(self):
        blocks = GenericIECStructuralParser.parse_text("Annex A - (informative)\nA.1 Guidance")
        annex = next(item for item in blocks if item.block_type == "ANNEX")
        self.assertIn("informative", (annex.title or "").lower())

    def test_12_existing_parent_not_duplicated(self):
        result = self.resolve(
            block("5", 0, block_type="CLAUSE"), block("5.2", 1), block("5.2.1", 2)
        )
        self.assertEqual([item.block_id for item in result].count("5.2"), 1)

    def test_13_recovered_and_later_real_parent_merge(self):
        result = self.resolve(
            block("5", 0, block_type="CLAUSE"), block("5.2.1", 1),
            block("5.2", 2), block("5.2.2", 3),
        )
        self.assertEqual([item.block_id for item in result].count("5.2"), 1)

    def test_14_source_ordering(self):
        result = self.resolve(
            block("5", 0, block_type="CLAUSE"), block("5.2.1", 1), block("5.2.2", 2)
        )
        ids = [item.block_id for item in result]
        self.assertLess(ids.index("5.2"), ids.index("5.2.1"))
        self.assertEqual([item.source_order for item in result], list(range(len(result))))

    def test_15_table_content_cannot_create_parent(self):
        result = self.resolve(block("5.2.1", 0, block_type="TABLE", context="TABLE"))
        self.assertNotIn("5.2", [item.block_id for item in result])

    def test_16_numeric_row_cannot_imply_parent(self):
        result = self.resolve(block("5.2.1", 0, block_type="OTHER", title=None, raw_text="5.2.1"))
        self.assertNotIn("5.2", [item.block_id for item in result])

    def test_17_list_item_cannot_imply_parent(self):
        result = self.resolve(block("5.2.1", 0, block_type="OTHER", title=None, raw_text="- 5.2.1"))
        self.assertNotIn("5.2", [item.block_id for item in result])

    def test_18_hierarchy_cycle_rejected(self):
        with self.assertRaises(ValueError):
            self.resolve(
                block("5", 0, block_type="CLAUSE", parent_id="5.1"),
                block("5.1", 1, parent_id="5"),
            )

    def test_19_iec_61058_clause_3_probe(self):
        kb = GenericIECKnowledgeBaseBuilder().build_base_kb(ROOT / "RawData/IEC 61058 .pdf")
        self.assertEqual(len([item for item in kb.clauses if item.clause_id == "3"]), 1)
        self.assertEqual(len(kb.definitions), 85)

    def test_20_iec_60335_regression(self):
        blocks = GenericIECStructuralParser(ROOT / "RawData/US_IEC_60335-1-01_01_2010-en-Aktuell__geaendert.pdf").parse()
        self.assertEqual(len({(item.semantic_context, item.block_id) for item in blocks}), len(blocks))

    def test_21_iec_60204_regression(self):
        ids = {item.block_id for item in GenericIECStructuralParser(ROOT / "RawData/IEC 60204-1pdf.pdf").parse()}
        self.assertTrue(any(item.startswith("18.") for item in ids))

    def test_22_iec_62841_101_series_regression(self):
        blocks = GenericIECStructuralParser(ROOT / "RawData/EN 62841-2-1 .pdf").parse()
        self.assertTrue(any(item.block_id.endswith(".101") for item in blocks))
        self.assertNotIn("0.5", {item.block_id for item in blocks})

    def test_23_iec_61427_clause_9_regression(self):
        ids = {item.block_id for item in GenericIECStructuralParser(ROOT / "RawData/US_IEC_61427-1 .pdf").parse()}
        self.assertIn("9", ids)
        self.assertIn("8.4.6", ids)

    def test_24_downstream_behavior_regression(self):
        names = [
            "washing_machine_31mb", "submersible_pump_31mb", "plastic_tube_welding_31mb",
            "iec_60204_31mb", "iec_62841_31mb", "iec_61427_31mb",
        ]
        self.assertTrue(all(
            (ROOT / "test_reports/output" / name / "decisions/final_compliance_response.json").is_file()
            for name in names
        ))


if __name__ == "__main__":
    unittest.main(verbosity=2)
