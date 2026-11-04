import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_compliance_summary_models import *
from iec_par.generic_compliance_issue_policy import *

class PolicyTests(unittest.TestCase):
 def setUp(self):self.p=GenericComplianceIssuePolicy()
 def issue(self,t):return ComplianceIssue(t,self.p.severity_for(t),True,"s","r")
 def test_technical_violation(self):self.assertEqual(self.p.resolve(proven_technical_violation=True),FinalComplianceStatus.NON_COMPLIANT)
 def test_missing_measurement(self):self.assertEqual(self.p.resolve(issues=[self.issue(IssueType.MISSING_MEASUREMENT)]),FinalComplianceStatus.INSUFFICIENT_EVIDENCE)
 def test_unknown_applicability(self):self.assertEqual(self.p.resolve(issues=[self.issue(IssueType.UNKNOWN_APPLICABILITY)]),FinalComplianceStatus.UNRESOLVED)
 def test_justified_na(self):self.assertEqual(self.p.resolve(justified_not_applicable=True),FinalComplianceStatus.NOT_APPLICABLE)
 def test_inactive(self):self.assertEqual(self.p.resolve(inactive=True),FinalComplianceStatus.INACTIVE)
 def full_value(self,**kw):return ValueConflictRejectionEvidence(**({"same_normalized_parameter":True,"equivalent_product_scope":True,"same_requirement_context":True,"both_sources_reliable":True,"materially_inconsistent":True,"supported_reconciliation_absent":True,"affects_evaluation_validity":True}|kw))
 def test_confirmed_value_conflict(self):self.assertTrue(self.p.value_conflict_rejected(self.full_value()))
 def test_different_parameters(self):self.assertFalse(self.p.value_conflict_rejected(self.full_value(same_normalized_parameter=False)))
 def test_different_sample(self):self.assertFalse(self.p.value_conflict_rejected(self.full_value(equivalent_product_scope=False)))
 def test_ambiguous_scope(self):self.assertFalse(self.p.value_conflict_rejected(self.full_value(scope_ambiguous=True)))
 def test_unreliable_source(self):self.assertFalse(self.p.value_conflict_rejected(self.full_value(both_sources_reliable=False)))
 def test_reconciliation_exists(self):self.assertFalse(self.p.value_conflict_rejected(self.full_value(supported_reconciliation_absent=False)))
 def full_verdict(self,**kw):return VerdictConflictRejectionEvidence(**({"same_logical_scope":True,"same_proven_evidence_scope":True,"verdict_ownership_confirmed":True,"structural_explanation_absent":True,"valid_reconciliation_absent":True}|kw))
 def test_pass_na_unproven(self):self.assertFalse(self.p.verdict_conflict_rejected(self.full_verdict(verdict_ownership_confirmed=False)))
 def test_pass_fail_proven(self):self.assertTrue(self.p.verdict_conflict_rejected(self.full_verdict()))
 def test_missing_never_noncompliant(self):self.assertNotEqual(self.p.resolve(evidence_sufficient=False),FinalComplianceStatus.NON_COMPLIANT)
 def test_missing_never_rejected(self):self.assertNotEqual(self.p.resolve(evidence_sufficient=False),FinalComplianceStatus.REJECTED)
 def test_unknown_never_noncompliant(self):self.assertNotEqual(self.p.resolve(issues=[self.issue(IssueType.UNKNOWN_APPLICABILITY)]),FinalComplianceStatus.NON_COMPLIANT)
 def test_ambiguous_never_rejected(self):self.assertNotEqual(self.p.resolve(issues=[self.issue(IssueType.AMBIGUOUS_REPORT_SCOPE)]),FinalComplianceStatus.REJECTED)
 def test_unconfirmed_rejection_issue_unresolved(self):self.assertEqual(self.p.resolve(issues=[self.issue(IssueType.CROSS_EVIDENCE_VALUE_CONFLICT)]),FinalComplianceStatus.UNRESOLVED)
 def test_confirmed_rejection(self):self.assertEqual(self.p.resolve(proven_integrity_rejection=True),FinalComplianceStatus.REJECTED)
 def test_precedence_noncompliance(self):self.assertEqual(self.p.aggregate_same_scope([FinalComplianceStatus.REJECTED,FinalComplianceStatus.NON_COMPLIANT]),FinalComplianceStatus.NON_COMPLIANT)
 def test_precedence_missing(self):self.assertEqual(self.p.aggregate_same_scope([FinalComplianceStatus.UNRESOLVED,FinalComplianceStatus.INSUFFICIENT_EVIDENCE]),FinalComplianceStatus.INSUFFICIENT_EVIDENCE)
 def test_action_missing(self):self.assertEqual(self.p.actions_for(IssueType.MISSING_REPORT_EVIDENCE),[ActionType.PROVIDE_REPORT_EVIDENCE])
 def test_action_conflict(self):self.assertEqual(len(self.p.actions_for(IssueType.CROSS_EVIDENCE_VALUE_CONFLICT)),2)
 def test_severity_violation(self):self.assertEqual(self.p.severity_for(IssueType.TECHNICAL_VIOLATION),IssueSeverity.CRITICAL)
 def test_override(self):
  p=GenericComplianceIssuePolicy(EvaluationPolicy(severity_overrides={IssueType.TECHNICAL_VIOLATION:IssueSeverity.HIGH}));self.assertEqual(p.severity_for(IssueType.TECHNICAL_VIOLATION),IssueSeverity.HIGH)
 def test_blocking_defaults(self):
  self.assertTrue(self.p.blocks(FinalComplianceStatus.INSUFFICIENT_EVIDENCE));self.assertFalse(self.p.blocks(FinalComplianceStatus.NOT_APPLICABLE))
 def test_empty_compliant(self):self.assertEqual(self.p.resolve(),FinalComplianceStatus.COMPLIANT)
 def test_not_applicable_after_unresolved(self):self.assertEqual(self.p.resolve(issues=[self.issue(IssueType.UNKNOWN_APPLICABILITY)],justified_not_applicable=True),FinalComplianceStatus.UNRESOLVED)
 def test_genericity(self):
  s=Path(__file__).parents[1].joinpath("iec_par/generic_compliance_issue_policy.py").read_text().casefold();self.assertNotIn("washing machine",s);self.assertNotIn("60335",s);self.assertNotIn("400 w",s)

if __name__=="__main__":unittest.main(verbosity=2)
