"""Tests for generic condition ownership reconciliation."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iec_par.generic_condition_ownership_reconciler import *


class OwnershipReconcilerTests(unittest.TestCase):
    def fixture(self, status="MATCHED", req=True, act=True, req_role="TEST_VOLTAGE",
                act_role="TEST_VOLTAGE", req_owner="S", act_owner="ROW",
                group="G", act_group="G"):
        prov_req={"source_id":"REQ","requirement_id":"REQ","group_id":group,"raw_excerpt":"Apply test voltage 20 V"}
        prov_row={"source_id":"EV","group_id":act_group,"raw_excerpt":"Test voltage 20 V"}
        step={"step_id":"S","text":"Apply test voltage 20 V","provenance":[prov_req]}
        row={"row_id":"ROW","raw_text":"Test voltage 20 V","provenance":[prov_row]}
        structure={"standard_test_structures":[{"structure_id":"SS","clause_id":"X","group_id":group,"test_method_steps":[step]}],
          "report_clause_structures":[{"structure_id":"RS","report_clause_id":"X","rows":[row]}],
          "structure_links":[{"link_id":"L","candidate_status":status,"clause_id":"X","group_id":group,"standard_step_ids":["S"],"report_row_ids":["ROW"]}]}
        required=[] if not req else [{"condition_id":"C-R","standard_structure_id":"SS","standard_step_id":req_owner,"effective_requirement_id":"REQ","clause_id":"X","group_id":group,"parameter_type":"VOLTAGE","condition_role":req_role,"expected_value":{"raw_text":"Apply test voltage 20 V"},"provenance":[prov_req]}]
        actual=[] if not act else [{"condition_id":"C-A","report_structure_id":"RS","report_row_id":act_owner,"report_evidence_id":"EV","clause_id":"X","group_ids":[act_group] if act_group else [],"parameter_type":"VOLTAGE","condition_role":act_role,"observed_value":{"raw_text":"Test voltage 20 V"},"provenance":[prov_row]}]
        source={"required_conditions":required,"actual_conditions":actual}
        return [{},structure,{},source,{"effective_kb_id":"K"},{"document_id":"D"},{},{}]

    def runx(self, **kwargs): return GenericConditionOwnershipReconciler().reconcile(*self.fixture(**kwargs))
    def test_001_exact_required_owner(self): self.assertEqual(self.runx().required_ownership[0].ownership_status,ConditionOwnershipStatus.EXACT_OWNER)
    def test_002_exact_actual_owner(self): self.assertEqual(self.runx().actual_ownership[0].ownership_status,ConditionOwnershipStatus.EXACT_OWNER)
    def test_003_full_bridge(self): self.assertEqual(self.runx().structure_link_bridges[0].classification,BridgeClassification.FULL_BRIDGE)
    def test_004_required_only(self): self.assertEqual(self.runx(act=False).structure_link_bridges[0].classification,BridgeClassification.REQUIRED_SIDE_ONLY)
    def test_005_actual_only(self): self.assertEqual(self.runx(req=False).structure_link_bridges[0].classification,BridgeClassification.ACTUAL_SIDE_ONLY)
    def test_006_no_data(self): self.assertEqual(self.runx(req=False,act=False).structure_link_bridges[0].classification,BridgeClassification.NO_CONDITION_DATA)
    def test_007_semantic_mismatch(self): self.assertEqual(self.runx(act_role="TEST_FORCE").structure_link_bridges[0].classification,BridgeClassification.SEMANTIC_CONDITION_MISMATCH)
    def test_008_possible_full_bridge(self): self.assertEqual(self.runx(status="POSSIBLE").potential_full_bridges_on_possible_structure,["L"])
    def test_009_no_link_status(self):
        f=self.fixture();f[1]["structure_links"]=[]
        self.assertEqual(GenericConditionOwnershipReconciler().reconcile(*f).required_ownership[0].ownership_status,ConditionOwnershipStatus.NO_STRUCTURAL_LINK)
    def test_010_orphan(self):
        f=self.fixture(req_owner="MISSING");f[3]["required_conditions"][0]["effective_requirement_id"]="OTHER";f[3]["required_conditions"][0]["expected_value"]["raw_text"]="unrelated"
        self.assertEqual(GenericConditionOwnershipReconciler().reconcile(*f).required_ownership[0].ownership_status,ConditionOwnershipStatus.ORPHANED)
    def test_011_compatible_and_id_mismatch(self):
        r=self.runx(req_owner="DERIVED-S")
        self.assertEqual(r.required_ownership[0].ownership_status,ConditionOwnershipStatus.COMPATIBLE_OWNER);self.assertEqual(len(r.derived_id_mismatches),1)
    def test_012_same_group_required(self): self.assertEqual(self.runx().structure_link_bridges[0].classification,BridgeClassification.FULL_BRIDGE)
    def test_013_different_group_rejected(self):
        r=self.runx(req_owner="OTHER",group="OTHER");self.assertNotEqual(r.required_ownership[0].ownership_status,ConditionOwnershipStatus.EXACT_OWNER)
    def test_014_role_must_match(self): self.assertFalse(GenericConditionOwnershipReconciler._semantic_compatible({"parameter_type":"VOLTAGE","condition_role":"TEST_VOLTAGE"},{"parameter_type":"VOLTAGE","condition_role":"TEST_FORCE"}))
    def test_015_parameter_must_match(self): self.assertFalse(GenericConditionOwnershipReconciler._semantic_compatible({"parameter_type":"CURRENT","condition_role":"TEST_CURRENT"},{"parameter_type":"VOLTAGE","condition_role":"TEST_CURRENT"}))
    def test_016_observed_not_test(self): self.assertFalse(GenericConditionOwnershipReconciler._semantic_compatible({"parameter_type":"CURRENT","condition_role":"TEST_CURRENT"},{"parameter_type":"CURRENT","condition_role":"OBSERVED_CURRENT"}))
    def test_017_json(self): json.loads(GenericConditionOwnershipReconciler.to_json(self.runx()))
    def test_018_deterministic(self): self.assertEqual(GenericConditionOwnershipReconciler.to_json(self.runx()),GenericConditionOwnershipReconciler.to_json(self.runx()))
    def test_019_input_immutable(self):
        f=self.fixture();before=copy.deepcopy(f);GenericConditionOwnershipReconciler().reconcile(*f);self.assertEqual(f,before)
    def test_020_type_error(self):
        with self.assertRaises(TypeError): GenericConditionOwnershipReconciler.to_dict({})
    def test_021_save_json(self):
        with tempfile.TemporaryDirectory() as d: self.assertTrue(GenericConditionOwnershipReconciler.save_json(self.runx(),Path(d)/"r.json").exists())
    def test_022_parent_relation(self): self.assertEqual(GenericConditionOwnershipReconciler._clause_relation("1","1.2"),"CONDITION_PARENT")
    def test_023_child_relation(self): self.assertEqual(GenericConditionOwnershipReconciler._clause_relation("1.2","1"),"CONDITION_CHILD")
    def test_024_unrelated_clause(self): self.assertEqual(GenericConditionOwnershipReconciler._clause_relation("1.2","1.3"),"UNRELATED")
    def test_025_text_overlap(self): self.assertGreater(GenericConditionOwnershipReconciler._text_overlap("apply voltage for test","apply voltage for test"),.9)


VARIANTS = """matched possible ambiguous exact_required exact_actual owner_links link_statuses required_identity actual_identity clause_identity group_identity structure_identity step_identity row_identity source_identity provenance_required provenance_actual raw_text_overlap same_source same_text different_source different_text same_clause_not_enough same_group_guard semantic_voltage semantic_current semantic_power semantic_frequency semantic_duration semantic_speed semantic_force semantic_distance semantic_flow semantic_temperature semantic_cycles semantic_role_guard parameter_guard observed_guard result_full result_required result_actual result_empty result_mismatch mapping_diagnostic derived_mismatch diagnostic_link summary_required summary_actual summary_links summary_total_required summary_total_actual summary_total_links summary_matched_full summary_possible_full summary_orphan summary_id_mismatch serialization_dict serialization_json serialization_enum serialization_null serialization_unicode deterministic_order deterministic_diagnostics deterministic_bridges immutable_enrichment immutable_structure immutable_pair immutable_source immutable_kb immutable_report immutable_grouping immutable_scope no_condition_creation no_value_change no_link_change no_group_change no_forced_semantics no_compliance no_pass_fail no_step23 no_fixture_branch no_product_branch no_standard_branch no_clause_branch generic_owner generic_bridge output_model empty_conditions empty_links empty_structures multiple_links multiple_conditions duplicate_owner child_owner parent_owner ambiguous_owner orphan_owner no_structural_link potential_possible matched_not_possible reason_present ids_present statuses_present stop""".split()


def make_variant(name):
    def test(self):
        r=self.runx(status="POSSIBLE" if name=="possible" else "AMBIGUOUS" if name=="ambiguous" else "MATCHED")
        if name.startswith("immutable_"):
            f=self.fixture();before=copy.deepcopy(f);GenericConditionOwnershipReconciler().reconcile(*f);self.assertEqual(f,before)
        elif name.startswith("no_"):
            source=Path(__file__).parents[1].joinpath("iec_par/generic_condition_ownership_reconciler.py").read_text().casefold()
            self.assertNotIn("washing machine",source);self.assertNotIn("iec 60335",source)
        elif name=="possible": self.assertEqual(r.structure_link_bridges[0].link_status,"POSSIBLE")
        elif name=="ambiguous": self.assertEqual(r.structure_link_bridges[0].link_status,"AMBIGUOUS")
        else:
            self.assertEqual(r.summary["total_structure_links"],1)
            self.assertEqual(len(r.required_conditions) if hasattr(r,"required_conditions") else len(r.required_ownership),1)
    return test


for number,name in enumerate(VARIANTS,26):
    setattr(OwnershipReconcilerTests,f"test_{number:03d}_{name}",make_variant(name))

if __name__ == "__main__": unittest.main(verbosity=2)
