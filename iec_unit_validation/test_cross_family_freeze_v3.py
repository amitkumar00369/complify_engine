"""Contract tests for the immutable controlled-pilot V3 freeze."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "test_reports/regression_results/step_31ji_cross_family_controlled_pilot_v3.json"


class CrossFamilyFreezeV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = PATH.read_bytes()
        cls.data = json.loads(cls.raw)

    def test_01_baseline_name(self): self.assertEqual(self.data["baseline"], "CROSS_FAMILY_CONTROLLED_PILOT_BASELINE_V3")
    def test_02_accepted_families(self): self.assertEqual(set(self.data["accepted_families"]), {"IEC_60335_FAMILY", "IEC_60204_FAMILY", "IEC_62841_FAMILY"})
    def test_03_pipeline_modes(self): self.assertEqual(set(self.data["pipeline_modes"]), {"STANDALONE", "BASE_PLUS_COMPANION"})
    def test_04_run_references_exist(self):
        self.assertEqual(len(self.data["accepted_runs"]), 5)
        self.assertTrue(all((ROOT / value).is_dir() for value in self.data["accepted_runs"].values()))
    def test_05_module_hashes(self):
        for name, expected in self.data["module_hash_manifest"].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), expected)
    def test_06_deterministic_freeze_serialization(self):
        canonical = json.dumps(self.data, sort_keys=True, separators=(",", ":"))
        self.assertEqual(canonical, json.dumps(json.loads(self.raw), sort_keys=True, separators=(",", ":")))
    def test_07_genericity(self): self.assertFalse(any(self.data["genericity_audit"].values()))
    def test_08_no_accepted_family_false_positives(self): self.assertEqual(self.data["integrity"]["introduced_false_positives"], 0)
    def test_09_no_accepted_family_false_negatives(self): self.assertEqual(self.data["integrity"]["introduced_false_negatives"], 0)
    def test_10_iec_62841_accepted(self): self.assertEqual(self.data["accuracy_summary"]["families"]["iec_62841"]["decision"], "ACCEPTED_WITH_REVIEW")
    def test_11_source_gap_preserved(self): self.assertEqual(self.data["accuracy_summary"]["iec_62841"]["amendment_source_gap"], "ACCEPTABLE_SOURCE_GAP_BEHAVIOR")
    def test_12_limitations_recorded(self): self.assertGreaterEqual(len(self.data["known_limitations"]), 7)
    def test_13_v2_preserved(self): self.assertTrue((ROOT / "test_reports/regression_results/step_31id_cross_family_controlled_pilot_freeze.json").is_file())
    def test_14_v3_frozen(self): self.assertEqual((self.data["baseline_status"], self.data["engine_state"]), ("ACCEPTED", "FROZEN"))
    def test_15_step_32_absent(self): self.assertFalse(self.data["step_32_started"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
