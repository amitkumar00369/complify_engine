"""Focused tests for persistent generic table ownership."""

from __future__ import annotations

import unittest
from pathlib import Path

from iec_par.generic_document_block_classifier import (
    DocumentBlockType,
    GenericDocumentBlockClassifier,
    SourceTextBlock,
)
from iec_par.generic_iec_structural_parser import GenericIECStructuralParser


class GenericPersistentTableOwnershipTests(unittest.TestCase):
    def classify_pages(self, *pages: str):
        blocks = []
        order = 0
        for page_number, page in enumerate(pages, 1):
            for line in page.splitlines():
                blocks.append(SourceTextBlock(line, page_number, order))
                order += 1
        return GenericDocumentBlockClassifier().classify(blocks)

    @staticmethod
    def structural_ids(*pages: str):
        return [block.block_id for block in GenericIECStructuralParser.parse_pages(pages)]

    def test_01_simple_table_ownership(self):
        items = self.classify_pages("Table 4 - Values\nItem Value\nA 10")
        self.assertTrue(all(item.internal_table_ownership_id for item in items))
        self.assertEqual({item.owning_table_id for item in items}, {"4"})

    def test_02_numeric_table_rows(self):
        items = self.classify_pages("Table 4 - Values\nItem Value\n1\n2")
        self.assertTrue(all(item.block_type == DocumentBlockType.TABLE_ROW for item in items[2:]))

    def test_03_decimal_like_identifiers(self):
        ids = self.structural_ids("8 Tests\nTable 4 - Codes\nCode Type\n1.1 First\n2.1 Second")
        self.assertNotIn("1.1", ids)
        self.assertNotIn("2.1", ids)

    def test_04_table_page_break(self):
        items = self.classify_pages("Table 4 - Values\nItem Value\n1 10", "2 20")
        self.assertEqual(items[-1].owning_table_id, "4")
        self.assertIn("page transition does not terminate table", items[-1].ownership_reasons)

    def test_05_repeated_header_after_page_break(self):
        items = self.classify_pages("Table 4 - Values\nItem Value Unit\n1 10 V", "Item Value Unit\n2 20 V")
        repeated = next(item for item in items if item.page == 2 and item.normalized_text == "Item Value Unit")
        self.assertEqual(repeated.block_type, DocumentBlockType.TABLE_HEADER)
        self.assertIn("repeated table-header signature", repeated.ownership_reasons)

    def test_06_continuation_without_repeated_header(self):
        items = self.classify_pages("Table 4 - Values\nItem Value\n1 10", "2 20\n3 30")
        self.assertTrue(all(item.owning_table_id == "4" for item in items[-2:]))

    def test_07_footer_header_interruption(self):
        items = self.classify_pages("Table 4 - Values\n1 10\nPage 1 of 2", "- 2 -\n2 20")
        self.assertEqual(items[-1].owning_table_id, "4")
        interruptions = [item for item in items if item.block_type == DocumentBlockType.HEADER_FOOTER]
        self.assertTrue(interruptions)
        self.assertTrue(all("layout header/footer interruption retained" in item.ownership_reasons for item in interruptions))

    def test_08_wrapped_table_row(self):
        items = self.classify_pages("Table 4 - Values\n1 Long requirement text begins\ncontinuation of the same cell\nadditional continuation")
        self.assertTrue(all(item.internal_table_ownership_id == items[0].internal_table_ownership_id for item in items[1:]))

    def test_09_genuine_clause_after_table(self):
        ids = self.structural_ids("8 Tests\nTable 4 - Values\nItem Value\n1 10\n9 Construction\nThe equipment shall be guarded.")
        self.assertIn("9", ids)

    def test_10_split_line_clause_after_table(self):
        ids = self.structural_ids("8 Tests\nTable 4 - Values\nItem Value\n1 10\n9\nConstruction\nThe equipment shall be guarded.")
        self.assertIn("9", ids)

    def test_11_new_table_transition(self):
        items = self.classify_pages("Table 2 - First\n1 10\nTable 3 - Second\n2 20")
        first, second = items[0], items[2]
        self.assertNotEqual(first.internal_table_ownership_id, second.internal_table_ownership_id)
        self.assertEqual((first.owning_table_id, second.owning_table_id), ("2", "3"))

    def test_12_continued_table_label(self):
        items = self.classify_pages("Table 4 - Values\n1 10", "Table 4 (continued)\n2 20")
        self.assertEqual(items[0].internal_table_ownership_id, items[2].internal_table_ownership_id)
        self.assertIn("explicit continued-table label", items[2].ownership_reasons)

    def test_13_sparse_table_rows(self):
        items = self.classify_pages("Table 4 - Values\n1\n\n\n10")
        self.assertEqual(items[-1].owning_table_id, "4")

    def test_14_unit_bearing_rows(self):
        items = self.classify_pages("Table 4 - Values\n250 V\n10 A\n50 Hz")
        self.assertTrue(all(item.table_row_candidate for item in items[1:]))

    def test_15_ambiguous_numeric_continuation(self):
        items = self.classify_pages("Table 4 - Values\n1.1\n2.1\n4.1")
        self.assertTrue(all(item.owning_table_id == "4" for item in items[1:]))
        self.assertTrue(all(not item.structural_heading_candidate for item in items[1:]))

    def test_16_non_table_numeric_prose(self):
        items = self.classify_pages("9 Construction\nThe equipment shall be guarded.\n250 V")
        self.assertEqual(items[0].block_type, DocumentBlockType.CLAUSE_HEADING)
        self.assertIsNone(items[-1].owning_table_id)

    def test_17_annex_after_table(self):
        items = self.classify_pages("Table 4 - Values\n1 10\nAnnex A - Tests")
        self.assertEqual(items[-1].block_type, DocumentBlockType.ANNEX_HEADING)
        self.assertIsNone(items[-1].internal_table_ownership_id)

    def test_18_list_after_table_remains_owned(self):
        items = self.classify_pages("Table 4 - Values\n- wrapped cell item")
        self.assertEqual(items[-1].block_type, DocumentBlockType.LIST_ITEM)
        self.assertEqual(items[-1].owning_table_id, "4")

    def test_19_real_numeric_clause_nine_regression(self):
        blocks = GenericIECStructuralParser(Path("RawData/US_IEC_61427-1 .pdf")).parse()
        ids = {block.block_id for block in blocks}
        self.assertIn("9", ids)
        self.assertIn("8.4.6", ids)

    def test_20_real_decimal_table_rows_regression(self):
        blocks = GenericIECStructuralParser(Path("RawData/EN_62841-1-01_08_2015-en-Aktuell__geaendert.pdf")).parse()
        ids = {block.block_id for block in blocks}
        self.assertNotIn("0.5", ids)
        self.assertNotIn("0.8", ids)

    def test_21_real_101_series_regression(self):
        blocks = GenericIECStructuralParser(Path("RawData/EN 62841-2-1 .pdf")).parse()
        self.assertTrue(any(block.block_id.endswith(".101") for block in blocks))

    def test_22_real_footnote_regression(self):
        blocks = GenericIECStructuralParser(Path("RawData/IEC 60204-1pdf.pdf")).parse()
        ids = [block.block_id for block in blocks if block.block_type in {"CLAUSE", "SUBCLAUSE", "DEFINITION_SECTION"}]
        self.assertEqual(ids.count("1"), 1)

    def test_23_real_base_part2_and_annex_hierarchy(self):
        base = GenericIECStructuralParser(Path("RawData/US_IEC_60335-1-01_01_2010-en-Aktuell__geaendert.pdf")).parse()
        delta = GenericIECStructuralParser(Path("RawData/US_IEC_60335-2-7-01_01_2012-en-Aktuell__geaendert.pdf")).parse()
        self.assertTrue(any(block.block_type == "ANNEX" for block in base))
        self.assertTrue(any(block.block_id.endswith(".101") for block in delta))

    def test_24_source_footnote_marker_in_table_title(self):
        items = self.classify_pages(
            "8.4 Test\nTable A.2 e - Specific conditions\n1 10",
            "Table A.2 (continued) e\n2 20",
        )
        titles = [item for item in items if item.block_type == DocumentBlockType.TABLE_TITLE]
        self.assertEqual([item.owning_table_id for item in titles], ["A.2", "A.2"])
        self.assertEqual(titles[0].internal_table_ownership_id, titles[1].internal_table_ownership_id)

    def test_25_annex_context_anchors_its_table(self):
        items = self.classify_pages(
            "Annex K - Tests\nK.28 Distances\nK.28.1 Values shall comply.\n"
            "Table K.1 - Values\n1 10"
        )
        title = next(item for item in items if item.block_type == DocumentBlockType.TABLE_TITLE)
        self.assertEqual(title.owning_table_anchor_id, "K.28.1")

    def test_26_structural_status_declaration_terminates_table(self):
        ids = self.structural_ids(
            "Annex K - Tests\nK.28 Distances\nK.28.1 Values shall comply.\n"
            "Table K.1 - Values\n1 10\nK.28.2 This subclause is not applicable."
        )
        self.assertIn("K.28.2", ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
