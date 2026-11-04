"""Generic regression tests for Part-2 applicability and negative semantics."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iec_par.generic_iec_applicability_extractor import GenericIECApplicabilityExtractor
from iec_par.generic_iec_applicability_normalizer import GenericIECApplicabilityNormalizer
from iec_par.generic_iec_feature_registry import CanonicalProductFeatureRegistry
from iec_par.generic_iec_kb_models import (
    ApplicabilityEffect, ApplicabilityRule, ApplicabilityStatus, Clause, ClauseType,
    DocumentType, KnowledgeBase, ParentRelationship, RelationshipType, Requirement,
    RequirementSemanticType, RequirementType, SourceReference, StandardDocument,
)
from iec_par.generic_iec_requirement_parser import GenericIECRequirementParser
from iec_par.generic_iec_effective_kb_builder import GenericIECEffectiveKnowledgeBaseBuilder
from iec_par.generic_product_profile_models import ProductFact, ProductFactStatus, ProductProfile
from iec_par.generic_requirement_applicability_evaluator import (
    GenericRequirementApplicabilityEvaluator, RequirementApplicabilityDecision,
)


class DeltaSemanticTests(unittest.TestCase):
    def parsed(self, text):
        clause = Clause("8", ClauseType.NORMATIVE, SourceReference(raw_text="8 " + text),
                        ParentRelationship(RelationshipType.ADDITION, "8"))
        clauses = GenericIECRequirementParser().parse([clause])
        clauses = GenericIECApplicabilityExtractor().parse(clauses)
        return GenericIECApplicabilityNormalizer(CanonicalProductFeatureRegistry()).parse(clauses)[0].requirements

    def test_01_unconditional_not_applicable(self):
        item = self.parsed("This requirement is not applicable.")[0]
        self.assertIs(item.semantic_type, RequirementSemanticType.EXCLUSION)
        self.assertIs(item.applicability.effect, ApplicabilityEffect.DOES_NOT_APPLY)

    def test_02_product_type_test_exclusion(self):
        item = self.parsed("Products of type A are not subjected to the test.")[0]
        self.assertIs(item.semantic_type, RequirementSemanticType.CONDITIONAL_EXCLUSION)
        self.assertEqual(item.applicability.logic["field"], "product_type")

    def test_03_conditional_test_exclusion(self):
        item = self.parsed("The test is not applicable when condition X is met.")[0]
        self.assertEqual(item.condition_text, "when condition X is met")

    def test_04_is_not_allowed_is_prohibition(self):
        self.assertIs(self.parsed("Component type X is not allowed.")[0].semantic_type,
                      RequirementSemanticType.PROHIBITION)

    def test_05_shall_not_is_prohibition(self):
        self.assertIs(self.parsed("The appliance shall not incorporate a fuse.")[0].semantic_type,
                      RequirementSemanticType.PROHIBITION)

    def test_06_applies_only_when_is_conditional(self):
        self.assertEqual(self.parsed("The requirement applies only when condition Y is present.")[0].condition_text,
                         "when condition Y is present")

    def test_07_positive_test_statement_retained(self):
        self.assertEqual(len(self.parsed("Other products are subjected to the test.")), 1)

    def test_08_addition_with_prohibition(self):
        self.assertTrue(self.parsed("Addition: Component type X is not allowed.")[0].normative)

    def test_09_note_not_prohibition(self):
        self.assertEqual(self.parsed("NOTE Component type X is not allowed."), [])

    def test_10_example_not_requirement(self):
        self.assertEqual(self.parsed("EXAMPLE The appliance shall not incorporate a fuse."), [])

    def test_11_definition_context_not_requirement(self):
        clause = Clause("3.1", ClauseType.NORMATIVE, SourceReference(raw_text="3.1 term definition is not allowed."), ParentRelationship(RelationshipType.NONE))
        from iec_par.generic_iec_structural_parser import StructuralBlock
        block = StructuralBlock("SUBCLAUSE", "3.1", "term", 2, "3", 1, 1,
                                "3.1 term definition is not allowed.", 1, "DEFINITION")
        self.assertEqual(GenericIECRequirementParser().parse([clause], [block])[0].requirements, [])

    def test_12_exclusion_true_false_and_missing(self):
        rule = {"status":"RESOLVED", "logic":{"field":"product_type","operator":"equals","value":"type a"}, "effect":"DOES_NOT_APPLY"}
        req = {"effective_requirement_id":"ER-1","clause_id":"8","effective_status":"ACTIVE","applicability":rule}
        evaluator = GenericRequirementApplicabilityEvaluator()
        profile = lambda value: ProductProfile("P", facts={} if value is None else {"product_type":ProductFact("product_type",value,ProductFactStatus.CONFIRMED,.9)})
        self.assertIs(evaluator.evaluate_requirement(req, profile("type a")).decision, RequirementApplicabilityDecision.NOT_APPLICABLE)
        self.assertIs(evaluator.evaluate_requirement(req, profile("type b")).decision, RequirementApplicabilityDecision.APPLICABLE)
        self.assertIs(evaluator.evaluate_requirement(req, profile(None)).decision, RequirementApplicabilityDecision.UNKNOWN)

    def test_13_serialization_deterministic(self):
        item = self.parsed("Products of type A are not subjected to the test.")[0]
        self.assertEqual(json.dumps(item.to_dict(), sort_keys=True), json.dumps(item.to_dict(), sort_keys=True))

    def test_14_mutable_defaults_isolated(self):
        a = ApplicabilityRule(ApplicabilityStatus.ALWAYS); b = ApplicabilityRule(ApplicabilityStatus.ALWAYS)
        a.unresolved_features.append("x"); self.assertEqual(b.unresolved_features, [])

    def test_15_effect_defaults_backward_compatible(self):
        self.assertIs(ApplicabilityRule(ApplicabilityStatus.ALWAYS).effect, ApplicabilityEffect.APPLIES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
