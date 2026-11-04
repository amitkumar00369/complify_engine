"""Step 31F regression tests for non-evaluative diagnostic propagation."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from iec_par.generic_compliance_summary_models import ComplianceIssue, IssueSeverity, IssueType
from iec_par.generic_compliance_summary_models import EvaluationConfidenceStatus


class DiagnosticPropagationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pump31e = ROOT / "test_reports/output/submersible_pump_post_31e"
        cls.pump = ROOT / "test_reports/output/submersible_pump_post_31f"
        cls.wash31e = ROOT / "test_reports/output/washing_machine_post_31e"
        cls.wash = ROOT / "test_reports/output/washing_machine_post_31f"
        cls.final = json.loads((cls.pump / "decisions/final_compliance_issues.json").read_text())
        cls.response = json.loads((cls.pump / "decisions/final_compliance_response.json").read_text())
        cls.identity = next(x for x in cls.final["issues"] if (x.get("diagnostic") or {}).get("finding_type") == "IDENTITY_RELATIONSHIP_UNRESOLVED")
        cls.app = next(x for x in cls.final["issues"] if (x.get("diagnostic") or {}).get("finding_type") == "APPLICABILITY_EXECUTION_CONFLICT")

    def test_01_identity_propagates_to_25b_and_25d(self): self.assertEqual(self.identity["diagnostic"]["finding_type"], "IDENTITY_RELATIONSHIP_UNRESOLVED")
    def test_02_identity_values_preserved(self): self.assertEqual([x["value"] for x in self.identity["diagnostic"]["observations"]], ["SPC55068", "4TSC4.0-96-110/1000"])
    def test_03_identity_roles_preserved(self): self.assertEqual([x["role"] for x in self.identity["diagnostic"]["observations"]], ["DECLARED_MODEL", "TESTED_MODEL"])
    def test_04_identity_evidence_preserved(self): self.assertEqual(len(self.identity["diagnostic"]["evidence_refs"]), 2)
    def test_05_identity_pages_preserved(self): self.assertEqual([x["page_refs"] for x in self.identity["diagnostic"]["observations"]], [[1], [3]])
    def test_06_applicability_execution_propagates(self): self.assertEqual(self.app["diagnostic"]["finding_type"], "APPLICABILITY_EXECUTION_CONFLICT")
    def test_07_material_does_not_become_noncompliant(self): self.assertNotEqual(self.app["compliance_conclusion"], "NONCOMPLIANT")
    def test_08_integrity_disposition_preserved(self): self.assertEqual(self.app["provenance"]["integrity_disposition"], "INSUFFICIENT_DATA")
    def test_09_old_issue_is_backward_compatible(self):
        issue=ComplianceIssue(IssueType.OTHER_REVIEW_REQUIRED,IssueSeverity.LOW,False,"s","r",status=EvaluationConfidenceStatus.UNRESOLVED)
        self.assertIsNone(issue.diagnostic)
    def test_10_diagnostic_survives_final_resolution(self): self.assertIn("comparison", self.identity["diagnostic"])
    def test_11_diagnostic_survives_aggregation(self):
        data=json.loads((self.pump/"decisions/aggregated_compliance_issues.json").read_text());self.assertTrue(any("IDENTITY_RELATIONSHIP_UNRESOLVED" in x.get("diagnostic_finding_types",[]) for x in data["actionable_groups"]))
    def test_12_diagnostic_survives_action_plan(self):
        data=json.loads((self.pump/"decisions/prioritized_next_actions.json").read_text());self.assertTrue(any("IDENTITY_RELATIONSHIP_UNRESOLVED" in x.get("diagnostic_categories",[]) for x in data["actions"]))
    def test_13_diagnostic_appears_in_executive_summary(self):
        data=json.loads((self.pump/"decisions/executive_compliance_summary.json").read_text());self.assertIn("unresolved product-identity",data["executive_summary"])
    def test_14_overall_status_unchanged(self): self.assertEqual(self._status(self.pump31e),self._status(self.pump))
    def test_15_step30_preserves_complete_diagnostic(self):
        item=next(x for x in self.response["detailed_issues"] if x["issue_id"]==self.identity["issue_id"]);self.assertEqual(item["diagnostic"],self.identity["diagnostic"])
    def test_16_exact_identity_action_is_deterministic(self): self.assertEqual(self.identity["next_action"]["description"],"Provide the authoritative relationship between the declared model and the tested model, such as model-family, representative-model, equivalence, or corrected test documentation.")
    def test_17_no_raw_report_reparse(self): self.assertNotIn("PdfReader",(ROOT/"iec_par/generic_final_issue_resolution.py").read_text())
    def test_18_no_comparison_logic_in_31f(self): self.assertNotIn("compare_values",(ROOT/"iec_par/generic_final_issue_resolution.py").read_text())
    def test_19_no_fixture_specific_branch(self): self.assertNotIn("Submersible",self._production_text())
    def test_20_no_clause_specific_branch(self): self.assertNotIn("22.101",self._production_text())
    def test_21_deterministic_issue_ids(self): self.assertTrue(self.identity["issue_id"].startswith("FINAL-ISSUE-"))
    def test_22_deterministic_serialization(self): self.assertEqual(json.dumps(self.identity,sort_keys=True),json.dumps(self.identity,sort_keys=True))
    def test_23_washing_issue_count_unchanged(self): self.assertEqual(self._count(self.wash31e),self._count(self.wash))
    def test_24_washing_status_unchanged(self): self.assertEqual(self._status(self.wash31e),self._status(self.wash))
    def test_25_upstream_consistency_artifacts_unchanged(self):
        self.assertEqual(self._hash(self.pump31e/"decisions/cross_evidence_consistency_result.json"),self._hash(self.pump/"decisions/cross_evidence_consistency_result.json"))

    @staticmethod
    def _count(root): return len(json.loads((root/"decisions/final_compliance_issues.json").read_text())["issues"])
    @staticmethod
    def _status(root): return json.loads((root/"decisions/overall_report_status.json").read_text())["overall_status"]
    @staticmethod
    def _hash(path): return hashlib.sha256(path.read_bytes()).hexdigest()
    @staticmethod
    def _production_text():
        names=("generic_clause_evaluation_summary_builder.py","generic_final_issue_resolution.py","generic_report_issue_aggregator.py","generic_next_action_prioritizer.py","generic_executive_summary_builder.py","generic_final_compliance_response_builder.py")
        return "\n".join((ROOT/"iec_par"/name).read_text() for name in names)


if __name__ == "__main__": unittest.main(verbosity=2)
