"""Integrity sentinels for Deterministic Compliance Engine V1."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "test_reports/regression_results/step_31me_deterministic_compliance_engine_v1_freeze.json"


class DeterministicComplianceEngineV1FreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(FREEZE.read_text(encoding="utf-8"))

    def test_01_baseline_name(self):
        self.assertEqual(self.data["baseline"], "DETERMINISTIC_COMPLIANCE_ENGINE_V1")

    def test_02_accepted_status(self):
        self.assertEqual(self.data["baseline_status"], "ACCEPTED")

    def test_03_frozen_state(self):
        self.assertEqual(self.data["engine_state"], "FROZEN")

    def test_04_parent_v4(self):
        self.assertEqual(self.data["parent_baseline"], "CROSS_FAMILY_CONTROLLED_PILOT_BASELINE_V4")

    def test_05_parser_finalized(self):
        self.assertEqual((self.data["parser_version"], self.data["parser_status"]), ("V1", "V1_FINALIZED"))

    def test_06_structural_foundation_accepted(self):
        self.assertEqual(self.data["structural_foundation"], "ACCEPTED")

    def test_07_four_compliance_accepted_families(self):
        self.assertEqual(len(self.data["accepted_families"]), 4)

    def test_08_iec_61058_structural_state(self):
        item = self.data["structural_validation_families"][0]
        self.assertEqual(item["status"], "STRUCTURAL_VALIDATION_ACCEPTED_SOURCE_SET_INCOMPLETE")
        self.assertFalse(item["full_compliance_accepted"])

    def test_09_both_pipeline_modes(self):
        self.assertEqual(set(self.data["pipeline_modes"]), {"STANDALONE", "BASE_PLUS_COMPANION"})

    def test_10_block_classifier_architecture(self):
        self.assertEqual(self.data["structural_architecture"]["flow"][0], "generic_document_block_classifier")

    def test_11_table_ownership_architecture(self):
        self.assertIn("generic_table_ownership_tracker", self.data["structural_architecture"]["flow"])

    def test_12_parent_recovery_architecture(self):
        self.assertIn("generic_structural_parent_resolver", self.data["structural_architecture"]["flow"])

    def test_13_numeric_comparator_baseline(self):
        numeric = self.data["numeric_baseline"]
        self.assertEqual(numeric["operators"], ["GT", "GTE", "LT", "LTE", "EQ", "NEQ"])
        self.assertEqual((numeric["boundaries"]["GT_equal"], numeric["boundaries"]["GTE_equal"]), ("VIOLATES", "SATISFIES"))

    def test_14_applicability_state_semantics(self):
        applicability = self.data["applicability_baseline"]
        self.assertEqual(applicability["fact_states"], ["PRESENT", "ABSENT", "UNKNOWN", "CONFLICT"])
        self.assertFalse(applicability["unknown_equals_absent"])

    def test_15_evidence_protections(self):
        evidence = self.data["evidence_baseline"]
        self.assertTrue(evidence["sibling_verdict_isolation"] and evidence["grouped_pass_protection"])
        self.assertFalse(evidence["numeric_suffix_cross_clause_fallback"])

    def test_16_source_gap_policy(self):
        self.assertEqual(self.data["source_gap_policy"]["missing_governing_source"], ["STANDARD_SOURCE_GAP", "NOT_EVALUATED", "STANDARD_SOURCE_REQUEST"])

    def test_17_integrity_counters(self):
        self.assertEqual(sum(self.data["integrity"].values()), 0)

    def test_18_genericity_counters(self):
        self.assertEqual(sum(self.data["genericity"].values()), 0)

    def test_19_known_limitations(self):
        self.assertGreaterEqual(len(self.data["known_limitations"]), 10)

    def test_20_post_v1_change_policy(self):
        policy = self.data["post_v1_change_policy"]
        self.assertFalse(policy["one_off_semantic_patch_allowed"])
        self.assertTrue(policy["generic_correctness_defect_required"])

    def test_21_llm_outside_freeze(self):
        self.assertEqual(self.data["llm_layer"], "NOT_INCLUDED")
        self.assertFalse(self.data["future_llm_boundary"]["included_in_v1"])

    def test_22_structured_explanation_readiness(self):
        self.assertEqual(self.data["client_style_readiness"], "STRUCTURED_EXPLANATION_READY")

    def test_23_module_hashes(self):
        self.assertGreaterEqual(len(self.data["module_hash_manifest"]), 50)
        for relative, expected in self.data["module_hash_manifest"].items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected)

    def test_24_deterministic_serialization(self):
        one = json.dumps(self.data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        two = json.dumps(json.loads(one), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(one, two)

    def test_25_v2_preserved(self):
        item = self.data["historical_baselines"]["V2"]
        self.assertEqual(hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest(), item["sha256"])

    def test_26_v3_preserved(self):
        item = self.data["historical_baselines"]["V3"]
        self.assertEqual(hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest(), item["sha256"])

    def test_27_v4_preserved(self):
        item = self.data["historical_baselines"]["V4"]
        self.assertEqual(hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest(), item["sha256"])

    def test_28_no_step_32_in_freeze(self):
        self.assertFalse(self.data["freeze_gate"]["step_32_started"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
