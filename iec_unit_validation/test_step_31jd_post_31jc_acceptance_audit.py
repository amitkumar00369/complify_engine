"""Acceptance tests for the read-only Step 31J-D audit."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from iec_par.generic_post_correction_acceptance_audit import (
    GenericPostCorrectionAcceptanceAudit as Audit,
)


ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / "test_reports/output/iec_62841_impact_drill_post_31ja"
AFTER = ROOT / "test_reports/output/iec_62841_impact_drill_post_31jc"
ARTIFACT = ROOT / "test_reports/regression_results/step_31jd_post_31jc_accuracy_regression_acceptance.json"


class Step31JDAcceptanceAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.audit = Audit(BEFORE, AFTER)
        cls.result = json.loads(ARTIFACT.read_text(encoding="utf-8"))

    def test_01_semantic_fingerprint_stable_across_changed_ids(self):
        base={"clause_id":"8.1","requirement_ids":["A"],"issue_type":"MISSING_EVIDENCE","compliance_conclusion":"UNRESOLVED","evidence_refs":["REPORT-EV-8.1-SUBROW-1"],"next_action":{"type":"EVIDENCE_REQUEST"}}
        changed={**base,"issue_id":"LOCAL-2","requirement_ids":["B"]}
        self.assertEqual(Audit.semantic_issue_fingerprint(base,{"A":"Tool shall be marked."}),Audit.semantic_issue_fingerprint(changed,{"B":"Tool shall be marked."}))

    def test_02_old_new_semantic_multiset_matching(self):
        delta=self.audit.issue_delta();self.assertEqual(delta["persisted_semantically"],106);self.assertEqual(delta["added"]-delta["removed"],554)

    def test_03_clause_row_subrow_trace(self):
        evidence=self.audit._evidence_index(self.audit.after["evidence"]);sub=next(x for x in evidence.values() if x.get("evidence_type")=="SUBROW");self.assertIn(sub.get("parent_evidence_id"),evidence)

    def test_04_mixed_sibling_verdict_trace(self):
        evidence=self.audit._evidence_index(self.audit.after["evidence"]);parents={}
        for x in evidence.values():
            if x.get("evidence_type")=="SUBROW":parents.setdefault(x.get("parent_evidence_id"),set()).add(x.get("reported_verdict"))
        self.assertTrue(any(len(x)>1 for x in parents.values()))

    def test_05_over_split_detection(self):
        self.assertEqual(Audit.classify_subrow({"raw_text":"Page 4 of 90 Report No. R Clause Requirement + Test Result","reported_verdict":"NA"}),"OVER_SPLIT_SUBROW")

    def test_06_under_split_detection(self):
        self.assertEqual(Audit.classify_subrow({"raw_text":"First assertion P Second assertion N/A","reported_verdict":"PASS"}),"UNDER_SPLIT_ROW")

    def test_07_true_conflict_classification_present(self):
        self.assertGreater(self.audit.conflict_audit()["true_conflict"],0)

    def test_08_false_sibling_conflict_classification_present(self):
        self.assertGreater(self.audit.conflict_audit()["false_scope_leakage"],0)

    def test_09_grouped_verdict_classification(self):
        self.assertEqual(self.result["iec_62841"]["known_targets"]["8.14.1.101"]["classification"],"GROUP_VERDICT_EXPANDED_AS_INDIVIDUAL_PROOF_AND_FALSE_CONFLICT")

    def test_10_sixty_nine_probe_reconstruction(self):
        self.assertEqual(self.result["iec_62841"]["reaudit_69"]["reconstructed"],69)

    def test_11_pump_known_probe_reconstruction(self):
        probes=self.result["accepted_family_regression"]["submersible_pump"]["known_probes"];self.assertEqual(len(probes),8);self.assertEqual(probes["25.8"],"UNRESOLVED_WITHOUT_INVENTED_DEPTH")

    def test_12_washing_reconstruction(self):
        self.assertEqual(self.result["accepted_family_regression"]["washing_machine"]["classification"],"FALSE_POSITIVE_INTRODUCED")

    def test_13_welding_reconstruction(self):
        self.assertIn("STRUCTURAL_ENRICHMENT",self.result["accepted_family_regression"]["plastic_tube_welding"]["classification"])

    def test_14_iec_60204_reconstruction(self):
        self.assertEqual(self.result["accepted_family_regression"]["iec_60204"]["accepted_probe_false_negatives"],0)

    def test_15_amendment_source_gap_classification(self):
        gap=self.result["iec_62841"]["amendment_alignment"];self.assertEqual(gap["status"],"AMENDMENT_MISSING");self.assertEqual(gap["fabricated_requirements"],0)

    def test_16_immutable_upstream_artifacts(self):
        labels={"iec_62841":"test_reports/output/iec_62841_impact_drill_post_31jc","washing_machine":"test_reports/output/washing_machine_post_31jc","submersible_pump":"test_reports/output/submersible_pump_post_31jc","plastic_tube_welding":"test_reports/output/plastic_tube_welding_tools_post_31jc","iec_60204":"test_reports/output/iec_60204_1_post_31jc","v2_freeze":"test_reports/regression_results/step_31id_cross_family_controlled_pilot_freeze.json","31jc_artifact":"test_reports/regression_results/step_31jc_iec_62841_generic_corrections.json"}
        expected=self.result["immutability"]["before"]
        self.assertEqual({key:Audit.aggregate_hash(ROOT/value) for key,value in labels.items()},expected)

    def test_17_no_production_evaluation_changes(self):
        self.assertEqual(self.result["quality"]["production_changes"],0)

    def test_18_deterministic_audit_serialization(self):
        first=json.dumps(self.result,sort_keys=True);second=json.dumps(json.loads(ARTIFACT.read_text(encoding="utf-8")),sort_keys=True);self.assertEqual(first,second)

    def test_19_no_specific_branch_in_generic_audit_tool(self):
        source=(ROOT/"iec_par/generic_post_correction_acceptance_audit.py").read_text(encoding="utf-8").casefold()
        for forbidden in ("62841","60335","60204","impact drill","id6808","19.102"):
            self.assertNotIn(forbidden,source)

    def test_20_decision_and_no_next_step(self):
        decision=self.result["decision"];self.assertEqual(decision["31jc_regression_status"],"REQUIRES_CORRECTION");self.assertFalse(decision["iec_62841_ready_for_v3"]);self.assertFalse(self.result["quality"]["step_31je_started"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
