"""Generic source-backed feature presence and absence tests."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iec_par.generic_iec_feature_registry import CanonicalProductFeatureRegistry
from iec_par.generic_product_profile_models import FeaturePresenceState, ProductProfile
from iec_par.generic_report_product_profile_builder import GenericReportProductProfileBuilder
from iec_par.generic_requirement_applicability_evaluator import GenericRequirementApplicabilityEvaluator


class NegativeProductContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        source = Path(self.temp.name) / "registry.json"
        source.write_text(json.dumps({"schema_version":"test","features":[
            {"key":"has_feature_alpha","category":"generic","data_type":"BOOLEAN","description":"Alpha feature","aliases":["feature alpha","alpha module"]},
            {"key":"has_feature_beta","category":"generic","data_type":"BOOLEAN","description":"Beta feature","aliases":["feature beta"]}
        ]}), encoding="utf-8")
        self.registry = CanonicalProductFeatureRegistry(source)
        self.builder = GenericReportProductProfileBuilder(self.registry)

    def tearDown(self): self.temp.cleanup()
    def build(self, text): return self.builder.build_from_pages(["Report No.: R\n"+text])
    def fact(self, text, key="has_feature_alpha"): return self.build(text).facts.get(key)
    def test_01_absent(self): self.assertFalse(self.fact("No feature alpha is provided.").value)
    def test_02_present(self): self.assertTrue(self.fact("The product is provided with feature alpha.").value)
    def test_03_unknown_when_unmentioned(self): self.assertIsNone(self.fact("Unrelated text."))
    def test_04_without_is_absent(self): self.assertFalse(self.fact("The product without feature alpha.").value)
    def test_05_requirement_not_fact(self): self.assertIsNone(self.fact("Products without feature alpha shall be marked."))
    def test_06_note_ignored(self): self.assertIsNone(self.fact("NOTE: no feature alpha is provided."))
    def test_07_example_ignored(self): self.assertIsNone(self.fact("EXAMPLE: no feature alpha is provided."))
    def test_08_conditional_ignored(self): self.assertIsNone(self.fact("If no feature alpha is provided, test it."))
    def test_09_conflict(self): self.assertEqual(self.fact("No feature alpha is provided.\nThe product has feature alpha.").status.value,"CONFLICT")
    def test_10_alias(self): self.assertFalse(self.fact("Without alpha module.").value)
    def test_11_punctuation_case(self): self.assertFalse(self.fact("NO FEATURE ALPHA!").value)
    def test_12_presence_metadata(self): self.assertEqual(self.fact("No feature alpha.").observations[0].presence_state,FeaturePresenceState.ABSENT)
    def test_13_source_strength(self): self.assertEqual(self.fact("No feature alpha.").observations[0].source_strength,"CONFIRMED_SOURCE_ASSERTION")
    def test_14_report_scope(self): self.assertEqual(self.fact("No feature alpha.").observations[0].scope_type,"REPORT_SCOPE")
    def test_15_model_scope_not_global(self):
        fact=self.fact("Model A-1 has no feature alpha.");self.assertIsNone(fact.value);self.assertEqual(fact.observations[0].model_scope,"A-1")
    def test_16_na_alone_not_absence(self): self.assertIsNone(self.fact("N/A"))
    def test_17_deterministic(self): self.assertEqual(self.build("No feature alpha.").to_json(),self.build("No feature alpha.").to_json())
    def test_18_old_profile_compatible(self):
        p=self.build("No feature alpha.").to_dict();p["facts"]["has_feature_alpha"]["observations"][0].pop("presence_state");self.assertIsInstance(ProductProfile.from_dict(p),ProductProfile)
    def evaluate(self,value,field="has_feature_alpha",expected=True):
        profile=self.build("No feature alpha." if value is False else "The product has feature alpha." if value is True else "Nothing stated.")
        req={"effective_requirement_id":"R","effective_status":"ACTIVE","clause_id":"1","applicability":{"status":"RESOLVED","effect":"APPLIES","logic":{"field":field,"operator":"equals","value":expected}}}
        return GenericRequirementApplicabilityEvaluator().evaluate_requirement(req,profile).decision.value
    def test_19_absence_condition_false(self): self.assertEqual(self.evaluate(False),"NOT_APPLICABLE")
    def test_20_inverse_absence_condition_true(self): self.assertEqual(self.evaluate(False,expected=False),"APPLICABLE")
    def test_21_unknown_unresolved(self): self.assertEqual(self.evaluate(None),"UNKNOWN")
    def test_22_unrelated_requirement_unresolved(self): self.assertEqual(self.evaluate(False,"has_feature_beta"),"UNKNOWN")
    def test_23_conflict_conservative(self):
        profile=self.build("No feature alpha.\nThe product has feature alpha.");req={"effective_requirement_id":"R","effective_status":"ACTIVE","clause_id":"1","applicability":{"status":"RESOLVED","effect":"APPLIES","logic":{"field":"has_feature_alpha","operator":"equals","value":True}}};self.assertEqual(GenericRequirementApplicabilityEvaluator().evaluate_requirement(req,profile).decision.value,"NEEDS_REVIEW")


if __name__ == "__main__": unittest.main(verbosity=2)
