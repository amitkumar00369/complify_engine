"""Focused tests for review-only missing-standard-source propagation."""
from __future__ import annotations
import unittest
from iec_par.generic_compliance_pipeline_runner import GenericCompliancePipelineRunner,StandardValidationResult,StandardValidationStatus
from iec_par.generic_final_issue_resolution import FinalComplianceIssueReport,FinalIssueType,ComplianceConclusion,FinalActionType

def empty_report():return FinalComplianceIssueReport("1.0",None,None,[],[],{"total_emitted_issues":0,"actionable_issues":0,"counts_by_issue_type":{},"counts_by_action_type":{}},{},{})
class AmendmentSourceGapTests(unittest.TestCase):
 def propagate(self,diagnostic="AMENDMENT_MISSING: governing source absent"):
  validation=StandardValidationResult(StandardValidationStatus.PARTIAL_MATCH,diagnostics=[diagnostic]);effective={"clauses":[{"clause_id":"7.2","children":[{"clause_id":"7.2.0","children":[]}]} ]};evidence={"clauses":[{"clause_id":"7.2.1","evidence_items":[{"evidence_id":"E1"}],"children":[]}]};return GenericCompliancePipelineRunner._propagate_standard_source_gaps(empty_report(),validation,effective,evidence)
 def test_01_source_gap_emitted(self):self.assertEqual(self.propagate().issues[0].issue_type,FinalIssueType.STANDARD_SOURCE_GAP)
 def test_02_not_noncompliant(self):self.assertEqual(self.propagate().issues[0].compliance_conclusion,ComplianceConclusion.NOT_EVALUATED)
 def test_03_source_request_action(self):self.assertEqual(self.propagate().issues[0].next_action.type,FinalActionType.STANDARD_SOURCE_REQUEST)
 def test_04_evidence_preserved(self):self.assertEqual(self.propagate().issues[0].evidence_refs,["E1"])
 def test_05_no_gap_without_diagnostic(self):self.assertEqual(self.propagate("edition review").issues,[])
 def test_06_no_gap_when_requirement_exists(self):
  v=StandardValidationResult(StandardValidationStatus.PARTIAL_MATCH,diagnostics=["AMENDMENT_MISSING: x"]);e={"clauses":[{"clause_id":"7.2.1","children":[]}]};r={"clauses":[{"clause_id":"7.2.1","evidence_items":[],"children":[]}]};self.assertEqual(GenericCompliancePipelineRunner._propagate_standard_source_gaps(empty_report(),v,e,r).issues,[])
 def test_07_parent_required(self):
  v=StandardValidationResult(StandardValidationStatus.PARTIAL_MATCH,diagnostics=["AMENDMENT_MISSING: x"]);self.assertEqual(GenericCompliancePipelineRunner._propagate_standard_source_gaps(empty_report(),v,{"clauses":[]},{"clauses":[{"clause_id":"7.2.1","children":[]}]}).issues,[])
 def test_08_no_requirement_fabricated(self):self.assertEqual(self.propagate().issues[0].requirement_ids,[])
 def test_09_diagnostic_says_not_fabricated(self):self.assertFalse(self.propagate().issues[0].diagnostic["fabricated_requirement"])
 def test_10_deterministic_issue_id(self):self.assertEqual(self.propagate().issues[0].issue_id,self.propagate().issues[0].issue_id)

if __name__=="__main__":unittest.main(verbosity=2)
