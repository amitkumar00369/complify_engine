"""Step 31K-A regressions for generic structural and evidence ownership."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from iec_par.generic_iec_requirement_parser import GenericIECRequirementParser
from iec_par.generic_iec_structural_parser import GenericIECStructuralParser
from iec_par.generic_report_evidence_extractor import GenericReportEvidenceExtractor
from iec_par.generic_requirement_evidence_matcher import GenericRequirementEvidenceMatcher


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "test_reports" / "output"


class GenericStructuralTableOwnershipTests(unittest.TestCase):
    def blocks(self, text: str):
        return GenericIECStructuralParser.parse_text(text)

    def report(self, *pages: str):
        return GenericReportEvidenceExtractor().extract_from_pages(pages, file_name="sample.pdf")

    @staticmethod
    def report_nodes(document):
        output = []

        def walk(nodes):
            for node in nodes:
                output.append(node)
                walk(node.children)

        walk(document.clauses)
        return output

    def test_01_standalone_integer_table_cell_not_clause(self):
        self.assertEqual([b.block_id for b in self.blocks("8 Test\nTable 2 - Values\na)\n9\nI10 (A)")], ["8", "2"])

    def test_02_numeric_unit_row_not_clause(self):
        self.assertEqual([b.block_id for b in self.blocks("1 Scope\n40 °C\n2 References")], ["1", "2"])

    def test_03_percent_row_not_clause(self):
        self.assertEqual([b.block_id for b in self.blocks("1 Scope\n80 %\n2 References")], ["1", "2"])

    def test_04_real_single_digit_clause_heading_accepted(self):
        self.assertIn("7", [b.block_id for b in self.blocks("7 Marking\nThe marking shall be durable.")])

    def test_05_real_clause_nine_accepted(self):
        ids = [b.block_id for b in self.blocks("8 Tests\nBody\n9 Recommended use of tests\n9.1 General")]
        self.assertEqual(ids, ["8", "9", "9.1"])

    def test_06_fake_table_cell_nine_rejected(self):
        ids = [b.block_id for b in self.blocks("8 Tests\nTable 1 - Current\na)\n9\nI10 (A)\n8.1 Capacity")]
        self.assertNotIn("9", ids)

    def test_07_table_continuation_across_page_break(self):
        blocks = GenericIECStructuralParser.parse_pages(["8 Tests\nTable 1 - Current\na)", "9\nI10 (A)\n8.1 Capacity"])
        self.assertNotIn("9", [b.block_id for b in blocks])

    def test_08_repeated_table_header_does_not_create_clause(self):
        ids = [b.block_id for b in self.blocks("8 Tests\nTable 1 - Values\nItem Value\na)\nItem Value\n9\nI10 (A)")]
        self.assertEqual(ids, ["8", "1"])

    def test_09_next_clause_boundary_terminates_prior_clause(self):
        blocks = self.blocks("8.4.5 Water consumption shall be measured.\n8.4.6 Gas recombination shall be measured.")
        first = next(b for b in blocks if b.block_id == "8.4.5")
        self.assertNotIn("Gas recombination", first.raw_text)

    def test_10_wrapped_next_clause_heading_is_recovered(self):
        blocks = self.blocks("8.4.5 Water consumption of partial gas\n8.4.6\nrecombination\nThe value shall be recorded.")
        self.assertIn("8.4.6", [b.block_id for b in blocks])

    def test_11_composite_requirement_is_removed(self):
        values = ["Equipment shall be guarded. Wiring shall be insulated.", "Equipment shall be guarded.", "Wiring shall be insulated."]
        self.assertEqual(GenericIECRequirementParser._remove_composite_duplicates(values), values[1:])

    def test_12_independent_requirements_are_preserved(self):
        values = ["Equipment shall be guarded.", "Wiring shall be insulated."]
        self.assertEqual(GenericIECRequirementParser._remove_composite_duplicates(values), values)

    def test_13_repeated_header_filtered(self):
        text = "Equipment shall comply.\nPage 4 of 20\nEquipment shall remain safe."
        self.assertNotIn("Page 4", GenericIECRequirementParser._remove_layout_chrome(text))

    def test_14_repeated_footer_filtered(self):
        text = "Equipment shall comply.\n— 14 —\nEquipment shall remain safe."
        self.assertNotIn("14", GenericIECRequirementParser._remove_layout_chrome(text))

    def test_15_licence_text_filtered_generically(self):
        text = "Equipment shall comply.\nLicensed by Example Organization\nEquipment shall remain safe."
        self.assertNotIn("Licensed", GenericIECRequirementParser._remove_layout_chrome(text))

    def test_16_page_number_filtered(self):
        self.assertEqual(GenericIECRequirementParser._remove_layout_chrome("\n42\n"), "")

    def test_17_report_numeric_table_row_not_evidence_clause(self):
        ids = [n.clause_id for n in self.report_nodes(self.report("8\nTABLE: current\na)\n9\nI10 (A)\nP"))]
        self.assertNotIn("9", ids)

    def test_18_report_table_child_retains_parent(self):
        node = self.report_nodes(self.report("8.1\nSee appended table\nP\nTABLE: values\nMeasured current: 2 A\nP"))[0]
        self.assertEqual(node.evidence_items[1].parent_evidence_id, node.evidence_items[0].evidence_id)

    def test_19_deterministic_evidence_ids(self):
        pages = ("8.1\nSee appended table\nP\nTABLE: values\nMeasured current: 2 A\nP",)
        first = self.report_nodes(self.report(*pages))[0].evidence_items
        second = self.report_nodes(self.report(*pages))[0].evidence_items
        self.assertEqual([x.evidence_id for x in first], [x.evidence_id for x in second])

    def test_20_no_orphan_table_references(self):
        node = self.report_nodes(self.report("8.1\nSee appended table\nP\nTABLE: values\nP"))[0]
        ids = {x.evidence_id for x in node.evidence_items}
        self.assertTrue(all(x.parent_evidence_id in ids for x in node.evidence_items if x.parent_evidence_id))

    def test_21_sibling_verdicts_remain_isolated(self):
        nodes = self.report_nodes(self.report("8.1\nParent\n8.1.1\nRelevant\nP\n8.1.2\nOther\nN/A"))
        self.assertNotEqual(nodes[1].reported_verdict, nodes[2].reported_verdict)

    def test_22_grouped_verdict_not_promoted_to_children(self):
        nodes = self.report_nodes(self.report("8.1\nParent\nP\n8.1.1\nChild without verdict"))
        self.assertNotEqual(nodes[1].reported_verdict.value, "PASS")

    def test_23_semantically_scoped_child_supports_parent(self):
        result = self._child_match("Thermal endurance cycling shall be performed", "Thermal endurance cycling shall be performed", "Unrelated marking")
        self.assertEqual(result.match_type, "PARENT_REQUIREMENT_SUPPORTED_BY_CHILD_EVIDENCE")

    def test_24_unrelated_child_does_not_support_parent(self):
        result = self._child_match("Thermal endurance cycling shall be performed", "Packaging label inspected", "Terminal colour checked")
        self.assertNotEqual(result.match_type, "PARENT_REQUIREMENT_SUPPORTED_BY_CHILD_EVIDENCE")

    def test_25_real_clause_nine_hierarchy_preserved(self):
        blocks = self.blocks("9 Recommended use of tests\n9.1 General\n9.2 Test sequence\n9.2.1 Capacity test")
        parents = {b.block_id: b.parent_id for b in blocks}
        self.assertEqual((parents["9.1"], parents["9.2.1"]), ("9", "9.2"))

    def test_26_multilingual_second_block_not_merged(self):
        blocks = self.blocks("INTERNATIONAL STANDARD\nCONTENTS\f1 Scope\nEnglish text.\fSOMMAIRE\f1 Domaine d application\nTexte français.")
        self.assertTrue(all("français" not in b.raw_text for b in blocks))

    def test_27_unseen_family_regression_artifact_exists(self):
        self.assertTrue((OUTPUT / "iec_61427_1_battery_post_31ka" / "standards" / "base_kb.json").is_file())

    def test_28_first_accepted_family_regression_exists(self):
        self.assertTrue((OUTPUT / "washing_machine_post_31ka" / "decisions" / "final_compliance_response.json").is_file())

    def test_29_standalone_family_regression_exists(self):
        self.assertTrue((OUTPUT / "iec_60204_1_post_31ka" / "decisions" / "final_compliance_response.json").is_file())

    def test_30_second_accepted_family_regression_exists(self):
        self.assertTrue((OUTPUT / "iec_62841_impact_drill_post_31ka" / "decisions" / "final_compliance_response.json").is_file())

    def test_31_serialized_outputs_are_valid_json(self):
        paths = list((OUTPUT / "iec_61427_1_battery_post_31ka").rglob("*.json"))
        self.assertTrue(paths)
        for path in paths:
            json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _child_match(requirement_text: str, relevant: str, unrelated: str):
        matcher = GenericRequirementEvidenceMatcher()
        requirement = {"effective_requirement_id": "ER-1", "clause_id": "4.4", "effective_status": "ACTIVE", "effective_source_type": "BASE", "text": requirement_text}
        kb = {"effective_kb_id": "KB", "clauses": [{"effective_clause_id": "EC", "requirements": [requirement], "children": []}], "annexes": []}
        def node(clause_id, text):
            item = {"evidence_id": "EV-" + clause_id, "evidence_type": "CLAUSE_ROW", "reported_verdict": "PASS", "page_start": 1, "page_end": 1, "source_order": 1, "raw_text": text, "measurements": [], "logical_row_id": "ROW-" + clause_id, "verdict_scope": "INDIVIDUAL_VERDICT", "verdict_owner_evidence_id": "EV-" + clause_id, "child_evidence_ids": []}
            return {"clause_id": clause_id, "result_id": "RC-" + clause_id, "reported_verdict": "PASS", "page_start": 1, "page_end": 1, "source_order": 1, "title": text, "raw_text": text, "measurements": [], "evidence_items": [item], "children": []}
        report = {"document_id": "DOC", "clauses": [node("4.4", "Parent"), node("4.4.1", relevant), node("4.4.2", unrelated)], "annexes": []}
        return matcher.match(kb, report).matches[0]


if __name__ == "__main__":
    unittest.main(verbosity=2)
