import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iec_par.generic_executive_summary_builder import GenericExecutiveSummaryBuilder


class ExecutiveSummaryBuilderTests(unittest.TestCase):
    def group(self, gid="G1", kind="MISSING_EVIDENCE", issues=2, severity="MEDIUM", conclusion="NOT_EVALUATED", clauses=None, reqs=None):
        clauses=clauses or ["1"];reqs=reqs or ["R1"]
        return {"group_id":gid,"issue_type":kind,"title":"Title "+kind,"summary":"Source summary","compliance_conclusion":conclusion,"conclusion_summary":{conclusion:issues},"primary_action":{"type":"PROVIDE_EVIDENCE","description":"source"},"issue_count":issues,"affected_clause_count":len(clauses),"affected_requirement_group_count":len(reqs),"affected_clauses":clauses,"requirement_group_ids":reqs,"issue_ids":[gid+"-I"+str(x) for x in range(issues)],"severity_summary":{"highest":severity,"high":issues if severity=="HIGH" else 0,"medium":issues if severity=="MEDIUM" else 0},"blocking_summary":{}}
    def action(self, aid="A1", action_type="PROVIDE_EVIDENCE", priority=2, groups=None):
        groups=groups or ["G1"]
        return {"action_id":aid,"action_type":action_type,"priority_level":priority,"priority_label":{1:"DO_FIRST",2:"DO_NEXT",3:"FOLLOW_UP",4:"OPTIONAL_OR_REVIEW"}[priority],"title":"Action "+action_type,"reason":"Reason","expected_outcome":"Outcome","affected_issue_count":2,"unique_clause_count":1,"affected_aggregate_group_ids":groups,"dependency":{"depends_on":[],"unlocks":[],"status":"RESOLVED"}}
    def aggregate(self, groups=None):return {"schema_version":"1.0","actionable_groups":groups or [],"source_final_issue_report_id":"SRC"}
    def plan(self, actions=None):return {"schema_version":"1.0","actions":actions or [],"source_aggregated_report_id":"AGG"}
    def build(self,groups=None,actions=None,limit=5):return GenericExecutiveSummaryBuilder(limit).build(self.aggregate(groups),self.plan(actions))

    def test_001_structured_summary(self):self.assertEqual(self.build([self.group()],[self.action()]).affected_scope_summary["actionable_issue_count"],2)
    def test_002_absent_type_not_mentioned(self):self.assertNotIn("traceability",self.build([self.group()],[self.action()]).executive_summary.casefold())
    def test_003_present_type_included(self):self.assertIn("required evidence",self.build([self.group()],[self.action()]).executive_summary.casefold())
    def test_004_findings_deterministic(self):
        g=[self.group("G1"),self.group("G2",issues=3)];self.assertEqual(self.build(g,[]).main_findings,self.build(reversed(g),[]).main_findings)
    def test_005_limit(self):self.assertEqual(len(self.build([self.group("G1"),self.group("G2")],[],1).main_findings),1)
    def test_006_hidden_accounted(self):
        s=self.build([self.group("G1"),self.group("G2")],[],1);self.assertEqual(s.other_finding_count,1);self.assertEqual(s.all_aggregate_group_ids,["G1","G2"])
    def test_007_severity_order(self):
        s=self.build([self.group("G1",severity="MEDIUM"),self.group("G2",severity="HIGH")],[]);self.assertEqual(s.main_findings[0].aggregate_group_ids,["G2"])
    def test_008_affected_counts(self):
        s=self.build([self.group(issues=3,clauses=["1","2"],reqs=["R1","R2"])],[]);self.assertEqual((s.main_findings[0].affected_issue_count,s.main_findings[0].affected_clause_count),(3,2))
    def test_009_unresolved_count(self):self.assertEqual(self.build([self.group(conclusion="UNRESOLVED",issues=3)],[]).unresolved_summary["unresolved_issue_count"],3)
    def test_010_not_evaluated_not_fail(self):self.assertNotIn("fail",self.build([self.group()],[]).unresolved_summary["text"].casefold())
    def test_011_unresolved_not_noncompliance(self):self.assertEqual(self.build([self.group(conclusion="UNRESOLVED")],[]).unresolved_summary["noncompliant_issue_count"],0)
    def test_012_noncompliance_not_invented(self):self.assertNotIn("non-compliant",self.build([self.group()],[]).executive_summary.casefold())
    def test_013_action_order_exact(self):
        a=[self.action("A2","PROVIDE_EVIDENCE",2),self.action("A1","LAB_CLARIFICATION",1)];self.assertEqual([x.action_id for x in self.build([self.group()],a).recommended_next_actions],["A2","A1"])
    def test_014_same_tier_not_falsely_sequenced(self):
        a=[self.action("A1","LAB_CLARIFICATION",1),self.action("A2","PROVIDE_PRODUCT_INFORMATION",1)];text=self.build([self.group()],a).action_summary_text;self.assertIn("The first actions are",text);self.assertNotIn("then",text.casefold())
    def test_015_dependency_preserved(self):
        a=self.action();a["dependency"]={"depends_on":["A0"],"unlocks":[],"status":"RESOLVED"};self.assertEqual(self.build([self.group()],[a]).recommended_next_actions[0].dependency,a["dependency"])
    def test_016_action_text_deterministic(self):
        s=self.build([self.group()],[self.action()]);self.assertEqual(s.action_summary_text,self.build([self.group()],[self.action()]).action_summary_text)
    def test_017_headline_deterministic(self):self.assertEqual(self.build([self.group()],[]).headline,"Additional information and evidence are required")
    def test_018_summary_deterministic(self):self.assertEqual(self.build([self.group()],[]).executive_summary,self.build([self.group()],[]).executive_summary)
    def test_019_no_certification_language(self):
        s=self.build([self.group()],[]);self.assertNotIn("certified",(s.headline+s.executive_summary).casefold())
    def test_020_no_safety_claim(self):
        s=self.build([self.group()],[]);text=(s.headline+s.executive_summary).casefold();self.assertNotIn("safe",text);self.assertNotIn("unsafe",text)
    def test_021_no_pass_fail(self):
        s=self.build([self.group()],[]);text=(s.headline+s.executive_summary).casefold();self.assertNotIn("report failed",text);self.assertNotIn("report passed",text)
    def test_022_group_ids(self):self.assertEqual(self.build([self.group()],[]).main_findings[0].aggregate_group_ids,["G1"])
    def test_023_action_ids(self):self.assertEqual(self.build([self.group()],[self.action()]).recommended_next_actions[0].action_id,"A1")
    def test_024_all_groups_accounted(self):self.assertTrue(self.build([self.group()],[]).accounting["all_aggregate_groups_accounted_for"])
    def test_025_all_actions_accounted(self):self.assertTrue(self.build([self.group()],[self.action()]).accounting["all_actions_accounted_for"])
    def test_026_serialization(self):
        s=self.build([self.group()],[self.action()]);self.assertEqual(GenericExecutiveSummaryBuilder.to_json(s),GenericExecutiveSummaryBuilder.to_json(s))
    def test_027_hash(self):
        s=self.build([self.group()],[self.action()]);a=hashlib.sha256(GenericExecutiveSummaryBuilder.to_json(s).encode()).hexdigest();b=hashlib.sha256(GenericExecutiveSummaryBuilder.to_json(s).encode()).hexdigest();self.assertEqual(a,b)
    def test_028_object_immutable(self):
        a=self.aggregate([self.group()]);p=self.plan([self.action()]);before=copy.deepcopy((a,p));GenericExecutiveSummaryBuilder().build(a,p);self.assertEqual((a,p),before)
    def test_029_artifact_immutable(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/"a.json";p=Path(d)/"p.json";a.write_text(json.dumps(self.aggregate([self.group()])));p.write_text(json.dumps(self.plan([self.action()])));before=(a.read_bytes(),p.read_bytes());GenericExecutiveSummaryBuilder().build(json.loads(a.read_text()),json.loads(p.read_text()));self.assertEqual((a.read_bytes(),p.read_bytes()),before)
    def test_030_severity_unmodified(self):
        g=self.group(severity="HIGH");self.build([g],[]);self.assertEqual(g["severity_summary"]["highest"],"HIGH")
    def test_031_conclusion_unmodified(self):
        g=self.group(conclusion="UNRESOLVED");self.build([g],[]);self.assertEqual(g["compliance_conclusion"],"UNRESOLVED")
    def test_032_priority_unmodified(self):
        a=self.action(priority=3);self.build([], [a]);self.assertEqual(a["priority_level"],3)
    def test_033_action_unmodified(self):
        a=self.action(action_type="LAB_CLARIFICATION");self.build([], [a]);self.assertEqual(a["action_type"],"LAB_CLARIFICATION")
    def test_034_dependency_unmodified(self):
        a=self.action();before=copy.deepcopy(a["dependency"]);self.build([], [a]);self.assertEqual(a["dependency"],before)
    def test_035_genericity(self):
        src=Path(__file__).parents[1].joinpath("iec_par/generic_executive_summary_builder.py").read_text().casefold()
        for forbidden in ("60335","washing machine","clause_id ==","page ==","model ==","report =="):
            self.assertNotIn(forbidden,src)
    def test_036_no_product_branch(self):self.test_035_genericity()
    def test_037_no_fixture_branch(self):self.test_035_genericity()
    def test_038_no_readiness_score(self):
        d=GenericExecutiveSummaryBuilder.to_dict(self.build([],[]));self.assertNotIn("readiness_score",d);self.assertNotIn("readiness_score",d["metadata"])
    def test_039_no_overall_status(self):self.assertNotIn("overall_status",GenericExecutiveSummaryBuilder.to_dict(self.build([],[])))
    def test_040_quality_zero(self):self.assertTrue(all(v==0 for v in self.build([self.group()],[self.action()]).quality_audit.values()))
    def test_041_category_counts(self):self.assertEqual(self.build([self.group(issues=3)],[]).issue_category_summary["MISSING_EVIDENCE"],{"aggregate_group_count":1,"individual_issue_count":3})
    def test_042_action_counts(self):self.assertEqual(self.build([], [self.action()]).action_summary["by_priority_level"],{"DO_NEXT":1})
    def test_043_save(self):
        with tempfile.TemporaryDirectory() as d:self.assertTrue(GenericExecutiveSummaryBuilder.save_json(self.build([],[]),Path(d)/"out.json").exists())


if __name__=="__main__":unittest.main(verbosity=2)
