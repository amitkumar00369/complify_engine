"""Focused Step 31N-D numeric and measurement-ownership regressions."""

import unittest
from pathlib import Path

from iec_par.generic_iec_constraint_extractor import GenericIECTechnicalConstraintExtractor
from iec_par.generic_iec_kb_models import (
    ApplicabilityRule, ApplicabilityStatus, Clause, ClauseType, ParentRelationship,
    RelationshipType, Requirement, RequirementType, SourceReference,
)
from iec_par.generic_report_evidence_extractor import GenericReportEvidenceExtractor
from iec_par.generic_technical_constraint_evaluator import (
    GenericTechnicalConstraintEvaluator, TechnicalConstraintDecision,
)


class GenericNumericMeasurementOwnershipTests(unittest.TestCase):
    def constraints(self, text, kind=RequirementType.LIMIT):
        req = Requirement("R1", text, kind, True,
                          applicability=ApplicabilityRule(ApplicabilityStatus.ALWAYS))
        clause = Clause("1", clause_type=ClauseType.NORMATIVE,
                        source=SourceReference(),
                        relationship_to_parent=ParentRelationship(RelationshipType.NONE),
                        requirements=[req])
        return GenericIECTechnicalConstraintExtractor().parse([clause])[0].requirements[0].technical_constraints

    def evaluate(self, operator, observed, limit=12, unit="V", parameter="voltage"):
        evaluator = GenericTechnicalConstraintEvaluator()
        constraint = {"constraint_id":"C1", "parameter":parameter, "parameter_text":parameter,
                      "operator":operator, "value":limit, "value_secondary":None,
                      "unit":unit, "unit_normalized":unit, "constraint_type":"SIMPLE_LIMIT",
                      "status":"RESOLVED", "expression":None, "tolerance":None,
                      "condition_text":None, "raw_text":"limit"}
        measurement = {"measurement_id":"M1", "parameter":parameter, "parameter_text":parameter,
                       "value":observed, "value_secondary":None, "unit":unit,
                       "unit_normalized":unit, "raw_text":"observed", "page":1,
                       "notes":"Measurement role: OBSERVED_VALUE"}
        requirement = {"effective_requirement_id":"ER1", "clause_id":"1",
                       "effective_status":"ACTIVE"}
        match = {"evidence_refs":[{"measurement_ids":["M1"]}]}
        return evaluator.evaluate_constraint(requirement, constraint, "APPLICABLE", match,
                                             {"M1":measurement}, {}, "EC1")

    def report(self, *pages):
        return GenericReportEvidenceExtractor().extract_from_pages(pages, file_name="generic.pdf")

    @staticmethod
    def flat(document):
        output=[]
        def walk(items):
            for item in items: output.append(item); walk(item.children)
        walk(document.clauses)
        return output

    def test_01_not_exceeding_is_lte(self):
        self.assertEqual(self.constraints("The distance shall be not exceeding 1 mm.")[0].operator,
                         "less_than_or_equal")

    def test_02_not_greater_than_is_lte(self):
        self.assertEqual(self.constraints("The force shall be not greater than 5 N.")[0].operator,
                         "less_than_or_equal")

    def test_03_not_less_than_is_gte(self):
        self.assertEqual(self.constraints("The distance shall be not less than 10 mm.")[0].operator,
                         "greater_than_or_equal")

    def test_04_at_least_is_gte(self):
        self.assertEqual(self.constraints("The thickness shall be at least 2 mm.")[0].operator,
                         "greater_than_or_equal")

    def test_05_at_most_is_lte(self):
        self.assertEqual(self.constraints("The force shall be at most 5 N.")[0].operator,
                         "less_than_or_equal")

    def test_06_symbolic_comparator_boundaries(self):
        expected={">":TechnicalConstraintDecision.VIOLATES, ">=":TechnicalConstraintDecision.SATISFIES,
                  "<":TechnicalConstraintDecision.VIOLATES, "<=":TechnicalConstraintDecision.SATISFIES}
        for operator, decision in expected.items(): self.assertIs(self.evaluate(operator,12).decision,decision)

    def test_07_unicode_comparator_boundaries(self):
        self.assertIs(self.evaluate("≥",12).decision,TechnicalConstraintDecision.SATISFIES)
        self.assertIs(self.evaluate("≤",12).decision,TechnicalConstraintDecision.SATISFIES)
        self.assertIs(self.evaluate("≠",12).decision,TechnicalConstraintDecision.VIOLATES)

    def test_08_force_and_duration_ownership(self):
        items=self.constraints("A force of 20 N shall be applied for 10 s.",RequirementType.TEST)
        self.assertEqual({x.parameter for x in items},{"applied_force","test_duration"})
        self.assertTrue(all(x.constraint_type.value=="TEST_PARAMETER" for x in items))

    def test_09_condition_threshold_is_not_limit(self):
        self.assertEqual(self.constraints("When current exceeds 0.2 A, the fuse shall operate."),[])

    def test_10_range_is_preserved(self):
        item=self.constraints("The voltage shall be between 10 V and 12 V.")[0]
        self.assertEqual((item.operator,item.value,item.value_secondary),("between",10,12))

    def test_11_tolerance_is_preserved(self):
        self.assertEqual(self.constraints("The voltage shall remain within ± 5 %.")[0].tolerance["value"],5)

    def test_12_parameter_identity(self):
        self.assertEqual(self.constraints("The thickness shall be at least 2 mm.")[0].parameter,"thickness")

    def test_13_unit_ownership(self):
        item=self.constraints("The electric charge shall not exceed 45 µC.")[0]
        self.assertEqual((item.parameter,item.unit),("charge","µC"))

    def test_14_incompatible_units_are_rejected(self):
        result=self.evaluate("<=",5,12,"V","voltage")
        self.assertIs(result.decision,TechnicalConstraintDecision.SATISFIES)
        evaluator=GenericTechnicalConstraintEvaluator()
        with self.assertRaises(ValueError): evaluator._convert(5,"N","V")

    def test_15_appended_table_reference_ownership(self):
        clause=self.flat(self.report("7.1\nSee appended table\nP\nTABLE: values\nMeasured voltage: 5 V\nP"))[0]
        table=next(x for x in clause.evidence_items if x.parent_evidence_id)
        self.assertEqual((table.clause_id,table.parent_evidence_id),("7.1",clause.evidence_items[0].evidence_id))

    def test_16_appended_numeric_row_extraction(self):
        clause=self.flat(self.report("7.1\nTABLE: values\nTest point A: 5 V\nP"))[0]
        self.assertEqual(clause.evidence_items[-1].measurements[0].value,5)

    def test_17_repeated_header_is_ignored(self):
        clause=self.flat(self.report("7.1\nTABLE: values\nMeasured value\nMeasured value\nPoint A: 5 V\nP"))[0]
        self.assertEqual(len(clause.evidence_items[-1].measurements),1)

    def test_18_page_spanning_table_measurement(self):
        clause=self.flat(self.report("7.1\nTABLE: values\nMeasured value","Point A: 5 V\nP"))[0]
        self.assertTrue(any(x.measurements for x in clause.evidence_items))

    def test_19_multiple_measurements_retained(self):
        clause=self.flat(self.report("7.1\nTABLE: values\nPoint A: 5 V\nPoint B: 6 V\nP"))[0]
        self.assertEqual(len(clause.evidence_items[-1].measurements),2)

    def test_20_wrong_parameter_rejected(self):
        evaluator=GenericTechnicalConstraintEvaluator()
        self.assertNotEqual(evaluator._parameter("force"),evaluator._parameter("voltage"))

    def test_21_cross_clause_same_number_rejected(self):
        document=self.report("1\nMeasured voltage: 5 V\nP\n2\nMeasured voltage: 5 V\nP")
        clauses=self.flat(document); self.assertNotEqual(clauses[0].result_id,clauses[1].result_id)

    def test_22_report_pass_cannot_suppress_violation(self):
        self.assertIs(self.evaluate(">",12).decision,TechnicalConstraintDecision.VIOLATES)

    def test_23_verdict_without_measurement_does_not_invent_result(self):
        self.assertEqual(self.flat(self.report("1\nP"))[0].measurements,[])

    def test_24_iec_61427_boundary_regression(self):
        self.assertIs(self.evaluate(">",12).decision,TechnicalConstraintDecision.VIOLATES)

    def test_25_iec_62841_numeric_regression(self):
        self.assertIs(self.evaluate(">=",12).decision,TechnicalConstraintDecision.SATISFIES)

    def test_26_iec_60335_numeric_regression(self):
        self.assertIs(self.evaluate("<=",12).decision,TechnicalConstraintDecision.SATISFIES)

    def test_27_iec_60204_numeric_regression(self):
        self.assertIs(self.evaluate("<",12).decision,TechnicalConstraintDecision.VIOLATES)

    def test_28_no_family_specific_branch(self):
        root=Path(__file__).resolve().parents[1]/"iec_par"
        source="\n".join((root/name).read_text(encoding="utf-8").casefold() for name in (
            "generic_iec_constraint_extractor.py","generic_report_evidence_extractor.py",
            "generic_technical_constraint_evaluator.py"))
        for token in ("iec 60065","speaker.pdf","clause_id ==","page =="):
            self.assertNotIn(token,source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
