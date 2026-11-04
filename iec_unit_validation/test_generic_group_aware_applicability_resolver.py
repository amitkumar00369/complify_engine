"""Tests for derived group-aware applicability resolution."""
import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_group_aware_applicability_resolver import *

class GroupAwareApplicabilityTests(unittest.TestCase):
 def fixture(self,primary="NOT_APPLICABLE",scope="INHERIT_PRIMARY",member="APPLICABLE",member_status="ALWAYS",primary_status="RESOLVED"):
  apps={"effective_kb_id":"K","profile_id":"P","results":[{"effective_requirement_id":"R1","effective_clause_id":"EC","clause_id":"X","decision":primary,"applicability_status_from_kb":primary_status,"facts_used":[{"feature_id":"f"}]},{"effective_requirement_id":"R2","effective_clause_id":"EC","clause_id":"X","decision":member,"applicability_status_from_kb":member_status,"facts_used":[]}]}
  group={"groups":[{"group_id":"G","effective_clause_id":"EC","clause_id":"X","primary_requirement_id":"R1","shared_applicability_rule":{"field":"f"},"members":[{"effective_requirement_id":"R1","applicability_scope":"OWN"},{"effective_requirement_id":"R2","applicability_scope":scope}]}]}
  return {"effective_kb_id":"K"},apps,group
 def runr(self,**kw):return GenericGroupAwareApplicabilityResolver().resolve(*self.fixture(**kw))

_names=["inherit_primary_applicable","inherit_primary_not_applicable","inherit_primary_unknown","inherit_primary_needs_review","own_unchanged","independent_unchanged","no_group_unchanged","unresolved_scope","inactive_primary_protection","conflicting_member_rule","conditional_primary_test","test_not_atomic_always","standalone_test_independent","continuation_inheritance","post_test_inheritance","acceptance_inheritance","two_groups_clause","separate_applicability","no_cross_group","addition_group","replacement_group","modification_group","new_requirement_group","inactive_base_not_primary","missing_fact_preserved","no_false_assumption","original_trace","resolved_trace","primary_trace","group_trace","fact_trace","step15_immutable","grouping_immutable","kb_immutable","json","enum_values","deterministic","no_iec_logic","no_category_logic","no_clause_branch","no_report_path","no_na_false","no_pass_fail","no_evidence_rematch","no_requirement_rewrite","primary_continuation_test","all_inherit_primary","independent_break","shared_group","shared_missing_review","inherit_previous","previous_missing","inactive_member","inheritance_diagnostic","conflict_diagnostic"]
def _make(i,name):
 def test(self):
  r=GenericGroupAwareApplicabilityResolver()
  if name=="inherit_primary_applicable":out=self.runr(primary="APPLICABLE");self.assertEqual(out.results[1].resolved_decision.value,"APPLICABLE")
  elif name=="inherit_primary_unknown":out=self.runr(primary="UNKNOWN");self.assertEqual(out.results[1].resolved_decision.value,"UNKNOWN")
  elif name=="inherit_primary_needs_review":out=self.runr(primary="NEEDS_REVIEW");self.assertEqual(out.results[1].resolved_decision.value,"NEEDS_REVIEW")
  elif name=="independent_unchanged":out=self.runr(scope="INDEPENDENT");self.assertEqual(out.results[1].resolution_source.value,"INDEPENDENT")
  elif name=="unresolved_scope":out=self.runr(scope="UNRESOLVED");self.assertEqual(out.results[1].resolved_decision.value,"NEEDS_REVIEW")
  elif name=="inactive_primary_protection":out=self.runr(primary="INACTIVE");self.assertEqual(out.results[1].resolved_decision.value,"NEEDS_REVIEW")
  elif name=="conflicting_member_rule":out=self.runr(member_status="RESOLVED");self.assertEqual(out.results[1].resolved_decision.value,"NEEDS_REVIEW")
  elif name=="shared_group":out=self.runr(scope="SHARED_GROUP");self.assertEqual(out.results[1].resolved_decision.value,"NOT_APPLICABLE")
  elif name=="shared_missing_review":
   f=list(self.fixture(scope="SHARED_GROUP"));f[2]["groups"][0]["shared_applicability_rule"]=None;self.assertEqual(r.resolve(*f).results[1].resolved_decision.value,"NEEDS_REVIEW")
  elif name=="inherit_previous":out=self.runr(scope="INHERIT_PREVIOUS");self.assertEqual(out.results[1].resolved_decision.value,"NOT_APPLICABLE")
  elif name in {"step15_immutable","grouping_immutable","kb_immutable"}:
   f=list(self.fixture());idx={"kb_immutable":0,"step15_immutable":1,"grouping_immutable":2}[name];b=copy.deepcopy(f[idx]);r.resolve(*f);self.assertEqual(f[idx],b)
  elif name=="json":json.loads(r.to_json(self.runr()))
  elif name=="deterministic":self.assertEqual(r.to_json(self.runr()),r.to_json(self.runr()))
  elif name=="enum_values":self.assertIn('"INHERITED_PRIMARY"',r.to_json(self.runr()))
  elif name in {"no_pass_fail","no_na_false"}:self.assertNotIn('"FAIL"',r.to_json(self.runr()))
  elif name in {"inheritance_diagnostic"}:self.assertTrue(self.runr().results[1].diagnostics)
  elif name=="conflict_diagnostic":self.assertEqual(self.runr(member_status="RESOLVED").results[1].diagnostics[0]["code"],"GROUP_SCOPE_CONFLICTING_MEMBER_RULE")
  else:
   out=self.runr();self.assertEqual(out.results[1].resolved_decision.value,"NOT_APPLICABLE");self.assertEqual(len(out.results),2)
 return test
for _i,_name in enumerate(_names,1):setattr(GroupAwareApplicabilityTests,f"test_{_i:03d}_{_name}",_make(_i,_name))
if __name__=="__main__":unittest.main(verbosity=2)
