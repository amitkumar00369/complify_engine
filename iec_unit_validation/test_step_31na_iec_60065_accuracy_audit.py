"""Acceptance checks for the read-only Step 31N-A accuracy audit."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "test_reports/regression_results/step_31na_iec_60065_deterministic_accuracy_audit.json"


class IEC60065AccuracyAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = json.loads(ARTIFACT.read_text(encoding="utf-8"))

    def test_01_audit_is_read_only(self):
        x = self.audit["immutability"]
        self.assertEqual((x["production_mutation_count"], x["run_mutation_count"]), (0, 0))

    def test_02_source_gap_classification(self):
        x = self.audit["source_alignment"]
        self.assertEqual(x["classification"], "STANDARD_SOURCE_GAP")
        self.assertEqual(x["source_gap_report_row_count_report_1"], 49)

    def test_03_structural_accounting(self):
        x = self.audit["structural_coverage"]
        self.assertEqual((x["reported_recursive_clauses"], x["reported_annexes"], x["reported_tables"]), (407, 14, 30))
        self.assertTrue(x["material_structural_loss"])

    def test_04_definition_audit_accounting(self):
        x = self.audit["definition_audit"]
        self.assertGreaterEqual(x["entries_audited"], 30)
        self.assertEqual(x["classification"], "MATERIAL_DEFINITION_LOSS")

    def test_05_requirement_audit_accounting(self):
        x = self.audit["requirement_coverage"]
        self.assertGreaterEqual(x["normative_source_statements_audited"], 100)
        self.assertEqual(x["requirement_extracted_correctly"] + x["missing_requirement"], 119)

    def test_06_evidence_audit_accounting(self):
        x = self.audit["report_evidence_audit"]
        self.assertGreaterEqual(x["report_1_rows_sampled"], 75)
        self.assertEqual(sum(x["report_1_classification"].values()), 75)

    def test_07_na_mismatch_explanation_present(self):
        x = self.audit["na_audit"]
        self.assertIn("absent Effective KB requirements", x["mismatch_explanation"])
        self.assertGreaterEqual(x["na_rows_sampled"], 60)

    def test_08_product_profile_audit(self):
        x = self.audit["product_profile_audit"]
        self.assertEqual(x["fabricated_fact_count"], 0)
        self.assertTrue(x["report_wide_promotion_error"])

    def test_09_applicability_audit(self):
        x = self.audit["applicability_audit"]
        self.assertGreaterEqual(x["conditional_cases_sampled"], 40)
        self.assertEqual(sum(x["classification"].values()), 40)

    def test_10_numeric_audit(self):
        x = self.audit["numeric_audit"]
        self.assertEqual(x["constraints_audited"], 18)
        self.assertGreater(x["material_misparse_count"], 0)
        self.assertEqual(x["material_miscomparison_count"], 0)

    def test_11_appended_table_integrity(self):
        x = self.audit["appended_table_audit"]
        self.assertEqual(x["orphan_table_children"], 0)
        self.assertEqual(x["measurement_retention_classification"], "MATERIAL_LOSS")

    def test_12_final_issue_accounting(self):
        x = self.audit["final_issue_audit"]
        self.assertTrue(x["all_issues_audited"])
        self.assertEqual(sum(x["issue_type_counts"].values()), x["issues_audited"])

    def test_13_false_positive_gate(self):
        self.assertEqual(self.audit["metrics"]["material_false_positives"], 0)

    def test_14_false_negative_gate(self):
        self.assertGreater(self.audit["metrics"]["material_false_negatives"], 0)
        self.assertEqual(self.audit["final_decision"]["IEC_60065_STATUS"], "NOT_ACCEPTED")

    def test_15_second_report_coverage(self):
        x = self.audit["second_report_audit"]
        self.assertGreaterEqual(x["evidence_rows_sampled"], 30)
        self.assertGreaterEqual(x["na_rows_sampled"], 20)
        self.assertGreaterEqual(x["numeric_cases_audited"], 10)

    def test_16_cross_report_isolation(self):
        x = self.audit["cross_report_isolation"]
        self.assertTrue(x["separate_input_hashes"] and x["same_deterministic_standard_kb"])
        self.assertFalse(x["evidence_leakage_detected"] or x["product_fact_leakage_detected"] or x["issue_leakage_detected"])

    def test_17_client_readiness(self):
        self.assertEqual(self.audit["client_readiness"]["status"], "NOT_READY")

    def test_18_v1_immutable(self):
        path = ROOT / "test_reports/regression_results/step_31me_deterministic_compliance_engine_v1_freeze.json"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         "adb2184fe9bf7a409fc3f03e8bfb991366e16fb8f7207d0f294e7a3e29b17453")
        self.assertEqual(self.audit["immutability"]["v1_mutation_count"], 0)

    def test_19_no_llm(self):
        self.assertFalse(self.audit["controls"]["llm_used"])

    def test_20_no_step_32(self):
        self.assertFalse(self.audit["controls"]["step_32_started"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
