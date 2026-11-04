"""Step 31K-E generic comparator extraction and numeric-boundary tests."""
from __future__ import annotations

import unittest

from iec_par.generic_final_requirement_decision_engine import (
    FinalRequirementDecision,
    GenericFinalRequirementDecisionEngine,
)
from iec_par.generic_iec_constraint_extractor import GenericIECTechnicalConstraintExtractor
from iec_par.generic_iec_kb_models import (
    ApplicabilityRule, ApplicabilityStatus, Clause, ClauseType, ConstraintStatus,
    ParentRelationship, RelationshipType, Requirement, RequirementType, SourceReference,
)
from iec_par.generic_technical_constraint_evaluator import (
    GenericTechnicalConstraintEvaluator, TechnicalConstraintDecision,
)
from iec_par.generic_report_evidence_extractor import GenericReportEvidenceExtractor


class GenericTechnicalConstraintOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = GenericIECTechnicalConstraintExtractor()
        self.evaluator = GenericTechnicalConstraintEvaluator()

    def extract(self, text: str):
        requirement = Requirement("R1", text, RequirementType.LIMIT, True,
                                  ApplicabilityRule(ApplicabilityStatus.ALWAYS))
        clause = Clause("1", None, ClauseType.NORMATIVE, SourceReference(),
                        ParentRelationship(RelationshipType.NONE), [requirement], [])
        return self.extractor.parse([clause])[0].requirements[0].technical_constraints

    def evaluate(self, operator: str, observed: float, threshold: float = 12,
                 source_unit: str = "V", observed_unit: str = "V"):
        requirement = {"effective_requirement_id":"ER1", "clause_id":"1", "effective_status":"ACTIVE"}
        constraint = {"constraint_id":"C1", "parameter":"voltage", "parameter_text":"voltage",
                      "operator":operator, "value":threshold, "value_secondary":None,
                      "unit":source_unit, "unit_normalized":source_unit,
                      "constraint_type":"VOLTAGE_LIMIT", "status":"RESOLVED",
                      "expression":None, "tolerance":None, "condition_text":None, "raw_text":"limit"}
        measurement = {"measurement_id":"M1", "parameter":"voltage", "parameter_text":"voltage",
                       "value":observed, "unit":observed_unit, "unit_normalized":observed_unit,
                       "raw_text":"observed", "page":1, "notes":"Measurement role: OBSERVED_VALUE"}
        match = {"evidence_refs":[{"measurement_ids":["M1"], "reported_verdict":"PASS"}]}
        return self.evaluator.evaluate_constraint(requirement, constraint, "APPLICABLE", match,
                                                  {"M1": measurement}, {}, "EC1")

    def assert_operator(self, text: str, expected: str) -> None:
        items = self.extract(text)
        self.assertEqual(len(items), 1, text)
        self.assertEqual(items[0].operator, expected, text)
        self.assertEqual(items[0].status, ConstraintStatus.RESOLVED, text)

    def test_01_gt_symbolic(self): self.assert_operator("voltage > 12 V", "greater_than")
    def test_02_gte_unicode(self): self.assert_operator("voltage ≥ 12 V", "greater_than_or_equal")
    def test_03_gte_ascii(self): self.assert_operator("voltage >= 12 V", "greater_than_or_equal")
    def test_04_lt_symbolic(self): self.assert_operator("voltage < 12 V", "less_than")
    def test_05_lte_unicode(self): self.assert_operator("voltage ≤ 12 V", "less_than_or_equal")
    def test_06_lte_ascii(self): self.assert_operator("voltage <= 12 V", "less_than_or_equal")
    def test_07_eq_symbolic(self): self.assert_operator("voltage = 12 V", "equals")
    def test_08_neq_unicode(self): self.assert_operator("voltage ≠ 12 V", "not_equals")
    def test_09_neq_ascii(self): self.assert_operator("voltage != 12 V", "not_equals")
    def test_10_greater_than(self): self.assert_operator("voltage greater than 12 V", "greater_than")
    def test_11_more_than(self): self.assert_operator("voltage more than 12 V", "greater_than")
    def test_12_exceeding(self): self.assert_operator("voltage exceeding 12 V", "greater_than")
    def test_13_at_least(self): self.assert_operator("voltage at least 12 V", "greater_than_or_equal")
    def test_14_not_less_than(self): self.assert_operator("voltage not less than 12 V", "greater_than_or_equal")
    def test_15_less_than(self): self.assert_operator("voltage less than 12 V", "less_than")
    def test_16_below(self): self.assert_operator("voltage below 12 V", "less_than")
    def test_17_at_most(self): self.assert_operator("voltage at most 12 V", "less_than_or_equal")
    def test_18_not_greater_than(self): self.assert_operator("voltage not greater than 12 V", "less_than_or_equal")
    def test_19_not_exceeding(self): self.assert_operator("voltage not exceeding 12 V", "less_than_or_equal")
    def test_20_up_to(self): self.assert_operator("voltage up to 12 V", "less_than_or_equal")
    def test_21_up_to_including(self): self.assert_operator("voltage up to and including 12 V", "less_than_or_equal")
    def test_22_equal_to(self): self.assert_operator("voltage equal to 12 V", "equals")
    def test_23_not_equal_to(self): self.assert_operator("voltage not equal to 12 V", "not_equals")
    def test_24_does_not_exceed(self): self.assert_operator("voltage does not exceed 12 V", "less_than_or_equal")
    def test_25_shall_not_be_less(self): self.assert_operator("voltage shall not be less than 12 V", "greater_than_or_equal")

    def test_26_gt_boundary(self): self.assertIs(self.evaluate("GT", 12).decision, TechnicalConstraintDecision.VIOLATES)
    def test_27_gte_boundary(self): self.assertIs(self.evaluate("GTE", 12).decision, TechnicalConstraintDecision.SATISFIES)
    def test_28_lt_boundary(self): self.assertIs(self.evaluate("LT", 12).decision, TechnicalConstraintDecision.VIOLATES)
    def test_29_lte_boundary(self): self.assertIs(self.evaluate("LTE", 12).decision, TechnicalConstraintDecision.SATISFIES)
    def test_30_eq_boundary(self): self.assertIs(self.evaluate("EQ", 12).decision, TechnicalConstraintDecision.SATISFIES)
    def test_31_neq_boundary(self): self.assertIs(self.evaluate("NEQ", 12).decision, TechnicalConstraintDecision.VIOLATES)

    def test_32_decimal_value(self): self.assertEqual(self.extract("voltage > 42.4 V")[0].value, 42.4)
    def test_33_signed_value(self): self.assertEqual(self.extract("temperature below -10 °C")[0].value, -10)
    def test_34_positive_signed_percent(self): self.assertEqual(self.extract("percentage > +6 %")[0].value, 6)
    def test_35_percentage_constraint(self): self.assertEqual(self.extract("percentage not exceeding 10 %")[0].unit, "%")
    def test_36_duration_constraint(self): self.assertEqual(self.extract("duration less than 5 s")[0].parameter, "test_duration")

    def test_37_compatible_unit_conversion(self):
        self.assertIs(self.evaluate("GT", 1000, .9, "V", "mV").decision,
                      TechnicalConstraintDecision.SATISFIES)

    def test_38_incompatible_unit_review(self):
        self.assertIs(self.evaluate("GT", 12, 12, "V", "s").decision,
                      TechnicalConstraintDecision.INCOMPARABLE)

    def test_39_multi_constraint_sentence(self):
        items = self.extract("voltage shall be > 12 V and <= 60 V")
        self.assertEqual([(x.operator, x.value) for x in items],
                         [("greater_than", 12), ("less_than_or_equal", 60)])

    def test_40_inclusive_range_extraction(self):
        item = self.extract("voltage shall be between 10 V and 20 V")[0]
        self.assertEqual((item.operator, item.value, item.value_secondary), ("between", 10, 20))

    def test_41_unknown_operator_unresolved(self):
        item = self.extract("voltage shall use 12 V")[0]
        self.assertIsNone(item.operator)
        self.assertIs(item.status, ConstraintStatus.UNRESOLVED)

    def test_42_tolerance_not_flattened(self):
        item = self.extract("voltage shall be 12 V ± 5 %")[0]
        self.assertIsNone(item.operator)
        self.assertIs(item.status, ConstraintStatus.UNRESOLVED)

    def test_43_report_pass_numeric_violation(self):
        result = self.evaluate("GT", 12)
        self.assertIs(result.decision, TechnicalConstraintDecision.VIOLATES)

    def test_44_report_fail_numeric_satisfies(self):
        result = self.evaluate("GTE", 12, 10)
        self.assertIs(result.decision, TechnicalConstraintDecision.SATISFIES)

    def test_45_canonical_and_legacy_operators_match(self):
        self.assertEqual(self.evaluate("GT", 13).decision, self.evaluate("greater_than", 13).decision)

    def test_46_iec_61427_regression_is_generic(self):
        item = self.extract("the test voltage is > 12 V")[0]
        self.assertEqual((item.operator, item.value, item.unit), ("greater_than", 12, "V"))
        self.assertIs(self.evaluate(item.operator, 12, item.value).decision,
                      TechnicalConstraintDecision.VIOLATES)

    def test_47_chemistry_not_inferred(self):
        item = self.extract("voltage > 12 V")[0]
        self.assertNotIn("chem", repr(item).casefold())

    def test_48_final_policy_pass_plus_violation(self):
        engine = GenericFinalRequirementDecisionEngine()
        kb={"effective_kb_id":"K","clauses":[{"requirements":[{"effective_requirement_id":"R1","clause_id":"1","effective_status":"ACTIVE","text":"voltage > 12 V","base_sources":[],"delta_sources":[]}],"children":[]}],"annexes":[]}
        profile={"profile_id":"P"}; app={"results":[{"effective_requirement_id":"R1","effective_clause_id":"EC","clause_id":"1","resolved_decision":"APPLICABLE"}]}
        evidence={"document_id":"D","clauses":[{"evidence_items":[{"evidence_id":"E","reported_verdict":"PASS"}],"children":[]}]}
        match={"matches":[{"effective_requirement_id":"R1","match_status":"EXACT_SUBCLAUSE"}]}
        technical={"results":[{"effective_requirement_id":"R1","decision":"VIOLATES","constraint":{"constraint_type":"VOLTAGE_LIMIT"},"selected_measurement_id":"M"}]}
        grouping={"groups":[{"group_id":"G","clause_id":"1","primary_requirement_id":"R1","members":[{"effective_requirement_id":"R1"}]}]}
        scope={"results":[{"report_evidence_id":"E","reported_verdict":"PASS","scope_status":"EXACT_GROUP","selected_groups":[{"group_id":"G"}],"candidate_groups":[{"group_id":"G"}]}]}
        result=engine.evaluate(kb,profile,app,evidence,match,technical,grouping,scope,{"member_results":[]})
        self.assertIs(result.results[0].final_decision, FinalRequirementDecision.NON_COMPLIANT)

    def test_49_compact_result_tail_is_observed_value(self):
        report = GenericReportEvidenceExtractor().extract_from_pages([
            "1\nGeneral\nP\nvoltage shall be > 12 V; 12V\nP\ncurrent shall be <= 2 A; 1A\nP"
        ])
        measurements = [m for item in report.clauses[0].evidence_items
                        for m in item.measurements]
        self.assertTrue(measurements)
        self.assertTrue(all("OBSERVED_VALUE" in (m.notes or "") for m in measurements))

    def test_50_single_unlabelled_unit_compatible_measurement(self):
        requirement = {"effective_requirement_id":"ER1", "clause_id":"1", "effective_status":"ACTIVE"}
        constraint = {"constraint_id":"C1", "parameter":"voltage", "operator":"GT", "value":12,
                      "value_secondary":None, "unit":"V", "unit_normalized":"V",
                      "constraint_type":"VOLTAGE_LIMIT", "status":"RESOLVED", "tolerance":None}
        measurement = {"measurement_id":"M1", "parameter":None, "parameter_text":None,
                       "value":12, "unit":"V", "unit_normalized":"V", "page":1,
                       "notes":"Measurement role: OBSERVED_VALUE"}
        result = self.evaluator.evaluate_constraint(
            requirement, constraint, "APPLICABLE", {"evidence_refs":[{"measurement_ids":["M1"]}]},
            {"M1":measurement}, {}, "EC1")
        self.assertIs(result.decision, TechnicalConstraintDecision.VIOLATES)

    def test_51_condition_threshold_is_not_acceptance_limit(self):
        items = self.extract(
            "When residual capacity is below 80 %, then the unit shall undergo another test."
        )
        self.assertFalse(any(item.operator == "less_than" for item in items))


if __name__ == "__main__":
    unittest.main(verbosity=2)
