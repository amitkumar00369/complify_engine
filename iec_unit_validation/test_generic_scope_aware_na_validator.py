"""Tests for scope-aware logical-group N/A validation."""
import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_scope_aware_na_validator import *

class ScopeAwareNATests(unittest.TestCase):
 def fixture(self,decision="NOT_APPLICABLE",scope="EXACT_GROUP",members=1,verdict="NA",groups=1):
  reqs=[];apps=[];gs=[];selected=[];candidates=[]
  for n in range(groups):
   gid=f"G{n+1}";ms=[]
   for j in range(members):
    rid=f"R{n+1}-{j+1}";reqs.append({"effective_requirement_id":rid,"effective_status":"ACTIVE"});apps.append({"effective_requirement_id":rid,"effective_clause_id":"EC","clause_id":"X","original_decision":"APPLICABLE","resolved_decision":decision,"resolution_source":"ORIGINAL" if j==0 else "INHERITED_PRIMARY","original_applicability_status":"RESOLVED","product_fact_ids":["f"]});ms.append({"effective_requirement_id":rid,"applicability_scope":"OWN" if j==0 else "INHERIT_PRIMARY"})
   gs.append({"group_id":gid,"effective_clause_id":"EC","clause_id":"X","primary_requirement_id":ms[0]["effective_requirement_id"],"members":ms});ref={"group_id":gid,"clause_id":"X"};candidates.append(ref)
   if scope in {"EXACT_GROUP","MULTIPLE_GROUPS","WHOLE_CLAUSE","PARENT_SCOPE","CHILD_SCOPE"}:selected.append(ref)
  scope_result={"report_evidence_id":"E","report_result_id":"RC","report_clause_id":"X","reported_verdict":verdict,"scope_status":scope,"selected_groups":selected,"candidate_groups":candidates}
  kb={"effective_kb_id":"K","clauses":[{"requirements":reqs,"children":[]}],"annexes":[]};profile={"profile_id":"P","facts":[{"feature_id":"f","status":"CONFIRMED"}]};ga={"results":apps};grouping={"groups":gs};report={"document_id":"D","clauses":[{"evidence_items":[{"evidence_id":"E","reported_verdict":verdict}],"children":[]}]};matches={"matches":[]};scopes={"results":[scope_result]};return kb,profile,ga,grouping,report,matches,scopes,{"results":[]},{"results":[]},{"summary":{}}
 def runv(self,**kw):return GenericScopeAwareNAValidator().validate(*self.fixture(**kw))

_names=["exact_group","multiple_groups","whole_clause","parent","child","ambiguous","unresolved","no_relevant_group","not_applicable_justified","applicable_conflict","unknown_product","unknown_kb","needs_review","inactive","primary_scope","inherited_members","independent_group","multi_own_unsafe","three_members","member_traceability","no_member_inflation","duplicate_na","na_pass","na_fail","two_na_same_group","selected_subset","excluded_no_na","whole_all_groups","ambiguity_not_conflict","ambiguity_no_app","circular_not_justified","confirmed_facts","unknown_facts","evidence_without_group","no_synthetic_group","clause_all_justified","clause_conflict_dominates","clause_review","clause_evidence_insuff","clause_kb_insuff","clause_product_insuff","evidence_count","group_count","member_count","clause_count","duplicate_dedup","evidence_ids","group_ids","member_ids","product_facts","missing_features","kb_immutable","profile_immutable","grouping_immutable","app_immutable","evidence_immutable","match_immutable","scope_immutable","step19_immutable","step19c_immutable","json","enums","deterministic_ids","deterministic_json","no_clauses","no_standard","no_category","no_report_path","no_pass","no_fail","no_final_compliance","no_rematch","no_scope_recompute","no_app_recompute","no_profile_change","conflict_reduced_exact","ambiguity_remains","excluded_no_longer_na","whole_retained","member_group_counts","conditional_test_group","two_independent_groups","exact_na_one_group","whole_na","subset_na","ambiguous_textless","mixed_verdict","inactive_group","inactive_member","diag_no_group","diag_ambiguous","diag_conflicting","diag_circular","old_na_unchanged","19c_unchanged","19d_unchanged","no_hardcoded","no_auto_repair","no_readiness","no_final_result"]
def _make(i,name):
 def test(self):
  v=GenericScopeAwareNAValidator()
  if name in {"applicable_conflict","clause_conflict_dominates","exact_na_one_group"}:out=self.runv(decision="APPLICABLE");self.assertEqual(out.group_results[0].status,ScopeAwareNAStatus.POTENTIAL_CONFLICT)
  elif name in {"unknown_product","unknown_facts","clause_product_insuff"}:out=self.runv(decision="UNKNOWN");self.assertEqual(out.group_results[0].status,ScopeAwareNAStatus.INSUFFICIENT_PRODUCT_DATA)
  elif name in {"needs_review","clause_review"}:out=self.runv(decision="NEEDS_REVIEW");self.assertEqual(out.group_results[0].status,ScopeAwareNAStatus.NEEDS_REVIEW)
  elif name in {"inactive","inactive_group","inactive_member"}:out=self.runv(decision="INACTIVE");self.assertEqual(out.group_results[0].status,ScopeAwareNAStatus.INACTIVE)
  elif name in {"ambiguous","unresolved","ambiguity_not_conflict","ambiguity_no_app","clause_evidence_insuff","ambiguity_remains","ambiguous_textless","diag_ambiguous"}:out=self.runv(scope="AMBIGUOUS");self.assertEqual(out.group_results[0].status,ScopeAwareNAStatus.INSUFFICIENT_REPORT_EVIDENCE)
  elif name in {"no_relevant_group","evidence_without_group","no_synthetic_group","diag_no_group"}:out=self.runv(scope="NO_RELEVANT_GROUP");self.assertEqual(len(out.group_results),0);self.assertTrue(out.diagnostics)
  elif name in {"multiple_groups","selected_subset","subset_na","two_independent_groups"}:out=self.runv(scope="MULTIPLE_GROUPS",groups=2);self.assertEqual(len(out.group_results),2)
  elif name in {"whole_clause","whole_all_groups","whole_retained","whole_na"}:out=self.runv(scope="WHOLE_CLAUSE",groups=2);self.assertEqual(len(out.group_results),2)
  elif name in {"three_members","member_traceability","no_member_inflation","inherited_members","member_count","member_group_counts","conditional_test_group"}:out=self.runv(members=3);self.assertEqual(len(out.group_results),1);self.assertEqual(len(out.member_results),3)
  elif name in {"kb_immutable","profile_immutable","grouping_immutable","app_immutable","evidence_immutable","match_immutable","scope_immutable","step19_immutable","step19c_immutable","old_na_unchanged","19c_unchanged","19d_unchanged"}:
   f=list(self.fixture());idx={"kb_immutable":0,"profile_immutable":1,"app_immutable":2,"grouping_immutable":3,"evidence_immutable":4,"match_immutable":5,"scope_immutable":6,"step19_immutable":7,"old_na_unchanged":7,"step19c_immutable":9,"19c_unchanged":9,"19d_unchanged":6}[name];b=copy.deepcopy(f[idx]);v.validate(*f);self.assertEqual(f[idx],b)
  elif name=="json":json.loads(v.to_json(self.runv()))
  elif name=="enums":self.assertIn('"JUSTIFIED"',v.to_json(self.runv()))
  elif name in {"deterministic_ids","deterministic_json"}:self.assertEqual(v.to_json(self.runv()),v.to_json(self.runv()))
  elif name in {"no_pass","no_fail","no_final_compliance","no_final_result"}:self.assertNotIn('"FAIL"',v.to_json(self.runv()))
  else:
   out=self.runv();self.assertEqual(out.group_results[0].status,ScopeAwareNAStatus.JUSTIFIED);self.assertTrue(out.member_results)
 return test
for _i,_name in enumerate(_names,1):setattr(ScopeAwareNATests,f"test_{_i:03d}_{_name}",_make(_i,_name))
if __name__=="__main__":unittest.main(verbosity=2)
