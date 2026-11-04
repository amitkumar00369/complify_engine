import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_final_issue_resolution import *

class FinalIssueTests(unittest.TestCase):
 def fixture(self,origin="MISSING_REPORT_EVIDENCE",status="INSUFFICIENT_EVIDENCE",severity="MEDIUM",disposition=None):
  issue={"issue_id":"UP-I","issue_type":origin,"severity":severity,"blocking":True,"reason":"upstream reason","evidence_ids":["E"],"requirement_ids":["R"],"product_fact_ids":["F"]};group={"group_id":"G","clause_id":"X","final_status":status,"issues":[issue]};clause={"clause_id":"X","group_summaries":[group]};summary={"clauses":[clause]};integrity={"source_clause_summary_id":"S","group_integrity_results":[]}
  if disposition:integrity["group_integrity_results"].append({"group_id":"G","clause_id":"X","resolved_status":status,"issues":[{"issue_id":"UP-I","integrity_status":disposition,"final_integrity_reason":"reason","reconciliation":"pointer" if disposition=="RECONCILED" else None}]})
  return summary,integrity
 def runx(self,**kw):return GenericFinalIssueResolver().resolve(*self.fixture(**kw))
 def test_001_noncompliance(self):self.assertEqual(self.runx(origin="TECHNICAL_VIOLATION",status="NON_COMPLIANT").issues[0].compliance_conclusion,ComplianceConclusion.NONCOMPLIANT)
 def test_002_unresolved(self):self.assertEqual(self.runx(origin="CONFLICTING_REPORT_VERDICT",status="UNRESOLVED",disposition="UNRESOLVED_CONFLICT").issues[0].compliance_conclusion,ComplianceConclusion.UNRESOLVED)
 def test_003_unresolved_action(self):self.assertEqual(self.runx(origin="CONFLICTING_REPORT_VERDICT",status="UNRESOLVED",disposition="UNRESOLVED_CONFLICT").issues[0].next_action.type,FinalActionType.LAB_CLARIFICATION)
 def test_004_reconciled_suppressed(self):
  r=self.runx(origin="CONFLICTING_REPORT_VERDICT",status="UNRESOLVED",disposition="RECONCILED");self.assertEqual(r.issues,[]);self.assertEqual(r.suppressed_findings[0].actionability,Actionability.SUPPRESSED)
 def test_005_missing_evidence(self):self.assertEqual(self.runx().issues[0].next_action.type,FinalActionType.PROVIDE_EVIDENCE)
 def test_006_insufficient_nonfailure(self):self.assertNotEqual(self.runx().issues[0].compliance_conclusion,ComplianceConclusion.NONCOMPLIANT)
 def test_007_invalid_test(self):self.assertEqual(self.runx(origin="TEST_CONDITION_MISMATCH").issues[0].next_action.type,FinalActionType.RETEST)
 def test_008_calculation(self):self.assertEqual(self.runx(origin="CALCULATION_MISMATCH").issues[0].next_action.type,FinalActionType.CORRECT_CALCULATION)
 def test_009_na(self):self.assertEqual(self.runx(origin="NA_APPLICABILITY_CONFLICT").issues[0].next_action.type,FinalActionType.PROVIDE_NA_JUSTIFICATION)
 def test_010_product(self):self.assertEqual(self.runx(origin="MISSING_PRODUCT_INFORMATION").issues[0].next_action.type,FinalActionType.PROVIDE_PRODUCT_INFORMATION)
 def test_011_traceability(self):self.assertEqual(self.runx(origin="EVIDENCE_NOT_LINKED").issues[0].issue_type,FinalIssueType.TRACEABILITY_ISSUE)
 def test_012_report_inconsistency(self):self.assertEqual(self.runx(origin="PRODUCT_INFORMATION_CONFLICT").issues[0].next_action.type,FinalActionType.CORRECT_REPORT)
 def test_013_severity(self):self.assertEqual(self.runx(severity="HIGH").issues[0].severity,FinalSeverity.HIGH)
 def test_014_unknown_severity(self):self.assertEqual(self.runx(severity=None).issues[0].severity,FinalSeverity.UNKNOWN)
 def test_015_actionable(self):self.assertEqual(self.runx().issues[0].actionability,Actionability.ACTIONABLE)
 def test_016_evidence(self):self.assertEqual(self.runx().issues[0].evidence_refs,["E"])
 def test_017_status_provenance(self):self.assertEqual(self.runx().issues[0].provenance.step_25b_status,"INSUFFICIENT_EVIDENCE")
 def test_018_origin_provenance(self):self.assertEqual(self.runx().issues[0].provenance.originating_issue_id,"UP-I")
 def test_019_ids(self):self.assertEqual(self.runx().issues[0].issue_id,self.runx().issues[0].issue_id)
 def test_020_json(self):self.assertEqual(GenericFinalIssueResolver.to_json(self.runx()),GenericFinalIssueResolver.to_json(self.runx()))
 def test_021_object_immutable(self):
  f=self.fixture();b=copy.deepcopy(f);GenericFinalIssueResolver().resolve(*f);self.assertEqual(f,b)
 def test_022_artifact_immutable(self):self.test_021_object_immutable()
 def test_023_status_not_mutated(self):self.assertEqual(self.fixture()[0]["clauses"][0]["group_summaries"][0]["final_status"],"INSUFFICIENT_EVIDENCE")
 def test_024_unresolved_not_failure(self):self.assertNotEqual(self.runx(status="UNRESOLVED").issues[0].compliance_conclusion,ComplianceConclusion.NONCOMPLIANT)
 def test_025_missing_not_failure(self):self.assertNotEqual(self.runx().issues[0].compliance_conclusion,ComplianceConclusion.NONCOMPLIANT)
 def test_026_reconciled_not_conflict(self):self.test_004_reconciled_suppressed()
 def test_027_no_overall(self):self.assertNotIn("overall_status",GenericFinalIssueResolver.to_json(self.runx()).casefold())
 def test_028_no_score(self):self.assertNotIn("readiness_score",GenericFinalIssueResolver.to_json(self.runx()))
 def test_029_no_certification(self):self.assertNotIn("certified",GenericFinalIssueResolver.to_json(self.runx()).casefold())
 def test_030_save(self):
  with tempfile.TemporaryDirectory() as d:self.assertTrue(GenericFinalIssueResolver.save_json(self.runx(),Path(d)/"x.json").exists())
 def test_031_genericity(self):
  s=Path(__file__).parents[1].joinpath("iec_par/generic_final_issue_resolution.py").read_text().casefold();self.assertNotIn("washing machine",s);self.assertNotIn("60335",s);self.assertNotIn("10.1",s);self.assertNotIn("11.8",s)
 def test_032_quality(self):self.assertTrue(all(v==0 for v in self.runx().quality_audit.values()))
 def test_033_every_actionable_has_action(self):self.assertNotEqual(self.runx().issues[0].next_action.type,FinalActionType.NO_ACTION)

if __name__=="__main__":unittest.main(verbosity=2)
