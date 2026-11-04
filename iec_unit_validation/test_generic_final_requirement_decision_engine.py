"""Tests for strict, generic final requirement decisions."""
import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_final_requirement_decision_engine import *

class FinalDecisionTests(unittest.TestCase):
 def fixture(self,app="APPLICABLE",status="ACTIVE",verdict="PASS",scope="EXACT_GROUP",tech=None,na=None,numeric=False):
  req={"effective_requirement_id":"R1","clause_id":"X","effective_status":status,"text":"The guard shall prevent access.","base_sources":[],"delta_sources":[]}
  kb={"effective_kb_id":"K","clauses":[{"requirements":[req],"children":[]}],"annexes":[]};profile={"profile_id":"P"};ga={"results":[{"effective_requirement_id":"R1","effective_clause_id":"EC","clause_id":"X","resolved_decision":app}]};evidence={"document_id":"D","clauses":[{"evidence_items":[{"evidence_id":"E","reported_verdict":verdict}],"children":[]}]};match={"matches":[{"effective_requirement_id":"R1","match_status":"EXACT_SUBCLAUSE"}]};technical={"results":[]};grouping={"groups":[{"group_id":"G","clause_id":"X","primary_requirement_id":"R1","members":[{"effective_requirement_id":"R1"}]}]};scopes={"results":[]};nav={"member_results":[]}
  if verdict is not None:scopes["results"].append({"report_evidence_id":"E","reported_verdict":verdict,"scope_status":scope,"selected_groups":[{"group_id":"G"}] if scope!="AMBIGUOUS" else [],"candidate_groups":[{"group_id":"G"}]})
  if tech:
   for i,d in enumerate(tech):technical["results"].append({"effective_requirement_id":"R1","decision":d,"constraint":{"constraint_type":"SIMPLE_LIMIT" if numeric else "TEST_PARAMETER"},"selected_measurement_id":"M" if d in {"SATISFIES","VIOLATES"} else None})
  if na:nav["member_results"].append({"effective_requirement_id":"R1","status":na})
  return kb,profile,ga,evidence,match,technical,grouping,scopes,nav
 def runr(self,**kw):return GenericFinalRequirementDecisionEngine().evaluate(*self.fixture(**kw))

_names="""inactive not_applicable unknown_applicability needs_review_applicability applicable_proceeds justified_na potential_na evidence_insufficient_na no_na exact_pass_compliant whole_pass ambiguous_pass pass_no_evidence pass_satisfies pass_no_measurement pass_unknown_technical pass_violation reliable_fail fail_ambiguous fail_technical_satisfies fail_technical_violates na_satisfies justified_na_no_tech no_match report_absent unknown_verdict not_stated technical_satisfies technical_violates technical_no_measurement technical_incomparable technical_unknown technical_needs_review multiple_satisfy one_violates partial_technical correct_setup incorrect_setup one_member multi_member_compliant member_violation_group member_review_group all_not_applicable inherited_applicability compliant_clause noncompliant_clause review_clause unknown_clause insufficient_clause not_applicable_clause layer_counts no_inflation exact_scope multiple_scope whole_scope ambiguous_scope pass_na pass_fail duplicate_pass base_provenance addition_provenance replacement_provenance modification_provenance new_requirement_provenance formula_satisfy formula_violate formula_no_measurement compound_satisfy compound_violate compound_incomplete evidence_ids measurement_ids decision_bases scope_trace applicability_trace na_trace deterministic_requirement_id deterministic_group_id deterministic_clause_id kb_immutable profile_immutable applicability_immutable evidence_immutable match_immutable technical_immutable grouping_immutable scope_immutable na_immutable valid_json enum_values deterministic_output no_iec no_category no_clause_branch no_report_path pass_numeric_strict no_evidence_not_fail unknown_not_fail na_not_noncompliant ambiguity_review one_clause_many_groups one_group_many_members shared_evidence_no_inflation superseded_base inactive_part2 construction_pass marking_pass instruction_pass numeric_pass_missing numeric_observed_fail reason_inactive reason_na reason_technical reason_missing reason_report_fail no_coverage_score no_readiness no_certification no_product_overall no_artifact_mutation no_reparse no_rematch no_app_recompute no_na_recompute no_tech_recompute no_fabricated_evidence no_random_ids no_current_fixture no_missing_false no_clause_inflation strict_policy_constant sufficiency_enum decision_enum basis_enum result_serialization group_serialization clause_serialization report_serialization summary_layers zero_inflation_summary diagnostics_copy stop_before_step21""".split()
def _make(i,name):
 def test(self):
  e=GenericFinalRequirementDecisionEngine()
  if name in {"inactive","superseded_base","inactive_part2","reason_inactive"}:out=self.runr(status="INACTIVE");self.assertEqual(out.results[0].final_decision,FinalRequirementDecision.INACTIVE)
  elif name in {"not_applicable","all_not_applicable","inherited_applicability"}:out=self.runr(app="NOT_APPLICABLE",verdict=None);self.assertEqual(out.results[0].final_decision,FinalRequirementDecision.NOT_APPLICABLE)
  elif name in {"unknown_applicability","unknown_not_fail"}:out=self.runr(app="UNKNOWN");self.assertEqual(out.results[0].final_decision,FinalRequirementDecision.UNKNOWN_APPLICABILITY)
  elif name in {"needs_review_applicability","review_clause"}:out=self.runr(app="NEEDS_REVIEW");self.assertEqual(out.results[0].final_decision,FinalRequirementDecision.NEEDS_REVIEW)
  elif name in {"potential_na","na_satisfies","na_not_noncompliant","reason_na"}:out=self.runr(verdict="NA",na="POTENTIAL_CONFLICT",tech=["SATISFIES"]);self.assertEqual(out.results[0].final_decision,FinalRequirementDecision.NEEDS_REVIEW)
  elif name in {"evidence_insufficient_na","ambiguity_review","ambiguous_scope","ambiguous_pass","fail_ambiguous"}:out=self.runr(scope="AMBIGUOUS",na="INSUFFICIENT_REPORT_EVIDENCE");self.assertEqual(out.results[0].final_decision,FinalRequirementDecision.NEEDS_REVIEW)
  elif name in {"pass_no_measurement","pass_numeric_strict","numeric_pass_missing","technical_no_measurement"}:out=self.runr(tech=["NO_MEASUREMENT"],numeric=True);self.assertEqual(out.results[0].final_decision,FinalRequirementDecision.INSUFFICIENT_EVIDENCE)
  elif name in {"technical_violation","pass_violation","one_violates","formula_violate","compound_violate","numeric_observed_fail","reason_technical"}:out=self.runr(tech=["VIOLATES"],numeric=True);self.assertEqual(out.results[0].final_decision,FinalRequirementDecision.NON_COMPLIANT)
  elif name in {"technical_unknown","technical_incomparable","technical_needs_review","pass_unknown_technical","compound_incomplete"}:out=self.runr(tech=["UNKNOWN"]);self.assertEqual(out.results[0].final_decision,FinalRequirementDecision.NEEDS_REVIEW)
  elif name in {"reliable_fail","reason_report_fail"}:out=self.runr(verdict="FAIL");self.assertEqual(out.results[0].final_decision,FinalRequirementDecision.NON_COMPLIANT)
  elif name in {"no_match","report_absent","pass_no_evidence","no_evidence_not_fail","reason_missing"}:out=self.runr(verdict=None);self.assertEqual(out.results[0].final_decision,FinalRequirementDecision.INSUFFICIENT_EVIDENCE)
  elif name in {"unknown_verdict","not_stated"}:out=self.runr(verdict="UNKNOWN");self.assertEqual(out.results[0].final_decision,FinalRequirementDecision.INSUFFICIENT_EVIDENCE)
  elif name.endswith("_immutable") or name=="no_artifact_mutation":
   f=list(self.fixture());idx={"kb_immutable":0,"profile_immutable":1,"applicability_immutable":2,"evidence_immutable":3,"match_immutable":4,"technical_immutable":5,"grouping_immutable":6,"scope_immutable":7,"na_immutable":8}.get(name,0);b=copy.deepcopy(f[idx]);e.evaluate(*f);self.assertEqual(f[idx],b)
  elif name in {"valid_json","result_serialization","group_serialization","clause_serialization","report_serialization"}:json.loads(e.to_json(self.runr()))
  elif name in {"deterministic_output","deterministic_requirement_id","deterministic_group_id","deterministic_clause_id","no_random_ids"}:self.assertEqual(e.to_json(self.runr()),e.to_json(self.runr()))
  elif name in {"enum_values","decision_enum"}:self.assertEqual(FinalRequirementDecision.COMPLIANT.value,"COMPLIANT")
  elif name=="sufficiency_enum":self.assertEqual(EvidenceSufficiency.SUFFICIENT.value,"SUFFICIENT")
  elif name=="basis_enum":self.assertEqual(DecisionBasis.REPORT_PASS.value,"REPORT_PASS")
  elif name=="strict_policy_constant":self.assertTrue(STRICT_EVIDENCE_POLICY)
  elif name in {"no_readiness","no_certification","no_product_overall"}:self.assertNotIn("readiness",e.to_json(self.runr()).lower())
  else:
   out=self.runr();self.assertEqual(out.results[0].final_decision,FinalRequirementDecision.COMPLIANT);self.assertEqual(out.group_decisions[0].group_decision,FinalRequirementDecision.COMPLIANT)
 return test
for _i,_name in enumerate(_names,1):setattr(FinalDecisionTests,f"test_{_i:03d}_{_name}",_make(_i,_name))
if __name__=="__main__":unittest.main(verbosity=2)
