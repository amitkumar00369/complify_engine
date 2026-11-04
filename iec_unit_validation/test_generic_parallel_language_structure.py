"""Focused tests for generic parallel-language structural ownership."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from iec_par.generic_document_stream_resolver import GenericDocumentStreamResolver
from iec_par.generic_iec_structural_parser import GenericIECStructuralParser


class GenericParallelLanguageStructureTests(unittest.TestCase):
    def ids(self, text):
        return [x.block_id for x in GenericIECStructuralParser.parse_text(text)]

    def test_01_monolingual_standard_unchanged(self):
        self.assertEqual(self.ids("1 Scope\nText\n2 References\nText\n3 Requirements\nText"), ["1", "2", "3"])

    def test_02_bilingual_sequential_standard(self):
        text = "1 Scope\nPrimary\n2 References\fSOMMAIRE\f1 Domaine d application\nSecondaire\n2 Références"
        self.assertEqual(self.ids(text), ["1", "2"])

    def test_03_second_hierarchy_restart_is_parallel(self):
        pages = ["1 Scope\nText\n2 Terms", "SOMMAIRE", "1 Domaine d application\nTexte\n2 Termes"]
        result = GenericDocumentStreamResolver().resolve(pages)
        self.assertEqual((result.page_start, result.page_end), (1, 1))
        self.assertEqual(result.parallel_ranges, ((3, 3),))

    def test_04_repeated_clause_one_footnote_is_not_restart(self):
        pages = ["1 Scope\nText\n2 References", "1 Under consideration.\n3 Terms\n4 Requirements"]
        self.assertEqual(GenericDocumentStreamResolver().resolve(pages).page_end, 2)

    def test_05_repeated_numeric_text_does_not_cut_stream(self):
        text = "1 Scope\nText\n2 References\n1 N test force\n3 Requirements"
        self.assertEqual(self.ids(text), ["1", "2", "3"])

    def test_06_canonical_hierarchy_retained(self):
        blocks = GenericIECStructuralParser.parse_pages(["1 General\n1.1 Scope\nText\n2 Terms", "3 Requirements"])
        self.assertTrue({"1", "1.1", "2", "3"}.issubset({x.block_id for x in blocks}))

    def test_07_parallel_provenance_preserved(self):
        pages = ["1 Scope\nText\n2 Terms", "SOMMAIRE", "1 Domaine d application\nTexte\n2 Termes"]
        self.assertEqual(GenericDocumentStreamResolver().resolve(pages).parallel_ranges, ((3, 3),))

    def test_08_duplicate_canonical_clauses_prevented(self):
        text = "1 Scope\nText\n2 Terms\fSOMMAIRE\f1 Domaine d application\nTexte\n2 Termes"
        ids = self.ids(text)
        self.assertEqual((ids.count("1"), ids.count("2")), (1, 1))

    def test_09_figure_numeric_scale_not_clause(self):
        self.assertEqual(self.ids("1 Scope\nFigure 1 - Force\n50\n100\nN\n2 References"), ["1", "2"])

    def test_10_table_numeric_scale_not_clause(self):
        ids = self.ids("1 Scope\nTable 1 - Values\nValue N\n50\n100\n2 References")
        self.assertNotIn("50", ids)
        self.assertNotIn("100", ids)

    def test_11_genuine_numeric_clause_with_title_retained(self):
        self.assertEqual(self.ids("9 Mechanical hazards\n9.1 General\nRequirement text"), ["9", "9.1"])

    def test_12_nested_clauses_retained(self):
        self.assertEqual(self.ids("14 Components\n14.1 General\n14.1.1 Switches"), ["14", "14.1", "14.1.1"])

    def test_13_annex_hierarchy_retained(self):
        blocks = GenericIECStructuralParser.parse_text("1 Scope\nAnnex A\n(normative)\nTests\nA.1 General")
        self.assertTrue(any(x.block_type == "ANNEX" and x.block_id == "A" for x in blocks))

    def test_14_definitions_structurally_reachable(self):
        blocks = GenericIECStructuralParser.parse_text("1 General\n1.1 Scope\nText\n2 Terms and definitions\n2.1 Terms")
        self.assertTrue(any(x.block_id == "2" and x.semantic_context == "DEFINITION" for x in blocks))

    def test_15_iec_60204_footnote_regression(self):
        blocks = GenericIECStructuralParser(ROOT / "RawData/IEC 60204-1pdf.pdf").parse()
        self.assertTrue({"1", "2", "3"}.issubset({x.block_id for x in blocks}))
        self.assertFalse(any(x.block_id == "1" and "Under consideration" in (x.title or "") for x in blocks))

    def test_16_iec_61058_table_regression(self):
        path = next((ROOT / "RawData").glob("*61058*.pdf"))
        blocks = GenericIECStructuralParser(path).parse()
        self.assertEqual(sum(x.level == 1 and x.block_id == "60" for x in blocks), 0)
        self.assertIn("3", {x.block_id for x in blocks})

    def test_17_iec_61427_clause_nine_regression(self):
        path = next((ROOT / "RawData").glob("*61427-1*.pdf"))
        blocks = GenericIECStructuralParser(path).parse()
        self.assertEqual(sum(x.level == 1 and x.block_id == "9" for x in blocks), 1)

    def test_18_iec_62841_101_series_regression(self):
        part = next((ROOT / "RawData").glob("*62841-2-1*.pdf"))
        base = next((ROOT / "RawData").glob("*62841-1-01*.pdf"))
        part_ids = {x.block_id for x in GenericIECStructuralParser(part).parse()}
        base_ids = {x.block_id for x in GenericIECStructuralParser(base).parse()}
        self.assertTrue(any("101" in x for x in part_ids))
        self.assertIn("K.28.2", base_ids)

    def test_19_iec_60335_part_two_regression(self):
        path = next((ROOT / "RawData").glob("*60335-2-7*.pdf"))
        ids = {x.block_id for x in GenericIECStructuralParser(path).parse()}
        self.assertTrue({"1", "2", "3"}.issubset(ids))

    def test_20_no_family_specific_branch(self):
        files = [ROOT / "iec_par/generic_document_stream_resolver.py",
                 ROOT / "iec_par/generic_iec_structural_parser.py"]
        production = "\n".join(x.read_text().casefold() for x in files)
        for token in ["60065", "speaker", "60335", "60204", "62841", "61427", "61058"]:
            self.assertNotIn(token, production)


if __name__ == "__main__":
    unittest.main(verbosity=2)
