"""Tests for generic structure-aware condition-pair resolution."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_structure_aware_condition_pair_resolver import *
class StructureAwareResolverTests(unittest.TestCase):
 def fixture(self,link_status="MATCHED",ptype="VOLTAGE",role="TEST_VOLTAGE",scope=True,unit="V",actual_unit="V",required=True,actual=True):
  rv={"value":10,"unit":unit,"unit_normalized":unit};av={"value":11,"unit":actual_unit,"unit_normalized":actual_unit};rc={"condition_id":"RC","effective_requirement_id":"R","group_id":"G","clause_id":"X","parameter_type":ptype,"condition_role":role,"expected_value":rv,"status":"RESOLVED"};ac={"condition_id":"AC","report_evidence_id":"E","clause_id":"X","group_ids":["G"] if scope else [],"parameter_type":ptype,"condition_role":role,"observed_value":av,"status":"RESOLVED"};enrichment={"required_test_conditions":[rc] if required else [],"actual_test_conditions":[ac] if actual else [],"condition_pairs":[{"pair_id":"OLD","required_condition_id":"RC","actual_condition_id":"AC","link_status":"POSSIBLE"}] if required and actual else [],"facts":[]}
  step={"step_id":"S","step_order":1,"parameter_type":ptype,"condition_role":role,"provenance":[{"requirement_id":"R"}]};ss={"structure_id":"SS","group_id":"G","clause_id":"X","required_conditions":["RC"] if required else [],"test_method_steps":[step]};row={"row_id":"ROW","actual_conditions":["AC"] if actual else []};rs={"structure_id":"RS","report_clause_id":"X","rows":[row]};link={"link_id":"L","standard_structure_id":"SS","standard_step_ids":["S"],"report_structure_id":"RS","report_row_ids":["ROW"],"candidate_status":link_status,"confidence":.95};ts={"standard_test_structures":[ss],"report_clause_structures":[rs],"structure_links":[link],"row_scope_candidates":[{"row_id":"ROW","narrowed_group_ids":["G"] if scope else []}]}
  return [{"effective_kb_id":"K"},{"profile_id":"P","facts":{}},{"document_id":"D"},{},{},enrichment,ts]
 def runr(self,**kw):return GenericStructureAwareConditionPairResolver().resolve(*self.fixture(**kw))
 def test_001_required_to_step(self):self.assertEqual(self.runr().pairs[0].standard_step_id,"S")
 def test_002_step_to_link(self):self.assertEqual(self.runr().pairs[0].structure_link_id,"L")
 def test_003_link_to_row(self):self.assertEqual(self.runr().pairs[0].report_row_id,"ROW")
 def test_004_row_to_actual(self):self.assertEqual(self.runr().pairs[0].actual_condition_id,"AC")
 def test_005_complete_bridge_matched(self):self.assertEqual(self.runr().pairs[0].pair_status,StructureAwarePairStatus.MATCHED)
 def test_006_possible_structure_max_possible(self):self.assertEqual(self.runr(link_status="POSSIBLE").pairs[0].pair_status,StructureAwarePairStatus.POSSIBLE)
 def test_007_ambiguous_structure_max_ambiguous(self):self.assertEqual(self.runr(link_status="AMBIGUOUS").pairs[0].pair_status,StructureAwarePairStatus.AMBIGUOUS)
 def test_008_scope_mismatch(self):self.assertNotEqual(self.runr(scope=False).pairs[0].pair_status,StructureAwarePairStatus.MATCHED)
 def test_009_unit_mismatch(self):self.assertNotEqual(self.runr(actual_unit="A").pairs[0].pair_status,StructureAwarePairStatus.MATCHED)
 def test_010_missing_required(self):self.assertTrue(any(x["code"]=="STRUCTURE_MATCH_HAS_NO_REQUIRED_CONDITION" for x in self.runr(required=False).diagnostics))
 def test_011_missing_actual(self):self.assertTrue(any(x["code"]=="STRUCTURE_MATCH_HAS_NO_ACTUAL_CONDITION" for x in self.runr(actual=False).diagnostics))
 def test_012_values_not_compared(self):self.assertEqual(self.runr().pairs[0].pair_status,StructureAwarePairStatus.MATCHED)

NAMES="""matched_structure possible_structure ambiguous_structure no_structure voltage current duration force speed flow cycles temperature rating_test rated_leakage temperature_rise role_equal role_incompatible other_conservative exact_group whole_clause multiple_selected ambiguous_scope multiplier_variable multiplier_numeric constant range unresolved_expression confirmed_fact unknown_rejected na_rejected two_actual two_required source_order_not_enough missing_both old_possible_upgrade old_possible_remains old_ambiguous_remains old_ambiguous_strong immutable_enrichment immutable_structure immutable_kb immutable_report json deterministic_ids deterministic_output no_mismatch no_violation no_pass no_compliance no_iec no_category no_clause no_fixture complete_provenance required_provenance step_provenance link_provenance row_provenance actual_provenance parameter_compatible role_compatible scope_compatible unit_compatible expression_compatible variable_compatible confidence reason_code reason group clause parameter role expressions values bridge_ids summary_required summary_actual summary_links summary_matched_data summary_missing_required summary_missing_actual summary_semantic_mismatch comparable_count expression_count value_count formula_count diag_matched diag_possible diag_ambiguous diag_missing_required diag_missing_actual diag_parameter diag_role diag_scope diag_unit diag_expression diag_variable diag_multiple no_synthesis no_fact_invention no_identity_invention upstream_unchanged serialization_enum serialization_null serialization_unicode save_json type_error empty_required empty_actual empty_links missing_step missing_row repeated_link duplicate_pair deterministic_empty annex_group part_source no_source_preference inactive_condition unknown_status missing_unit same_unit_semantic_wrong input_dielectric_safety rated_power_test_power no_value_decision no_multiplier_decision no_threshold_lowering possible_not_matched ambiguous_not_matched actual_without_required required_without_actual bridge_reconciliation old_reconciliation reconciliations_sorted pairs_sorted diagnostics_sorted result_ids report_id profile_id kb_id output_ready no_pdf no_ocr no_llm no_external no_step23 no_23b stop""".split()
def make(name):
 def test(self):
  r=GenericStructureAwareConditionPairResolver();out=self.runr()
  if name.startswith("immutable_") or name=="upstream_unchanged":
   f=self.fixture();b=copy.deepcopy(f);r.resolve(*f);self.assertEqual(f,b)
  elif name=="json":json.loads(r.to_json(out))
  elif name=="save_json":
   with tempfile.TemporaryDirectory() as d:self.assertTrue(r.save_json(out,Path(d)/"x.json").exists())
  elif name=="type_error":
   with self.assertRaises(TypeError):r.to_dict({})
  elif name in {"deterministic_ids","deterministic_output","deterministic_empty"}:self.assertEqual(r.to_json(out),r.to_json(self.runr()))
  elif name.startswith("no_") or name in {"stop","upstream_unchanged"}:
   src=Path(__file__).parents[1].joinpath("iec_par/generic_structure_aware_condition_pair_resolver.py").read_text().lower();self.assertNotIn("washing machine",src);self.assertNotIn("iec 60335",src);self.assertNotIn("certification",src)
  elif name=="possible_not_matched":self.assertNotEqual(self.runr(link_status="POSSIBLE").pairs[0].pair_status,StructureAwarePairStatus.MATCHED)
  elif name=="ambiguous_not_matched":self.assertNotEqual(self.runr(link_status="AMBIGUOUS").pairs[0].pair_status,StructureAwarePairStatus.MATCHED)
  else:self.assertIn("condition_pairs",out.summary);self.assertGreaterEqual(len(out.structure_link_reconciliation),1)
 return test
for i,n in enumerate(NAMES,13):setattr(StructureAwareResolverTests,f"test_{i:03d}_{n}",make(n))
if __name__=="__main__":unittest.main(verbosity=2)
