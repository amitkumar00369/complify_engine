"""Read-only acceptance checks for Step 31J-I."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "test_reports/regression_results/step_31ji_cross_family_controlled_pilot_v3.json"
RUN = ROOT / "test_reports/output/iec_62841_impact_drill_post_31jh"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def walk(clauses):
    for clause in clauses or []:
        yield clause
        yield from walk(clause.get("children", []))


class Step31JIFinalAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.freeze = load(RESULT)
        cls.accuracy = cls.freeze["accuracy_summary"]
        cls.effective = load(RUN / "standards/effective_kb.json")
        cls.evidence = load(RUN / "report/report_evidence.json")
        cls.matches = load(RUN / "report/evidence_match_result.json")
        cls.profile = load(RUN / "report/product_profile.json")
        cls.issues = load(RUN / "decisions/final_compliance_issues.json")["issues"]
        cls.effective_clauses = {x["clause_id"]: x for x in walk(cls.effective["clauses"])}
        cls.report_clauses = {x["clause_id"]: x for x in walk(cls.evidence["clauses"])}

    def test_01_iec_62841_semantic_reconstruction(self):
        probe = self.accuracy["iec_62841"]["probe_reconstruction_69"]
        self.assertEqual(probe["total"], 69)
        self.assertEqual(sum(probe[key] for key in (
            "TRUE_POSITIVE", "FALSE_POSITIVE", "FALSE_NEGATIVE", "CORRECT_BUT_TOO_GENERIC",
            "UNRESOLVED_AUDIT", "RESOLVED_FALSE_POSITIVE", "RESOLVED_FALSE_NEGATIVE")), 69)

    def test_02_iec_62841_false_positive_gate(self):
        self.assertEqual(self.accuracy["iec_62841"]["probe_reconstruction_69"]["FALSE_POSITIVE"], 0)

    def test_03_iec_62841_false_negative_gate(self):
        search = self.accuracy["iec_62841"]["false_negative_search"]
        self.assertGreaterEqual(search["probes"], 20)
        self.assertEqual(search["material_false_negatives"], 0)

    def test_04_missing_evidence_sample(self):
        sample = self.accuracy["iec_62841"]["missing_evidence_sample"]
        self.assertGreaterEqual(sample["sample_size"], 20)
        self.assertEqual(sample["REPORT_LINKAGE_LOSS"], 0)
        self.assertEqual(sample["APPLICABILITY_ERROR"], 0)

    def test_05_19_101_is_conservative_not_systematic(self):
        self.assertEqual(self.accuracy["iec_62841"]["probe_19_101"], "ACCEPTABLE_CONSERVATIVE_REVIEW")
        matches = [x for x in self.matches["matches"] if x.get("source_clause_id") == "19.101"]
        self.assertTrue(any(x.get("match_type") == "EXPLICIT_PARENT_CHILD_REPORT_OWNERSHIP" for x in matches))

    def test_06_19_102_hierarchy_and_requirements(self):
        expected = {"19.102.1": 4, "19.102.2": 12, "19.102.3": 7}
        self.assertEqual({key: len(self.effective_clauses[key]["requirements"]) for key in expected}, expected)

    def test_07_8_14_1_101_independent_verdicts(self):
        self.assertEqual(len(self.effective_clauses["8.14.1.101"]["requirements"]), 7)
        subrows = [x for x in self.report_clauses["8.14.1.101"]["evidence_items"]
                   if x.get("evidence_type") == "SUBROW" and x.get("reported_verdict") == "PASS"]
        self.assertEqual(len(subrows), 7)
        links = [x for x in self.matches["matches"] if x.get("source_clause_id") == "8.14.1.101"]
        self.assertEqual(sum(x.get("match_type") == "EXACT_SUBROW_SEMANTIC" for x in links), 7)

    def test_08_17_2_classification(self):
        self.assertEqual(self.accuracy["iec_62841"]["probe_17_2"], "ACCEPTABLE_CONSERVATIVE_REVIEW")

    def test_09_18_8_classification(self):
        self.assertEqual(self.accuracy["iec_62841"]["probe_18_8"], "ACCEPTABLE_CONSERVATIVE_REVIEW")

    def test_10_23_3_classification(self):
        self.assertEqual(self.accuracy["iec_62841"]["probe_23_3"], "ACCEPTABLE_CONSERVATIVE_REVIEW")

    def test_11_amendment_source_gap(self):
        gaps = [x for x in self.issues if x["issue_type"] == "STANDARD_SOURCE_GAP"]
        self.assertEqual(len(gaps), 1)
        self.assertEqual((gaps[0]["compliance_conclusion"], gaps[0]["next_action"]["type"]),
                         ("NOT_EVALUATED", "STANDARD_SOURCE_REQUEST"))
        self.assertFalse(gaps[0]["diagnostic"]["fabricated_requirement"])

    def test_12_product_profile_acceptance(self):
        required = {"product_type", "rated_voltage", "rated_frequency", "rated_power_input",
                    "protection_class", "ip_rating", "no_load_speed", "tool_capacity",
                    "has_adjustable_guard", "has_control_position_indicator"}
        self.assertTrue(required.issubset(self.profile["facts"]))
        self.assertTrue(any(x["relationship_type"] == "TESTED_REPRESENTATIVE"
                            for x in self.profile["identity"]["relationships"]))

    def test_13_washing_acceptance(self):
        self.assertEqual(self.accuracy["families"]["washing_machine"]["decision"], "ACCEPTED")

    def test_14_pump_acceptance(self):
        self.assertEqual(self.accuracy["families"]["submersible_pump"]["decision"],
                         "ACCEPTED_WITH_CONSERVATIVE_REVIEW")

    def test_15_welding_acceptance(self):
        self.assertEqual(self.accuracy["families"]["plastic_tube_welding"]["decision"], "ACCEPTED")

    def test_16_iec_60204_acceptance(self):
        self.assertEqual(self.accuracy["families"]["iec_60204"]["decision"], "ACCEPTED")

    def test_17_genericity_counters(self):
        self.assertTrue(all(value == 0 for value in self.freeze["genericity_audit"].values()))

    def test_18_determinism_and_evidence_integrity(self):
        integrity = self.freeze["integrity"]
        self.assertTrue(all(integrity[key] for key in integrity if key.startswith("deterministic_")))
        all_items = [x for clause in walk(self.evidence["clauses"])
                     for x in clause.get("evidence_items", [])]
        ids = [x["evidence_id"] for x in all_items]
        identity_ids = {e["evidence_id"] for x in self.profile["identity"]["product_identities"]
                        for e in x.get("evidence", [])}
        known = set(ids) | identity_ids
        refs = {ref["evidence_id"] for match in self.matches["matches"]
                for ref in match.get("evidence_refs", [])}
        refs |= {ref for issue in self.issues for ref in issue.get("evidence_refs", [])}
        self.assertEqual(len(ids) - len(set(ids)), 0)
        self.assertFalse(refs - known)

    def test_19_explanation_readiness(self):
        self.assertEqual(self.freeze["client_style_readiness"], "STRUCTURED_EXPLANATION_READY")

    def test_20_v3_created_only_after_pass(self):
        self.assertEqual((self.freeze["baseline_status"], self.freeze["engine_state"]),
                         ("ACCEPTED", "FROZEN"))
        self.assertEqual(self.accuracy["accepted_family_regression"],
                         {"introduced_false_negatives": 0, "introduced_false_positives": 0})

    def test_21_v2_preserved(self):
        path = ROOT / "test_reports/regression_results/step_31id_cross_family_controlled_pilot_freeze.json"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         self.freeze["immutability"]["historical_v2_sha256"])

    def test_22_step_32_not_started(self):
        self.assertFalse(self.freeze["step_32_started"])
        self.assertNotIn("step_32", self.freeze["module_hash_manifest"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
