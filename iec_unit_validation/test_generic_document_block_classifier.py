"""Focused tests for context-aware structural block classification."""

from __future__ import annotations

import unittest
from pathlib import Path

from iec_par.generic_document_block_classifier import (
    DocumentBlockType,
    GenericDocumentBlockClassifier,
    SourceTextBlock,
)
from iec_par.generic_iec_structural_parser import GenericIECStructuralParser


class GenericDocumentBlockClassifierTests(unittest.TestCase):
    def classify(self, text: str):
        blocks = [SourceTextBlock(line, 1, index) for index, line in enumerate(text.splitlines())]
        return GenericDocumentBlockClassifier().classify(blocks)

    def ids(self, text: str):
        return [block.block_id for block in GenericIECStructuralParser.parse_text(text)]

    def test_01_simple_clause_heading(self):
        self.assertEqual(self.classify("1 Scope\nThis standard applies.")[0].block_type, DocumentBlockType.CLAUSE_HEADING)

    def test_02_split_line_clause_heading(self):
        self.assertEqual(self.classify("8\nMarking\nThe marking shall be durable.")[0].block_type, DocumentBlockType.CLAUSE_HEADING)
        self.assertIn("8", self.ids("8\nMarking\nThe marking shall be durable."))

    def test_03_nested_clause_heading(self):
        self.assertEqual(self.ids("8 Marking\nBody text applies.\n8.1 General\nThe marking shall remain legible."), ["8", "8.1"])

    def test_04_table_title(self):
        self.assertEqual(self.classify("Table 2 - Values")[0].block_type, DocumentBlockType.TABLE_TITLE)

    def test_05_table_header(self):
        classified = self.classify("Table 2 - Values\nItem Value Unit")
        self.assertEqual(classified[1].block_type, DocumentBlockType.TABLE_HEADER)

    def test_06_numeric_table_row(self):
        classified = self.classify("Table 2 - Values\nItem Value\n1\n40 °C")
        self.assertEqual(classified[2].block_type, DocumentBlockType.TABLE_ROW)

    def test_07_decimal_table_code(self):
        self.assertNotIn("1.1", self.ids("8 Classification\nTable 2 - Codes\nCode Type\n1.1 Single pole\n1.2 Double pole"))

    def test_08_unit_bearing_table_row(self):
        classified = self.classify("Table 2 - Values\nItem Value\n1\n250 V")
        self.assertEqual(classified[3].block_type, DocumentBlockType.TABLE_ROW)

    def test_09_table_row_followed_by_table_row(self):
        self.assertEqual(self.ids("1 Scope\nTable 2 - Codes\n1.1 First type\n2.1 Second type"), ["1", "2"])

    def test_10_genuine_clause_after_table(self):
        text = "7 Classification\nTable 2 - Codes\nCode Type\n1.1 Single pole\n8 Marking\nThe marking shall be durable."
        self.assertIn("8", self.ids(text))

    def test_11_list_item(self):
        self.assertEqual(self.classify("- first item")[0].block_type, DocumentBlockType.LIST_ITEM)

    def test_12_definition_entry(self):
        classified = self.classify("3 Terms and definitions\n3.1 rated value\nTerm defined as a declared value.")
        self.assertEqual(classified[1].block_type, DocumentBlockType.DEFINITION_ENTRY)

    def test_13_note(self):
        self.assertEqual(self.classify("NOTE This is informative.")[0].block_type, DocumentBlockType.NOTE)

    def test_14_annex_heading(self):
        self.assertEqual(self.classify("Annex A - Tests")[0].block_type, DocumentBlockType.ANNEX_HEADING)

    def test_15_ambiguous_numeric_block(self):
        item = self.classify("1.1\n2.1")[0]
        self.assertEqual(item.block_type, DocumentBlockType.UNKNOWN)
        self.assertFalse(item.structural_heading_candidate)

    def test_16_hierarchy_continuity(self):
        self.assertEqual(self.ids("10 Operation\nBody applies.\n10.1 General\nThe equipment shall operate."), ["10", "10.1"])

    def test_17_page_transition_table_context(self):
        blocks = GenericIECStructuralParser.parse_pages(["8 Tests\nTable 1 - Current\nItem Value", "9\nI10 (A)\n8.1 Capacity\nThe capacity shall be stated."])
        self.assertNotIn("9", [block.block_id for block in blocks])

    def test_18_clause_nine_protection(self):
        self.assertNotIn("9", self.ids("8 Tests\nTable 1 - Current\nItem Value\n9\nI10 (A)"))

    def test_19_footnote_protection(self):
        self.assertEqual(self.ids("1 Scope\nBody applies.\n1 Under consideration.\n2 References\nReferences apply."), ["1", "2"])

    def test_20_101_series_protection(self):
        ids = self.ids("19 Tests\nBody applies.\n19.101 Additional test\nThe tool shall withstand the test.\n19.102 Second test\nThe tool shall remain safe.")
        self.assertEqual(ids, ["19", "19.101", "19.102"])

    def test_21_real_unseen_table_codes_are_not_clauses(self):
        path = Path("RawData/IEC 61058 .pdf")
        blocks = GenericIECStructuralParser(path).parse()
        contaminated = [
            block for block in blocks
            if block.block_type in {"CLAUSE", "SUBCLAUSE", "DEFINITION_SECTION"}
            and 31 <= block.page_start <= 41
            and block.block_id not in {
                "7.23", "7.23.1", "7.23.2", "7.23.3", "7.23.4", "7.23.5",
                "8", "8.1", "8.1.1", "8.1.2", "8.1.3", "8.2",
            }
        ]
        self.assertEqual(contaminated, [])

    def test_22_real_unseen_clauses_and_tables_are_retained(self):
        blocks = GenericIECStructuralParser(Path("RawData/IEC 61058 .pdf")).parse()
        ids = {block.block_id for block in blocks}
        self.assertTrue({str(value) for value in range(8, 13)}.issubset(ids))
        for table_id in ("2", "3"):
            table = next(block for block in blocks if block.block_type == "TABLE" and block.block_id == table_id)
            self.assertGreater(len(table.raw_text), 1000)

    def test_23_real_numeric_table_clause_protection(self):
        blocks = GenericIECStructuralParser(Path("RawData/US_IEC_61427-1 .pdf")).parse()
        ids = {block.block_id for block in blocks}
        self.assertIn("9", ids)
        self.assertIn("8.4.6", ids)

    def test_24_real_footnote_and_late_heading_protection(self):
        blocks = GenericIECStructuralParser(Path("RawData/IEC 60204-1pdf.pdf")).parse()
        ids = [block.block_id for block in blocks if block.block_type in {"CLAUSE", "SUBCLAUSE", "DEFINITION_SECTION"}]
        self.assertEqual(ids.count("1"), 1)
        self.assertTrue({"5.3", "10.3", "12.7"}.issubset(ids))

    def test_25_real_101_series_protection(self):
        blocks = GenericIECStructuralParser(Path("RawData/EN 62841-2-1 .pdf")).parse()
        self.assertTrue(any(block.block_id.endswith(".101") for block in blocks))

    def test_26_annex_prefixed_hierarchy(self):
        blocks = GenericIECStructuralParser.parse_text(
            "Annex A - Tests\nA.1 General\nThe test shall be performed.\n"
            "A.1.1 Sequence\nThe sequence shall be recorded."
        )
        parents = {block.block_id: block.parent_id for block in blocks}
        self.assertEqual(parents["A.1.1"], "A.1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
