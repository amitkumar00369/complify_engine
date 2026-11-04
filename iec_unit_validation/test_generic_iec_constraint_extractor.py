"""Tests for deterministic IEC technical-constraint extraction."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from iec_par.generic_iec_constraint_extractor import (
    GenericIECTechnicalConstraintExtractor,
)
from iec_par.generic_iec_kb_models import (
    ApplicabilityRule,
    ApplicabilityStatus,
    Clause,
    ClauseType,
    ConstraintStatus,
    ConstraintType,
    NumericLimit,
    ParentRelationship,
    RelationshipType,
    Requirement,
    RequirementType,
    SourceReference,
)


def requirement(
    text: str,
    requirement_id: str = "7-R1",
    requirement_type: RequirementType = RequirementType.LIMIT,
) -> Requirement:
    return Requirement(
        requirement_id=requirement_id,
        text=text,
        requirement_type=requirement_type,
        normative=True,
        condition_text="For class II appliances",
        applicability=ApplicabilityRule(
            status=ApplicabilityStatus.RESOLVED,
            condition_text="For class II appliances",
            logic={"field": "protection_class", "operator": "equals", "value": "CLASS_II"},
        ),
    )


def clause(
    item: Requirement | None = None,
    clause_id: str = "7",
    children: list[Clause] | None = None,
    relationship: RelationshipType = RelationshipType.NONE,
) -> Clause:
    return Clause(
        clause_id=clause_id,
        clause_type=ClauseType.NORMATIVE,
        source=SourceReference(raw_text="source"),
        relationship_to_parent=ParentRelationship(type=relationship, parent_clause_id="7"),
        requirements=[item] if item else [],
        children=list(children or []),
    )


class TestGenericIECTechnicalConstraintExtractor(unittest.TestCase):
    """Verify extraction semantics and preservation guarantees."""

    def setUp(self) -> None:
        self.extractor = GenericIECTechnicalConstraintExtractor()

    def extract(
        self, text: str, requirement_type: RequirementType = RequirementType.LIMIT
    ) -> tuple[Requirement, list]:
        output = self.extractor.parse([clause(requirement(text, requirement_type=requirement_type))])
        item = output[0].requirements[0]
        return item, item.technical_constraints

    def test_01_decimal_comma_current_limit(self) -> None:
        _, items = self.extract("The leakage current shall not exceed 3,5 mA.")
        self.assertEqual((items[0].operator, items[0].value, items[0].unit_normalized),
                         ("less_than_or_equal", 3.5, "mA"))

    def test_02_opening_distance_limit(self) -> None:
        _, items = self.extract("The opening shall not exceed 50 mm.")
        self.assertEqual((items[0].parameter, items[0].value), ("opening_distance", 50))

    def test_03_drum_speed_limit(self) -> None:
        _, items = self.extract("The drum speed shall be no higher than 60 r/min.")
        self.assertEqual((items[0].operator, items[0].value, items[0].unit),
                         ("less_than_or_equal", 60, "r/min"))

    def test_04_operation_cycles_minimum(self) -> None:
        _, items = self.extract("The number of cycles shall not be less than 6 000.")
        self.assertEqual((items[0].operator, items[0].value, items[0].unit),
                         ("greater_than_or_equal", 6000, "cycles"))

    def test_05_water_flow_limit_and_unit_normalization(self) -> None:
        _, items = self.extract("Any flow of water shall not exceed 0,5 l/min.")
        self.assertEqual((items[0].parameter, items[0].value, items[0].unit_normalized),
                         ("water_flow_rate", 0.5, "L/min"))

    def test_06_at_least_distance(self) -> None:
        _, items = self.extract("The width shall be at least 5 mm.")
        self.assertEqual(items[0].operator, "greater_than_or_equal")

    def test_07_voltage_range(self) -> None:
        _, items = self.extract("The voltage shall be between 220 V and 240 V.")
        self.assertEqual((items[0].operator, items[0].value, items[0].value_secondary),
                         ("between", 220, 240))
        self.assertIs(items[0].constraint_type, ConstraintType.RANGE)

    def test_08_plus_minus_tolerance(self) -> None:
        _, items = self.extract("The value shall remain within ± 5 %.")
        self.assertEqual(items[0].tolerance, {"type": "PLUS_MINUS", "value": 5})
        self.assertIs(items[0].constraint_type, ConstraintType.TOLERANCE)

    def test_09_decimal_comma_normalization(self) -> None:
        self.assertEqual(self.extractor._normalize_decimal("0,5"), 0.5)

    def test_10_spaced_thousands_normalization(self) -> None:
        self.assertEqual(self.extractor._normalize_decimal("6 000"), 6000)

    def test_11_requirement_text_unchanged(self) -> None:
        text = "The opening shall not exceed 50 mm."
        item, _ = self.extract(text)
        self.assertEqual(item.text, text)

    def test_12_condition_text_unchanged(self) -> None:
        item, _ = self.extract("The opening shall not exceed 50 mm.")
        self.assertEqual(item.condition_text, "For class II appliances")

    def test_13_applicability_unchanged(self) -> None:
        original = requirement("The opening shall not exceed 50 mm.")
        result = self.extractor.parse([clause(original)])[0].requirements[0]
        self.assertEqual(result.applicability, original.applicability)

    def test_14_relationship_unchanged(self) -> None:
        original = clause(requirement("The opening shall not exceed 50 mm."),
                          relationship=RelationshipType.REPLACEMENT)
        result = self.extractor.parse([original])[0]
        self.assertEqual(result.relationship_to_parent, original.relationship_to_parent)

    def test_15_hierarchy_unchanged(self) -> None:
        child = clause(requirement("The opening shall not exceed 50 mm."), "7.1")
        result = self.extractor.parse([clause(children=[child])])
        self.assertEqual(result[0].children[0].clause_id, "7.1")

    def test_16_requirement_id_unchanged(self) -> None:
        original = requirement("The opening shall not exceed 50 mm.", "8.2-R9")
        result = self.extractor.parse([clause(original)])[0].requirements[0]
        self.assertEqual(result.requirement_id, "8.2-R9")

    def test_17_deep_copy(self) -> None:
        original = clause(requirement("The opening shall not exceed 50 mm."))
        result = self.extractor.parse([original])
        self.assertIsNot(result[0], original)
        self.assertEqual(original.requirements[0].technical_constraints, [])

    def test_18_clause_reference_ignored(self) -> None:
        _, items = self.extract("Clause 29")
        self.assertEqual(items, [])

    def test_19_iec_reference_ignored(self) -> None:
        _, items = self.extract("IEC 60730-2-12")
        self.assertEqual(items, [])

    def test_20_symbol_identifier_ignored(self) -> None:
        _, items = self.extract("IEC 60417-5005")
        self.assertEqual(items, [])

    def test_21_table_number_ignored(self) -> None:
        _, items = self.extract("Table 3")
        self.assertEqual(items, [])

    def test_22_figure_number_ignored(self) -> None:
        _, items = self.extract("Figure 7")
        self.assertEqual(items, [])

    def test_23_force_and_duration_are_test_parameters(self) -> None:
        _, items = self.extract("Apply a force of 30 N for 10 s.", RequirementType.TEST)
        self.assertEqual({item.parameter for item in items}, {"applied_force", "test_duration"})
        self.assertTrue(all(item.constraint_type is ConstraintType.TEST_PARAMETER for item in items))

    def test_24_tested_for_one_hour_is_duration(self) -> None:
        _, items = self.extract("The appliance is tested for 1 h.", RequirementType.TEST)
        self.assertEqual((items[0].parameter, items[0].value, items[0].unit),
                         ("test_duration", 1, "h"))

    def test_25_rated_voltage_reference_not_acceptance_limit(self) -> None:
        _, items = self.extract("The appliance is supplied at rated voltage.", RequirementType.TEST)
        self.assertEqual(items, [])

    def test_26_temperature_celsius(self) -> None:
        _, items = self.extract("The temperature shall not exceed 75 °C.")
        self.assertEqual((items[0].parameter, items[0].unit), ("temperature", "°C"))

    def test_27_temperature_rise_kelvin(self) -> None:
        _, items = self.extract("The temperature rise shall not exceed 50 K.")
        self.assertEqual((items[0].parameter, items[0].unit), ("temperature_rise", "K"))

    def test_28_percentage_limit(self) -> None:
        _, items = self.extract("The deviation shall not exceed 10 %.")
        self.assertEqual(items[0].constraint_type, ConstraintType.PERCENTAGE_LIMIT)

    def test_29_two_independent_limits(self) -> None:
        _, items = self.extract(
            "The opening shall not exceed 50 mm and the force shall not exceed 10 N."
        )
        self.assertEqual(len(items), 2)
        self.assertEqual({item.parameter for item in items}, {"opening_distance", "applied_force"})

    def test_30_unknown_numeric_context_is_conservative(self) -> None:
        _, items = self.extract("The unexplained setting shall use 42 V.")
        self.assertTrue(not items or items[0].status is not ConstraintStatus.RESOLVED)

    def test_31_whichever_greater_is_max(self) -> None:
        text = ("The leakage current shall not exceed 3,5 mA, or 1 mA/kW of rated power "
                "input with a limit of 5 mA, whichever is greater.")
        _, items = self.extract(text)
        self.assertEqual(items[0].expression["selection"], "MAX")

    def test_32_whichever_lesser_is_min(self) -> None:
        _, items = self.extract(
            "The voltage shall not exceed 240 V or 220 V, whichever is less."
        )
        self.assertEqual(items[0].expression["selection"], "MIN")

    def test_33_leakage_formula_fully_preserved(self) -> None:
        text = ("The leakage current shall not exceed 3,5 mA, or 1 mA/kW of rated power "
                "input with a limit of 5 mA, whichever is greater.")
        _, items = self.extract(text)
        self.assertIs(items[0].constraint_type, ConstraintType.FORMULA)
        self.assertEqual(items[0].expression["operands"][1]["variable"], "rated_power_input")
        self.assertIsNone(items[0].value)

    def test_34_formula_cap_preserved(self) -> None:
        text = ("The leakage current shall not exceed 3,5 mA, or 1 mA/kW of rated power "
                "input with a limit of 5 mA, whichever is greater.")
        _, items = self.extract(text)
        self.assertEqual(items[0].expression["operands"][1]["cap"], {
            "operator": "less_than_or_equal", "value": 5, "unit": "mA"
        })

    def test_35_time_dependent_compound(self) -> None:
        text = ("The drum speed shall be no higher than 60 r/min within 7 s of opening "
                "the lid or door by 50 mm.")
        _, items = self.extract(text)
        item = items[0]
        self.assertEqual((item.value, item.expression["time_window"]["value"],
                          item.expression["trigger"]["value"]), (60, 7, 50))
        self.assertIs(item.constraint_type, ConstraintType.COMPOUND)

    def test_36_electrolyser_or_structure(self) -> None:
        text = ("The electrolyser shall have an aperture of at least 5 mm in diameter, "
                "or 20 mm2 in area with a width of at least 3 mm.")
        _, items = self.extract(text)
        expression = items[0].expression
        self.assertEqual(expression["any"][0]["field"], "aperture_diameter")
        self.assertEqual(expression["any"][1]["all"][0]["field"], "aperture_area")

    def test_37_or_not_converted_to_and(self) -> None:
        text = ("The electrolyser shall have an aperture of at least 5 mm in diameter, "
                "or 20 mm² in area with a width of at least 3 mm.")
        _, items = self.extract(text)
        self.assertIn("any", items[0].expression)
        self.assertNotIn("all", items[0].expression)

    def test_38_technical_constraints_default_behavior(self) -> None:
        self.assertEqual(requirement("The appliance shall comply.").technical_constraints, [])

    def test_39_constraint_ids_are_stable(self) -> None:
        _, items = self.extract(
            "The opening shall not exceed 50 mm and the force shall not exceed 10 N."
        )
        self.assertEqual([item.constraint_id for item in items], ["7-R1-C1", "7-R1-C2"])

    def test_40_no_duplicate_semantic_constraints(self) -> None:
        text = ("The leakage current shall not exceed 3,5 mA, or 1 mA/kW of rated power "
                "input with a limit of 5 mA, whichever is greater.")
        _, items = self.extract(text)
        self.assertEqual(len(items), 1)

    def test_41_no_pass_fail_or_na_output(self) -> None:
        _, items = self.extract("The opening shall not exceed 50 mm.")
        serialized = json.dumps([item.to_dict() for item in items]).upper()
        self.assertNotIn('"PASS"', serialized)
        self.assertNotIn('"FAIL"', serialized)
        self.assertNotIn('"N/A"', serialized)

    def test_42_existing_limits_field_unchanged(self) -> None:
        original = requirement("The opening shall not exceed 50 mm.")
        original.limits.append(NumericLimit(parameter="legacy", value=1))
        result = self.extractor.parse([clause(original)])[0].requirements[0]
        self.assertEqual(result.limits, original.limits)

    def test_43_embedded_clause_heading_is_not_an_ampere_value(self) -> None:
        text = (
            "Compliance is checked by the test of 21.101.1 for lids. "
            "21.101.1 A rubber hemisphere is used."
        )
        _, items = self.extract(text, RequirementType.TEST)
        self.assertFalse(any(item.unit == "A" and item.value == 101.1 for item in items))

    def test_44_declared_interlock_cycles_with_references(self) -> None:
        text = (
            "The number of cycles of operation declared for Subclauses 6.10 and 6.11 "
            "of IEC 60730-2-12 shall not be less than 6 000."
        )
        _, items = self.extract(text)
        self.assertEqual((items[0].parameter, items[0].value, items[0].unit),
                         ("operation_cycles", 6000, "cycles"))

    def test_45_roller_separation_preserves_or_and_structure(self) -> None:
        text = (
            "The rollers shall separate either by at least 45 mm at both ends or by at "
            "least 25 mm at one end and 75 mm at the other."
        )
        _, items = self.extract(text)
        self.assertEqual(len(items), 1)
        self.assertIn("any", items[0].expression)
        self.assertIn("all", items[0].expression["any"][1])

    def test_46_unsupported_unit_is_not_partially_matched(self) -> None:
        _, items = self.extract("The mass shall not exceed 3 kg.")
        self.assertFalse(any(item.unit in {"k", "g"} for item in items))

    def test_47_single_decimal_clause_heading_is_not_current(self) -> None:
        _, items = self.extract(
            "Compliance is checked as specified. 22.51 Appliances shall be constructed.",
            RequirementType.TEST,
        )
        self.assertFalse(any(item.value == 22.51 and item.unit == "A" for item in items))

    def test_48_colon_form_iec_year_is_not_current(self) -> None:
        _, items = self.extract(
            "Copyright IEC:2010 Appliances shall comply.", RequirementType.TEST
        )
        self.assertFalse(any(item.value == 2010 and item.unit == "A" for item in items))


if __name__ == "__main__":
    unittest.main(verbosity=2)
