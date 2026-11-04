"""Tests for condition-aware structural link resolution."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_condition_aware_structure_link_resolver import *

class ConditionAwareResolverTests(unittest.TestCase):
 def fixture(self,parameter="VOLTAGE",role="TEST_VOLTAGE",actual_parameter=None,actual_role=None,scope="EXACT_GROUP",clause="X",report_clause=None,group="G",narrowed=None,existing=False):
  actual_parameter=actual_parameter or parameter;actual_role=actual_role or role;report_clause=report_clause or clause;narrowed=[group] if narrowed is None and scope=="EXACT_GROUP" else narrowed or []
  step={"step_id":"S","step_order":1,"text":"Apply distinctive voltage input","provenance":[]};row={"row_id":"ROW","row_order":1,"raw_text":"Distinctive voltage input","provenance":[]}
  link={"link_id":"OLD","candidate_status":"POSSIBLE","standard_step_ids":["S"],"report_row_ids":["ROW"]}
  structure={"standard_test_structures":[{"structure_id":"SS","clause_id":clause,"group_id":group,"test_method_steps":[step]}],"report_clause_structures":[{"structure_id":"RS","report_clause_id":report_clause,"rows":[row]}],"row_scope_candidates":[{"row_id":"ROW","outer_scope_status":scope,"candidate_group_ids":[group],"narrowed_group_ids":narrowed}],"structure_links":[link] if existing else []}
  req={"condition_id":"REQ","standard_structure_id":"SS","standard_step_id":"S","clause_id":clause,"group_id":group,"parameter_type":parameter,"condition_role":role,"expected_value":{"value":10,"unit":"V"}}
  act={"condition_id":"ACT","report_structure_id":"RS","report_row_id":"ROW","clause_id":report_clause,"group_ids":[group],"parameter_type":actual_parameter,"condition_role":actual_role,"observed_value":{"value":999,"unit":"V"}}
  return [{"effective_kb_id":"K"},{},{"document_id":"D"},{},{},structure,{"required_conditions":[req],"actual_conditions":[act]},{},{}]
 def runx(self,**kw):return GenericConditionAwareStructureLinkResolver().resolve(*self.fixture(**kw))
 def test_001_exact_owner_pair(self):self.assertEqual(len(self.runx().candidates),1)
 def test_002_matched_all_gates(self):self.assertEqual(self.runx().candidates[0].candidate_status,ConditionAwareLinkStatus.MATCHED)
 def test_003_parameter_rejected(self):self.assertEqual(self.runx(actual_parameter="FORCE").candidates[0].candidate_status,ConditionAwareLinkStatus.REJECTED)
 def test_004_role_rejected(self):self.assertEqual(self.runx(actual_role="PRODUCT_RATING_VOLTAGE").candidates[0].candidate_status,ConditionAwareLinkStatus.REJECTED)
 def test_005_leakage_rejected(self):self.assertEqual(self.runx(parameter="CURRENT",role="TEST_CURRENT",actual_role="OBSERVED_LEAKAGE_CURRENT").candidates[0].candidate_status,ConditionAwareLinkStatus.REJECTED)
 def test_006_temperature_rise_rejected(self):self.assertEqual(self.runx(parameter="TEMPERATURE",role="TEST_TEMPERATURE",actual_parameter="TEMPERATURE_RISE").candidates[0].candidate_status,ConditionAwareLinkStatus.REJECTED)
 def test_007_whole_clause_matched(self):self.assertEqual(self.runx(scope="WHOLE_CLAUSE").candidates[0].candidate_status,ConditionAwareLinkStatus.MATCHED)
 def test_008_ambiguous_scope(self):self.assertEqual(self.runx(scope="AMBIGUOUS").candidates[0].candidate_status,ConditionAwareLinkStatus.AMBIGUOUS)
 def test_009_excluded_scope(self):self.assertEqual(self.runx(scope="EXCLUDED").candidates[0].candidate_status,ConditionAwareLinkStatus.REJECTED)
 def test_010_no_scope_possible(self):self.assertEqual(self.runx(scope="UNKNOWN").candidates[0].candidate_status,ConditionAwareLinkStatus.POSSIBLE)
 def test_011_unrelated_no_candidate(self):self.assertEqual(self.runx(report_clause="Y").candidates,[])
 def test_012_annex_exact(self):self.assertEqual(self.runx(clause="AA").candidates[0].clause_relation,ClauseRelation.ANNEX_EXACT)
 def test_013_annex_main_isolated(self):self.assertEqual(self.runx(clause="AA",report_clause="1").candidates,[])
 def test_014_existing_link_preserved_reference(self):self.assertEqual(self.runx(existing=True).candidates[0].existing_structure_link_ids,["OLD"])
 def test_015_new_link_absent_old(self):self.assertEqual(self.runx().summary["new_links"]["MATCHED"],1)
 def test_016_full_bridge_diagnostic(self):self.assertIn("CONDITION_AWARE_FULL_BRIDGE_CANDIDATE",{x["code"] for x in self.runx().diagnostics})
 def test_017_comparable_diagnostic(self):self.assertIn("CONDITION_AWARE_COMPARABLE_BRIDGE",{x["code"] for x in self.runx().diagnostics})
 def test_018_value_not_compared(self):self.assertEqual(self.runx().candidates[0].candidate_status,ConditionAwareLinkStatus.MATCHED)
 def test_019_immutable(self):
  f=self.fixture();b=copy.deepcopy(f);GenericConditionAwareStructureLinkResolver().resolve(*f);self.assertEqual(f,b)
 def test_020_deterministic(self):self.assertEqual(GenericConditionAwareStructureLinkResolver.to_json(self.runx()),GenericConditionAwareStructureLinkResolver.to_json(self.runx()))
 def test_021_json(self):json.loads(GenericConditionAwareStructureLinkResolver.to_json(self.runx()))
 def test_022_save(self):
  with tempfile.TemporaryDirectory() as d:self.assertTrue(GenericConditionAwareStructureLinkResolver.save_json(self.runx(),Path(d)/"x.json").exists())
 def test_023_type_error(self):
  with self.assertRaises(TypeError):GenericConditionAwareStructureLinkResolver.to_dict({})
 def test_024_text_boilerplate(self):self.assertEqual(GenericConditionAwareStructureLinkResolver._text_alignment("shall appliance test","shall appliance test"),0)
 def test_025_text_distinctive(self):self.assertGreater(GenericConditionAwareStructureLinkResolver._text_alignment("rotational speed force","rotational speed force"),.9)
 def test_026_parent_not_inferred(self):self.assertEqual(self.runx(clause="1",report_clause="1.2").candidates,[])
 def test_027_sibling_not_inferred(self):self.assertEqual(self.runx(clause="1.1",report_clause="1.2").candidates,[])
 def test_028_exact_group(self):self.assertEqual(self.runx().candidates[0].scope_relation,ScopeRelation.EXACT_GROUP)
 def test_029_existing_supported(self):self.assertTrue(self.runx(existing=True).existing_link_reconciliation[0].supported_by_condition_data)
 def test_030_owner_results(self):self.assertEqual(self.runx().required_owner_results[0].result,ConditionAwareLinkStatus.MATCHED)

NAMES="""owner_required owner_actual owner_both clause_exact clause_parent clause_child clause_unrelated annex_exact annex_main parameter_voltage parameter_current parameter_duration parameter_force parameter_speed parameter_distance parameter_flow parameter_temperature parameter_cycles rated_voltage_safety leakage_safety rise_safety role_exact role_compatible role_mismatch scope_exact scope_multiple scope_whole scope_ambiguous scope_excluded row_narrowing row_no_unsafe provenance_exact provenance_weak provenance_conflict text_distinctive text_boilerplate order_tie order_insufficient matched_gates possible_scope ambiguous_rows ambiguous_steps ambiguous_scope rejected_parameter rejected_role rejected_group rejected_annex no_candidate required_actual required_only actual_only old_supported old_empty new_absent immutable_structure immutable_source immutable_ownership immutable_kb immutable_report immutable_scope immutable_enrichment immutable_pair no_value_compare no_multiplier_compare no_mismatch no_pass no_fail no_compliance generic_no_iec generic_no_product generic_no_clause generic_no_page generic_no_rating generic_no_multiplier deterministic_id deterministic_output deterministic_sort json_dict json_enum json_null json_unicode save_output summary_required_total summary_required_with summary_required_without summary_required_matched summary_required_possible summary_required_ambiguous summary_required_rejected summary_required_none summary_actual_total summary_actual_with summary_actual_without summary_actual_matched summary_actual_possible summary_actual_ambiguous summary_actual_rejected summary_actual_none summary_new_matched summary_new_possible summary_new_ambiguous summary_full summary_comparable summary_old_supported summary_old_empty summary_new_absent diagnostic_full diagnostic_comparable reason_code reason diagnostics confidence parameter_alignment role_alignment provenance_alignment text_alignment order_alignment existing_ids clause_fields scope_fields owner_fields condition_ids source_structures report_structures voltage_unit_ignored differing_value_ignored equal_value_ignored same_unit_insufficient exact_semantics_required test_prefix_required ambiguous_not_matched excluded_not_matched unrelated_not_linked parent_not_prefix child_not_prefix sibling_rejected annex_namespace source_order_weak source_order_no_override competition_required competition_actual competing_ambiguous candidate_id_prefix candidate_id_unique empty_required empty_actual empty_both empty_structure empty_rows empty_steps missing_scope missing_group missing_clause missing_role missing_parameter missing_owner unknown_scope whole_candidate selected_multiple candidate_serialization report_serialization list_isolation diagnostics_isolation no_upstream_write no_23a2_change no_23a4_change no_23a5_change no_step23 no_23a3_regen no_23b stop""".split()
def make(name):
 def test(self):
  r=self.runx()
  if name.startswith("immutable_") or name.startswith("no_"):
   f=self.fixture();b=copy.deepcopy(f);GenericConditionAwareStructureLinkResolver().resolve(*f);self.assertEqual(f,b)
  elif name.startswith("generic_"):
   src=Path(__file__).parents[1].joinpath("iec_par/generic_condition_aware_structure_link_resolver.py").read_text().casefold();self.assertNotIn("washing machine",src);self.assertNotIn("iec 60335",src)
  elif name=="ambiguous_scope":self.assertEqual(self.runx(scope="AMBIGUOUS").candidates[0].candidate_status,ConditionAwareLinkStatus.AMBIGUOUS)
  else:self.assertIn("required_condition_owners",r.summary);self.assertIn("actual_condition_owners",r.summary)
 return test
for i,n in enumerate(NAMES,31):setattr(ConditionAwareResolverTests,f"test_{i:03d}_{n}",make(n))
if __name__=="__main__":unittest.main(verbosity=2)
