import copy,hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_evaluation_root_cause_audit import *

class RootCauseAuditTests(unittest.TestCase):
 def fixture(self,root):
  (root/"standards").mkdir();(root/"report").mkdir();(root/"decisions").mkdir();(root/"manifest").mkdir();(root/"manifest/pipeline_manifest.json").write_text('{"run_id":"R"}')
  data={"standards/effective_kb.json":{"clauses":[{"clause_id":"1","requirements":[{"effective_requirement_id":"REQ1","text":"shall"}]}]},"report/report_evidence.json":{"clauses":[{"clause_id":"1","evidence_items":[{"evidence_id":"EV1","reported_verdict":"PASS"},{"evidence_id":"EV2","parent_evidence_id":"EV1"}]}]},"report/applicability_result.json":{"results":[{"effective_requirement_id":"REQ1","decision":"NOT_APPLICABLE"}]},"report/evidence_match_result.json":{"matches":[{"effective_requirement_id":"REQ1","evidence_refs":[{"evidence_id":"EV1"},{"evidence_id":"EV2"}],"match_status":"MATCHED"}]},"report/requirement_grouping_result.json":{"groups":[{"group_id":"G1","clause_id":"1","members":[{"effective_requirement_id":"REQ1"},{"effective_requirement_id":"REQ2"}]}]},"decisions/final_compliance_issues.json":{"issues":[{"issue_id":"I1","clause_id":"1","requirement_group_id":"G1","requirement_ids":["REQ1"],"evidence_refs":["EV1"]}]},"decisions/final_compliance_response.json":{"detailed_issues":[{"issue_id":"I1","clause_id":"1"}]}}
  for rel,value in data.items():p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))
 def runx(self,probe=None):
  d=tempfile.TemporaryDirectory();root=Path(d.name);self.fixture(root);result=GenericEvaluationRootCauseAudit().audit(root,[probe or AuditProbe("one",clause_id="1",requirement_id="REQ1")]);return d,root,result
 def test_01_trace_requirement(self):d,r,a=self.runx();self.assertTrue(any(x["observed"]["match_count"] for x in a.cases[0]["trace"]));d.cleanup()
 def test_02_first_change(self):d,r,a=self.runx(AuditProbe("x",requirement_id="REQ1",expected_stage_contains={"evidence_match":["ABSENT"]}));self.assertEqual(a.cases[0]["first_incorrect_stage"],"evidence_match");d.cleanup()
 def test_03_immutable(self):d,r,a=self.runx();p=r/"report/report_evidence.json";before=p.read_bytes();GenericEvaluationRootCauseAudit().audit(r,[AuditProbe("x",evidence_id="EV1")]);self.assertEqual(p.read_bytes(),before);d.cleanup()
 def test_04_missing_safe(self):d,r,a=self.runx();(r/"report/evidence_match_result.json").unlink();a=GenericEvaluationRootCauseAudit().audit(r,[AuditProbe("x")]);self.assertTrue(a.diagnostics);d.cleanup()
 def test_05_multiple_evidence(self):d,r,a=self.runx(AuditProbe("x",requirement_id="REQ1"));self.assertIn("EV2",json.dumps(a.cases[0]));d.cleanup()
 def test_06_parent_child(self):d,r,a=self.runx(AuditProbe("x",evidence_id="EV2"));self.assertIn("parent_evidence_id",json.dumps(a.cases[0]));d.cleanup()
 def test_07_explicit_na(self):d,r,a=self.runx(AuditProbe("x",requirement_id="REQ1"));self.assertIn("NOT_APPLICABLE",json.dumps(a.cases[0]));d.cleanup()
 def test_08_multi_requirement_group(self):d,r,a=self.runx(AuditProbe("x",requirement_group_id="G1"));self.assertIn("REQ2",json.dumps(a.cases[0]));d.cleanup()
 def test_09_no_final_issue(self):d,r,a=self.runx(AuditProbe("none",clause_id="99"));self.assertEqual(a.audit_status,"COMPLETE");d.cleanup()
 def test_10_no_decision_inference(self):d,r,a=self.runx();self.assertNotIn("compliance_conclusion",a.cases[0]);d.cleanup()
 def test_11_deterministic(self):d,r,a=self.runx();self.assertEqual(GenericEvaluationRootCauseAudit.to_json(a),GenericEvaluationRootCauseAudit.to_json(GenericEvaluationRootCauseAudit().audit(r,[AuditProbe("one",clause_id="1",requirement_id="REQ1")])));d.cleanup()
 def test_12_genericity_zero(self):d,r,a=self.runx();self.assertTrue(all(v==0 for v in a.genericity_audit.values()));d.cleanup()
 def test_13_helpers(self):d,r,a=self.runx();engine=GenericEvaluationRootCauseAudit();self.assertEqual(engine.trace_clause(r,"1")["query"]["clause_id"],"1");self.assertEqual(engine.trace_requirement_group(r,"G1")["query"]["requirement_group_id"],"G1");self.assertEqual(engine.trace_evidence(r,"EV1")["query"]["evidence_id"],"EV1");d.cleanup()
 def test_14_save(self):d,r,a=self.runx();self.assertTrue(GenericEvaluationRootCauseAudit.save_json(a,r/"audit/out.json").exists());d.cleanup()
 def test_15_no_specific_branch(self):
  src=Path(__file__).parents[1].joinpath("iec_par/generic_evaluation_root_cause_audit.py").read_text().casefold()
  for x in ("60335","submersible","washing machine","clause_id ==","report-ev-96-001"):self.assertNotIn(x,src)

if __name__=="__main__":unittest.main(verbosity=2)
