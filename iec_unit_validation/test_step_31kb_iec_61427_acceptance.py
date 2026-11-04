"""Read-only acceptance assertions for the Step 31K-B audit artifact."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from iec_par.generic_post_correction_acceptance_audit import GenericPostCorrectionAcceptanceAudit


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "test_reports/regression_results/step_31kb_iec_61427_unseen_family_acceptance.json"
RUN = ROOT / "test_reports/output/iec_61427_1_battery_post_31ka"


class Step31KBAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = json.loads(RESULT.read_text(encoding="utf-8"))
        cls.family = cls.audit["iec_61427"]

    def test_01_all_27_issues_classified(self):
        self.assertEqual(len(self.family["finding_reconstruction"]), 27)

    def test_02_classification_accounting(self):
        self.assertEqual(sum(self.family["classification"].values()), 27)

    def test_03_false_positive_gate_fails(self):
        self.assertEqual(self.family["material_false_positive_findings"], 15)
        self.assertEqual(self.audit["audit_result"], "REQUIRES_FURTHER_GENERIC_CORRECTION")

    def test_04_false_negative_gate(self):
        self.assertEqual(self.family["false_negative_search"], {**self.family["false_negative_search"], "probes": 25, "material_false_negatives": 0})

    def test_05_8_4_2_2_result(self):
        probe = self.family["probes"]["8.4.2.2"]
        self.assertEqual((probe["high_applicability_gaps"], probe["classification"]), (2, "TRUE_APPLICABILITY_GAP"))

    def test_06_4_4_11_result(self):
        probe = self.family["probes"]["4.4.11"]
        self.assertTrue(probe["child_support"])
        self.assertEqual(probe["classification"], "TRUE_APPLICABILITY_GAP")

    def test_07_4_3_result(self):
        self.assertEqual(self.family["probes"]["4.3"]["material_blocker"], "PURPOSE_PHRASE_AS_APPLICABILITY")

    def test_08_4_4_3_result(self):
        self.assertEqual(self.family["probes"]["4.4.3"], {"child_support": True, "false_issues": 0, "sibling_leakage": 0})

    def test_09_8_1_result(self):
        probe = self.family["probes"]["8.1"]
        self.assertEqual((probe["licence_contamination"], probe["remaining_issues"]), (0, 0))

    def test_10_8_4_1_result(self):
        probe = self.family["probes"]["8.4.1"]
        self.assertEqual((probe["next_heading_contamination"], probe["report_linkage_losses"]), (1, 4))

    def test_11_8_4_5_and_8_4_6_separation(self):
        self.assertFalse(self.family["probes"]["8.4.5"]["owns_8_4_6"])
        self.assertTrue(self.family["probes"]["8.4.6"]["independent_clause"])

    def test_12_genuine_clause_9_hierarchy(self):
        for clause in ("9", "9.1", "9.2", "9.2.1", "9.2.2"):
            self.assertTrue(self.family["probes"][clause]["genuine"])

    def test_13_false_clause_9_contamination_absent(self):
        self.assertEqual(self.family["probes"]["9"]["false_requirements"], 0)
        self.assertEqual(self.family["probes"]["9"]["false_report_evidence"], 0)

    def test_14_missing_evidence_audit(self):
        missing = [x for x in self.family["finding_reconstruction"] if x["final_issue"] == "MISSING_EVIDENCE"]
        self.assertEqual(len(missing), 4)
        self.assertEqual({x["classification"] for x in missing}, {"TRUE_MISSING_EVIDENCE", "REPORT_LINKAGE_LOSS"})

    def test_15_traceability_audit_detects_blockers(self):
        traces = [x for x in self.family["finding_reconstruction"] if x["final_issue"] == "TRACEABILITY_ISSUE"]
        self.assertEqual(len(traces), 16)
        self.assertTrue(any(x["classification"] == "STRUCTURAL_CONTAMINATION" for x in traces))

    def test_16_applicability_audit(self):
        items = [x for x in self.family["finding_reconstruction"] if x["final_issue"] == "APPLICABILITY_JUSTIFICATION_REQUIRED"]
        self.assertEqual(len(items), 7)
        self.assertIn("KB_SEMANTIC_LOSS", {x["classification"] for x in items})

    def test_17_numeric_table_evidence_audit(self):
        probe = self.family["numeric_table_audit"]
        self.assertGreaterEqual(probe["sample_count"], 12)
        self.assertTrue(probe["values_and_units_retained"])
        self.assertEqual(probe["false_limit_comparisons"], 0)

    def test_18_cross_standard_ownership(self):
        self.assertEqual(self.audit["standard_alignment"]["cross_standard_ownership_errors"], 0)

    def test_19_integrity(self):
        integrity = self.audit["integrity"]
        for key in ("duplicate_evidence_ids", "orphan_evidence_refs", "unresolved_parent_refs", "sibling_verdict_leakage", "grouped_PASS_promotion", "cross_standard_leakage"):
            self.assertEqual(integrity[key], 0)
        self.assertEqual(integrity["cross_clause_contamination"], 2)

    def test_20_v3_regression(self):
        regression = self.audit["v3_regression"]
        self.assertEqual((regression["behavioral_runs_reconfirmed"], regression["introduced_false_positives"], regression["introduced_false_negatives"]), (5, 0, 0))

    def test_21_genericity(self):
        self.assertTrue(all(value == 0 for value in self.audit["genericity"].values()))

    def test_22_explanation_readiness(self):
        self.assertEqual(self.audit["client_style_readiness"], "NOT_READY")

    def test_23_no_v3_mutation(self):
        path = ROOT / "test_reports/regression_results/step_31ji_cross_family_controlled_pilot_v3.json"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), self.audit["immutability"]["v3_artifact_sha256"])
        self.assertFalse(self.audit["decision"]["v3_modified"])

    def test_24_no_v4(self):
        self.assertFalse(self.audit["decision"]["v4_created"])

    def test_25_no_step_32(self):
        self.assertFalse(self.audit["decision"]["step_32_started"])
        self.assertEqual(self.audit["decision"]["iec_61427_status"], "NOT_ACCEPTED")

    def test_candidate_run_was_not_mutated(self):
        self.assertEqual(GenericPostCorrectionAcceptanceAudit.aggregate_hash(RUN), self.audit["immutability"]["candidate_run_sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
