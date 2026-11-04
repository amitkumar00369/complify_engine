"""Contract tests for the read-only IEC 61427-1 unseen-family audit."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "test_reports/regression_results/step_31k_iec_61427_unseen_family_acceptance_audit.json"
V3 = ROOT / "test_reports/regression_results/step_31ji_cross_family_controlled_pilot_v3.json"


class Step31KAcceptanceAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.data = json.loads(ARTIFACT.read_text(encoding="utf-8"))

    def test_01_step_and_run(self):
        self.assertEqual(self.data["step"], "31K")
        self.assertEqual(self.data["run_identification"]["mode"], "STANDALONE")

    def test_02_standard_identity(self):
        self.assertEqual(self.data["standard_identification"]["standard_number"], "IEC 61427-1")

    def test_03_all_issues_accounted(self):
        counts = self.data["classification_counts"]
        self.assertEqual(sum(counts.values()), 38)
        self.assertEqual(self.data["issue_reconstruction"]["classification_accounted"], 38)

    def test_04_required_probe_set(self):
        expected = {"4.3", "4.4.3", "4.4.11", "5.1", "5.3", "8.1", "8.4.1",
                    "8.4.2.2", "8.4.5", "8.4.7", "9", "9.1", "9.2.1"}
        self.assertEqual(set(self.data["per_clause_probes"]), expected)

    def test_05_clause_9_structural_blocker(self):
        probe = self.data["per_clause_probes"]["9"]
        self.assertEqual(probe["classification"], "KB_SEMANTIC_LOSS")
        self.assertEqual(probe["finding_count"], 10)
        self.assertFalse(probe["cross_standard_ownership_error"])

    def test_06_high_na_conflicts_audited(self):
        self.assertEqual(self.data["applicability_audit"]["high_na_conflicts"], 2)
        self.assertIn("TRUE_APPLICABILITY_GAP", self.data["applicability_audit"]["8.4.2.2"])

    def test_07_missing_evidence_distinguished(self):
        self.assertEqual(self.data["classification_counts"]["TRUE_MISSING_EVIDENCE"], 3)
        self.assertGreater(self.data["classification_counts"]["REPORT_LINKAGE_LOSS"], 0)

    def test_08_false_negative_search(self):
        search = self.data["false_negative_search"]
        self.assertGreaterEqual(search["probes"], 15)
        self.assertEqual(search["material_false_negatives"], 0)

    def test_09_integrity_accounting(self):
        integrity = self.data["integrity_audit"]
        self.assertEqual(integrity["duplicate_evidence_ids"], 0)
        self.assertEqual(integrity["orphan_evidence_references"], 0)
        self.assertEqual(integrity["sibling_verdict_leakage"], 0)
        self.assertEqual(integrity["grouped_pass_promotion"], 0)

    def test_10_cross_clause_contamination_detected(self):
        self.assertEqual(self.data["integrity_audit"]["cross_clause_evidence_leakage"], 10)

    def test_11_no_cross_standard_ownership_error(self):
        self.assertEqual(self.data["classification_counts"]["CROSS_STANDARD_OWNERSHIP_ERROR"], 0)

    def test_12_genericity_zero(self):
        self.assertFalse(any(self.data["genericity_audit"].values()))

    def test_13_first_fault_is_generic(self):
        fault = self.data["first_incorrect_generic_stage"]
        self.assertEqual(fault["primary"], "generic_iec_structural_parser")
        self.assertNotIn("battery-specific", fault["explanation"].casefold())

    def test_14_decision_requires_correction(self):
        self.assertEqual(self.data["recommended_next_decision"], "REQUIRES_GENERIC_CORRECTION")

    def test_15_v3_preserved(self):
        self.assertEqual(hashlib.sha256(V3.read_bytes()).hexdigest(),
                         "196c0350066bb0157696cc35f46dfe94543375a54e84e9f88b7f4a50a65cdc45")
        self.assertFalse(self.data["v3_modified"])

    def test_16_no_step_32(self):
        self.assertNotIn("step_32", json.dumps(self.data).casefold())


if __name__ == "__main__": unittest.main(verbosity=2)
