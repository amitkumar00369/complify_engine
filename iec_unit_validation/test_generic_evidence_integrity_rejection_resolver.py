import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_evidence_integrity_rejection_resolver import *
from iec_par.generic_compliance_summary_models import IssueType,FinalComplianceStatus

class IntegrityTests(unittest.TestCase):
 def setUp(self):self.r=GenericEvidenceIntegrityRejectionResolver()
 def value(self,**kw):
  d=dict(issue_type=IssueType.CROSS_EVIDENCE_VALUE_CONFLICT,normalized_parameter="rated_power",comparison_parameter="rated_power",scope_state=EvidenceScopeState.SAME_SCOPE,requirement_context_ids=["G"],comparison_context_ids=["G"],source_reliability=[EvidenceReliability.HIGH,EvidenceReliability.HIGH],materially_inconsistent=True,materiality_rule_id="EXACT_IDENTITY",reconciliation_checked=True,affects_evaluation_validity=True,evidence_ids=["E1","E2"],compared_values=[1,2]);d.update(kw);return IntegrityConflictCandidate(**d)
 def verdict(self,**kw):
  d=dict(issue_type=IssueType.CONFLICTING_REPORT_VERDICT,scope_state=EvidenceScopeState.SAME_SCOPE,requirement_context_ids=["G"],comparison_context_ids=["G"],source_reliability=[EvidenceReliability.HIGH,EvidenceReliability.HIGH],materially_inconsistent=True,reconciliation_checked=True,affects_evaluation_validity=True,evidence_ids=["E1","E2"],compared_verdicts=["PASS","FAIL"],ownership_confirmed=True,structural_explanation_absent=True);d.update(kw);return IntegrityConflictCandidate(**d)
 def test_001_exact_rating_rejected(self):self.assertEqual(self.r.evaluate_candidate(self.value()).integrity_status,IntegrityStatus.CONFIRMED_MATERIAL_CONFLICT)
 def test_002_different_model(self):self.assertEqual(self.r.evaluate_candidate(self.value(scope_state=EvidenceScopeState.DIFFERENT_SCOPE)).integrity_status,IntegrityStatus.NON_MATERIAL_DIFFERENCE)
 def test_003_unknown_scope(self):self.assertEqual(self.r.evaluate_candidate(self.value(scope_state=EvidenceScopeState.UNKNOWN_SCOPE)).integrity_status,IntegrityStatus.UNRESOLVED_CONFLICT)
 def test_004_different_parameter(self):self.assertEqual(self.r.evaluate_candidate(self.value(comparison_parameter="measured_power")).integrity_status,IntegrityStatus.NON_MATERIAL_DIFFERENCE)
 def test_005_rated_measured_reconciled(self):self.assertEqual(self.r.evaluate_candidate(self.value(supported_reconciliation="rated versus measured semantics")).integrity_status,IntegrityStatus.RECONCILED)
 def test_006_input_calculated_reconciled(self):self.assertEqual(self.r.evaluate_candidate(self.value(supported_reconciliation="input and calculated result")).integrity_status,IntegrityStatus.RECONCILED)
 def test_007_pass_fail_rejected(self):self.assertEqual(self.r.evaluate_candidate(self.verdict()).integrity_status,IntegrityStatus.CONFIRMED_MATERIAL_CONFLICT)
 def test_008_pointer_reconciled(self):self.assertEqual(self.r.evaluate_candidate(self.verdict(supported_reconciliation="parent points to table",structural_explanation_absent=False)).integrity_status,IntegrityStatus.RECONCILED)
 def test_009_parent_child_unresolved(self):self.assertEqual(self.r.evaluate_candidate(self.verdict(ownership_confirmed=None,scope_state=EvidenceScopeState.AMBIGUOUS_SCOPE)).integrity_status,IntegrityStatus.UNRESOLVED_CONFLICT)
 def test_010_identical_no_issue(self):self.assertEqual(self.r.evaluate_candidate(self.value(materially_inconsistent=False,compared_values=[1,1])).integrity_status,IntegrityStatus.NON_MATERIAL_DIFFERENCE)
 def test_011_missing_second(self):self.assertEqual(self.r.evaluate_candidate(self.value(evidence_ids=["E1"],compared_values=[1])).integrity_status,IntegrityStatus.INSUFFICIENT_DATA)
 def test_012_low_reliability(self):self.assertEqual(self.r.evaluate_candidate(self.value(source_reliability=[EvidenceReliability.HIGH,EvidenceReliability.LOW])).integrity_status,IntegrityStatus.UNRESOLVED_CONFLICT)
 def test_013_mode_reconciled(self):self.assertEqual(self.r.evaluate_candidate(self.value(supported_reconciliation="different operating mode")).integrity_status,IntegrityStatus.RECONCILED)
 def test_014_identity_requires_scope(self):self.assertNotEqual(self.r.evaluate_candidate(self.value(issue_type=IssueType.SAMPLE_IDENTITY_CONFLICT,scope_state=EvidenceScopeState.UNKNOWN_SCOPE)).integrity_status,IntegrityStatus.CONFIRMED_MATERIAL_CONFLICT)
 def test_015_calculation_proven(self):self.assertEqual(self.r.evaluate_candidate(self.value(issue_type=IssueType.CALCULATION_MISMATCH)).integrity_status,IntegrityStatus.CONFIRMED_MATERIAL_CONFLICT)
 def test_016_calculation_unsafe(self):self.assertEqual(self.r.evaluate_candidate(self.value(issue_type=IssueType.CALCULATION_MISMATCH,materially_inconsistent=None,materiality_rule_id=None)).integrity_status,IntegrityStatus.UNRESOLVED_CONFLICT)
 def test_017_matched_condition(self):self.assertEqual(self.r.evaluate_candidate(self.value(issue_type=IssueType.TEST_CONDITION_MISMATCH,linkage_status="MATCHED")).integrity_status,IntegrityStatus.CONFIRMED_MATERIAL_CONFLICT)
 def test_018_possible_never_rejected(self):self.assertNotEqual(self.r.evaluate_candidate(self.value(linkage_status="POSSIBLE")).integrity_status,IntegrityStatus.CONFIRMED_MATERIAL_CONFLICT)
 def test_019_ambiguous_never_rejected(self):self.assertNotEqual(self.r.evaluate_candidate(self.value(linkage_status="AMBIGUOUS")).integrity_status,IntegrityStatus.CONFIRMED_MATERIAL_CONFLICT)
 def test_020_no_tolerance(self):self.assertEqual(self.r.evaluate_candidate(self.value(materially_inconsistent=None,materiality_rule_id=None)).integrity_status,IntegrityStatus.UNRESOLVED_CONFLICT)
 def fixture(self):
  issue={"issue_id":"I","issue_type":"CONFLICTING_REPORT_VERDICT","requirement_ids":["R"]};g={"group_id":"G","clause_id":"X","final_status":"UNRESOLVED","issues":[issue],"report_evidence":[{"evidence_id":"E1","reported_verdict":"NA","scope_status":"EXACT_GROUP","text_preview":"see appended table"},{"evidence_id":"E2","reported_verdict":"PASS","scope_status":"EXACT_GROUP","text_preview":"TABLE: result"}]};c={"clause_id":"X","final_status":"UNRESOLVED","group_summaries":[g],"source_traceability":{}};return [{"clauses":[c]},{},{},{},{},{},None,None,None,None,None,None,None,None]
 def test_021_pointer_fixture(self):self.assertEqual(self.r.resolve(*self.fixture()).group_integrity_results[0].issues[0].integrity_status,IntegrityStatus.RECONCILED)
 def test_022_serialization(self):json.loads(self.r.to_json(self.r.resolve(*self.fixture())))
 def test_023_deterministic(self):self.assertEqual(self.r.to_json(self.r.resolve(*self.fixture())),self.r.to_json(self.r.resolve(*self.fixture())))
 def test_024_immutable(self):
  f=self.fixture();b=copy.deepcopy(f);self.r.resolve(*f);self.assertEqual(f,b)
 def test_025_optional_absent(self):self.assertEqual(self.r.resolve(*self.fixture()).summary["groups_with_integrity_issues"],1)
 def test_026_save(self):
  with tempfile.TemporaryDirectory() as d:self.assertTrue(self.r.save_json(self.r.resolve(*self.fixture()),Path(d)/"x.json").exists())
 def test_027_genericity(self):
  s=Path(__file__).parents[1].joinpath("iec_par/generic_evidence_integrity_rejection_resolver.py").read_text().casefold();self.assertNotIn("washing machine",s);self.assertNotIn("60335",s);self.assertNotIn("10.1",s)
 def test_028_quality_zero(self):self.assertTrue(all(v==0 for v in self.r.resolve(*self.fixture()).quality_audit.values()))
 def test_029_missing_not_rejected(self):self.assertNotEqual(self.r.evaluate_candidate(IntegrityConflictCandidate(IssueType.CONFLICTING_EVIDENCE)).integrity_status,IntegrityStatus.CONFIRMED_MATERIAL_CONFLICT)
 def test_030_prior_not_modified(self):self.assertEqual(self.r.resolve(*self.fixture()).group_integrity_results[0].prior_25b_status,FinalComplianceStatus.UNRESOLVED)

if __name__=="__main__":unittest.main(verbosity=2)
