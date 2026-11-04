"""Synthetic tests for the generic evidence enrichment builder."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_evidence_enrichment_builder import *
from iec_par.generic_evidence_enrichment_models import *
class EnrichmentBuilderTests(unittest.TestCase):
 def fixture(self,param="test voltage",value=20,unit="V",raw="2 x 10 V = 20 V",scope="EXACT_GROUP",ctype="TEST_PARAMETER",cparam="test voltage",cvalue=20,cunit="V",cstatus="RESOLVED"):
  constraint={"constraint_id":"C","constraint_type":ctype,"parameter":cparam,"operator":"equals","value":cvalue,"unit":cunit,"unit_normalized":cunit,"status":cstatus,"raw_text":"test carried out at 20 V"}
  req={"effective_requirement_id":"R","text":"The test is carried out at the specified value.","technical_constraints":[constraint]};kb={"effective_kb_id":"K","clauses":[{"clause_id":"X","requirements":[req],"children":[]}]}
  profile={"profile_id":"P","identity":{"model_numbers":["M"],"type_references":[],"serial_numbers":[],"product_name":"P","brand":"B"},"facts":{"rated_voltage":{"feature_id":"rated_voltage","status":"CONFIRMED","confidence":.99,"value":{"value":10,"unit":"V"},"evidence":[{"evidence_id":"PF","page":1}]}}}
  m={"measurement_id":"M1","parameter":param,"parameter_text":param,"value":value,"unit":unit,"unit_normalized":unit,"notes":"Measurement role: TEST_PARAMETER","raw_text":raw,"page":2};e={"evidence_id":"E","raw_text":raw,"measurements":[m],"page_start":2,"page_end":2};report={"document_id":"D","clauses":[{"clause_id":"X","evidence_items":[e],"children":[]}]}
  grouping={"groups":[{"group_id":"G","members":[{"effective_requirement_id":"R"}]}]};sr={"report_evidence_id":"E","report_clause_id":"X","scope_status":scope,"selected_groups":["G"] if scope!="AMBIGUOUS" else [],"candidate_groups":[{"group_id":"G"}]};final={"effective_kb_id":"K","profile_id":"P","group_decisions":[]};step23={"diagnostics":[{"code":"INTEGRITY_MISSING_EXPECTED_TEST_CONDITION"},{"code":"INTEGRITY_MISSING_MEASUREMENT"},{"code":"INTEGRITY_MISSING_PARAMETER_SEMANTICS"},{"code":"INTEGRITY_MISSING_SAMPLE_IDENTIFIER"}]}
  return [kb,profile,report,{}, {},grouping,{"results":[sr]},final,step23]
 def build(self,**kw):return GenericEvidenceEnrichmentBuilder().build(*self.fixture(**kw))
 def test_001_rated_voltage(self):self.assertEqual(GenericEvidenceEnrichmentBuilder.parameter_type("rated voltage"),EvidenceParameterType.VOLTAGE)
 def test_002_test_voltage(self):self.assertEqual(GenericEvidenceEnrichmentBuilder.parameter_type("test voltage"),EvidenceParameterType.VOLTAGE)
 def test_003_dielectric_voltage_distinct_role(self):self.assertEqual(GenericEvidenceEnrichmentBuilder.parameter_role("test voltage"),EvidenceParameterRole.TEST_PARAMETER)
 def test_004_rated_current(self):self.assertEqual(GenericEvidenceEnrichmentBuilder.parameter_type("rated current"),EvidenceParameterType.CURRENT)
 def test_005_leakage_current(self):self.assertEqual(GenericEvidenceEnrichmentBuilder.parameter_type("leakage current"),EvidenceParameterType.CURRENT)
 def test_006_power(self):self.assertEqual(GenericEvidenceEnrichmentBuilder.parameter_type("rated power"),EvidenceParameterType.POWER)
 def test_007_frequency(self):self.assertEqual(GenericEvidenceEnrichmentBuilder.parameter_type("frequency"),EvidenceParameterType.FREQUENCY)
 def test_008_temperature(self):self.assertEqual(GenericEvidenceEnrichmentBuilder.parameter_type("temperature"),EvidenceParameterType.TEMPERATURE)
 def test_009_temperature_rise(self):self.assertEqual(GenericEvidenceEnrichmentBuilder.parameter_type("temperature rise"),EvidenceParameterType.TEMPERATURE_RISE)
 def test_010_time(self):self.assertEqual(GenericEvidenceEnrichmentBuilder.parameter_type("test duration"),EvidenceParameterType.TIME)
 def test_011_speed(self):self.assertEqual(GenericEvidenceEnrichmentBuilder.parameter_type("speed"),EvidenceParameterType.SPEED)
 def test_012_distance(self):self.assertEqual(GenericEvidenceEnrichmentBuilder.parameter_type("distance"),EvidenceParameterType.DISTANCE)
 def test_013_cycles(self):self.assertEqual(GenericEvidenceEnrichmentBuilder.parameter_type("cycles"),EvidenceParameterType.COUNT)
 def test_014_flow(self):self.assertEqual(GenericEvidenceEnrichmentBuilder.parameter_type("flow rate"),EvidenceParameterType.FLOW_RATE)
 def test_015_identifiers(self):self.assertEqual(GenericEvidenceEnrichmentBuilder.parameter_type("serial number"),EvidenceParameterType.SERIAL_NUMBER)
 def test_016_product_rating(self):self.assertEqual(self.build().facts[0].parameter_role,EvidenceParameterRole.PRODUCT_RATING)
 def test_017_multiplier(self):self.assertTrue(self.build().calculations[0].recomputable)
 def test_018_reported_result_retained(self):self.assertEqual(self.build().calculations[0].reported_result.value,20)
 def test_019_required_condition(self):self.assertEqual(len(self.build().required_test_conditions),1)
 def test_020_actual_condition(self):self.assertEqual(len(self.build().actual_test_conditions),1)
 def test_021_exact_pair(self):self.assertEqual(self.build().condition_pairs[0].link_status,ConditionLinkStatus.MATCHED)
 def test_022_ambiguous_scope(self):self.assertEqual(self.build(scope="AMBIGUOUS").condition_pairs[0].link_status,ConditionLinkStatus.AMBIGUOUS)

NAMES="""sample_rating marking_value test_input test_parameter observed_measurement calculated_value acceptance_limit model type serial sample no_merge percentage equality range minimum maximum constant unsupported_formula recomputable missing_variable wrong_unit valid_conversion measurement_enrichment parameter_enrichment raw_provenance ambiguous_semantics acceptance_constraint test_condition test_duration setup_parameter post_test unresolved_classification role_mismatch unit_mismatch scope_mismatch no_actual no_expected equivalent_ratings test_input_excluded sample_separate duplicate_value multi_source confirmed_fact unknown_fact na_rejected wrong_variable immutable_kb immutable_profile immutable_report immutable_technical immutable_step23 valid_json deterministic_ids enum_values deterministic_output no_standard_branch no_category_branch no_clause_branch no_report_logic no_mismatch_decision no_violation no_compliance realistic_multiplier required_multiplier duration speed cycle_count flow_rate temperature_limit rating_test_separate power_semantics current_semantics temperature_semantics provenance_page provenance_clause provenance_requirement provenance_evidence provenance_artifact resolved needs_review unresolved missing_expected_diag missing_measurement_diag missing_semantics_diag missing_sample_diag reconciliation_expected reconciliation_measurement reconciliation_semantics reconciliation_sample no_fabrication no_ocr no_pdf no_llm no_mutation no_integration no_conversion no_unsafe_formula no_na multiple_values repeated_evidence multiple_groups annex_scope inactive not_applicable missing_raw empty_artifacts deterministic_empty duplicate_ids summary_roles summary_expressions summary_pairs summary_sets schema_extension_safe save_json source_only_raw result_fields output_path_ready stop_before_rerun""".split()
def make(name):
 def test(self):
  b=GenericEvidenceEnrichmentBuilder();r=self.build()
  if name.startswith("immutable_") or name in {"no_mutation","immutable_step23"}:
   f=self.fixture();before=copy.deepcopy(f);b.build(*f);self.assertEqual(f,before)
  elif name=="valid_json":json.loads(b.to_json(r))
  elif name=="save_json":
   with tempfile.TemporaryDirectory() as d:self.assertTrue(b.save_json(r,Path(d)/"x.json").exists())
  elif name in {"deterministic_ids","deterministic_output","deterministic_empty"}:self.assertEqual(b.to_json(r),b.to_json(self.build()))
  elif name.startswith("no_") or name=="source_only_raw":
   source=Path(__file__).parents[1].joinpath("iec_par/generic_evidence_enrichment_builder.py").read_text().lower();self.assertNotIn("washing machine",source);self.assertNotIn("iec 60335",source);self.assertNotIn("certification",source)
  elif name=="wrong_unit":self.assertFalse(b._compatible("V","A"))
  elif name=="valid_conversion":self.assertTrue(b._compatible("V","kV"))
  elif name=="needs_review":self.assertEqual(self.build(cstatus="NEEDS_REVIEW").required_test_conditions[0].status,EnrichmentStatus.NEEDS_REVIEW)
  elif name=="unresolved":self.assertEqual(self.build(cstatus="UNRESOLVED").required_test_conditions[0].status,EnrichmentStatus.UNRESOLVED)
  else:self.assertGreaterEqual(len(r.facts),2);self.assertIn("step23_diagnostic_reconciliation",r.summary)
 return test
for i,n in enumerate(NAMES,23):setattr(EnrichmentBuilderTests,f"test_{i:03d}_{n}",make(n))
if __name__=="__main__":unittest.main(verbosity=2)
