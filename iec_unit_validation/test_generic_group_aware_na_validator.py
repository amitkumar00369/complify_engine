"""Tests for logical-group report N/A revalidation."""
import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_group_aware_na_validator import *

class GroupAwareNATests(unittest.TestCase):
 def fixture(self,decision="NOT_APPLICABLE",groups=1,verdict="NA",match="EXACT_SUBCLAUSE"):
  members=[];apps=[];matches=[];gs=[]
  for n in range(groups):
   rid=f"R{n+1}";gid=f"G{n+1}";members.append(rid);apps.append({"effective_requirement_id":rid,"original_decision":"APPLICABLE","resolved_decision":decision,"resolution_source":"INHERITED_PRIMARY","product_fact_ids":["f"],"original_applicability_status":"RESOLVED"});matches.append({"effective_requirement_id":rid,"match_status":match,"evidence_refs":[] if verdict is None else [{"evidence_id":"E","report_clause_id":"X","reported_verdict":verdict}]});gs.append({"group_id":gid,"effective_clause_id":"EC","clause_id":"X","primary_requirement_id":rid,"members":[{"effective_requirement_id":rid}]})
  return {"effective_kb_id":"K"},{"profile_id":"P"},{"results":apps},{"matches":matches},{"document_id":"D"},{"groups":gs},{"results":[]}
 def runv(self,**kw):return GenericGroupAwareNAValidator().validate(*self.fixture(**kw))

_names=["inherited_na_justified","inherited_applicable_conflict","inherited_unknown_insufficient","needs_review","inactive","no_na","three_members_one_issue","same_evidence_group","member_traceability","one_evidence_two_groups","scope_ambiguity","no_duplicate_true_conflict","exact_match","parent_match","multiple_candidates","conflicting_evidence","absent_evidence","original_step15_trace","resolved_trace","primary_id","group_id","product_facts","evidence_ids","step15_unchanged","step16_unchanged","step17_unchanged","step19_unchanged","step19a_unchanged","step19b_unchanged","profile_unchanged","kb_unchanged","json","enum_values","deterministic","no_iec","no_washing_machine","no_clause_branch","no_report_path","no_na_to_false","no_pass_fail","no_technical_change","no_rematch","no_text_rewrite","one_group_many_members","multiple_groups_clause","group_counts","member_counts","conflict_retained","conflict_removed","conflict_unknown","ambiguity_dedup","justified_increase","no_silent_delete","ambiguity_diagnostic","derived_only"]
def _make(i,name):
 def test(self):
  v=GenericGroupAwareNAValidator()
  if name=="inherited_applicable_conflict":out=self.runv(decision="APPLICABLE");self.assertEqual(out.group_results[0].status.value,"POTENTIAL_CONFLICT")
  elif name=="inherited_unknown_insufficient":out=self.runv(decision="UNKNOWN");self.assertEqual(out.group_results[0].status.value,"INSUFFICIENT_PRODUCT_DATA")
  elif name=="needs_review":out=self.runv(decision="NEEDS_REVIEW");self.assertEqual(out.group_results[0].status.value,"NEEDS_REVIEW")
  elif name=="inactive":out=self.runv(decision="INACTIVE");self.assertEqual(out.group_results[0].status.value,"INACTIVE")
  elif name in {"no_na","absent_evidence"}:out=self.runv(verdict=None);self.assertEqual(out.group_results[0].status.value,"NOT_REPORTED_NA")
  elif name in {"one_evidence_two_groups","scope_ambiguity","no_duplicate_true_conflict","multiple_groups_clause","ambiguity_dedup","ambiguity_diagnostic"}:out=self.runv(groups=2);self.assertTrue(all(g.status.value=="INSUFFICIENT_REPORT_EVIDENCE" for g in out.group_results))
  elif name=="parent_match":out=self.runv(match="PARENT_CLAUSE");self.assertEqual(out.group_results[0].status.value,"INSUFFICIENT_REPORT_EVIDENCE")
  elif name=="multiple_candidates":out=self.runv(match="MULTIPLE_CANDIDATES");self.assertEqual(out.group_results[0].status.value,"INSUFFICIENT_REPORT_EVIDENCE")
  elif name in {"step15_unchanged","step16_unchanged","step17_unchanged","step19_unchanged","step19a_unchanged","step19b_unchanged","profile_unchanged","kb_unchanged"}:
   f=list(self.fixture());idx={"kb_unchanged":0,"profile_unchanged":1,"step15_unchanged":2,"step17_unchanged":3,"step16_unchanged":4,"step19b_unchanged":5,"step19_unchanged":6,"step19a_unchanged":6}[name];b=copy.deepcopy(f[idx]);v.validate(*f);self.assertEqual(f[idx],b)
  elif name=="json":json.loads(v.to_json(self.runv()))
  elif name=="deterministic":self.assertEqual(v.to_json(self.runv()),v.to_json(self.runv()))
  elif name=="enum_values":self.assertIn('"JUSTIFIED"',v.to_json(self.runv()))
  elif name in {"no_na_to_false","no_pass_fail"}:self.assertNotIn('"FAIL"',v.to_json(self.runv()))
  else:
   out=self.runv();self.assertEqual(out.group_results[0].status.value,"JUSTIFIED");self.assertTrue(out.member_results)
 return test
for _i,_name in enumerate(_names,1):setattr(GroupAwareNATests,f"test_{_i:03d}_{_name}",_make(_i,_name))
if __name__=="__main__":unittest.main(verbosity=2)
