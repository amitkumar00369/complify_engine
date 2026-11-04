"""Tests for generic four-state effective-requirement applicability evaluation."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iec_par.generic_product_profile_models import (
    EvidenceSourceType, ProductFact, ProductFactEvidence, ProductFactStatus,
    ProductProfile,
)
from iec_par.generic_requirement_applicability_evaluator import (
    ApplicabilityEvaluationReport, GenericRequirementApplicabilityEvaluator,
    RequirementApplicabilityDecision as D,
)


class GenericRequirementApplicabilityEvaluatorTests(unittest.TestCase):
    def setUp(self): self.e=GenericRequirementApplicabilityEvaluator()
    def profile(self, facts=None): return ProductProfile("PROFILE-X",facts=facts or {})
    def fact(self,key,value,status=ProductFactStatus.CONFIRMED):
        ev=ProductFactEvidence("EV-1",EvidenceSourceType.REPORT_METADATA,raw_text="explicit")
        return ProductFact(key,value,status,.9 if status not in {ProductFactStatus.UNKNOWN,ProductFactStatus.CONFLICT} else None,[ev])
    def req(self,status="ACTIVE",app="RESOLVED",logic=None,rid="ER-1"):
        return {"effective_requirement_id":rid,"clause_id":"7.1","effective_status":status,
                "effective_source_type":"BASE","condition_text":"condition",
                "applicability":{"status":app,"logic":logic},"base_sources":[],"delta_sources":[]}
    def result(self,logic,facts=None,**kwargs): return self.e.evaluate_requirement(self.req(logic=logic,**kwargs),self.profile(facts))
    def leaf(self,field="has_timer",op="equals",value=True): return {"field":field,"operator":op,"value":value}

    # EFFECTIVE STATUS / KB STATUS
    def test_01_inactive(self): self.assertIs(self.result(self.leaf(),status="INACTIVE").decision,D.INACTIVE)
    def test_02_effective_review(self): self.assertIs(self.result(self.leaf(),status="NEEDS_REVIEW").decision,D.NEEDS_REVIEW)
    def test_03_always_active(self): self.assertIs(self.result(None,app="ALWAYS").decision,D.APPLICABLE)
    def test_04_unresolved(self): self.assertEqual(self.result(self.leaf(),app="UNRESOLVED").reason_code,"KB_APPLICABILITY_UNRESOLVED")
    def test_05_kb_review(self): self.assertEqual(self.result(self.leaf(),app="NEEDS_REVIEW").reason_code,"KB_APPLICABILITY_NEEDS_REVIEW")

    # BOOLEAN
    def test_06_true_equals_true(self): self.assertIs(self.result(self.leaf(),{"has_timer":self.fact("has_timer",True)}).decision,D.APPLICABLE)
    def test_07_false_equals_true(self): self.assertIs(self.result(self.leaf(),{"has_timer":self.fact("has_timer",False)}).decision,D.NOT_APPLICABLE)
    def test_08_missing_boolean(self): self.assertIs(self.result(self.leaf()).decision,D.UNKNOWN)
    def test_09_unknown_boolean(self): self.assertIs(self.result(self.leaf(),{"has_timer":self.fact("has_timer",None,ProductFactStatus.UNKNOWN)}).decision,D.UNKNOWN)
    def test_10_na_boolean(self): self.assertIs(self.result(self.leaf(),{"has_timer":self.fact("has_timer",None,ProductFactStatus.INFERRED_FROM_NA)}).decision,D.UNKNOWN)
    def test_11_conflict_boolean(self): self.assertIs(self.result(self.leaf(),{"has_timer":self.fact("has_timer",None,ProductFactStatus.CONFLICT)}).decision,D.NEEDS_REVIEW)

    # ENUM
    def test_12_enum_equal_true(self): self.assertIs(self.result(self.leaf("protection_class",value="CLASS_I"),{"protection_class":self.fact("protection_class","CLASS_I")}).decision,D.APPLICABLE)
    def test_13_enum_equal_false(self): self.assertIs(self.result(self.leaf("protection_class",value="CLASS_II"),{"protection_class":self.fact("protection_class","CLASS_I")}).decision,D.NOT_APPLICABLE)
    def test_14_enum_not_equals(self): self.assertIs(self.result(self.leaf("protection_class","not_equals","CLASS_III"),{"protection_class":self.fact("protection_class","CLASS_I")}).decision,D.APPLICABLE)
    def test_15_enum_missing(self): self.assertIs(self.result(self.leaf("protection_class",value="CLASS_I")).decision,D.UNKNOWN)

    # NUMERIC
    def test_16_less_equal_true(self): self.assertIs(self.result(self.leaf("rated_current","less_than_or_equal",16),{"rated_current":self.fact("rated_current",10)}).decision,D.APPLICABLE)
    def test_17_less_equal_false(self): self.assertIs(self.result(self.leaf("rated_current","less_than_or_equal",16),{"rated_current":self.fact("rated_current",20)}).decision,D.NOT_APPLICABLE)
    def test_18_greater_true(self): self.assertIs(self.result(self.leaf("rated_power_input","greater_than",100),{"rated_power_input":self.fact("rated_power_input",400)}).decision,D.APPLICABLE)
    def test_19_incompatible_numeric(self): self.assertEqual(self.result(self.leaf("rated_current","less_than",16),{"rated_current":self.fact("rated_current","high")}).reason_code,"INCOMPARABLE_VALUE")

    # EXISTS
    def test_20_exists_true(self): self.assertIs(self.result(self.leaf("has_timer","exists",None),{"has_timer":self.fact("has_timer",False)}).decision,D.APPLICABLE)
    def test_21_exists_missing_unknown(self): self.assertIs(self.result(self.leaf("has_timer","exists",None)).decision,D.UNKNOWN)

    # ALL
    def test_22_all_true(self): self.assertIs(self.result({"all":[self.leaf("a"),self.leaf("b")]},{"a":self.fact("a",True),"b":self.fact("b",True)}).decision,D.APPLICABLE)
    def test_23_all_one_false(self): self.assertIs(self.result({"all":[self.leaf("a"),self.leaf("b")]},{"a":self.fact("a",True),"b":self.fact("b",False)}).decision,D.NOT_APPLICABLE)
    def test_24_all_one_unknown(self): self.assertIs(self.result({"all":[self.leaf("a"),self.leaf("b")]},{"a":self.fact("a",True)}).decision,D.UNKNOWN)
    def test_25_all_false_beats_unknown(self): self.assertIs(self.result({"all":[self.leaf("a"),self.leaf("b")]},{"a":self.fact("a",False)}).decision,D.NOT_APPLICABLE)
    def test_26_all_review_no_false(self): self.assertIs(self.result({"all":[self.leaf("a"),self.leaf("b")]},{"a":self.fact("a",True),"b":self.fact("b",None,ProductFactStatus.CONFLICT)}).decision,D.NEEDS_REVIEW)

    # ANY
    def test_27_any_true(self): self.assertIs(self.result({"any":[self.leaf("a"),self.leaf("b")]},{"a":self.fact("a",False),"b":self.fact("b",True)}).decision,D.APPLICABLE)
    def test_28_any_all_false(self): self.assertIs(self.result({"any":[self.leaf("a"),self.leaf("b")]},{"a":self.fact("a",False),"b":self.fact("b",False)}).decision,D.NOT_APPLICABLE)
    def test_29_any_unknown(self): self.assertIs(self.result({"any":[self.leaf("a"),self.leaf("b")]},{"a":self.fact("a",False)}).decision,D.UNKNOWN)
    def test_30_any_true_beats_unknown(self): self.assertIs(self.result({"any":[self.leaf("a"),self.leaf("b")]},{"a":self.fact("a",True)}).decision,D.APPLICABLE)
    def test_31_any_review_no_true(self): self.assertIs(self.result({"any":[self.leaf("a"),self.leaf("b")]},{"a":self.fact("a",False),"b":self.fact("b",None,ProductFactStatus.CONFLICT)}).decision,D.NEEDS_REVIEW)

    # NOT
    def test_32_not_true(self): self.assertIs(self.result({"not":self.leaf()},{"has_timer":self.fact("has_timer",True)}).decision,D.NOT_APPLICABLE)
    def test_33_not_false(self): self.assertIs(self.result({"not":self.leaf()},{"has_timer":self.fact("has_timer",False)}).decision,D.APPLICABLE)
    def test_34_not_unknown(self): self.assertIs(self.result({"not":self.leaf()}).decision,D.UNKNOWN)
    def test_35_not_review(self): self.assertIs(self.result({"not":self.leaf()},{"has_timer":self.fact("has_timer",None,ProductFactStatus.CONFLICT)}).decision,D.NEEDS_REVIEW)

    # TRUST
    def test_36_confirmed_snapshot(self): self.assertEqual(self.result(self.leaf(),{"has_timer":self.fact("has_timer",True)}).facts_used[0].status,"CONFIRMED")
    def test_37_inferred_strong_used(self): self.assertIs(self.result(self.leaf(),{"has_timer":self.fact("has_timer",True,ProductFactStatus.INFERRED_STRONG)}).decision,D.APPLICABLE)
    def test_38_inferred_review(self): self.assertEqual(self.result(self.leaf(),{"has_timer":self.fact("has_timer",True,ProductFactStatus.INFERRED)}).reason_code,"PRODUCT_FACT_INFERRED")
    def test_39_na_unknown(self): self.assertEqual(self.result(self.leaf(),{"has_timer":self.fact("has_timer",None,ProductFactStatus.INFERRED_FROM_NA)}).reason_code,"PRODUCT_FACT_INFERRED_FROM_NA")
    def test_40_conflict_review(self): self.assertEqual(self.result(self.leaf(),{"has_timer":self.fact("has_timer",None,ProductFactStatus.CONFLICT)}).reason_code,"PRODUCT_FACT_CONFLICT")

    # SAFETY
    def test_41_missing_never_false(self): self.assertIsNot(self.result(self.leaf()).decision,D.NOT_APPLICABLE)
    def test_42_na_never_false(self): self.assertIsNot(self.result(self.leaf(),{"has_timer":self.fact("has_timer",None,ProductFactStatus.INFERRED_FROM_NA)}).decision,D.NOT_APPLICABLE)
    def test_43_verdict_ignored(self):
        f=self.fact("has_timer",True); f.evidence[0].reported_verdict="FAIL"; self.assertIs(self.result(self.leaf(),{"has_timer":f}).decision,D.APPLICABLE)
    def test_44_kb_not_mutated(self):
        kb={"effective_kb_id":"KB","clauses":[{"effective_clause_id":"EC","requirements":[self.req(logic=self.leaf())],"children":[]}],"annexes":[]}; before=copy.deepcopy(kb); self.e.evaluate(kb,self.profile()); self.assertEqual(kb,before)
    def test_45_profile_not_mutated(self):
        p=self.profile({"has_timer":self.fact("has_timer",True)}); before=p.to_dict(); self.result(self.leaf(),p.facts); self.assertEqual(p.to_dict(),before)

    # TRACEABILITY
    def test_46_deterministic_id(self): self.assertEqual(self.result(self.leaf(),rid="R 1").evaluation_id,"APP-EVAL-R_1")
    def test_47_required_features_sorted(self): self.assertEqual(self.result({"all":[self.leaf("z"),self.leaf("a")]}).required_features,["a","z"])
    def test_48_facts_used(self): self.assertEqual(self.result(self.leaf(),{"has_timer":self.fact("has_timer",True)}).facts_used[0].evidence_ids,["EV-1"])
    def test_49_missing_features(self): self.assertEqual(self.result(self.leaf()).missing_features,["has_timer"])
    def test_50_conflicting_features(self): self.assertEqual(self.result(self.leaf(),{"has_timer":self.fact("has_timer",None,ProductFactStatus.CONFLICT)}).conflicting_features,["has_timer"])

    # SERIALIZATION
    def test_51_valid_json(self): json.loads(self.e.to_json(self.e.evaluate({"effective_kb_id":"K","clauses":[],"annexes":[]},self.profile())))
    def test_52_enum_plain(self): self.assertIn('"decision": "APPLICABLE"',self.e.to_json(self.result(None,app="ALWAYS")))
    def test_53_deterministic_serialization(self):
        r=self.result(self.leaf(),{"has_timer":self.fact("has_timer",True)}); self.assertEqual(self.e.to_json(r),self.e.to_json(r))

    # RULE VALIDATION
    def test_54_unknown_operator(self): self.assertEqual(self.result(self.leaf(op="approximately")).reason_code,"INVALID_RULE")
    def test_55_malformed_all(self): self.assertEqual(self.result({"all":[]}).reason_code,"INVALID_RULE")
    def test_56_malformed_any(self): self.assertEqual(self.result({"any":"bad"}).reason_code,"INVALID_RULE")
    def test_57_invalid_field_node(self): self.assertEqual(self.result({"field":"","operator":"equals","value":1}).reason_code,"INVALID_RULE")

    # NO SCOPE CREEP
    def test_58_no_pass(self): self.assertNotIn("PASS",self.e.to_json(self.result(None,app="ALWAYS")))
    def test_59_no_fail(self): self.assertNotIn("FAIL",self.e.to_json(self.result(None,app="ALWAYS")))
    def test_60_no_na_correctness(self): self.assertNotIn("correctness",self.e.to_json(self.result(None,app="ALWAYS")).casefold())

    # Additional operator/measurement/report coverage
    def test_61_in_operator(self): self.assertIs(self.result(self.leaf("x","in",["A","B"]),{"x":self.fact("x","A")}).decision,D.APPLICABLE)
    def test_62_not_in_operator(self): self.assertIs(self.result(self.leaf("x","not_in",["A"]),{"x":self.fact("x","B")}).decision,D.APPLICABLE)
    def test_63_measurement_scalar_comparison(self): self.assertIs(self.result(self.leaf("rated_power_input","greater_than",300),{"rated_power_input":self.fact("rated_power_input",{"value":400,"unit":"W"})}).decision,D.APPLICABLE)
    def test_64_measurement_unit_mismatch(self): self.assertEqual(self.result(self.leaf("rated_power_input","equals",{"value":400,"unit":"kW"}),{"rated_power_input":self.fact("rated_power_input",{"value":400,"unit":"W"})}).reason_code,"INCOMPARABLE_VALUE")
    def test_65_annex_requirements_evaluated(self):
        kb={"effective_kb_id":"K","clauses":[],"annexes":[{"effective_annex_id":"EA","requirements":[self.req(app="ALWAYS")]}]}; self.assertEqual(len(self.e.evaluate(kb,self.profile()).results),1)
    def test_66_save_json(self):
        report=self.e.evaluate({"effective_kb_id":"K","clauses":[],"annexes":[]},self.profile())
        with tempfile.TemporaryDirectory() as td: self.assertTrue(self.e.save_json(report,Path(td)/"result.json").is_file())


if __name__ == "__main__": unittest.main(verbosity=2)
