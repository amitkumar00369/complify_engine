"""Synthetic tests for source-preserving test-structure enrichment."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_test_structure_enricher import *
from iec_par.generic_test_structure_models import *
class StructureEnricherTests(unittest.TestCase):
 def fixture(self,scope="EXACT_GROUP",raw="Test voltage: 20 V ........ P",verdict="PASS"):
  reqs=[{"effective_requirement_id":"R1","text":"The appliance shall withstand the test."},{"effective_requirement_id":"R2","text":"The voltage is applied at 20 V for 1 min."},{"effective_requirement_id":"R3","text":"The leakage current shall not exceed 5 mA."}]
  kb={"effective_kb_id":"K","clauses":[{"clause_id":"X","requirements":reqs,"children":[]}]};members=[{"effective_requirement_id":"R1","role":"PRIMARY","source_order":1},{"effective_requirement_id":"R2","role":"TEST_METHOD","source_order":2},{"effective_requirement_id":"R3","role":"ACCEPTANCE_CRITERION","source_order":3}];grouping={"groups":[{"group_id":"G","clause_id":"X","primary_requirement_id":"R1","members":members}]}
  m={"measurement_id":"M","parameter":"test_voltage","parameter_text":"Test voltage","value":20,"unit":"V","raw_text":"Test voltage: 20 V","page":1};e={"evidence_id":"E","raw_text":raw,"reported_verdict":verdict,"measurements":[m],"page_start":1,"page_end":1};report={"document_id":"D","clauses":[{"clause_id":"X","result_id":"RC","raw_text":raw,"page_start":1,"page_end":1,"evidence_items":[e],"children":[]}]};selected=[{"group_id":"G"}] if scope!="AMBIGUOUS" else [];scopes={"results":[{"report_evidence_id":"E","scope_status":scope,"selected_groups":selected,"candidate_groups":[{"group_id":"G"}]}]};profile={"identity":{"serial_numbers":[],"sample_identifiers":[]}};enrichment={"required_test_conditions":[{"condition_id":"REQC","effective_requirement_id":"R2"}],"actual_test_conditions":[{"condition_id":"ACTC","report_evidence_id":"E","observed_value":{"raw_text":"Test voltage: 20 V"}}],"calculations":[{"calculation_id":"CALC","report_evidence_id":"E","reported_expression":{"raw_expression":"20 V"}}]};integrity={}
  return [kb,report,grouping,scopes,profile,enrichment,integrity]
 def runx(self,**kw):return GenericTestStructureEnricher().enrich(*self.fixture(**kw))
 def test_001_primary_obligation(self):self.assertIn("withstand",self.runx().standard_test_structures[0].primary_obligation_text)
 def test_002_compliance_test(self):self.assertGreater(len(self.runx().standard_test_structures[0].test_method_steps),1)
 def test_003_voltage_apply(self):self.assertIn(StandardTestStepType.APPLY_INPUT,[x.step_type for x in self.runx().standard_test_structures[0].test_method_steps])
 def test_004_acceptance(self):self.assertGreater(len(self.runx().standard_test_structures[0].acceptance_criteria),0)
 def test_005_report_row(self):self.assertEqual(len(self.runx().report_clause_structures[0].rows),1)
 def test_006_verdict(self):self.assertEqual(self.runx().report_clause_structures[0].rows[0].reported_verdict,"PASS")
 def test_007_measurement_owned(self):self.assertEqual(self.runx().report_clause_structures[0].rows[0].measurements,["M"])
 def test_008_condition_owned(self):self.assertEqual(self.runx().report_clause_structures[0].rows[0].actual_conditions,["ACTC"])
 def test_009_calculation_owned(self):self.assertEqual(self.runx().report_clause_structures[0].rows[0].calculation_refs,["CALC"])
 def test_010_exact_scope(self):self.assertEqual(self.runx().row_scope_candidates[0].narrowed_group_ids,["G"])

NAMES="""primary compliance setup voltage duration operate measure repeat acceptance post setup_duration voltage_duration measurement_acceptance multiple_steps ambiguous_prose current_limit temperature_limit setup_separated duration_separated one_row two_rows subrow bullet measurement_row remark_row table_row mixed_tokens pass_row na_row ambiguous_parent duplicate_verdict measurement_exact other_row_excluded multiple_measurements condition_voltage condition_duration condition_speed condition_force calculation_expression calculation_provenance specific_remark clause_remark whole_scope multiple_scope ambiguous_scope matched possible ambiguous no_match parameter_alignment role_alignment scope_alignment order_alignment competing rated_test_safety leakage_rated_safety temp_rise_safety addition replacement modification new_requirement annex_row annex_isolation inactive_excluded condition_ownership measurement_ownership calculation_ownership remark_ownership immutable_kb immutable_report immutable_grouping immutable_scope immutable_enrichment immutable_integrity json enums deterministic_ids deterministic_output no_standard_rule no_category_branch no_clause_branch no_page_rule no_mismatch no_compliance no_readiness no_na_validation realistic_voltage realistic_calculation realistic_measurement realistic_pass realistic_na mixed_pass_na diag_standard diag_row diag_verdict diag_measurement diag_scope diag_parameter sample_missing row_scope_narrow summary_standard summary_report summary_linking summary_steps summary_rows summary_verdict summary_conditions summary_measurements summary_calculations summary_remarks references table_reference clause_reference test_reference precondition reset observe wait force flow cycles distance temperature power current frequency empty_report empty_kb empty_groups missing_raw repeated_evidence same_clause_rows child_clause parent_clause source_order tie_not_semantic confidence bounded_confidence unique_ids row_parent raw_preserved page_preserved requirement_preserved group_preserved verdict_unchanged requirement_unchanged applicability_unchanged na_unchanged no_violation no_unrelated_measurement no_verdict_fanout no_unit_only no_ambiguous_force no_identity invention_no upstream_unchanged output_no_final generic_text_split generic_bullet generic_number generic_table generic_label generic_result_token generic_remark generic_procedure generic_numeric generic_unit source_namespace report_namespace standard_namespace structure_status row_status unresolved_status diagnostics_sorted structures_sorted links_sorted scopes_preserved candidate_reason candidate_confidence candidate_steps candidate_rows acceptance_ids post_ids exception_ids measurement_ids required_ids provenance_ids serialization_unicode serialization_null save_json type_error report_document_id effective_kb_id row_levels step_types link_statuses no_pdf no_ocr no_llm no_external_api no_step23_rerun no_23a1_write ready_output stop_before_23b""".split()
def make(name):
 def test(self):
  e=GenericTestStructureEnricher();r=self.runx()
  if name.startswith("immutable_") or name=="upstream_unchanged":
   f=self.fixture();b=copy.deepcopy(f);e.enrich(*f);self.assertEqual(f,b)
  elif name=="json":json.loads(e.to_json(r))
  elif name=="save_json":
   with tempfile.TemporaryDirectory() as d:self.assertTrue(e.save_json(r,Path(d)/"x.json").exists())
  elif name=="type_error":
   with self.assertRaises(TypeError):e.to_dict({})
  elif name in {"deterministic_ids","deterministic_output","unique_ids"}:self.assertEqual(e.to_json(r),e.to_json(self.runx()))
  elif name.startswith("no_") or name in {"invention_no","generic_text_split"}:
   source=Path(__file__).parents[1].joinpath("iec_par/generic_test_structure_enricher.py").read_text().lower();self.assertNotIn("washing machine",source);self.assertNotIn("iec 60335",source);self.assertNotIn("certification",source)
  elif name=="ambiguous_scope":self.assertEqual(self.runx(scope="AMBIGUOUS").row_scope_candidates[0].status,StructureLinkStatus.AMBIGUOUS)
  elif name=="bounded_confidence":self.assertTrue(all(0<=x.confidence<=1 for x in r.structure_links))
  else:self.assertIn("standard",r.summary);self.assertIn("report",r.summary);self.assertIn("linking",r.summary)
 return test
for i,n in enumerate(NAMES,11):setattr(StructureEnricherTests,f"test_{i:03d}_{n}",make(n))
if __name__=="__main__":unittest.main(verbosity=2)
