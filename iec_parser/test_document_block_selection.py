import unittest
from pathlib import Path
from types import SimpleNamespace

from iec_parser.pdf_knowledge_base import (
    Clause,
    IECBlockExtractor,
    IECClauseEnricher,
    IECClauseParser,
    IECDocumentProfile,
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

    def test_normative_operator_phrases_are_validated(self) -> None:
        limits = IECClauseEnricher._parse_limits(
            "The rated voltage shall not exceed 1 000 V and the test current "
            "shall be at least 2 A; insulation resistance shall be not less than 5 MΩ."
        )

        self.assertEqual([item["operator"] for item in limits], ["<=", ">=", ">="])
        self.assertTrue(all(
            item["operator_validation"] == "validated_normative_phrase"
            for item in limits
        ))
        self.assertEqual([item["parameter_context"] for item in limits], [
            "rated voltage", "test current", "insulation resistance",
        ])

    def test_parameter_resolver_uses_unit_and_full_sentence_context(self) -> None:
        limits = IECClauseEnricher._parse_limits(
            "The rated voltage shall not exceed 1 kV, leakage current shall not "
            "exceed 3 mA, supply frequency shall be 50 Hz, duration shall be 60 s, "
            "insulation resistance shall be at least 2 MΩ, and input power 500 W."
        )

        self.assertEqual([item["parameter"] for item in limits], [
            "rated_voltage", "leakage_current", "supply_frequency", "duration",
            "insulation_resistance", "power",
        ])
        self.assertTrue(all(
            item["parameter_resolution"] == "context_and_unit_validated"
            for item in limits
        ))

    def test_numeric_values_are_normalized_to_evaluation_units(self) -> None:
        limits = IECClauseEnricher._parse_limits(
            "The voltage shall not exceed 2 kV, current 500 mA, frequency 2 kHz, "
            "duration 2 min, resistance 3 MΩ, and power 1 500 W."
        )

        self.assertEqual([item["normalized_value"] for item in limits], [
            2000.0, 0.5, 2000.0, 120.0, 3000000.0, 1500.0,
        ])
        self.assertEqual([item["normalized_unit"] for item in limits], [
            "V", "A", "Hz", "s", "Ω", "W",
        ])
        self.assertTrue(all(
            item["numeric_normalization_status"] == "normalized" for item in limits
        ))

    def test_mandatory_limit_is_also_a_requirement(self) -> None:
        section = Clause(
            id="4.2",
            title="Voltage withstand",
            level=2,
            parent_id="4",
            kind="subclause",
            page_start=1,
            page_end=1,
            paragraphs=["The rated voltage shall not exceed 1 000 V."],
        )
        section.text = section.paragraphs[0]

        IECClauseEnricher(Path("final.pdf")).enrich(section)

        self.assertTrue(section.mandatory)
        self.assertEqual(len(section.requirements), 1)
        self.assertEqual(len(section.limits), 1)

    def test_test_evaluation_readiness_requires_numeric_criteria_and_acceptance(self) -> None:
        section = Clause(
            id="4.3",
            title="Dielectric test",
            level=2,
            parent_id="4",
            kind="subclause",
            page_start=1,
            page_end=1,
            paragraphs=[
                "The equipment shall be tested at a test voltage of at least 2 kV."
            ],
        )
        section.text = section.paragraphs[0]

        IECClauseEnricher(Path("final.pdf")).enrich(section)

        self.assertEqual(
            section.compliance["test_evaluation_readiness"]["status"],
            "ready_for_numeric_evaluation",
        )
        self.assertEqual(section.tests[0]["evaluation_inputs"][0]["normalized_value"], 2000.0)

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
        self.assertEqual(tables[1][0]["semantic_validation"]["status"], "validated")
        self.assertEqual(
            tables[1][0]["semantic_validation"]["classification"],
            "compliance_or_limit_table",
        )

    def test_ragged_table_requires_semantic_review(self) -> None:
        validation = IECClauseParser._table_semantic_validation(
            ["Voltage", "Result"], [["1 000 V"]]
        )

        self.assertEqual(validation["status"], "needs_domain_review")
        self.assertFalse(validation["row_shape_valid"])

    def test_inline_licence_footer_is_removed_without_losing_clause_text(self) -> None:
        text = (
            "The enclosure shall withstand 1 000 V. Licensed to Example Ltd / "
            "Max. Networking: 3 / downloaded: 2026-01-01"
        )

        clean = IECBlockExtractor._strip_licence_contamination(text)

        self.assertEqual(clean, "The enclosure shall withstand 1 000 V.")
        self.assertTrue(IECBlockExtractor._is_licence_or_footer("Licensed by Example Ltd"))


if __name__ == "__main__":
    unittest.main()
