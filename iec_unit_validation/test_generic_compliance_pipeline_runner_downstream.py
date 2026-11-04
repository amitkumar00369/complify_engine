"""Integration tests for runner orchestration through the final SaaS response."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_compliance_pipeline_runner import GenericCompliancePipelineRunner,PipelineStatus

class Save:
 def save_json(self,value,path):Path(path).write_text(json.dumps(value,sort_keys=True,default=str))
class KB(Save):
 def build_base_kb(self,p):return {"document":{"standard_number":"100-1"}}
 def build_delta_kb(self,p):return {"document":{"standard_number":"100-2","parent_standard":"100-1"}}
class Validator:
 def validate(self,x):return {"valid":True}
 def validate_pair(self,a,b):return {"valid":True}
class Effective(Save):
 def build(self,*x):return {"clauses":[]}
class Evidence(Save):
 def extract(self,p):return {"standard_numbers":["100-1","100-2"],"clauses":[]}
class Method(Save):
 def __init__(self,name,method,calls,result):self.name=name;self.calls=calls;self.result=result;setattr(self,method,self.invoke)
 def invoke(self,*args,**kwargs):self.calls.append((self.name,args,kwargs));return copy.deepcopy(self.result)
class ClauseSummary(Save):
 def __init__(self,calls):self.calls=calls
 def build(self,*args):self.calls.append(("clause_summary",args,{}));return []
 def to_dict(self,value):return {"schema_version":"1.0","clauses":value,"summary":{}}
class FailingSummary(ClauseSummary):
 def build(self,*args):raise RuntimeError("downstream failure")

class DownstreamRunnerTests(unittest.TestCase):
 def setup(self,calls,fail=False):
  integrity={"group_integrity_results":[]};final_issues={"issues":[],"suppressed_findings":[],"summary":{"total_input_groups":0,"total_input_issues":0}}
  aggregated={"actionable_groups":[],"summary":{"actionable_source_issue_count":0}}
  actions={"actions":[],"metadata":{"source_aggregate_group_count":0}}
  executive={"headline":"Headline","executive_summary":"Summary","main_findings":[],"metadata":{"source_action_count":0,"source_aggregate_group_count":0}}
  status={"overall_status":"ACTION_REQUIRED","product_compliance_conclusion":"NOT_DETERMINED","decision_basis":{"planned_action_count":0}}
  response={"schema_version":"1.0","evaluation":{"overall_status":"ACTION_REQUIRED"}}
  components={"kb_builder":KB(),"kb_validator":Validator(),"effective_builder":Effective(),"report_evidence_extractor":Evidence(),
   "profile_builder":Method("profile","build",calls,{}),"applicability":Method("app","evaluate",calls,{}),"evidence_matcher":Method("matches","match",calls,{}),"technical":Method("tech","evaluate",calls,{}),"na_validator":Method("na","validate",calls,{}),"na_auditor":Method("audit","audit",calls,{}),"grouping":Method("grouping","resolve",calls,{"groups":[]}),"group_applicability":Method("group_app","resolve",calls,{}),"group_na":Method("group_na","validate",calls,{}),"scope":Method("scope","resolve",calls,{}),"scope_na":Method("scope_na","validate",calls,{}),"final":Method("final","evaluate",calls,{}),"coverage":Method("coverage","analyze",calls,{}),"readiness":Method("readiness","build",calls,{}),
   "clause_summary":FailingSummary(calls) if fail else ClauseSummary(calls),"evidence_integrity":Method("integrity","resolve",calls,integrity),"final_issues":Method("final_issues","resolve",calls,final_issues),"issue_aggregator":Method("aggregated","aggregate",calls,aggregated),"action_prioritizer":Method("actions","prioritize",calls,actions),"executive_summary":Method("executive","build",calls,executive),"overall_report_status":Method("status","resolve",calls,status),"final_response":Method("response","build",calls,response)}
  return components
 def pdfs(self,d):
  paths=[]
  for name in ("base.pdf","part.pdf","report.pdf"):p=Path(d)/name;p.write_bytes(b"%PDF-1.4\n");paths.append(p)
  return paths
 def test_full_pipeline_reaches_step_30_and_preserves_handoffs(self):
  calls=[]
  with tempfile.TemporaryDirectory() as d:
   base,part,report=self.pdfs(d);out=Path(d)/"run";runner=GenericCompliancePipelineRunner(components=self.setup(calls),clock=lambda:"T")
   result=runner.run(base,part,report,out,run_id="RUN-TEST")
   self.assertEqual(result.pipeline_status,PipelineStatus.SUCCESS_WITH_REVIEW)
   resolved_out=out.resolve();self.assertEqual(result.final_artifact,str(resolved_out/"decisions/final_compliance_response.json"))
   artifacts=["clause_evaluation_summary.json","evidence_integrity_rejection_result.json","final_compliance_issues.json","aggregated_compliance_issues.json","prioritized_next_actions.json","executive_compliance_summary.json","overall_report_status.json","final_compliance_response.json"]
   self.assertTrue(all((resolved_out/"decisions"/name).is_file() for name in artifacts))
   manifest=json.loads((resolved_out/"manifest/pipeline_manifest.json").read_text());self.assertEqual(manifest["final_result"],{"overall_status":"ACTION_REQUIRED","product_compliance_conclusion":"NOT_DETERMINED","output_artifact":str(resolved_out/"decisions/final_compliance_response.json")})
   self.assertEqual([x["step_name"] for x in manifest["step_execution_records"]],list(GenericCompliancePipelineRunner.STEP_ORDER))
   by_name={name:(args,kwargs) for name,args,kwargs in calls}
   self.assertIs(by_name["integrity"][0][0],by_name["final_issues"][0][0]);self.assertIs(by_name["aggregated"][0][0],by_name["response"][0][0]);self.assertIs(by_name["actions"][0][0],by_name["executive"][0][0]);self.assertIs(by_name["executive"][0][1],by_name["status"][0][1]);self.assertEqual(len(by_name["response"][0]),5)
 def test_downstream_failure_is_manifested(self):
  calls=[]
  with tempfile.TemporaryDirectory() as d:
   base,part,report=self.pdfs(d);out=Path(d)/"run";result=GenericCompliancePipelineRunner(components=self.setup(calls,True),clock=lambda:"T").run(base,part,report,out,run_id="RUN-FAIL")
   self.assertEqual(result.pipeline_status,PipelineStatus.FAILED);manifest=json.loads((out/"manifest/pipeline_manifest.json").read_text());record=manifest["step_execution_records"][-1];self.assertEqual(record["step_name"],"clause_evaluation_summary");self.assertEqual(record["status"],"FAILED")
 def test_steps_1_through_24_order_unchanged(self):
  expected=("base_kb","base_validation","delta_kb","delta_validation","pair_validation","effective_kb","report_evidence","standard_validation","product_profile","applicability","evidence_match","technical_constraints","na_validation","na_conflict_audit","requirement_grouping","group_aware_applicability","group_aware_na_validation","report_evidence_scope","scope_aware_na_validation","final_decision","coverage_gap","overall_readiness")
  self.assertEqual(GenericCompliancePipelineRunner.STEP_ORDER[:len(expected)],expected)
 def test_genericity(self):
  source=Path(__file__).parents[1].joinpath("iec_par/generic_compliance_pipeline_runner.py").read_text().casefold()
  for value in ("60335","washing machine","pump","clause_id ==","model ==","report =="):self.assertNotIn(value,source)
 def test_deterministic_final_response_artifact(self):
  calls=[]
  with tempfile.TemporaryDirectory() as d:
   base,part,report=self.pdfs(d);runner=GenericCompliancePipelineRunner(components=self.setup(calls),clock=lambda:"T");one=Path(d)/"one";two=Path(d)/"two";runner.run(base,part,report,one,run_id="RUN-ONE");runner.run(base,part,report,two,run_id="RUN-TWO");self.assertEqual((one/"decisions/final_compliance_response.json").read_bytes(),(two/"decisions/final_compliance_response.json").read_bytes())

if __name__=="__main__":unittest.main(verbosity=2)
