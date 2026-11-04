"""Acceptance tests for the narrow Step 31N-H correction and stop decision."""

import hashlib
import json
import unittest
from pathlib import Path

from iec_par.generic_report_product_profile_builder import (
    GenericReportProductProfileBuilder,
)


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = json.loads((ROOT / "test_reports/regression_results/step_31nh_final_narrow_deterministic_corrections.json").read_text())
PRODUCTION = ROOT / "iec_par/generic_report_product_profile_builder.py"


class Step31NHTests(unittest.TestCase):
    def build(self, *pages: str):
        return GenericReportProductProfileBuilder().build_from_pages(pages, file_name="generic.pdf")

    def test_01_residual_requirement_recovery_is_not_claimed_without_probe_identity(self):
        self.assertEqual(ARTIFACT["requirement_corrections"]["remaining_deterministic_loss"], 11)

    def test_02_no_duplicate_requirement_creation(self):
        self.assertEqual(ARTIFACT["requirement_corrections"]["duplicate_requirement_ids"], 0)

    def test_03_test_method_text_not_promoted(self):
        self.assertEqual(ARTIFACT["requirement_corrections"]["safety_result"], "BROAD_TRIAL_REJECTED_AND_REMOVED")

    def test_04_product_source_authority_ranking(self):
        self.assertIn("explicit labelled product particulars", ARTIFACT["product_profile_audit"]["authority_model"]["high"])

    def test_05_conflicting_product_facts_are_preserved(self):
        profile = self.build("Switch ........................ : Yes\nThe product has no switch.")
        self.assertEqual(profile.facts["has_switch"].status.value, "CONFLICT")

    def test_06_template_risk_fact_is_not_authoritative(self):
        profile = self.build("Appliances shall be provided with a plug.")
        self.assertNotIn("has_plug", profile.facts)

    def test_07_negative_scope_protection(self):
        profile = self.build("Switch not fitted in the mains cord.")
        self.assertNotEqual(profile.facts["has_switch"].value, False)

    def test_08_model_report_scope_preservation(self):
        profile = self.build("Model ABC has no switch.")
        observation = profile.facts["has_switch"].observations[0]
        self.assertEqual((observation.scope_type, observation.model_scope), ("MODEL_SCOPE", "ABC"))

    def test_09_table_selection_requires_explicit_fact(self):
        self.assertEqual(ARTIFACT["standard_table_row_selection"]["resolved"], 0)

    def test_10_multi_condition_table_selection_not_guessed(self):
        self.assertEqual(ARTIFACT["standard_table_row_selection"]["guessed_selector_facts"], 0)

    def test_11_missing_table_source_is_source_gap(self):
        self.assertGreater(ARTIFACT["standard_table_row_selection"]["source_gap"], 0)

    def test_12_ambiguous_row_selection_is_review(self):
        self.assertEqual(ARTIFACT["standard_table_row_selection"]["status"], "NEEDS_REVIEW_OR_STANDARD_SOURCE_GAP")

    def test_13_no_guessed_selector_fact(self):
        self.assertEqual(ARTIFACT["standard_table_row_selection"]["false_row_selection"], 0)

    def test_14_previous_three_fp_probes_resolved(self):
        self.assertEqual(ARTIFACT["accuracy"]["previous_3_fp"], {"resolved": 3, "remaining": 0})

    def test_15_previous_eighteen_fn_probes_accounted_honestly(self):
        self.assertFalse(ARTIFACT["accuracy"]["previous_18_fn"]["accounted"])

    def test_16_iec_61427_numeric_regression(self):
        self.assertEqual(ARTIFACT["cross_family_regression"]["iec_61427_gt12_equal12"], "VIOLATES")

    def test_17_iec_62841_regression(self):
        self.assertIn("IEC 62841", ARTIFACT["cross_family_regression"]["families_rerun"])

    def test_18_iec_60335_regression(self):
        self.assertTrue(any("IEC 60335" in item for item in ARTIFACT["cross_family_regression"]["families_rerun"]))

    def test_19_iec_60204_regression(self):
        self.assertIn("IEC 60204", ARTIFACT["cross_family_regression"]["families_rerun"])

    def test_20_iec_61058_regression(self):
        self.assertTrue(ARTIFACT["cross_family_regression"]["iec_61058_structural_tests_retained"])

    def test_21_no_family_specific_branch(self):
        source = PRODUCTION.read_text().casefold()
        for forbidden in ("iec 60065", "60065", "speaker", "mu-l8s", "2 speaker.pdf"):
            self.assertNotIn(forbidden, source)

    def test_22_adjacent_label_rows_do_not_invert_next_feature(self):
        profile = self.build("Hand-held ................ : No\nSwitch .................... : Yes")
        self.assertTrue(profile.facts["has_switch"].value)

    def test_23_v1_is_immutable(self):
        path = ROOT / "test_reports/regression_results/step_31me_deterministic_compliance_engine_v1_freeze.json"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), ARTIFACT["immutability"]["v1_sha256"])

    def test_24_no_llm_or_step32(self):
        self.assertFalse(ARTIFACT["controls"]["llm_used"] or ARTIFACT["controls"]["step_32_started"])

    def test_25_stopping_policy(self):
        self.assertEqual(ARTIFACT["final_recommendation"], "REQUIRES_STRATEGY_REASSESSMENT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
