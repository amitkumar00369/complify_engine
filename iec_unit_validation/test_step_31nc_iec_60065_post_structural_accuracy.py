"""Acceptance checks for the read-only Step 31N-C reassessment."""

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "test_reports/regression_results/step_31nc_iec_60065_post_structural_accuracy_reassessment.json"
V1 = ROOT / "test_reports/regression_results/step_31me_deterministic_compliance_engine_v1_freeze.json"


class IEC60065PostStructuralReassessmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = json.loads(ARTIFACT.read_text(encoding="utf-8"))

    def test_01_audit_is_read_only(self):
        x = self.audit["immutability"]
        self.assertEqual((x["production_mutation_count"], x["run_mutation_count"]), (0, 0))

    def test_02_v1_is_immutable(self):
        self.assertEqual(hashlib.sha256(V1.read_bytes()).hexdigest(),
                         "adb2184fe9bf7a409fc3f03e8bfb991366e16fb8f7207d0f294e7a3e29b17453")
        self.assertEqual(self.audit["immutability"]["v1_mutation_count"], 0)

    def test_03_31nb_structural_acceptance_is_retained(self):
        x = self.audit["structural_reconfirmation"]
        self.assertTrue(x["accepted"])
        self.assertEqual((x["recursive_clauses"], x["annexes"], x["tables"]), (300, 14, 30))
        self.assertEqual(x["top_level_clause_ids"], [str(i) for i in range(1, 21)])

    def test_04_requirement_reconstruction_accounting(self):
        x = self.audit["probe_119_reconstruction"]
        self.assertEqual(sum(x["classification"].values()), 119)
        self.assertEqual(x["previously_missing"], x["now_recovered_from_previously_missing"] + x["still_missing"])

    def test_05_false_negative_reconstruction_accounting(self):
        x = self.audit["false_negative_reconstruction_75"]
        self.assertEqual(sum(x["classification"].values()), 75)
        self.assertEqual(x["remaining_material_false_negatives"], x["classification"]["STILL_FALSE_NEGATIVE"])

    def test_06_definition_audit_accounting(self):
        x = self.audit["definition_audit"]
        self.assertGreaterEqual(x["entries_audited"], 40)
        self.assertEqual(sum(x["classification"].values()), x["entries_audited"])

    def test_07_evidence_audit_accounting(self):
        x = self.audit["report_evidence_audit"]
        self.assertGreaterEqual(x["rows_sampled"], 100)
        self.assertEqual(sum(x["classification"].values()), x["rows_sampled"])

    def test_08_na_audit_accounting(self):
        x = self.audit["na_audit"]
        self.assertGreaterEqual(x["rows_sampled"], 80)
        self.assertEqual(sum(x["classification"].values()), x["rows_sampled"])
        self.assertGreater(x["after_matched_na_clauses"], x["before_matched_na_clauses"])

    def test_09_product_profile_audit(self):
        x = self.audit["product_profile_audit"]
        self.assertEqual(x["fabricated_fact_count"], 0)
        self.assertTrue(x["material"])

    def test_10_applicability_audit_accounting(self):
        x = self.audit["applicability_audit"]
        self.assertGreaterEqual(x["conditional_cases_sampled"], 60)
        self.assertEqual(sum(x["classification"].values()), x["conditional_cases_sampled"])

    def test_11_all_numeric_constraints_are_audited(self):
        x = self.audit["numeric_audit"]
        self.assertEqual(x["constraints_audited"], len(x["records"]))
        self.assertEqual(sum(x["classification"].values()), x["constraints_audited"])
        self.assertGreater(x["materially_defective_count"], 0)

    def test_12_all_appended_tables_are_audited(self):
        x = self.audit["appended_table_audit"]
        self.assertTrue(x["all_referenced_tables_audited"])
        self.assertEqual(sum(x["classification"].values()), x["report_1_table_references"])

    def test_13_final_response_accounting(self):
        x = self.audit["final_response_audit"]
        self.assertTrue(x["all_issues_audited"])
        self.assertEqual(sum(x["issue_type_counts"].values()), x["issues_audited"])
        self.assertTrue(x["no_longer_clause_20_concentrated"])

    def test_14_false_positive_gate(self):
        self.assertGreaterEqual(self.audit["false_positive_audit"]["issues_audited"], 100)
        self.assertGreater(self.audit["false_positive_audit"]["material_false_positives"], 0)

    def test_15_false_negative_gate(self):
        x = self.audit["independent_false_negative_audit"]
        self.assertGreaterEqual(x["probes_total"], 100)
        self.assertGreater(x["material_false_negatives"], 0)

    def test_16_second_report_coverage(self):
        x = self.audit["second_report_audit"]
        self.assertGreaterEqual(x["evidence_rows_sampled"], 40)
        self.assertGreaterEqual(x["na_rows_sampled"], 30)
        self.assertGreaterEqual(x["numeric_cases_audited"], 15)
        self.assertGreaterEqual(x["final_findings_or_probes_audited"], 30)

    def test_17_cross_report_isolation(self):
        x = self.audit["cross_report_isolation"]
        self.assertTrue(x["separate_report_hashes"] and x["same_deterministic_standard_kb"])
        self.assertFalse(x["issue_leakage_detected"] or x["product_fact_leakage_detected"] or x["evidence_leakage_detected"])

    def test_18_root_causes_are_classified(self):
        x = self.audit["root_cause_classification"]
        self.assertGreaterEqual(len(x), 1)
        self.assertTrue(all(item["first_incorrect_stage"] for item in x))

    def test_19_client_readiness_and_final_decision(self):
        self.assertEqual(self.audit["client_readiness"]["status"], "NOT_READY")
        self.assertEqual(self.audit["final_decision"]["IEC_60065_STATUS"], "NOT_ACCEPTED")
        self.assertEqual(self.audit["final_decision"]["POST_31NB_STATUS"],
                         "MULTIPLE_GENERIC_CORRECTIONS_REQUIRED")

    def test_20_no_llm(self):
        self.assertFalse(self.audit["controls"]["llm_used"])

    def test_21_step_32_not_started(self):
        self.assertFalse(self.audit["controls"]["step_32_started"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
