import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iec_par.generic_next_action_prioritizer import GenericNextActionPrioritizer, PriorityLevel


class NextActionPrioritizerTests(unittest.TestCase):
    def group(self, gid="G1", action="PROVIDE_EVIDENCE", issue="I1", clause="1", req_group="R1", severity="MEDIUM", blocking=(1, 0, 0), conclusion="NOT_EVALUATED", depends=None):
        value = {"group_id": gid, "issue_type": "MISSING_EVIDENCE", "root_reason": "GAP",
                 "compliance_conclusion": conclusion, "conclusion_summary": {conclusion: 1},
                 "primary_action": {"type": action, "description": "source " + action},
                 "issue_count": 1, "affected_requirement_count": 1, "affected_requirement_group_count": 1,
                 "affected_clause_count": 1, "affected_clauses": [clause],
                 "severity_summary": {"highest": severity, "high": int(severity == "HIGH"), "medium": int(severity == "MEDIUM")},
                 "blocking_summary": {"blocking_count": blocking[0], "non_blocking_count": blocking[1], "unknown_count": blocking[2]},
                 "issue_ids": [issue], "requirement_group_ids": [req_group], "requirement_ids": [issue + "-REQ"],
                 "evidence_refs": [issue + "-EV"]}
        if depends is not None: value["depends_on_action_types"] = depends
        return value

    def report(self, groups=None): return {"schema_version": "1.0", "actionable_groups": groups or [], "informational_groups": [], "summary": {}}
    def plan(self, groups=None): return GenericNextActionPrioritizer().prioritize(self.report(groups))

    def test_001_same_action_consolidates(self): self.assertEqual(len(self.plan([self.group(), self.group("G2", issue="I2")]).actions), 1)
    def test_002_different_actions_separate(self): self.assertEqual(len(self.plan([self.group(), self.group("G2", "LAB_CLARIFICATION", "I2")]).actions), 2)
    def test_003_incompatible_dependencies_separate(self): self.assertEqual(len(self.plan([self.group(), self.group("G2", issue="I2", depends=["LAB_CLARIFICATION"])]).actions), 2)
    def test_004_all_groups_accounted(self): self.assertEqual(self.plan([self.group(), self.group("G2", issue="I2")]).accounting["aggregate_groups_accounted_for"], 2)
    def test_005_no_group_lost(self): self.assertEqual(self.plan([self.group()]).accounting["aggregate_groups_unaccounted_for"], 0)
    def test_006_deterministic_ids(self): self.assertEqual(self.plan([self.group()]).actions[0].action_id, self.plan([self.group()]).actions[0].action_id)
    def test_007_deterministic_order(self):
        a=[self.group("G1","TECHNICAL_REVIEW"),self.group("G2","PROVIDE_EVIDENCE","I2")]; self.assertEqual([x.action_id for x in self.plan(a).actions],[x.action_id for x in self.plan(reversed(a)).actions])
    def test_008_deterministic_serialization(self):
        p=self.plan([self.group()]); self.assertEqual(GenericNextActionPrioritizer.to_json(p),GenericNextActionPrioritizer.to_json(p))
    def test_009_description_deterministic(self): self.assertEqual(self.plan([self.group()]).actions[0].title,"Provide missing or incomplete test evidence")
    def test_010_prerequisite_precedes_dependent(self):
        p=self.plan([self.group("G1","LAB_CLARIFICATION"),self.group("G2","TECHNICAL_REVIEW","I2",depends=["LAB_CLARIFICATION"])]); self.assertLess(int(next(x for x in p.actions if x.action_type=="LAB_CLARIFICATION").priority_level),int(next(x for x in p.actions if x.action_type=="TECHNICAL_REVIEW").priority_level))
    def test_011_no_dependency_without_hint(self): self.assertTrue(all(not x.dependency.depends_on for x in self.plan([self.group(),self.group("G2","LAB_CLARIFICATION","I2")]).actions))
    def test_012_graph_no_cycles(self): self.assertFalse(self.plan([self.group()]).dependency_graph["cycle_detected"])
    def test_013_cycle_deterministic(self):
        groups=[self.group("G1","PROVIDE_EVIDENCE",depends=["LAB_CLARIFICATION"]),self.group("G2","LAB_CLARIFICATION","I2",depends=["PROVIDE_EVIDENCE"])]; a=self.plan(groups);b=self.plan(reversed(groups));self.assertTrue(a.dependency_graph["cycle_detected"]);self.assertEqual(a.dependency_graph,b.dependency_graph)
    def test_014_severity_summary(self): self.assertEqual(self.plan([self.group(severity="HIGH"),self.group("G2",issue="I2")]).actions[0].severity_summary.highest,"HIGH")
    def test_015_severity_not_modified(self): self.assertEqual(self.group(severity="HIGH")["severity_summary"]["highest"],"HIGH")
    def test_016_blocking_preserved(self):
        a=self.plan([self.group(blocking=(2,1,3))]).actions[0];self.assertEqual((a.blocking_summary.blocking_count,a.blocking_summary.non_blocking_count,a.blocking_summary.unknown_count),(2,1,3))
    def test_017_issue_count(self): self.assertEqual(self.plan([self.group(),self.group("G2",issue="I2")]).actions[0].affected_issue_count,2)
    def test_018_clause_count(self): self.assertEqual(self.plan([self.group(clause="1"),self.group("G2",issue="I2",clause="2")]).actions[0].unique_clause_count,2)
    def test_019_requirement_group_count(self): self.assertEqual(self.plan([self.group(),self.group("G2",issue="I2",req_group="R2")]).actions[0].unique_requirement_group_count,2)
    def test_020_group_ids_preserved(self): self.assertEqual(self.plan([self.group(),self.group("G2",issue="I2")]).actions[0].affected_aggregate_group_ids,["G1","G2"])
    def test_021_issue_ids_traceable(self): self.assertEqual(self.plan([self.group(),self.group("G2",issue="I2")]).actions[0].affected_issue_ids,["I1","I2"])
    def test_022_evidence_traceable(self): self.assertEqual(self.plan([self.group()]).actions[0].evidence_refs,["I1-EV"])
    def test_023_conclusion_preserved(self): self.assertEqual(self.plan([self.group(conclusion="UNRESOLVED")]).actions[0].conclusion_summary,{"UNRESOLVED":1})
    def test_024_no_noncompliance_created(self): self.assertNotIn("NONCOMPLIANT",self.plan([self.group()]).actions[0].conclusion_summary)
    def test_025_no_readiness_score(self):
        d=GenericNextActionPrioritizer.to_dict(self.plan([self.group()]));self.assertNotIn("readiness_score",d);self.assertNotIn("readiness_score",d["metadata"])
    def test_026_no_overall_status(self): self.assertNotIn("overall_status",GenericNextActionPrioritizer.to_dict(self.plan([self.group()])))
    def test_027_no_certification(self): self.assertNotIn("certified",GenericNextActionPrioritizer.to_json(self.plan([self.group()])).casefold())
    def test_028_no_pdf_parsing(self): self.assertNotIn("pdf",Path(__file__).parents[1].joinpath("iec_par/generic_next_action_prioritizer.py").read_text().casefold())
    def test_029_no_recalculation(self): self.assertNotIn("technical_constraint",Path(__file__).parents[1].joinpath("iec_par/generic_next_action_prioritizer.py").read_text())
    def test_030_no_applicability_reevaluation(self): self.assertNotIn("applicabilitystatus",Path(__file__).parents[1].joinpath("iec_par/generic_next_action_prioritizer.py").read_text().casefold())
    def test_031_input_object_immutable(self):
        r=self.report([self.group()]);before=copy.deepcopy(r);GenericNextActionPrioritizer().prioritize(r);self.assertEqual(r,before)
    def test_032_input_artifact_immutable(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"in.json";path.write_text(json.dumps(self.report([self.group()])),encoding="utf-8");before=path.read_bytes();GenericNextActionPrioritizer().prioritize(json.loads(path.read_text()));self.assertEqual(path.read_bytes(),before)
    def test_033_genericity(self):
        source=Path(__file__).parents[1].joinpath("iec_par/generic_next_action_prioritizer.py").read_text().casefold()
        for forbidden in ("60335","washing machine","clause_id ==","page ==","model ==","report =="):
            self.assertNotIn(forbidden,source)
    def test_034_quality_zero(self): self.assertTrue(all(v==0 for v in self.plan([self.group()]).quality_audit.values()))
    def test_035_baseline_tiers(self):
        p=self.plan([self.group("G1","PROVIDE_PRODUCT_INFORMATION"),self.group("G2","PROVIDE_EVIDENCE","I2"),self.group("G3","TECHNICAL_REVIEW","I3")]);self.assertEqual([int(x.priority_level) for x in p.actions],[1,2,3])
    def test_036_source_actions_preserved(self): self.assertEqual(self.plan([self.group()]).actions[0].source_action_descriptions,["source PROVIDE_EVIDENCE"])
    def test_037_cycle_not_silently_broken(self):
        p=self.plan([self.group("G1","PROVIDE_EVIDENCE",depends=["LAB_CLARIFICATION"]),self.group("G2","LAB_CLARIFICATION","I2",depends=["PROVIDE_EVIDENCE"])]);self.assertTrue(all(x.dependency.status=="UNRESOLVED_CYCLE" for x in p.actions))
    def test_038_save(self):
        with tempfile.TemporaryDirectory() as d:self.assertTrue(GenericNextActionPrioritizer.save_json(self.plan([self.group()]),Path(d)/"out.json").exists())


if __name__=="__main__": unittest.main(verbosity=2)
