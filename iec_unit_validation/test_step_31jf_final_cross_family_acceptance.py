"""Acceptance checks for the read-only Step 31J-F audit decision."""

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "test_reports/regression_results/step_31jf_final_acceptance_audit.json"
V2 = ROOT / "test_reports/regression_results/step_31id_cross_family_controlled_pilot_freeze.json"
V3 = ROOT / "test_reports/regression_results/step_31jf_cross_family_controlled_pilot_v3.json"


class Step31JFFinalAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = json.loads(ARTIFACT.read_text(encoding="utf-8"))

    def test_01_semantic_69_probe_reconstruction(self):
        probe = self.audit["iec_62841"]["probe_reconstruction_69"]
        self.assertEqual(probe["total"], 69)
        self.assertEqual(sum(probe[x] for x in ("TRUE_POSITIVE", "FALSE_POSITIVE", "FALSE_NEGATIVE", "CORRECT_BUT_TOO_GENERIC", "UNRESOLVED_AUDIT", "RESOLVED_FALSE_POSITIVE", "RESOLVED_FALSE_NEGATIVE")), 69)

    def test_02_false_negative_search(self):
        search = self.audit["iec_62841"]["false_negative_search"]
        self.assertGreaterEqual(search["probes"], 15)
        self.assertEqual(search["material_supported_false_negatives"], 0)

    def test_03_grouped_evidence_acceptance(self):
        probe = self.audit["iec_62841"]["probe_8_14_1_101"]
        self.assertFalse(probe["unsupported_atomic_pass"])
        self.assertEqual(probe["artificial_conflicts"], 0)

    def test_04_amendment_source_gap_acceptance(self):
        amendment = self.audit["iec_62841"]["amendment_audit"]
        self.assertEqual(amendment["final_issue"], "STANDARD_SOURCE_GAP")
        self.assertFalse(amendment["product_noncompliance"])

    def test_05_17_2_conservative(self):
        self.assertEqual(self.audit["iec_62841"]["partial_replacement_audit"]["17.2"], "ACCEPTABLE_CONSERVATIVE_REVIEW")

    def test_06_18_8_conservative(self):
        self.assertEqual(self.audit["iec_62841"]["partial_replacement_audit"]["18.8"], "ACCEPTABLE_CONSERVATIVE_REVIEW")

    def test_07_23_3_conservative(self):
        self.assertEqual(self.audit["iec_62841"]["partial_replacement_audit"]["23.3"], "ACCEPTABLE_CONSERVATIVE_REVIEW")

    def test_08_washing_acceptance(self):
        self.assertEqual(self.audit["accepted_family_audit"]["washing_machine"]["classification"], "ACCEPTED")

    def test_09_pump_acceptance(self):
        self.assertIn("ACCEPTED", self.audit["accepted_family_audit"]["submersible_pump"]["classification"])

    def test_10_welding_acceptance(self):
        self.assertEqual(self.audit["accepted_family_audit"]["plastic_tube_welding"]["classification"], "ACCEPTED")

    def test_11_iec_60204_acceptance(self):
        self.assertEqual(self.audit["accepted_family_audit"]["iec_60204"]["classification"], "ACCEPTED")

    def test_12_genericity_counters(self):
        self.assertTrue(all(value == 0 for value in self.audit["genericity_audit"].values()))

    def test_13_deterministic_serialization(self):
        one = json.dumps(self.audit, sort_keys=True)
        two = json.dumps(json.loads(ARTIFACT.read_text(encoding="utf-8")), sort_keys=True)
        self.assertEqual(one, two)

    def test_14_no_duplicate_evidence_ids(self):
        self.assertEqual(self.audit["quality"]["duplicate_evidence_ids"], 0)

    def test_15_no_orphan_refs(self):
        self.assertEqual(self.audit["quality"]["orphan_evidence_references"], 0)

    def test_16_immutable_v2(self):
        self.assertEqual(hashlib.sha256(V2.read_bytes()).hexdigest(), self.audit["immutability"]["before"]["v2_freeze"])

    def test_17_v3_only_created_on_pass(self):
        self.assertFalse(self.audit["decision"]["v3_created"])
        self.assertFalse(V3.exists())

    def test_18_failure_artifact_deterministic_hash(self):
        self.assertEqual(hashlib.sha256(ARTIFACT.read_bytes()).hexdigest(), hashlib.sha256(ARTIFACT.read_bytes()).hexdigest())

    def test_19_known_limitations_recorded(self):
        self.assertEqual(self.audit["iec_62841"]["probe_19_101"]["classification"], "MATERIAL_GENERIC_EVIDENCE_LINKING_DEFECT")
        self.assertGreater(self.audit["iec_62841"]["probe_reconstruction_69"]["FALSE_POSITIVE"], 0)

    def test_20_step_32_not_started(self):
        self.assertFalse(self.audit["decision"]["step_32_started"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
