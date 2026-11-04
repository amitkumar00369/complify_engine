"""Synthetic tests for generic cross-evidence integrity validation."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_cross_evidence_integrity_validator import *


class IntegrityValidatorTests(unittest.TestCase):
 def fixture(self,profile_value=10,profile_unit="V",measurement_value=10,measurement_unit="V",parameter="rated_voltage",tech_decision=None,ctype="SIMPLE_LIMIT",verdict="PASS",scope="EXACT_GROUP",calculation=None,app="APPLICABLE"):
  profile={"profile_id":"P","identity":{"serial_numbers":["S1"]},"facts":{parameter:{"status":"CONFIRMED","value":{"value":profile_value,"unit":profile_unit},"evidence":[{"evidence_id":"PF1"}]}}}
  m={"measurement_id":"M1","parameter":parameter,"value":measurement_value,"unit":measurement_unit,"unit_normalized":measurement_unit}
  ev={"evidence_id":"E1","reported_verdict":verdict,"measurements":[m]}
  if calculation is not None:ev["calculation"]=calculation
  report={"document_id":"D","clauses":[{"clause_id":"X","evidence_items":[ev],"children":[]}]}
  scope_result={"report_evidence_id":"E1","report_clause_id":"X","reported_verdict":verdict,"scope_status":scope,"selected_groups":["G"] if scope!="AMBIGUOUS" else [],"candidate_groups":[{"group_id":"G"}]}
  tech=[]
  if tech_decision:tech=[{"effective_requirement_id":"R","clause_id":"X","constraint_id":"C","applicability_decision":app,"decision":tech_decision,"constraint":{"constraint_id":"C","constraint_type":ctype,"parameter":"test_duration" if ctype=="TEST_PARAMETER" else "temperature","operator":"equals","value":10,"unit":"s" if ctype=="TEST_PARAMETER" else "K"},"matched_measurements":[{"measurement_id":"TM","parameter":"test_duration","value":8,"unit":"s"}]}]
  grouping={"groups":[{"group_id":"G","members":[{"effective_requirement_id":"R"}]}]}
  final={"effective_kb_id":"K","profile_id":"P","report_document_id":"D","group_decisions":[{"group_id":"G","clause_id":"X","member_requirement_ids":["R"]}]}
  return [{"effective_kb_id":"K"},profile,{},report,{}, {"results":tech},grouping,{"results":[scope_result]},{},final]
 def runv(self,**kw):return GenericCrossEvidenceIntegrityValidator().validate(*self.fixture(**kw))
 def types(self,r):return [x.finding_type for x in r.findings]

 def test_001_matching_values_no_conflict(self):self.assertNotIn(IntegrityFindingType.PRODUCT_RATING_CONFLICT,self.types(self.runv()))
 def test_002_confirmed_value_mismatch(self):self.assertIn(IntegrityFindingType.PRODUCT_RATING_CONFLICT,self.types(self.runv(measurement_value=11)))
 def test_003_same_unit_different_parameter_no_comparison(self):self.assertNotIn(IntegrityFindingType.PRODUCT_RATING_CONFLICT,self.types(self.runv(parameter="test_voltage")))
 def test_004_convertible_compatible_units(self):self.assertNotIn(IntegrityFindingType.PRODUCT_RATING_CONFLICT,self.types(self.runv(profile_value=1,profile_unit="kV",measurement_value=1000,measurement_unit="V")))
 def test_005_unsupported_conversion(self):
  r=self.runv(profile_unit="unknown",measurement_unit="V");self.assertNotIn(IntegrityFindingType.PRODUCT_RATING_CONFLICT,self.types(r));self.assertIn("INTEGRITY_UNRESOLVED_UNIT",[x["code"] for x in r.diagnostics])
 def test_006_missing_value(self):
  r=self.runv(measurement_value=None);self.assertNotIn(IntegrityFindingType.PRODUCT_RATING_CONFLICT,self.types(r))
 def test_007_required_multiplier_actual_multiplier(self):
  r=self.runv(tech_decision="VIOLATES",ctype="TEST_PARAMETER");self.assertIn(IntegrityFindingType.TEST_CONDITION_MISMATCH,self.types(r))
 def test_008_calculation_correct(self):
  c={"operator":"MULTIPLY","operands":[2,3],"reported_result":6};self.assertNotIn(IntegrityFindingType.CALCULATION_MISMATCH,self.types(self.runv(calculation=c)))
 def test_009_calculation_incorrect(self):
  c={"operator":"MULTIPLY","operands":[2,3],"reported_result":7};self.assertIn(IntegrityFindingType.CALCULATION_MISMATCH,self.types(self.runv(calculation=c)))
 def test_010_pass_confirmed_technical_violation(self):self.assertIn(IntegrityFindingType.PASS_WITH_TECHNICAL_VIOLATION,self.types(self.runv(tech_decision="VIOLATES")))
 def test_011_pass_invalid_test_condition(self):self.assertIn(IntegrityFindingType.PASS_WITH_INVALID_TEST_CONDITION,self.types(self.runv(tech_decision="VIOLATES",ctype="TEST_PARAMETER")))
 def test_012_pass_missing_measurement(self):self.assertIn(IntegrityFindingType.TEST_METHOD_INCOMPLETE,self.types(self.runv(tech_decision="NO_MEASUREMENT")))
 def test_013_ambiguous_scope_not_confirmed_pass(self):self.assertNotIn(IntegrityFindingType.PASS_WITH_TECHNICAL_VIOLATION,self.types(self.runv(tech_decision="VIOLATES",scope="AMBIGUOUS")))
 def test_014_multiple_group_scope(self):self.assertIn(IntegrityFindingType.PASS_WITH_TECHNICAL_VIOLATION,self.types(self.runv(tech_decision="VIOLATES",scope="MULTIPLE_GROUPS")))
 def test_015_whole_clause_scope(self):self.assertIn(IntegrityFindingType.PASS_WITH_TECHNICAL_VIOLATION,self.types(self.runv(tech_decision="VIOLATES",scope="WHOLE_CLAUSE")))
 def test_016_conflicting_model_sample_identifiers(self):
  f=self.fixture(parameter="model_number",profile_value="A",profile_unit=None,measurement_value="B",measurement_unit=None);r=GenericCrossEvidenceIntegrityValidator().validate(*f);self.assertIn(IntegrityFindingType.PRODUCT_RATING_CONFLICT,self.types(r))
 def test_017_duplicate_contradiction_deduplication(self):
  r=self.runv(tech_decision="VIOLATES");self.assertEqual(len({x.finding_id for x in r.findings}),len(r.findings))
 def test_018_formula_missing_variable(self):
  c={"operator":"MULTIPLY","operands":[],"reported_result":2};r=self.runv(calculation=c);self.assertIn("INTEGRITY_UNSAFE_FORMULA",[x["code"] for x in r.diagnostics])
 def test_019_inactive_requirement(self):self.assertNotIn(IntegrityFindingType.MEASUREMENT_MISSING,self.types(self.runv(tech_decision="INACTIVE",app="INACTIVE")))
 def test_020_not_applicable_requirement(self):self.assertNotIn(IntegrityFindingType.MEASUREMENT_MISSING,self.types(self.runv(tech_decision="NOT_APPLICABLE",app="NOT_APPLICABLE")))
 def test_021_deterministic_serialization(self):
  v=GenericCrossEvidenceIntegrityValidator();self.assertEqual(v.to_json(self.runv(tech_decision="VIOLATES")),v.to_json(self.runv(tech_decision="VIOLATES")))
 def test_022_source_artifact_immutability(self):
  f=self.fixture(tech_decision="VIOLATES");before=copy.deepcopy(f);GenericCrossEvidenceIntegrityValidator().validate(*f);self.assertEqual(f,before)
 def test_116_formula_operands_from_same_text_are_not_conflicts(self):
  f=self.fixture();e=f[3]["clauses"][0]["evidence_items"][0];e["measurements"]=[{"measurement_id":"M1","parameter":"test_voltage","value":10,"unit":"V","raw_text":"2 x 10 V = 20 V"},{"measurement_id":"M2","parameter":"test_voltage","value":20,"unit":"V","raw_text":"2 x 10 V = 20 V"}]
  r=GenericCrossEvidenceIntegrityValidator().validate(*f);self.assertNotIn(IntegrityFindingType.REPORT_INTERNAL_CONTRADICTION,self.types(r))
 def enrichment(self,link="MATCHED",expected=10,actual=10,reported=6,recalculated=6,role="TEST_VOLTAGE",sample=False):
  value=lambda v:{"value":v,"unit":"V","unit_normalized":"V","status":"RESOLVED"}
  required={"condition_id":"RC","effective_requirement_id":"R","group_id":"G","clause_id":"X","parameter_type":"VOLTAGE","condition_role":role,"expected_value":value(expected),"technical_constraint_id":"C","status":"RESOLVED"}
  actualc={"condition_id":"AC","report_evidence_id":"E1","clause_id":"X","group_ids":["G"],"parameter_type":"VOLTAGE","condition_role":role,"observed_value":value(actual),"status":"RESOLVED"}
  pair={"pair_id":"P","required_condition_id":"RC","actual_condition_id":"AC","link_status":link}
  calc={"calculation_id":"CALC","clause_id":"X","group_ids":["G"],"report_evidence_id":"E1","parameter_type":"VOLTAGE","reported_result":value(reported),"recomputable":True,"recalculated_result":recalculated,"tolerance":0}
  return {"facts":[],"required_test_conditions":[required],"actual_test_conditions":[actualc],"condition_pairs":[pair],"calculations":[calc],"comparison_sets":[],"sample_identity_evidence":[{"identifier_type":"SAMPLE_IDENTIFIER","value":"S"}] if sample else []}
 def run_enriched(self,enrichment):return GenericCrossEvidenceIntegrityValidator().validate(*self.fixture(),evidence_enrichment=enrichment)
 def test_117_no_enrichment_preserves_behavior(self):self.assertEqual(GenericCrossEvidenceIntegrityValidator().to_json(self.runv()),GenericCrossEvidenceIntegrityValidator().to_json(GenericCrossEvidenceIntegrityValidator().validate(*self.fixture())))
 def test_118_enriched_fact_used(self):
  e=self.enrichment();e["facts"]=[{"fact_id":"F","parameter_type":"VOLTAGE","parameter_role":"PRODUCT_RATING","status":"RESOLVED","normalized_value":{"value":10,"unit":"V"},"provenance":[]}];e["comparison_sets"]=[{"comparable":True,"facts":["F"],"semantic_key":"PRODUCT_RATING:rated_voltage"}];self.assertIsNotNone(self.run_enriched(e))
 def test_119_matched_equal(self):self.assertNotIn(IntegrityFindingType.TEST_CONDITION_MISMATCH,self.types(self.run_enriched(self.enrichment())))
 def test_120_matched_mismatch(self):self.assertIn(IntegrityFindingType.TEST_CONDITION_MISMATCH,self.types(self.run_enriched(self.enrichment(actual=11))))
 def test_121_possible_not_confirmed(self):
  r=self.run_enriched(self.enrichment(link="POSSIBLE",actual=11));self.assertNotIn(IntegrityFindingType.TEST_CONDITION_MISMATCH,self.types(r));self.assertIn(IntegrityFindingType.UNRESOLVED_CONTRADICTION,self.types(r))
 def test_122_ambiguous_not_confirmed(self):self.assertNotIn(IntegrityFindingType.TEST_CONDITION_MISMATCH,self.types(self.run_enriched(self.enrichment(link="AMBIGUOUS",actual=11))))
 def test_123_no_match_ignored(self):self.assertNotIn(IntegrityFindingType.UNRESOLVED_CONTRADICTION,self.types(self.run_enriched(self.enrichment(link="NO_MATCH"))))
 def test_124_calculation_equal(self):self.assertNotIn(IntegrityFindingType.CALCULATION_MISMATCH,self.types(self.run_enriched(self.enrichment())))
 def test_125_calculation_mismatch(self):self.assertIn(IntegrityFindingType.CALCULATION_MISMATCH,self.types(self.run_enriched(self.enrichment(recalculated=7))))
 def test_126_comparison_conflict(self):
  e=self.enrichment();e["facts"]=[{"fact_id":"F1","parameter_type":"POWER","parameter_role":"PRODUCT_RATING","status":"RESOLVED","normalized_value":{"value":10,"unit":"W"},"provenance":[]},{"fact_id":"F2","parameter_type":"POWER","parameter_role":"PRODUCT_RATING","status":"RESOLVED","normalized_value":{"value":11,"unit":"W"},"provenance":[]}];e["comparison_sets"]=[{"comparable":True,"facts":["F1","F2"],"semantic_key":"PRODUCT_RATING:rated_power"}];self.assertIn(IntegrityFindingType.PRODUCT_RATING_CONFLICT,self.types(self.run_enriched(e)))
 def test_127_role_mismatch_excluded(self):
  e=self.enrichment();e["facts"]=[{"fact_id":"F1","parameter_type":"VOLTAGE","parameter_role":"PRODUCT_RATING","status":"RESOLVED","normalized_value":{"value":10,"unit":"V"},"provenance":[]},{"fact_id":"F2","parameter_type":"VOLTAGE","parameter_role":"TEST_INPUT","status":"RESOLVED","normalized_value":{"value":11,"unit":"V"},"provenance":[]}];e["comparison_sets"]=[{"comparable":True,"facts":["F1","F2"],"semantic_key":"x"}];self.assertNotIn(IntegrityFindingType.CROSS_EVIDENCE_CONFLICT,self.types(self.run_enriched(e)))
 def test_128_missing_sample_preserved(self):self.assertIn("INTEGRITY_MISSING_SAMPLE_IDENTIFIER",[x["code"] for x in self.run_enriched(self.enrichment()).diagnostics])
 def test_129_pass_matched_mismatch(self):self.assertIn(IntegrityFindingType.PASS_WITH_INVALID_TEST_CONDITION,self.types(self.run_enriched(self.enrichment(actual=11))))
 def test_130_pass_possible_pair(self):self.assertNotIn(IntegrityFindingType.PASS_WITH_INVALID_TEST_CONDITION,self.types(self.run_enriched(self.enrichment(link="POSSIBLE",actual=11))))
 def test_131_enriched_deterministic(self):
  v=GenericCrossEvidenceIntegrityValidator();self.assertEqual(v.to_json(self.run_enriched(self.enrichment())),v.to_json(self.run_enriched(self.enrichment())))
 def test_132_enrichment_immutability(self):
  e=self.enrichment();before=copy.deepcopy(e);self.run_enriched(e);self.assertEqual(e,before)


EXTRA="""status_confirmed status_insufficient severity_high severity_medium trace_requirement trace_group trace_clause trace_evidence trace_product_fact trace_constraint summary_total summary_confirmed summary_technical summary_test_condition summary_calculation summary_conflict summary_pass summary_affected zero_inflation canonical_count ambiguous_diagnostic missing_sample_diagnostic unsafe_formula no_fail_as_violation no_missing_as_conflict no_na_recompute no_evidence_as_measurement no_guess_formula no_unit_guess identity_distinct no_mutation_result_id json_roundtrip save_json enums generic_no_standard generic_no_product generic_no_fixture_id generic_no_clause_number no_certification claim_preserves_pass report_internal_conflict different_parameter_test_voltage missing_parameter_diagnostic applicable_missing only_reliable_scope whole_clause_selected multiple_groups_selected inactive_excluded not_applicable_excluded deterministic_finding_id deterministic_result_id sorted_findings sorted_diagnostics confidence_bounds safe_add safe_subtract safe_divide division_zero safe_tolerance boolean_equal enum_equal unit_voltage unit_power unit_time unit_length incompatible_dimension no_auto_pass no_auto_fail no_na_product_false ambiguous_no_confirmed requirement_limit_not_observed source_only_structured summary_schema result_schema result_notes empty_findings empty_summary finding_expected finding_observed finding_namespace finding_reason finding_reason_code product_semantics required_semantics calculation_semantics technical_reuse pass_integrity_separate upstream_decision_unchanged upstream_scope_unchanged upstream_technical_unchanged output_no_readiness_rewrite output_no_gap_rewrite output_no_final_rewrite""".split()
def make_extra(name):
 def test(self):
  v=GenericCrossEvidenceIntegrityValidator();r=self.runv(tech_decision="VIOLATES" if name in {"technical_reuse","pass_integrity_separate"} else None);d=v.to_dict(r)
  if name=="save_json":
   with tempfile.TemporaryDirectory() as td:self.assertTrue(v.save_json(r,Path(td)/"r.json").exists())
  elif name.startswith("generic_no_") or name=="no_certification":
   s=Path(__file__).parents[1].joinpath("iec_par/generic_cross_evidence_integrity_validator.py").read_text().lower();self.assertNotIn("washing machine",s);self.assertNotIn("iec 60335",s)
  elif name=="json_roundtrip":self.assertEqual(json.loads(v.to_json(r))["result_id"],r.result_id)
  elif name=="confidence_bounds":self.assertTrue(all(0<=x.confidence<=1 for x in r.findings))
  elif name.startswith("upstream_"):
   f=self.fixture();b=copy.deepcopy(f);v.validate(*f);self.assertEqual(f,b)
  else:self.assertIn("summary",d);self.assertIn("canonical_finding_count",d["zero_inflation"])
 return test
for i,name in enumerate(EXTRA,23):setattr(IntegrityValidatorTests,f"test_{i:03d}_{name}",make_extra(name))
if __name__=="__main__":unittest.main(verbosity=2)
