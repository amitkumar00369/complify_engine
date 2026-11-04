"""Step 31K-C regressions for generic semantic boundaries and rating facts."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from iec_par.generic_iec_applicability_extractor import GenericIECApplicabilityExtractor
from iec_par.generic_iec_kb_models import ApplicabilityStatus
from iec_par.generic_iec_requirement_parser import GenericIECRequirementParser
from iec_par.generic_iec_structural_parser import GenericIECStructuralParser
from iec_par.generic_report_product_profile_builder import GenericReportProductProfileBuilder
from iec_par.generic_requirement_evidence_matcher import GenericRequirementEvidenceMatcher


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "test_reports/output/iec_61427_1_battery_post_31kc"


class GenericRequirementSemanticBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.requirements = GenericIECRequirementParser()
        self.applicability = GenericIECApplicabilityExtractor()

    def test_01_purpose_phrase_is_not_applicability(self):
        condition, status = self.applicability._detect_condition("For optimum service life, instructions shall be followed.")
        self.assertEqual((condition, status), (None, ApplicabilityStatus.ALWAYS))

    def test_02_products_having_feature_remains_applicability(self):
        condition, status = self.applicability._detect_condition("For products having ventilation openings, guards shall be fitted.")
        self.assertEqual((condition, status), ("For products having ventilation openings", ApplicabilityStatus.UNRESOLVED))

    def test_03_if_feature_is_provided_remains_applicability(self):
        condition, status = self.applicability._detect_condition("If a filter is provided, it shall be removable.")
        self.assertEqual((condition, status), ("If a filter is provided", ApplicabilityStatus.UNRESOLVED))

    def test_04_list_item_segmentation(self):
        values = self.requirements._split_requirement_candidates("a) The guard shall remain fixed;\nb) The cover shall resist force.")
        self.assertEqual(len(values), 2)

    def test_05_independent_normative_statements_segmented(self):
        values = self.requirements._split_requirement_candidates("The guard shall remain fixed. The cover shall resist force.")
        self.assertEqual(len(values), 2)

    def test_06_wrapped_line_not_independently_segmented(self):
        values = self.requirements._split_requirement_candidates("The guard shall remain\nfixed under normal use.")
        self.assertEqual(values, ["The guard shall remain fixed under normal use."])

    def test_07_overlapping_composite_removed(self):
        values = ["The guard shall remain fixed. The cover shall resist force.", "The guard shall remain fixed.", "The cover shall resist force."]
        self.assertEqual(self.requirements._remove_composite_duplicates(values), values[1:])

    def test_08_distinct_independent_requirements_retained(self):
        values = ["The guard shall remain fixed.", "The cover shall resist force."]
        self.assertEqual(self.requirements._remove_composite_duplicates(values), values)

    def test_09_next_valid_heading_terminates_prior_semantics(self):
        blocks = GenericIECStructuralParser.parse_text("8.4.4 Residual test\nThe value shall be recorded.\nTest termination\n8.4.5\nThe test shall stop.")
        first = next(x for x in blocks if x.block_id == "8.4.4")
        self.assertNotIn("Test termination", first.raw_text)

    def test_10_harmless_footer_does_not_create_requirement(self):
        values = self.requirements._split_requirement_candidates("The guard shall remain fixed.\nPage 4 of 20")
        self.assertEqual(values, ["The guard shall remain fixed."])

    def test_11_footer_number_not_requirement(self):
        self.assertEqual(self.requirements._split_requirement_candidates("— 15 —"), [])

    def test_12_clear_report_child_links_to_requirement(self):
        result = self._child_match("Load current shall be supplied during charging", "Load current shall be supplied during charging")
        self.assertEqual(result.match_type, "PARENT_REQUIREMENT_SUPPORTED_BY_CHILD_EVIDENCE")

    def test_13_unrelated_child_rejected(self):
        result = self._child_match("Load current shall be supplied during charging", "Marking colour was inspected")
        self.assertNotEqual(result.match_type, "PARENT_REQUIREMENT_SUPPORTED_BY_CHILD_EVIDENCE")

    def test_14_grouped_evidence_remains_conservative(self):
        matcher = GenericRequirementEvidenceMatcher()
        self.assertFalse(matcher._statement_present("Guard shall remain fixed", "General test completed"))

    def test_15_rated_capacity_200_extracted(self):
        fact = self._capacity_fact()
        self.assertIn(200, [x.value["value"] for x in fact.observations])

    def test_16_rated_capacity_100_extracted(self):
        fact = self._capacity_fact()
        self.assertIn(100, [x.value["value"] for x in fact.observations])

    def test_17_multiple_capacity_observations_preserved(self):
        self.assertEqual(len(self._capacity_fact().observations), 2)

    def test_18_capacity_does_not_infer_chemistry(self):
        profile = self._profile()
        self.assertFalse(any("chem" in key.casefold() for key in profile.facts))

    def test_19_capacity_values_do_not_conflict(self):
        profile = self._profile()
        self.assertNotIn("rated_capacity", profile.conflicting_features)
        self.assertEqual(profile.facts["rated_capacity"].status.value, "CONFIRMED")

    def test_20_clause_4_3_regression(self):
        clause = self._base_clause("4.3")
        self.assertEqual(len(clause["requirements"]), 1)
        self.assertIsNone(clause["requirements"][0]["condition_text"])

    def test_21_clause_8_4_1_regression(self):
        clause = self._base_clause("8.4.1")
        self.assertEqual(len(clause["requirements"]), 6)
        self.assertEqual(len({x["text"] for x in clause["requirements"]}), 6)

    def test_22_clause_8_4_4_regression(self):
        clause = self._base_clause("8.4.4")
        self.assertEqual(len(clause["requirements"]), 4)
        self.assertTrue(all("Test termination" not in x["text"] for x in clause["requirements"]))

    def test_23_clause_8_4_5_regression(self):
        clause = self._base_clause("8.4.5")
        self.assertEqual(len(clause["requirements"]), 2)
        self.assertFalse(clause["requirements"][1]["text"] in clause["requirements"][0]["text"])

    def test_24_true_applicability_gaps_preserved(self):
        issues = self._json("decisions/final_compliance_issues.json")["issues"]
        gaps = [x for x in issues if x["clause_id"] == "8.4.2.2" and x["issue_type"] == "APPLICABILITY_JUSTIFICATION_REQUIRED"]
        self.assertGreaterEqual(len(gaps), 2)

    def test_25_v3_regression_outputs_exist(self):
        names = ("washing_machine", "submersible_pump", "plastic_tube_welding_tools", "iec_60204_1", "iec_62841_impact_drill")
        for name in names:
            self.assertTrue((ROOT / "test_reports/output" / f"{name}_post_31kc/decisions/final_compliance_response.json").is_file())

    def test_26_candidate_serialization_is_valid(self):
        paths = list(RUN.rglob("*.json"))
        self.assertTrue(paths)
        for path in paths:
            json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _profile():
        return GenericReportProductProfileBuilder().build_from_pages(
            ["Report No.: R-1\nProduct: storage unit\nRatings: 25.6 V 200 Ah; 25.6 V 100 Ah"],
            file_name="sample.pdf",
        )

    def _capacity_fact(self):
        return self._profile().facts["rated_capacity"]

    @staticmethod
    def _json(relative: str):
        return json.loads((RUN / relative).read_text(encoding="utf-8"))

    def _base_clause(self, clause_id: str):
        payload = self._json("standards/base_kb.json")
        def walk(items):
            for clause in items:
                if clause["clause_id"] == clause_id:
                    return clause
                found = walk(clause.get("children", []))
                if found:
                    return found
            return None
        return walk(payload["clauses"])

    @staticmethod
    def _child_match(requirement_text: str, child_text: str):
        matcher = GenericRequirementEvidenceMatcher()
        requirement = {"effective_requirement_id":"ER-1","clause_id":"4.4","effective_status":"ACTIVE","effective_source_type":"BASE","text":requirement_text}
        kb = {"effective_kb_id":"KB","clauses":[{"effective_clause_id":"EC","requirements":[requirement],"children":[]}],"annexes":[]}
        def node(clause_id, text):
            evidence_id = "EV-" + clause_id
            item = {"evidence_id":evidence_id,"evidence_type":"CLAUSE_ROW","reported_verdict":"PASS","page_start":1,"page_end":1,"source_order":1,"raw_text":text,"measurements":[],"logical_row_id":"ROW-"+clause_id,"verdict_scope":"INDIVIDUAL_VERDICT","verdict_owner_evidence_id":evidence_id,"child_evidence_ids":[]}
            return {"clause_id":clause_id,"result_id":"RC-"+clause_id,"reported_verdict":"PASS","page_start":1,"page_end":1,"source_order":1,"title":text,"raw_text":text,"measurements":[],"evidence_items":[item],"children":[]}
        report = {"document_id":"DOC","clauses":[node("4.4","Parent"),node("4.4.1",child_text)],"annexes":[]}
        return matcher.match(kb, report).matches[0]


if __name__ == "__main__":
    unittest.main(verbosity=2)
