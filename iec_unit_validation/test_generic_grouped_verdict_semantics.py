"""Focused tests for sibling isolation and grouped-verdict sufficiency."""
from __future__ import annotations
import unittest
from iec_par.generic_requirement_evidence_matcher import (GenericRequirementEvidenceMatcher,RequirementEvidenceMatchResult,RequirementEvidenceMatchStatus,ReportEvidenceReference)
from iec_par.generic_final_requirement_decision_engine import GenericFinalRequirementDecisionEngine,FinalRequirementDecision,EvidenceSufficiency

def result(rid,eid,verdict="PASS"):
 return RequirementEvidenceMatchResult("M-"+rid,rid,"C","7.1","ACTIVE","APPLICABLE",RequirementEvidenceMatchStatus.EXACT_SUBCLAUSE,1,["7.1"],[ReportEvidenceReference(eid,"7.1","R",verdict)],[])

class GroupedVerdictTests(unittest.TestCase):
 def test_01_shared_evidence_becomes_group_verdict(self):
  xs=[result("R1","E1"),result("R2","E1")];GenericRequirementEvidenceMatcher()._mark_grouped_verdicts(xs);self.assertTrue(all(x.evidence_scope=="GROUP_VERDICT" for x in xs))
 def test_02_distinct_evidence_remains_individual(self):
  xs=[result("R1","E1"),result("R2","E2")];GenericRequirementEvidenceMatcher()._mark_grouped_verdicts(xs);self.assertTrue(all(x.evidence_scope is None for x in xs))
 def test_03_group_pass_not_atomic_compliant(self):
  engine=GenericFinalRequirementDecisionEngine();x=engine.evaluate_requirement({"effective_requirement_id":"R1","effective_status":"ACTIVE","clause_id":"7.1"},{"resolved_decision":"APPLICABLE","effective_clause_id":"C"},{"evidence_scope":"GROUP_VERDICT","evidence_refs":[{"evidence_id":"E1"}],"match_status":"NEEDS_REVIEW"},[],None,"G",[{"report_evidence_id":"E1","reported_verdict":"PASS","scope_status":"EXACT_GROUP"}],{});self.assertEqual(x.final_decision,FinalRequirementDecision.NEEDS_REVIEW);self.assertEqual(x.evidence_sufficiency,EvidenceSufficiency.PARTIAL)
 def test_04_group_na_not_atomic_na(self):
  engine=GenericFinalRequirementDecisionEngine();x=engine.evaluate_requirement({"effective_requirement_id":"R1","effective_status":"ACTIVE","clause_id":"7.1"},{"resolved_decision":"APPLICABLE"},{"evidence_scope":"GROUP_VERDICT","evidence_refs":[{"evidence_id":"E1"}]},[],None,"G",[{"report_evidence_id":"E1","reported_verdict":"NA","scope_status":"EXACT_GROUP"}],{});self.assertEqual(x.final_decision,FinalRequirementDecision.NEEDS_REVIEW)
 def test_05_sibling_na_is_filtered(self):
  engine=GenericFinalRequirementDecisionEngine();x=engine.evaluate_requirement({"effective_requirement_id":"R1","effective_status":"ACTIVE","clause_id":"7.1"},{"resolved_decision":"APPLICABLE"},{"evidence_refs":[{"evidence_id":"E1"}]},[],None,"G",[{"report_evidence_id":"E1","reported_verdict":"PASS","scope_status":"EXACT_GROUP"},{"report_evidence_id":"E2","reported_verdict":"NA","scope_status":"EXACT_GROUP"}],{});self.assertEqual(x.final_decision,FinalRequirementDecision.COMPLIANT);self.assertEqual(x.report_verdicts,["PASS"])
 def test_06_sibling_pass_does_not_prove_na_child(self):
  engine=GenericFinalRequirementDecisionEngine();x=engine.evaluate_requirement({"effective_requirement_id":"R2","effective_status":"ACTIVE","clause_id":"7.1"},{"resolved_decision":"APPLICABLE"},{"evidence_refs":[{"evidence_id":"E2"}]},[],None,"G",[{"report_evidence_id":"E1","reported_verdict":"PASS","scope_status":"EXACT_GROUP"},{"report_evidence_id":"E2","reported_verdict":"NA","scope_status":"EXACT_GROUP"}],{});self.assertNotIn("PASS",x.report_verdicts)
 def test_07_fail_pass_siblings_not_conflict(self):
  engine=GenericFinalRequirementDecisionEngine();x=engine.evaluate_requirement({"effective_requirement_id":"R1","effective_status":"ACTIVE","clause_id":"7.1"},{"resolved_decision":"APPLICABLE"},{"evidence_refs":[{"evidence_id":"E1"}]},[],None,"G",[{"report_evidence_id":"E1","reported_verdict":"FAIL","scope_status":"EXACT_GROUP"},{"report_evidence_id":"E2","reported_verdict":"PASS","scope_status":"EXACT_GROUP"}],{});self.assertEqual(x.report_verdicts,["FAIL"])
 def test_08_group_reason_explicit(self):
  xs=[result("R1","E1"),result("R2","E1")];GenericRequirementEvidenceMatcher()._mark_grouped_verdicts(xs);self.assertIn("shared",xs[0].match_reason)
 def test_09_match_ids_unchanged_by_group_marking(self):
  xs=[result("R1","E1"),result("R2","E1")];before=[x.match_id for x in xs];GenericRequirementEvidenceMatcher()._mark_grouped_verdicts(xs);self.assertEqual(before,[x.match_id for x in xs])
 def test_10_no_parent_child_duplicate_conflict(self):
  engine=GenericFinalRequirementDecisionEngine();x=engine.evaluate_requirement({"effective_requirement_id":"R1","effective_status":"ACTIVE","clause_id":"7.1"},{"resolved_decision":"APPLICABLE"},{"evidence_refs":[{"evidence_id":"CHILD"}]},[],None,"G",[{"report_evidence_id":"PARENT","reported_verdict":"NOT_STATED","scope_status":"WHOLE_CLAUSE"},{"report_evidence_id":"CHILD","reported_verdict":"PASS","scope_status":"EXACT_GROUP"}],{});self.assertEqual(x.final_decision,FinalRequirementDecision.COMPLIANT)

if __name__=="__main__":unittest.main(verbosity=2)
