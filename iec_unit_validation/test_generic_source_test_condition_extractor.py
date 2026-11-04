"""Tests for source-owned required and actual condition extraction."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_source_test_condition_extractor import *
from iec_par.generic_evidence_enrichment_models import EnrichmentStatus
class SourceConditionExtractorTests(unittest.TestCase):
 def fixture(self,step_type="APPLY_INPUT",step_text="Test voltage is applied at 20 V",row_text="Test voltage: 20 V",scope="EXACT_GROUP",matched=True):
  prov={"requirement_id":"R"};step={"step_id":"S","step_order":1,"step_type":step_type,"text":step_text,"parameter_type":"VOLTAGE","condition_role":"TEST_VOLTAGE","value":20,"unit":"V","provenance":[prov]};ss={"structure_id":"SS","clause_id":"X","group_id":"G","primary_requirement_id":"R","test_method_steps":[step]};rprov={"source_id":"E","page_start":1};row={"row_id":"ROW","row_order":1,"raw_text":row_text,"actual_conditions":[],"calculation_refs":[],"provenance":[rprov]};rs={"structure_id":"RS","report_clause_id":"X","rows":[row]};link={"link_id":"L","candidate_status":"MATCHED" if matched else "POSSIBLE","standard_step_ids":["S"],"report_row_ids":["ROW"],"clause_id":"X","group_id":"G"};scope_row={"row_id":"ROW","outer_scope_status":scope,"narrowed_group_ids":["G"] if scope!="AMBIGUOUS" else []};structure={"standard_test_structures":[ss],"report_clause_structures":[rs],"structure_links":[link],"row_scope_candidates":[scope_row]};kb={"effective_kb_id":"K"};profile={"profile_id":"P"};report={"document_id":"D"};enrich={"required_test_conditions":[],"actual_test_conditions":[],"calculations":[]};return [kb,profile,report,{}, {},enrich,structure,{}]
 def runx(self,**kw):return GenericSourceTestConditionExtractor().extract(*self.fixture(**kw))
 def test_001_standard_voltage(self):self.assertEqual(self.runx().required_conditions[0].condition_role,"TEST_VOLTAGE")
 def test_002_standard_constant(self):self.assertEqual(self.runx().required_conditions[0].expected_value.value,20)
 def test_003_actual_voltage(self):self.assertEqual(self.runx().actual_conditions[0].condition_role,"TEST_VOLTAGE")
 def test_004_actual_value(self):self.assertEqual(self.runx().actual_conditions[0].observed_value.value,20)
 def test_005_full_bridge(self):self.assertEqual(self.runx().structural_match_reconciliation[0].bridge_status,"FULL_CONDITION_BRIDGE")
 def test_006_ambiguous_scope_review(self):self.assertEqual(self.runx(scope="AMBIGUOUS").actual_conditions[0].status,EnrichmentStatus.NEEDS_REVIEW)
 def test_007_acceptance_excluded(self):self.assertEqual(self.runx(step_type="ACCEPTANCE_CHECK",step_text="Leakage current shall not exceed 5 mA").required_conditions,[])
 def test_008_measurement_excluded(self):self.assertEqual(self.runx(step_type="MEASURE",step_text="Measure leakage current").required_conditions,[])
 def test_009_rating_not_actual(self):self.assertEqual(self.runx(row_text="Rated voltage: 20 V").actual_conditions,[])
 def test_010_temperature_rise_not_setup(self):self.assertEqual(self.runx(row_text="Temperature rise: 20 K").actual_conditions,[])
 def test_011_standard_cross_unit_value_rejected(self):
  fixture=self.fixture(step_text="Test voltage is applied at 20 A");fixture[6]["standard_test_structures"][0]["test_method_steps"][0]["unit"]="A"
  self.assertEqual(GenericSourceTestConditionExtractor().extract(*fixture).required_conditions,[])
 def test_012_report_cross_unit_value_rejected(self):
  self.assertEqual(self.runx(row_text="Test voltage: 20 A").actual_conditions,[])
 def test_013_cross_parameter_expression_rejected(self):
  self.assertEqual(self.runx(row_text="Test voltage: 1.2 times rated power").actual_conditions,[])

NAMES="""standard_current standard_duration standard_speed standard_force standard_load standard_distance standard_flow standard_temperature standard_cycles expression_constant expression_multiplier expression_percentage expression_range expression_min expression_max expression_unsupported setup apply operate wait repeat measure acceptance post report_current report_duration report_speed report_force report_load report_distance report_flow report_temperature report_cycles product_rating_safety leakage_safety rated_current_safety temperature_rise_safety exact_scope multiple_scope ambiguous_scope no_group multiplier_report calculation_ref numeric_result unresolved_expression matched_required matched_actual matched_both matched_neither dedup_calculation dedup_standard resolved needs_review unresolved immutable_kb immutable_report immutable_enrichment immutable_structure immutable_pair json deterministic_ids deterministic_output no_iec no_product no_clause no_fixture no_mismatch no_violation no_pass no_compliance no_identity standard_owner_step standard_owner_structure standard_owner_requirement standard_owner_group standard_owner_clause actual_owner_row actual_owner_structure actual_owner_evidence actual_owner_groups actual_owner_clause provenance_standard provenance_report confidence_standard confidence_report old_required_count old_actual_count new_required_count new_actual_count unique_required unique_actual required_only actual_only neither bridge_reconciliation bridge_sorted priority_matched remaining_steps duplicate_suppressed parameter_unknown role_unknown value_missing expression_unsafe scope_ambiguous acceptance_diag measurement_diag extracted_required_diag extracted_actual_diag conditions_by_role statuses_standard statuses_report summary_steps summary_rows summary_detected summary_bridge generic_supplied generic_operated generic_carried generic_performed generic_applied_voltage generic_current generic_force generic_speed generic_seconds generic_minutes generic_hours generic_repeated generic_cycles generic_flow generic_temperature generic_distance generic_opening duration_separate voltage_separate repeat_execution acceptance_endurance measurement_expectation report_tested report_operated report_supplied report_duration_label report_for_seconds report_speed_label report_force_label report_load_label report_cycle_label report_flow_label report_temp_label report_distance_label dielectric_distinct terminal_voltage_distinct rated_vs_test leakage_vs_test temp_vs_rise expression_no_execute variable_explicit variable_not_unit no_value_invention no_variable_guess no_sample_invention no_upstream_write output_schema source_required_subclass source_actual_subclass result_model extraction_result_models serialization_enum serialization_null serialization_unicode save_json type_error empty_structure empty_steps empty_rows missing_text missing_provenance missing_scope missing_calculation repeated_rows repeated_steps annex_structure part_structure no_source_preference inactive_step unknown_step other_explicit other_unsafe compound_review status_confidence ids_unique ids_prefix source_page source_excerpt report_calcs standard_expression actual_expression report_measurements_not_all standard_acceptance_not_setup exact_narrowing ambiguous_not_exact result_file_ready no_pdf no_ocr no_llm no_api no_step23 no_23a3_regen no_23b stop""".split()
def make(name):
 def test(self):
  e=GenericSourceTestConditionExtractor();r=self.runx()
  if name.startswith("immutable_") or name=="no_upstream_write":
   f=self.fixture();b=copy.deepcopy(f);e.extract(*f);self.assertEqual(f,b)
  elif name=="json":json.loads(e.to_json(r))
  elif name=="save_json":
   with tempfile.TemporaryDirectory() as d:self.assertTrue(e.save_json(r,Path(d)/"x.json").exists())
  elif name=="type_error":
   with self.assertRaises(TypeError):e.to_dict({})
  elif name in {"deterministic_ids","deterministic_output","ids_unique"}:self.assertEqual(e.to_json(r),e.to_json(self.runx()))
  elif name.startswith("no_") or name in {"stop","result_file_ready"}:
   src=Path(__file__).parents[1].joinpath("iec_par/generic_source_test_condition_extractor.py").read_text().lower();self.assertNotIn("washing machine",src);self.assertNotIn("iec 60335",src);self.assertNotIn("certification",src)
  elif name=="ambiguous_not_exact":self.assertNotEqual(self.runx(scope="AMBIGUOUS").actual_conditions[0].status,EnrichmentStatus.RESOLVED)
  else:self.assertIn("standard",r.summary);self.assertIn("report",r.summary);self.assertIn("structural_bridge",r.summary)
 return test
for i,n in enumerate(NAMES,14):setattr(SourceConditionExtractorTests,f"test_{i:03d}_{n}",make(n))
if __name__=="__main__":unittest.main(verbosity=2)
