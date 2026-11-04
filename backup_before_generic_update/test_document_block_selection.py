import unittest
from pathlib import Path
from types import SimpleNamespace

from iec_parser1.pdf_knowledge_base import (
    Clause,
    IECBlockExtractor,
    IECClauseEnricher,
    IECClauseParser,
    IECDocumentProfile,
    IECHeadingDetector,
)


class DocumentBlockSelectionTests(unittest.TestCase):
    def test_selects_english_child_of_final_block_not_redline(self) -> None:
        toc = [
            (1, "Redline version", 5),
            (2, "English", 6),
            (3, "1 Scope", 19),
            (2, "Français", 144),
            (1, "Final version", 287),
            (2, "English", 288),
            (3, "1 Scope", 301),
            (2, "Français", 431),
        ]

        selected = IECDocumentProfile._select_document_block(toc, 570)

        self.assertEqual(selected["version"], "final")
        self.assertEqual(selected["english_start"], 288)
        self.assertEqual(selected["english_end"], 430)
        self.assertEqual(selected["rejected_blocks"], ["redline"])

    def test_rejects_a_redline_only_document(self) -> None:
        with self.assertRaisesRegex(ValueError, "redline-only"):
            IECDocumentProfile._select_document_block(
                [(1, "Redline version", 5), (2, "English", 6)], 100
            )

    def test_enrichment_is_derived_from_selected_final_text(self) -> None:
        section = Clause(
            id="4.1",
            title="Final requirement",
            level=2,
            parent_id="4",
            kind="subclause",
            page_start=301,
            page_end=301,
            paragraphs=[
                "The enclosure shall withstand 2 kV.",
                "Compliance is checked by the following test.",
                "NOTE Informative guidance.",
            ],
        )
        section.text = "\n\n".join(section.paragraphs)

        IECClauseEnricher(Path("final.pdf")).enrich(section)

        derived = " ".join(
            [section.summary, section.compliance_requirement or ""]
            + [item["text"] for item in section.requirements + section.tests + section.limits + section.notes]
            + [section.compliance["pass_condition"] or "", section.compliance["fail_condition"] or ""]
        )
        self.assertIn("2 kV", derived)
        self.assertNotIn("redline-only 1 kV", derived)
        self.assertTrue(section.mandatory)
        self.assertTrue(section.test_required)

    def test_grouped_numbers_and_semantic_parameters_are_normalized(self) -> None:
        limits = IECClauseEnricher._parse_limits(
            "The test voltage shall be at least 1 000 V and the rated current 2\u202f000 mA."
        )

        self.assertEqual([limit["value"] for limit in limits], [1000.0, 2000.0])
        self.assertEqual(limits[0]["parameter"], "test_voltage")
        self.assertEqual(limits[1]["parameter"], "rated_current")

    def test_scope_limits_do_not_become_compliance_criteria(self) -> None:
        section = Clause(
            id="1.1",
            title="Scope",
            level=2,
            parent_id="1",
            kind="subclause",
            page_start=1,
            page_end=1,
            paragraphs=["This document applies to equipment with a rated voltage of 1 000 V."],
        )
        section.text = section.paragraphs[0]

        IECClauseEnricher(Path("final.pdf")).enrich(section)

        self.assertEqual(section.limits, [])
        self.assertEqual(section.scope_limits[0]["value"], 1000.0)
        self.assertIsNone(section.compliance_requirement)
        self.assertIsNone(section.compliance["pass_condition"])

    def test_acceptance_criteria_deduplicate_repeated_text(self) -> None:
        criteria = {"text": "The enclosure shall withstand 1 000 V.", "normative": True}
        pass_condition, fail_condition = IECClauseEnricher._acceptance_criteria(
            Clause("4.1", None, 2, "4", "subclause", 1, 1),
            {"requirements": [criteria], "tests": [criteria], "limits": [criteria]},
        )

        self.assertEqual(pass_condition.count("1 000 V"), 1)
        self.assertEqual(fail_condition.count("1 000 V"), 1)

    def test_informative_annex_does_not_create_compliance_requirement(self) -> None:
        section = Clause(
            id="A.1",
            title="Guidance",
            level=2,
            parent_id="annex:A",
            kind="annex_clause",
            page_start=1,
            page_end=1,
            annex_type="informative",
            paragraphs=["The guidance shall be considered during design."],
        )
        section.text = section.paragraphs[0]

        IECClauseEnricher(Path("final.pdf")).enrich(section)

        self.assertEqual(section.semantic_classification, "informative_annex_content")
        self.assertFalse(section.mandatory)
        self.assertIsNone(section.compliance_requirement)
        self.assertEqual(section.scope_applicability["status"], "informative_annex")

    def test_normative_reference_sections_do_not_emit_compliance_items(self) -> None:
        section = Clause(
            id="2",
            title="Normative references",
            level=1,
            parent_id=None,
            kind="clause",
            page_start=1,
            page_end=1,
            paragraphs=["IEC 60601-1:2020 shall be used at 1 000 V for the test."],
        )
        section.text = section.paragraphs[0]

        IECClauseEnricher(Path("final.pdf")).enrich(section)

        self.assertEqual(section.semantic_classification, "normative_reference")
        self.assertEqual(section.requirements, [])
        self.assertEqual(section.tests, [])
        self.assertEqual(section.limits, [])
        self.assertFalse(section.mandatory)
        self.assertFalse(section.test_required)
        self.assertIsNone(section.compliance_requirement)
        self.assertIsNone(section.compliance["pass_condition"])
        self.assertEqual(section.normative_references[0]["identifier"], "IEC 60601-1:2020")

    def test_definition_titles_and_false_unresolved_test_references_are_cleaned(self) -> None:
        section = Clause(
            id="3.7.4",
            title="hand-held appliance portable appliance",
            level=3,
            parent_id="3.7",
            kind="subclause",
            page_start=1,
            page_end=1,
            paragraphs=["A test description is provided for context."],
        )
        section.text = section.paragraphs[0]

        IECClauseEnricher(Path("final.pdf")).enrich(section)

        self.assertEqual(section.title, "hand-held appliance")
        self.assertEqual(
            IECClauseEnricher._clean_definition_title(
                "self-resetting thermal cut-out thermal cut-out"
            ),
            "self-resetting thermal cut-out",
        )
        self.assertEqual(section.unresolved_cross_references, [])

    def test_structured_table_preserves_header_and_rows(self) -> None:
        class Header:
            external = False
            names = ["Rated voltage", "Result"]

        class Table:
            bbox = (1.0, 2.0, 3.0, 4.0)
            header = Header()

            @staticmethod
            def extract():
                return [["Rated voltage", "Result"], ["1 000 V", "Pass"]]

        class Page:
            @staticmethod
            def find_tables():
                return SimpleNamespace(tables=[Table()])

        class Document:
            @staticmethod
            def __getitem__(_index):
                return Page()

        tables = IECClauseParser._tables_by_page(
            Document(), SimpleNamespace(_english_page_start=1, _english_page_end=1)
        )

        self.assertEqual(tables[1][0]["header"], ["Rated voltage", "Result"])
        self.assertEqual(tables[1][0]["rows"], [["1 000 V", "Pass"]])

    def test_inline_licence_footer_is_removed_without_losing_clause_text(self) -> None:
        text = (
            "The enclosure shall withstand 1 000 V. Licensed to Example Ltd / "
            "Max. Networking: 3 / downloaded: 2026-01-01"
        )

        clean = IECBlockExtractor._strip_licence_contamination(text)

        self.assertEqual(clean, "The enclosure shall withstand 1 000 V.")
        self.assertTrue(IECBlockExtractor._is_licence_or_footer("Licensed by Example Ltd"))

    def test_detects_identifier_last_subclause_using_generic_toc_validation(self) -> None:
        profile = SimpleNamespace(
            _main_roots={"4"},
            _annex_roots=set(),
            _known_clause_ids={"4", "4.4", "4.4.10"},
            _toc_titles_by_id={"4.4.10": "Operating temperature"},
            _main_body_last_page=None,
        )
        detector = IECHeadingDetector(profile)
        block = SimpleNamespace(
            text="Operating temperature 4.4.10",
            page=12,
            first_bold=True,
            font_size=10.0,
            leading_bold_text="Operating temperature 4.4.10",
        )

        self.assertEqual(
            detector.heading(block),
            ("4.4.10", "Operating temperature", "subclause", None),
        )

    def test_identifier_last_detection_rejects_bold_cross_reference_prose(self) -> None:
        profile = SimpleNamespace(
            _main_roots={"4"},
            _annex_roots=set(),
            _known_clause_ids={"4.4.10"},
            _toc_titles_by_id={"4.4.10": "Operating temperature"},
            _main_body_last_page=None,
        )
        detector = IECHeadingDetector(profile)
        block = SimpleNamespace(
            text="The test shall be performed according to 4.4.10",
            page=12,
            first_bold=True,
            font_size=10.0,
            leading_bold_text="The test shall be performed according to 4.4.10",
        )

        self.assertIsNone(detector.heading(block))

    def test_identifier_last_detection_requires_toc_title_similarity(self) -> None:
        profile = SimpleNamespace(
            _main_roots={"4"},
            _annex_roots=set(),
            _known_clause_ids={"4.4.10"},
            _toc_titles_by_id={"4.4.10": "Operating temperature"},
            _main_body_last_page=None,
        )
        detector = IECHeadingDetector(profile)
        block = SimpleNamespace(
            text="Unrelated bold statement 4.4.10",
            page=12,
            first_bold=True,
            font_size=10.0,
            leading_bold_text="Unrelated bold statement 4.4.10",
        )

        self.assertIsNone(detector.heading(block))

    def test_identifier_last_annex_subclause_is_supported_generically(self) -> None:
        profile = SimpleNamespace(
            _main_roots=set(),
            _annex_roots={"A"},
            _known_clause_ids={"A.3"},
            _toc_titles_by_id={"A.3": "Test method"},
            _main_body_last_page=None,
        )
        detector = IECHeadingDetector(profile)
        block = SimpleNamespace(
            text="Test method A.3",
            page=30,
            first_bold=True,
            font_size=10.0,
            leading_bold_text="Test method A.3",
        )

        self.assertEqual(
            detector.heading(block),
            ("A.3", "Test method", "annex_clause", None),
        )


    def test_embedded_identifier_from_line_wrap_is_reconstructed_generically(self) -> None:
        profile = SimpleNamespace(
            _main_roots={"8"},
            _annex_roots=set(),
            _known_clause_ids={"8.4.6"},
            _toc_titles_by_id={
                "8.4.6": "Water consumption of flooded battery types and cells with partial gas recombination"
            },
            _main_body_last_page=None,
        )
        detector = IECHeadingDetector(profile)
        block = SimpleNamespace(
            text="Water consumption of flooded battery types and cells with partial gas 8.4.6 recombination",
            page=18,
            first_bold=True,
            font_size=10.0,
            leading_bold_text="Water consumption of flooded battery types and cells with partial gas 8.4.6 recombination",
        )

        self.assertEqual(
            detector.heading(block),
            (
                "8.4.6",
                "Water consumption of flooded battery types and cells with partial gas recombination",
                "subclause",
                None,
            ),
        )



if __name__ == "__main__":
    unittest.main()