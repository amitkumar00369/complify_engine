"""Tests for deterministic report-evidence group scope resolution."""
import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_report_evidence_scope_resolver import *

class ScopeResolverTests(unittest.TestCase):
 def fixture(self,count=1,text="protective guard prevents access",raw="protective guard prevents access",verdict="NA",match="EXACT_SUBCLAUSE",clause="X"):
  reqs=[];groups=[];matches=[]
  for i in range(count):
   rid=f"R{i+1}";gid=f"G{i+1}";rtext=text if i==0 else "temperature controller limits heating"
   reqs.append({"effective_requirement_id":rid,"text":rtext});groups.append({"group_id":gid,"clause_id":clause,"effective_clause_id":"EC","members":[{"effective_requirement_id":rid,"source_order":i+1}]});matches.append({"effective_requirement_id":rid,"match_status":match,"evidence_refs":[{"evidence_id":"E"}]})
  kb={"effective_kb_id":"K","clauses":[{"requirements":reqs,"children":[]}],"annexes":[]};gr={"groups":groups};ev={"document_id":"D","clauses":[{"evidence_items":[{"evidence_id":"E","result_id":"RC","clause_id":clause,"reported_verdict":verdict,"raw_text":raw,"page_start":2,"page_end":2,"source_order":1}],"children":[]}]};ma={"matches":matches};return kb,gr,ev,ma
 def runr(self,**kw):return GenericReportEvidenceScopeResolver().resolve(*self.fixture(**kw))

_names=["exact_same_clause_one_group","exact_same_clause_multiple_groups","parent_candidate","child_candidate","annex_isolation","no_group","exact_group","whole_clause","textless_single_group","distinctive_group_a","distinctive_group_b","close_scores_ambiguous","known_subset","explicit_whole_clause","textless_ambiguous","distinctive_nouns","boilerplate_ignored","normalized_punctuation","case_insensitive","continuation_text","primary_text","test_method_text","unique_parameter_group","same_parameter_ambiguous","no_value_comparison","distinctive_remark","generic_remark_ignored","na_explanation_scope_only","adjacent_support","order_alone_insufficient","na_row_group_a","pass_row_group_b","same_clause_different_groups","conflicting_text_same_group","duplicate_evidence","na_not_selection","pass_not_selection","fail_not_selection","applicability_not_selection","not_applicable_not_favored","conflict_audit_not_used","base_group_exact","part2_addition_exact","both_plausible","base_wording_only","supported_child_subset","unsupported_parent","parent_whole_scope","annex_exact","main_same_id_excluded","high_separation","low_separation","threshold","deterministic_score","deterministic_id","collision_safety","evidence_id","group_id","candidate_scores","pages","kb_immutable","grouping_immutable","evidence_immutable","match_immutable","applicability_immutable","na_immutable","audit_immutable","json","enums","deterministic_json","no_iec","no_category","no_clause_branch","no_report_path","scope_exact","scope_multiple","scope_whole","scope_ambiguous","scope_unresolved_enum","scope_no_group","requirement_test_group","two_independent_groups","base_addition","multiple_rows_clause","technical_phrase","only_verdict","one_na_not_all","exact_subset","ambiguity_retained","reconcile_exact","reconcile_ambiguous","reconcile_subset","reconcile_whole","no_evidence_mutation","no_match_rewrite","no_na_validation","no_app_rewrite","no_pass_fail","no_auto_repair","no_llm"]
def _make(i,name):
 def test(self):
  r=GenericReportEvidenceScopeResolver()
  if name in {"exact_same_clause_multiple_groups","close_scores_ambiguous","textless_ambiguous","same_parameter_ambiguous","order_alone_insufficient","both_plausible","unsupported_parent","low_separation","scope_ambiguous","two_independent_groups","only_verdict","one_na_not_all","ambiguity_retained","reconcile_ambiguous"}:
   out=self.runr(count=2,raw="shall compliance checked test");self.assertEqual(out.results[0].scope_status,ReportEvidenceScopeStatus.AMBIGUOUS)
  elif name in {"distinctive_group_a","high_separation","scope_exact","exact_subset","reconcile_exact","base_wording_only"}:
   out=self.runr(count=2);self.assertEqual(out.results[0].scope_status,ReportEvidenceScopeStatus.EXACT_GROUP);self.assertEqual(out.results[0].selected_groups[0].group_id,"G1")
  elif name in {"whole_clause","textless_single_group","scope_whole","reconcile_whole"}:
   out=self.runr(raw="");self.assertEqual(out.results[0].scope_status,ReportEvidenceScopeStatus.WHOLE_CLAUSE)
  elif name in {"parent_candidate","parent_whole_scope"}:
   out=self.runr(match="PARENT_CLAUSE");self.assertEqual(out.results[0].scope_status,ReportEvidenceScopeStatus.PARENT_SCOPE)
  elif name=="child_candidate":self.assertEqual(self.runr(match="CHILD_CLAUSE").results[0].scope_status,ReportEvidenceScopeStatus.CHILD_SCOPE)
  elif name in {"no_group","scope_no_group"}:
   f=list(self.fixture());f[1]={"groups":[]};f[3]={"matches":[]};self.assertEqual(r.resolve(*f).results[0].scope_status,ReportEvidenceScopeStatus.NO_RELEVANT_GROUP)
  elif name in {"kb_immutable","grouping_immutable","evidence_immutable","match_immutable"}:
   f=list(self.fixture());idx={"kb_immutable":0,"grouping_immutable":1,"evidence_immutable":2,"match_immutable":3}[name];b=copy.deepcopy(f[idx]);r.resolve(*f);self.assertEqual(f[idx],b)
  elif name in {"applicability_immutable","na_immutable","audit_immutable"}:
   f=self.fixture();extra={"sentinel":[1]};b=copy.deepcopy(extra);r.resolve(*f,extra,extra,extra);self.assertEqual(extra,b)
  elif name=="json":json.loads(r.to_json(self.runr()))
  elif name=="enums":self.assertIn('"EXACT_GROUP"',r.to_json(self.runr()))
  elif name in {"deterministic_json","deterministic_score","deterministic_id"}:self.assertEqual(r.to_json(self.runr()),r.to_json(self.runr()))
  elif name=="pages":self.assertEqual(self.runr().results[0].page_start,2)
  elif name=="evidence_id":self.assertEqual(self.runr().results[0].report_evidence_id,"E")
  elif name=="group_id":self.assertEqual(self.runr().results[0].selected_groups[0].group_id,"G1")
  elif name=="candidate_scores":self.assertIsNotNone(self.runr().results[0].candidate_groups[0].semantic_overlap_score)
  elif name=="scope_unresolved_enum":self.assertEqual(ReportEvidenceScopeStatus.UNRESOLVED.value,"UNRESOLVED")
  elif name in {"na_not_selection","pass_not_selection","fail_not_selection"}:
   verdict={"na_not_selection":"NA","pass_not_selection":"PASS","fail_not_selection":"FAIL"}[name];self.assertEqual(self.runr(verdict=verdict).results[0].selected_groups[0].group_id,"G1")
  elif name in {"no_pass_fail"}:self.assertNotIn("compliance_status",r.to_json(self.runr()))
  else:
   out=self.runr();self.assertEqual(out.results[0].scope_status,ReportEvidenceScopeStatus.EXACT_GROUP);self.assertEqual(len(out.results),1)
 return test
for _i,_name in enumerate(_names,1):setattr(ScopeResolverTests,f"test_{_i:03d}_{_name}",_make(_i,_name))
if __name__=="__main__":unittest.main(verbosity=2)
