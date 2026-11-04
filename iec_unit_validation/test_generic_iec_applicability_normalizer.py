"""Tests for conservative canonical applicability normalization."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from iec_par.generic_iec_applicability_normalizer import (
    GenericIECApplicabilityNormalizer,
)
from iec_par.generic_iec_feature_registry import (
    CanonicalProductFeatureRegistry,
)
from iec_par.generic_iec_kb_models import (
    ApplicabilityRule,
    ApplicabilityStatus,
    Clause,
    ClauseType,
    ParentRelationship,
    RelationshipType,
    Requirement,
    RequirementType,
    SourceReference,
)


def make_requirement(text: str, condition: str | None, requirement_id: str = "7-R1") -> Requirement:
    return Requirement(
        requirement_id=requirement_id,
        text=text,
        requirement_type=RequirementType.CONDITIONAL,
        normative=True,
        condition_text=condition,
        applicability=ApplicabilityRule(
            status=ApplicabilityStatus.UNRESOLVED if condition else ApplicabilityStatus.ALWAYS,
            condition_text=condition,
        ),
    )


def make_clause(
    requirement: Requirement | None = None,
    clause_id: str = "7",
    children: list[Clause] | None = None,
    relationship: RelationshipType = RelationshipType.NONE,
) -> Clause:
    return Clause(
        clause_id=clause_id,
        title="Heading",
        clause_type=ClauseType.NORMATIVE,
        source=SourceReference(raw_text="source"),
        relationship_to_parent=ParentRelationship(type=relationship),
        requirements=[requirement] if requirement else [],
        children=list(children or []),
    )


class TestGenericIECApplicabilityNormalizer(unittest.TestCase):
    """Verify required mappings, safety behavior, and traceability."""

    def setUp(self) -> None:
        self.registry = CanonicalProductFeatureRegistry()
        self.normalizer = GenericIECApplicabilityNormalizer(self.registry)

    def normalize(self, condition: str, text: str | None = None) -> Requirement:
        requirement = make_requirement(text or f"{condition}, it shall comply.", condition)
        return self.normalizer.parse([make_clause(requirement)])[0].requirements[0]

    def test_01_class_ii(self) -> None:
        item = self.normalize("For class II appliances")
        self.assertEqual(item.applicability.logic, {
            "field": "protection_class", "operator": "equals", "value": "CLASS_II"
        })

    def test_02_class_iii_exclusion(self) -> None:
        item = self.normalize("This requirement does not apply to class III appliances.")
        self.assertEqual(item.applicability.logic, {
            "field": "protection_class", "operator": "not_equals", "value": "CLASS_III"
        })

    def test_03_heating_element(self) -> None:
        item = self.normalize("Appliances incorporating heating elements")
        self.assertEqual(item.applicability.logic["value"], True)
        self.assertEqual(item.applicability.logic["field"], "has_heating_element")

    def test_04_not_provided_with_heating_elements(self) -> None:
        condition = "Appliances not intended for connection to the hot water supply and not provided with heating elements"
        item = self.normalize(condition)
        heating = item.applicability.logic["all"][1]
        self.assertEqual(heating, {
            "field": "has_heating_element", "operator": "equals", "value": False
        })

    def test_05_type_y_attachment(self) -> None:
        item = self.normalize("For appliances with type Y attachment")
        self.assertEqual(item.applicability.logic, {
            "field": "attachment_type", "operator": "equals", "value": "TYPE_Y"
        })

    def test_06_stationary_class_i_is_all(self) -> None:
        item = self.normalize("For stationary class I appliances")
        self.assertEqual(set(rule["field"] for rule in item.applicability.logic["all"]), {
            "is_stationary", "protection_class"
        })

    def test_07_programmer_or_timer_is_any(self) -> None:
        item = self.normalize("Appliances incorporating a programmer or timer")
        self.assertEqual(set(rule["field"] for rule in item.applicability.logic["any"]), {
            "has_programmer", "has_timer"
        })

    def test_08_hot_water_false_and_heating_false(self) -> None:
        item = self.normalize(
            "Appliances not intended for connection to the hot water supply and not provided with heating elements"
        )
        self.assertTrue(all(rule["value"] is False for rule in item.applicability.logic["all"]))

    def test_09_base_ventilation_openings(self) -> None:
        item = self.normalize("For washing machines having ventilation openings in the base")
        fields = self.normalizer._collect_fields(item.applicability.logic)
        self.assertEqual(fields, {"has_washing_function", "has_base_ventilation_openings"})

    def test_10_openable_filter_compartment(self) -> None:
        item = self.normalize("If the filter compartment can be opened")
        self.assertEqual(item.applicability.logic["field"], "has_openable_filter_compartment")

    def test_11_drum_front_or_top_compound(self) -> None:
        item = self.normalize(
            "For washing machines of the drum type that are loaded from the front or from the top"
        )
        self.assertIn("any", item.applicability.logic["all"][2])
        values = {rule["value"] for rule in item.applicability.logic["all"][2]["any"]}
        self.assertEqual(values, {"FRONT", "TOP"})

    def test_12_pollution_degree_1(self) -> None:
        item = self.normalize("Except for pollution degree 1")
        self.assertEqual(item.applicability.logic, {
            "field": "pollution_degree", "operator": "not_equals",
            "value": "POLLUTION_DEGREE_1",
        })

    def test_13_unconditional_stays_always(self) -> None:
        requirement = make_requirement("Appliances shall comply.", None)
        item = self.normalizer.parse([make_clause(requirement)])[0].requirements[0]
        self.assertIs(item.applicability.status, ApplicabilityStatus.ALWAYS)
        self.assertIsNone(item.applicability.logic)

    def test_14_unknown_concept_stays_unresolved(self) -> None:
        item = self.normalize("For appliances with quantum flux stabilizers")
        self.assertIs(item.applicability.status, ApplicabilityStatus.UNRESOLVED)
        self.assertIsNone(item.applicability.logic)

    def test_15_subjective_condition_does_not_resolve(self) -> None:
        item = self.normalize("Unless it is obviously unnecessary")
        self.assertIsNot(item.applicability.status, ApplicabilityStatus.RESOLVED)

    def test_16_short_circuit_test_state_does_not_resolve(self) -> None:
        item = self.normalize("If any one of the components is short-circuited or open-circuited")
        self.assertIsNone(item.applicability.logic)

    def test_17_gwfi_availability_does_not_resolve(self) -> None:
        item = self.normalize("If the glow-wire flammability index (GWFI) is not available")
        self.assertIsNone(item.applicability.logic)

    def test_18_no_invented_field_keys(self) -> None:
        item = self.normalize("For appliances with quantum flux stabilizers")
        self.assertEqual(self.normalizer._collect_fields(item.applicability.logic), set())

    def test_19_invalid_enum_value_rejected(self) -> None:
        self.assertFalse(self.normalizer.validate_logic({
            "field": "protection_class", "operator": "equals", "value": "CLASS_IV"
        }))

    def test_20_requirement_text_unchanged(self) -> None:
        text = "For class II appliances,  the terminal shall comply."
        self.assertEqual(self.normalize("For class II appliances", text).text, text)

    def test_21_condition_text_unchanged(self) -> None:
        condition = "For class II appliances."
        item = self.normalize(condition)
        self.assertEqual(item.condition_text, condition)
        self.assertEqual(item.applicability.condition_text, condition)

    def test_22_clause_hierarchy_unchanged(self) -> None:
        child = make_clause(make_requirement("It shall comply.", None, "7.1-R1"), "7.1")
        result = self.normalizer.parse([make_clause(children=[child])])
        self.assertEqual(result[0].children[0].clause_id, "7.1")

    def test_23_requirement_ids_unchanged(self) -> None:
        item = make_requirement("For class II appliances, it shall comply.", "For class II appliances", "X-R9")
        self.assertEqual(self.normalizer.parse([make_clause(item)])[0].requirements[0].requirement_id, "X-R9")

    def test_24_relationships_unchanged(self) -> None:
        clause = make_clause(
            make_requirement("For class II appliances, it shall comply.", "For class II appliances"),
            relationship=RelationshipType.REPLACEMENT,
        )
        result = self.normalizer.parse([clause])
        self.assertIs(result[0].relationship_to_parent.type, RelationshipType.REPLACEMENT)

    def test_25_deep_copy_behavior(self) -> None:
        original = make_clause(make_requirement("For class II appliances, it shall comply.", "For class II appliances"))
        result = self.normalizer.parse([original])
        self.assertIsNot(result[0], original)
        self.assertIsNone(original.requirements[0].applicability.logic)

    def test_26_all_validator(self) -> None:
        self.assertTrue(self.normalizer.validate_logic({"all": [
            {"field": "is_stationary", "operator": "equals", "value": True},
            {"field": "protection_class", "operator": "equals", "value": "CLASS_I"},
        ]}))

    def test_27_any_validator(self) -> None:
        self.assertTrue(self.normalizer.validate_logic({"any": [
            {"field": "has_programmer", "operator": "equals", "value": True},
            {"field": "has_timer", "operator": "equals", "value": True},
        ]}))

    def test_28_not_validator(self) -> None:
        self.assertTrue(self.normalizer.validate_logic({"not": {
            "field": "has_timer", "operator": "equals", "value": True
        }}))

    def test_29_empty_all_rejected(self) -> None:
        self.assertFalse(self.normalizer.validate_logic({"all": []}))

    def test_30_unknown_operator_rejected(self) -> None:
        self.assertFalse(self.normalizer.validate_logic({
            "field": "has_timer", "operator": "contains", "value": True
        }))

    def test_31_unknown_field_rejected(self) -> None:
        self.assertFalse(self.normalizer.validate_logic({
            "field": "invented_field", "operator": "equals", "value": True
        }))

    def test_32_partial_multi_feature_mapping_rejected(self) -> None:
        item = self.normalize("For stationary class I appliances with turbo mode")
        self.assertIsNot(item.applicability.status, ApplicabilityStatus.RESOLVED)
        self.assertIsNone(item.applicability.logic)

    def test_33_ambiguous_alias_does_not_auto_resolve(self) -> None:
        item = self.normalize("Stationary appliance")
        self.assertIsNot(item.applicability.status, ApplicabilityStatus.RESOLVED)

    def test_34_registry_is_source_of_truth(self) -> None:
        logic = {"field": "has_base_ventilation_openings", "operator": "equals", "value": True}
        self.assertTrue(self.registry.exists("has_base_ventilation_openings"))
        self.assertTrue(self.normalizer.validate_logic(logic))

    def test_35_resolved_only_for_complete_condition(self) -> None:
        resolved = self.normalize("For class II appliances")
        partial = self.normalize("For class II appliances with an unknown accessory")
        self.assertIs(resolved.applicability.status, ApplicabilityStatus.RESOLVED)
        self.assertIsNot(partial.applicability.status, ApplicabilityStatus.RESOLVED)

    def test_36_component_relationship_is_not_reduced_to_presence(self) -> None:
        item = self.normalize("If the switch operates a relay or contactor")
        self.assertIs(item.applicability.status, ApplicabilityStatus.NEEDS_REVIEW)
        self.assertIsNone(item.applicability.logic)

    def test_37_electrolyser_construction_is_not_partially_resolved(self) -> None:
        item = self.normalize(
            "Appliances fitted with an electrolyser, consisting of cathodic and anodic "
            "chambers separated by an electrolytic separator,"
        )
        self.assertIs(item.applicability.status, ApplicabilityStatus.NEEDS_REVIEW)
        self.assertIsNone(item.applicability.logic)


if __name__ == "__main__":
    unittest.main(verbosity=2)
