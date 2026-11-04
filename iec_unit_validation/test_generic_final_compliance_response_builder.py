import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_final_compliance_response_builder import FinalResponseContractError,GenericFinalComplianceResponseBuilder


class FinalComplianceResponseBuilderTests(unittest.TestCase):
 def issue(self,iid="I1",actionability="ACTIONABLE",clause="1",rg="R1"):
  return {"issue_id":iid,"clause_id":clause,"requirement_group_id":rg,"issue_type":"MISSING_EVIDENCE","compliance_conclusion":"NOT_EVALUATED","severity":"MEDIUM","actionability":actionability,"blocking":True,"user_explanation":"Explanation","impact":"Impact","next_action":{"type":"PROVIDE_EVIDENCE","description":"Provide"},"evidence_refs":[iid+"-E"],"provenance":{"source":"upstream"}}
 def group(self,gid="G1",issues=None):
  issues=issues or ["I1"];return {"group_id":gid,"issue_type":"MISSING_EVIDENCE","root_reason":"GAP","title":"Title","summary":"Summary","compliance_conclusion":"NOT_EVALUATED","conclusion_summary":{"NOT_EVALUATED":len(issues)},"primary_action":{"type":"PROVIDE_EVIDENCE","description":"Provide"},"issue_count":len(issues),"affected_requirement_count":len(issues),"affected_requirement_group_count":1,"affected_clause_count":1,"affected_clauses":["1"],"severity_summary":{"highest":"MEDIUM"},"blocking_summary":{"blocking_count":len(issues),"non_blocking_count":0,"unknown_count":0},"issue_ids":issues,"requirement_group_ids":["R1"],"evidence_refs":["I1-E"],"individual_issues":[]}
 def action(self,aid="A1",groups=None):
  return {"action_id":aid,"action_type":"PROVIDE_EVIDENCE","priority_level":2,"priority_label":"DO_NEXT","title":"Action","reason":"Reason","expected_outcome":"Outcome","affected_aggregate_group_ids":groups or ["G1"],"affected_issue_ids":["I1"],"affected_requirement_group_ids":["R1"],"affected_clauses":["1"],"affected_issue_count":1,"unique_clause_count":1,"severity_summary":{"highest":"MEDIUM"},"blocking_summary":{"blocking_count":1},"dependency":{"depends_on":[],"unlocks":[],"status":"RESOLVED"}}
 def fixtures(self):
  final={"issues":[self.issue()],"suppressed_findings":[],"summary":{"total_input_groups":1,"total_input_issues":1}}
  agg={"actionable_groups":[self.group()],"summary":{"actionable_source_issue_count":1},"source_final_issue_report_id":"FINAL"}
  plan={"actions":[self.action()],"metadata":{"source_aggregate_group_count":1},"source_aggregated_report_id":"AGG"}
  summary={"headline":"Headline","executive_summary":"Executive","main_findings":[],"unresolved_summary":{},"affected_scope_summary":{},"severity_summary":{},"issue_category_summary":{},"action_summary_text":"Actions","action_summary":{},"other_finding_count":1,"all_aggregate_group_ids":["G1"],"metadata":{"source_action_count":1,"source_aggregate_group_count":1}}
  status={"overall_status":"ACTION_REQUIRED","status_scope":"REPORT_EVALUATION","product_compliance_conclusion":"NOT_DETERMINED","requires_user_action":True,"can_complete_evaluation_now":False,"status_reason":"Reason","reason_codes":["ACTIONABLE_EVIDENCE_GAPS"],"decision_basis":{"planned_action_count":1}}
  return final,agg,plan,summary,status
 def build(self,fixtures=None,paths=None):return GenericFinalComplianceResponseBuilder().build(*(fixtures or self.fixtures()),source_artifact_paths=paths)
 def error(self,code,fixtures):
  with self.assertRaises(FinalResponseContractError) as ctx:self.build(fixtures)
  self.assertEqual(ctx.exception.code,code)

 def test_001_build(self):self.assertEqual(self.build().schema_version,"1.0")
 def test_002_status_exact(self):self.assertEqual(self.build().evaluation["overall_status"],"ACTION_REQUIRED")
 def test_003_product_exact(self):self.assertEqual(self.build().evaluation["product_compliance_conclusion"],"NOT_DETERMINED")
 def test_004_headline_exact(self):self.assertEqual(self.build().summary["headline"],"Headline")
 def test_005_summary_exact(self):self.assertEqual(self.build().summary["executive_summary"],"Executive")
 def test_006_action_order(self):
  f=list(self.fixtures());f[2]["actions"]=[self.action("A2"),self.action("A1")];f[2]["metadata"]["source_aggregate_group_count"]=1;f[3]["metadata"]["source_action_count"]=2;f[4]["decision_basis"]["planned_action_count"]=2;self.assertEqual([x["action_id"] for x in self.build(tuple(f)).next_actions],["A2","A1"])
 def test_007_priority(self):self.assertEqual(self.build().next_actions[0]["priority_level"],2)
 def test_008_group_order(self):
  f=list(self.fixtures());f[0]["issues"].append(self.issue("I2"));f[0]["summary"]["total_input_issues"]=2;f[1]["actionable_groups"]=[self.group("G2",["I2"]),self.group("G1")];f[1]["summary"]["actionable_source_issue_count"]=2;f[2]["actions"][0]["affected_aggregate_group_ids"]=["G2","G1"];f[2]["metadata"]["source_aggregate_group_count"]=2;f[3]["metadata"]["source_aggregate_group_count"]=2;self.assertEqual([x["group_id"] for x in self.build(tuple(f)).issue_groups],["G2","G1"])
 def test_009_issue_order(self):
  f=list(self.fixtures());f[0]["issues"]=[self.issue("I2"),self.issue("I1")];f[0]["summary"]["total_input_issues"]=2;f[1]["actionable_groups"][0]["issue_ids"]=["I2","I1"];f[1]["actionable_groups"][0]["issue_count"]=2;f[1]["summary"]["actionable_source_issue_count"]=2;self.assertEqual([x["issue_id"] for x in self.build(tuple(f)).detailed_issues],["I2","I1"])
 def test_010_all_actionable(self):self.assertEqual(len(self.build().detailed_issues),1)
 def test_011_suppressed_excluded(self):
  f=list(self.fixtures());f[0]["suppressed_findings"]=[self.issue("S1","SUPPRESSED")];f[0]["summary"]["total_input_issues"]=2;r=self.build(tuple(f));self.assertEqual(r.accounting["suppressed_finding_count"],1);self.assertNotIn("S1",[x["issue_id"] for x in r.detailed_issues])
 def test_012_informational_separate(self):
  f=list(self.fixtures());f[0]["issues"].append(self.issue("N1","INFORMATIONAL"));f[0]["summary"]["total_input_issues"]=2;r=self.build(tuple(f));self.assertEqual(len(r.informational_issues),1)
 def test_013_issue_refs(self):self.assertTrue(self.build().contract_validation["all_issue_references_valid"])
 def test_014_group_refs(self):self.assertTrue(self.build().contract_validation["all_action_references_valid"])
 def test_015_duplicate_issue(self):
  f=list(self.fixtures());f[0]["issues"].append(copy.deepcopy(f[0]["issues"][0]));self.error("DUPLICATE_ISSUE_ID",tuple(f))
 def test_016_duplicate_action(self):
  f=list(self.fixtures());f[2]["actions"].append(copy.deepcopy(f[2]["actions"][0]));self.error("DUPLICATE_ACTION_ID",tuple(f))
 def test_017_missing_issue_ref(self):
  f=list(self.fixtures());f[1]["actionable_groups"][0]["issue_ids"]=["UNKNOWN"];self.error("UNKNOWN_ISSUE_REFERENCE",tuple(f))
 def test_018_missing_group_ref(self):
  f=list(self.fixtures());f[2]["actions"][0]["affected_aggregate_group_ids"]=["UNKNOWN"];self.error("UNKNOWN_AGGREGATE_GROUP_REFERENCE",tuple(f))
 def test_019_action_count(self):
  f=list(self.fixtures());f[4]["decision_basis"]["planned_action_count"]=2;self.error("ACTION_COUNT_MISMATCH",tuple(f))
 def test_020_group_count(self):
  f=list(self.fixtures());f[3]["metadata"]["source_aggregate_group_count"]=2;self.error("AGGREGATE_COUNT_MISMATCH",tuple(f))
 def test_021_accounting(self):self.assertEqual(self.build().accounting["actionable_issue_count"],1)
 def test_022_clause_count(self):self.assertEqual(self.build().accounting["unique_clause_count"],1)
 def test_023_requirement_count(self):self.assertEqual(self.build().accounting["unique_requirement_group_count"],1)
 def test_024_evidence(self):self.assertEqual(self.build().detailed_issues[0]["evidence_refs"],["I1-E"])
 def test_025_provenance(self):self.assertEqual(self.build().detailed_issues[0]["provenance"],{"source":"upstream"})
 def test_026_hashes(self):self.assertEqual(set(self.build().provenance["artifact_hashes"]),set(GenericFinalComplianceResponseBuilder.SOURCE_NAMES))
 def test_027_source_hash_unchanged(self):
  with tempfile.TemporaryDirectory() as d:
   f=self.fixtures();paths={};before={}
   for name,value in zip(GenericFinalComplianceResponseBuilder.SOURCE_NAMES,f):p=Path(d)/name;p.write_text(json.dumps(value));paths[name]=p;before[name]=p.read_bytes()
   self.build(f,paths);self.assertEqual(before,{name:path.read_bytes() for name,path in paths.items()})
 def test_028_schema(self):self.assertEqual(self.build().schema_version,"1.0")
 def test_029_serialization(self):
  r=self.build();self.assertEqual(GenericFinalComplianceResponseBuilder.to_json(r),GenericFinalComplianceResponseBuilder.to_json(r))
 def test_030_output_hash(self):
  r=self.build();a=hashlib.sha256(GenericFinalComplianceResponseBuilder.to_json(r).encode()).hexdigest();b=hashlib.sha256(GenericFinalComplianceResponseBuilder.to_json(r).encode()).hexdigest();self.assertEqual(a,b)
 def test_031_object_immutable(self):
  f=self.fixtures();before=copy.deepcopy(f);self.build(f);self.assertEqual(f,before)
 def test_032_artifact_immutable(self):self.test_027_source_hash_unchanged()
 def test_033_no_status_recompute(self):self.assertEqual(self.build().evaluation["status_reason"],"Reason")
 def test_034_no_new_noncompliance(self):self.assertEqual(self.build().evaluation["product_compliance_conclusion"],"NOT_DETERMINED")
 def test_035_no_readiness_score(self):self.assertNotIn("readiness_score",GenericFinalComplianceResponseBuilder.to_dict(self.build()))
 def test_036_no_percentage(self):self.assertNotIn("compliance_percentage",GenericFinalComplianceResponseBuilder.to_dict(self.build()))
 def test_037_no_repriority(self):self.test_007_priority()
 def test_038_no_rewrite(self):self.test_005_summary_exact()
 def test_039_no_certification(self):self.assertNotIn("certified",self.build().summary["executive_summary"].casefold())
 def test_040_no_safety(self):self.assertNotIn("safe",self.build().summary["executive_summary"].casefold())
 def test_041_genericity(self):
  s=Path(__file__).parents[1].joinpath("iec_par/generic_final_compliance_response_builder.py").read_text().casefold()
  for x in ("60335","washing machine","clause_id ==","page ==","model ==","report =="):self.assertNotIn(x,s)
 def test_042_product_genericity(self):self.test_041_genericity()
 def test_043_fixture_genericity(self):self.test_041_genericity()
 def test_044_quality_zero(self):self.assertTrue(all(v==0 for v in self.build().quality_audit.values()))
 def test_045_missing_source(self):
  f=list(self.fixtures());f[0]=None;self.error("MISSING_SOURCE_ARTIFACT",tuple(f))
 def test_046_groups_do_not_duplicate_details(self):self.assertNotIn("individual_issues",self.build().issue_groups[0])
 def test_047_save(self):
  with tempfile.TemporaryDirectory() as d:self.assertTrue(GenericFinalComplianceResponseBuilder.save_json(self.build(),Path(d)/"out.json").exists())

if __name__=="__main__":unittest.main(verbosity=2)
