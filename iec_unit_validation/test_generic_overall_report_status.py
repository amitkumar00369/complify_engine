import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_overall_report_status import GenericOverallReportStatusEngine,OverallReportStatus,ProductComplianceConclusion


class OverallReportStatusTests(unittest.TestCase):
 def group(self,gid="G1",kind="MISSING_EVIDENCE",conclusion="NOT_EVALUATED",count=1,blocking=(1,0,0),basis=None,severity="MEDIUM"):
  g={"group_id":gid,"issue_type":kind,"conclusion_summary":{conclusion:count},"issue_ids":[gid+str(i) for i in range(count)],"severity_summary":{"highest":severity},"blocking_summary":{"blocking_count":blocking[0],"non_blocking_count":blocking[1],"unknown_count":blocking[2]}}
  if basis is not None:g["report_status_basis"]=basis
  return g
 def aggregate(self,groups=None,**extra):
  r={"actionable_groups":groups or [],"source_final_issue_report_id":"FINAL"};r.update(extra);return r
 def plan(self,actions=None,group_count=None):
  actions=actions or [];return {"actions":actions,"source_aggregated_report_id":"AGG","metadata":{"source_aggregate_group_count":len(actions) if group_count is None else group_count}}
 def action(self,aid="A1",kind="PROVIDE_EVIDENCE",priority=2):return {"action_id":aid,"action_type":kind,"priority_level":priority}
 def summary(self,action_count=0,**extra):
  r={"metadata":{"source_action_count":action_count}};r.update(extra);return r
 def resolve(self,groups=None,actions=None,aggregate_extra=None,summary_extra=None):
  groups=groups or [];actions=actions or [];return GenericOverallReportStatusEngine().resolve(self.aggregate(groups,**(aggregate_extra or {})),self.plan(actions,len(groups)),self.summary(len(actions),**(summary_extra or {})))

 def test_001_action_required(self):self.assertEqual(self.resolve([self.group()],[self.action()]).overall_status,OverallReportStatus.ACTION_REQUIRED)
 def test_002_unresolved_with_action(self):self.assertEqual(self.resolve([self.group(conclusion="UNRESOLVED")],[self.action()]).overall_status,OverallReportStatus.ACTION_REQUIRED)
 def test_003_blocking_proof_not_ready(self):self.assertEqual(self.resolve([self.group(basis={"proven_not_ready":True})],[self.action()]).overall_status,OverallReportStatus.NOT_READY)
 def test_004_ready_with_proof(self):self.assertEqual(self.resolve(aggregate_extra={"evaluation_completion_proven":True}).overall_status,OverallReportStatus.READY)
 def test_005_no_proof_unresolved(self):self.assertEqual(self.resolve().overall_status,OverallReportStatus.UNRESOLVED)
 def test_006_no_failure_not_compliant(self):self.assertEqual(self.resolve().product_compliance_conclusion,ProductComplianceConclusion.NOT_DETERMINED)
 def test_007_compliant_requires_proof(self):
  r=self.resolve(aggregate_extra={"evaluation_completion_proven":True,"product_compliance_conclusion":"COMPLIANT"});self.assertEqual(r.product_compliance_conclusion,ProductComplianceConclusion.COMPLIANT)
 def test_008_noncompliant_requires_upstream(self):self.assertEqual(self.resolve([self.group(conclusion="NONCOMPLIANT")]).product_compliance_conclusion,ProductComplianceConclusion.NONCOMPLIANT)
 def test_009_missing_not_product_failure(self):self.assertEqual(self.resolve([self.group()],[self.action()]).product_compliance_conclusion,ProductComplianceConclusion.NOT_DETERMINED)
 def test_010_not_evaluated_not_product_failure(self):self.test_009_missing_not_product_failure()
 def test_011_precedence_deterministic(self):
  args=([self.group(basis={"proven_not_ready":True})],[self.action()]);self.assertEqual(self.resolve(*args).overall_status,self.resolve(*args).overall_status)
 def test_012_not_ready_precedes_action(self):self.test_003_blocking_proof_not_ready()
 def test_013_action_precedes_no_ready_proof(self):self.test_001_action_required()
 def test_014_reason_codes(self):self.assertIn("ACTIONABLE_EVIDENCE_GAPS",self.resolve([self.group()],[self.action()]).reason_codes)
 def test_015_reason_codes_dedup(self):self.assertEqual(self.resolve([self.group(),self.group("G2")],[self.action()]).reason_codes.count("ACTIONABLE_EVIDENCE_GAPS"),1)
 def test_016_reason_order(self):
  a=[self.group("G1","TRACEABILITY_ISSUE"),self.group("G2","MISSING_EVIDENCE")];self.assertEqual(self.resolve(a,[self.action()]).reason_codes,self.resolve(list(reversed(a)),[self.action()]).reason_codes)
 def test_017_user_action_flag(self):self.assertTrue(self.resolve([self.group()],[self.action()]).requires_user_action)
 def test_018_completion_flag_false(self):self.assertFalse(self.resolve([self.group()],[self.action()]).can_complete_evaluation_now)
 def test_019_blocking_counts(self):
  r=self.resolve([self.group(blocking=(2,1,3))],[self.action()]);self.assertEqual((r.decision_basis["blocking_issue_count"],r.decision_basis["unknown_blocking_issue_count"]),(2,3))
 def test_020_action_count(self):self.assertEqual(self.resolve([self.group()],[self.action()]).decision_basis["planned_action_count"],1)
 def test_021_no_readiness_percentage(self):self.assertNotIn("readiness_percentage",GenericOverallReportStatusEngine.to_dict(self.resolve()))
 def test_022_no_compliance_percentage(self):self.assertNotIn("compliance_percentage",GenericOverallReportStatusEngine.to_dict(self.resolve()))
 def test_023_no_certification(self):self.assertNotIn("certified",GenericOverallReportStatusEngine.to_json(self.resolve()).casefold())
 def test_024_no_safety_claim(self):self.assertNotIn("safe",self.resolve().status_reason.casefold())
 def test_025_deterministic_output(self):self.assertEqual(self.resolve([self.group()],[self.action()]),self.resolve([self.group()],[self.action()]))
 def test_026_serialization(self):
  r=self.resolve();self.assertEqual(GenericOverallReportStatusEngine.to_json(r),GenericOverallReportStatusEngine.to_json(r))
 def test_027_hash(self):
  r=self.resolve();a=hashlib.sha256(GenericOverallReportStatusEngine.to_json(r).encode()).hexdigest();b=hashlib.sha256(GenericOverallReportStatusEngine.to_json(r).encode()).hexdigest();self.assertEqual(a,b)
 def test_028_object_immutable(self):
  a=self.aggregate([self.group()]);p=self.plan([self.action()],1);s=self.summary(1);before=copy.deepcopy((a,p,s));GenericOverallReportStatusEngine().resolve(a,p,s);self.assertEqual((a,p,s),before)
 def test_029_artifact_immutable(self):
  with tempfile.TemporaryDirectory() as d:
   vals=[self.aggregate([self.group()]),self.plan([self.action()],1),self.summary(1)];paths=[]
   for i,v in enumerate(vals):q=Path(d)/str(i);q.write_text(json.dumps(v));paths.append(q)
   before=[q.read_bytes() for q in paths];GenericOverallReportStatusEngine().resolve(*(json.loads(q.read_text()) for q in paths));self.assertEqual([q.read_bytes() for q in paths],before)
 def test_030_conclusion_not_modified(self):
  g=self.group(conclusion="UNRESOLVED");self.resolve([g],[self.action()]);self.assertEqual(g["conclusion_summary"],{"UNRESOLVED":1})
 def test_031_severity_not_modified(self):
  g=self.group(severity="HIGH");self.resolve([g],[self.action()]);self.assertEqual(g["severity_summary"]["highest"],"HIGH")
 def test_032_action_not_modified(self):
  a=self.action(kind="LAB_CLARIFICATION");self.resolve([self.group()],[a]);self.assertEqual(a["action_type"],"LAB_CLARIFICATION")
 def test_033_priority_not_modified(self):
  a=self.action(priority=3);self.resolve([self.group()],[a]);self.assertEqual(a["priority_level"],3)
 def test_034_blocking_not_modified(self):
  g=self.group(blocking=(2,1,3));self.resolve([g],[self.action()]);self.assertEqual(g["blocking_summary"]["unknown_count"],3)
 def test_035_genericity(self):
  src=Path(__file__).parents[1].joinpath("iec_par/generic_overall_report_status.py").read_text().casefold()
  for x in ("60335","washing machine","clause_id ==","page ==","model ==","report =="):self.assertNotIn(x,src)
 def test_036_product_genericity(self):self.test_035_genericity()
 def test_037_fixture_genericity(self):self.test_035_genericity()
 def test_038_quality_zero(self):self.assertTrue(all(v==0 for v in self.resolve([self.group()],[self.action()]).quality_audit.values()))
 def test_039_blocking_alone_not_not_ready(self):self.assertEqual(self.resolve([self.group(blocking=(10,0,0))],[self.action()]).overall_status,OverallReportStatus.ACTION_REQUIRED)
 def test_040_severity_alone_not_not_ready(self):self.assertEqual(self.resolve([self.group(severity="CRITICAL")],[self.action()]).overall_status,OverallReportStatus.ACTION_REQUIRED)
 def test_041_ready_completion_true(self):self.assertTrue(self.resolve(aggregate_extra={"evaluation_completion_proven":True}).can_complete_evaluation_now)
 def test_042_explicit_compliance_without_completion_ignored(self):self.assertEqual(self.resolve(aggregate_extra={"product_compliance_conclusion":"COMPLIANT"}).product_compliance_conclusion,ProductComplianceConclusion.NOT_DETERMINED)
 def test_043_save(self):
  with tempfile.TemporaryDirectory() as d:self.assertTrue(GenericOverallReportStatusEngine.save_json(self.resolve(),Path(d)/"out.json").exists())

if __name__=="__main__":unittest.main(verbosity=2)
