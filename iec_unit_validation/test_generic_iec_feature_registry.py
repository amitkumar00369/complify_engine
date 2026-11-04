"""Tests for the generic canonical IEC product-feature registry."""

from __future__ import annotations

import unittest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from iec_par.generic_iec_feature_registry import (
    CanonicalProductFeature,
    CanonicalProductFeatureRegistry,
    FeatureDataType,
)


class TestCanonicalProductFeatureRegistry(unittest.TestCase):
    """Verify loading, lookup, validation, and required vocabulary coverage."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = CanonicalProductFeatureRegistry()

    def test_01_registry_loads_successfully(self) -> None:
        self.assertGreater(len(self.registry.get_all()), 0)

    def test_02_all_canonical_keys_are_unique(self) -> None:
        keys = [feature.key for feature in self.registry.get_all()]
        self.assertEqual(len(keys), len(set(keys)))

    def test_03_get_returns_correct_feature(self) -> None:
        feature = self.registry.get("has_heating_element")
        self.assertIsNotNone(feature)
        self.assertEqual(feature.category, "heating")

    def test_04_exists_works(self) -> None:
        self.assertTrue(self.registry.exists("has_timer"))
        self.assertFalse(self.registry.exists("not_a_feature"))

    def test_05_boolean_feature_validation(self) -> None:
        self.assertTrue(self.registry.validate_feature_value("has_timer", True))
        self.assertFalse(self.registry.validate_feature_value("has_timer", 1))

    def test_06_enum_valid_value_is_accepted(self) -> None:
        self.assertTrue(self.registry.validate_feature_value("supply_type", "AC"))

    def test_07_enum_invalid_value_is_rejected(self) -> None:
        self.assertFalse(self.registry.validate_feature_value("supply_type", "STEAM"))

    def test_08_measurement_feature_validates_numeric_value(self) -> None:
        self.assertTrue(self.registry.validate_feature_value("rated_voltage", 230))
        self.assertFalse(self.registry.validate_feature_value("rated_voltage", "230 V"))

    def test_09_alias_lookup_exact(self) -> None:
        matches = self.registry.search_alias("heating element")
        self.assertIn("has_heating_element", [feature.key for feature in matches])

    def test_10_alias_lookup_is_case_insensitive(self) -> None:
        matches = self.registry.search_alias("HEATING ELEMENT")
        self.assertIn("has_heating_element", [feature.key for feature in matches])

    def test_11_alias_lookup_normalizes_whitespace(self) -> None:
        matches = self.registry.search_alias("  heating   element  ")
        self.assertIn("has_heating_element", [feature.key for feature in matches])

    def test_12_duplicate_aliases_return_multiple_matches(self) -> None:
        keys = {feature.key for feature in self.registry.search_alias("stationary appliance")}
        self.assertEqual(keys, {"installation_type", "is_stationary"})

    def test_13_unknown_feature_returns_appropriate_results(self) -> None:
        self.assertIsNone(self.registry.get("unknown_feature"))
        self.assertFalse(self.registry.validate_feature_value("unknown_feature", True))
        self.assertEqual(self.registry.search_alias("unknown feature"), [])

    def test_14_get_by_category_works(self) -> None:
        features = self.registry.get_by_category("heating")
        self.assertTrue(features)
        self.assertTrue(all(feature.category == "heating" for feature in features))

    def test_15_get_all_returns_complete_registry(self) -> None:
        all_features = self.registry.get_all()
        category_total = sum(
            len(self.registry.get_by_category(category))
            for category in {feature.category for feature in all_features}
        )
        self.assertEqual(len(all_features), category_total)

    def test_16_mutable_defaults_are_not_shared(self) -> None:
        first = CanonicalProductFeature("a", "test", FeatureDataType.BOOLEAN, "First")
        second = CanonicalProductFeature("b", "test", FeatureDataType.BOOLEAN, "Second")
        first.aliases.append("first")
        first.allowed_values.append("one")
        self.assertEqual(second.aliases, [])
        self.assertEqual(second.allowed_values, [])

    def test_17_protection_class_has_required_enum_values(self) -> None:
        feature = self.registry.get("protection_class")
        self.assertEqual(
            feature.allowed_values,
            ["CLASS_0", "CLASS_0I", "CLASS_I", "CLASS_II", "CLASS_III"],
        )

    def test_18_installation_type_has_defined_enum_values(self) -> None:
        feature = self.registry.get("installation_type")
        self.assertEqual(
            feature.allowed_values,
            ["PORTABLE", "STATIONARY", "FIXED", "BUILT_IN", "FREESTANDING",
             "WALL_MOUNTED", "CEILING_MOUNTED", "OTHER"],
        )

    def test_19_attachment_type_has_xyz_values(self) -> None:
        feature = self.registry.get("attachment_type")
        self.assertTrue({"TYPE_X", "TYPE_Y", "TYPE_Z"}.issubset(feature.allowed_values))

    def test_20_rated_voltage_uses_volts(self) -> None:
        self.assertEqual(self.registry.get("rated_voltage").unit, "V")

    def test_21_rated_frequency_uses_hertz(self) -> None:
        self.assertEqual(self.registry.get("rated_frequency").unit, "Hz")

    def test_22_rated_power_input_uses_watts(self) -> None:
        self.assertEqual(self.registry.get("rated_power_input").unit, "W")

    def test_23_rated_current_uses_amperes(self) -> None:
        self.assertEqual(self.registry.get("rated_current").unit, "A")

    def test_24_has_heating_element_exists(self) -> None:
        self.assertTrue(self.registry.exists("has_heating_element"))

    def test_25_has_programmer_exists(self) -> None:
        self.assertTrue(self.registry.exists("has_programmer"))

    def test_26_has_timer_exists(self) -> None:
        self.assertTrue(self.registry.exists("has_timer"))

    def test_27_has_transformer_exists(self) -> None:
        self.assertTrue(self.registry.exists("has_transformer"))

    def test_28_has_drying_function_exists(self) -> None:
        self.assertTrue(self.registry.exists("has_drying_function"))

    def test_29_has_door_interlock_exists(self) -> None:
        self.assertTrue(self.registry.exists("has_door_interlock"))

    def test_30_automatic_water_level_control_exists(self) -> None:
        self.assertTrue(self.registry.exists("automatic_water_level_control"))

    def test_31_controlled_update_features_exist(self) -> None:
        keys = {
            "rated_value_configuration",
            "uses_standard_symbols",
            "uses_numeric_control_position_markings",
            "requires_user_maintenance_precautions",
            "requires_installation_precautions",
            "has_protective_impedance",
            "has_tool_free_accessible_compartment",
            "pollution_degree",
            "requires_attended_operation",
            "has_base_ventilation_openings",
            "has_openable_filter_compartment",
        }
        self.assertTrue(all(self.registry.exists(key) for key in keys))

    def test_32_controlled_update_features_have_correct_data_types(self) -> None:
        expected_types = {
            "rated_value_configuration": FeatureDataType.ENUM,
            "uses_standard_symbols": FeatureDataType.BOOLEAN,
            "uses_numeric_control_position_markings": FeatureDataType.BOOLEAN,
            "requires_user_maintenance_precautions": FeatureDataType.BOOLEAN,
            "requires_installation_precautions": FeatureDataType.BOOLEAN,
            "has_protective_impedance": FeatureDataType.BOOLEAN,
            "has_tool_free_accessible_compartment": FeatureDataType.BOOLEAN,
            "pollution_degree": FeatureDataType.ENUM,
            "requires_attended_operation": FeatureDataType.BOOLEAN,
            "has_base_ventilation_openings": FeatureDataType.BOOLEAN,
            "has_openable_filter_compartment": FeatureDataType.BOOLEAN,
        }
        for key, expected_type in expected_types.items():
            with self.subTest(key=key):
                self.assertEqual(self.registry.get(key).data_type, expected_type)

    def test_33_rated_value_configuration_enum_validation(self) -> None:
        valid_values = [
            "SINGLE", "CONTINUOUS_RANGE", "SELECTABLE_VALUES", "OTHER", "UNKNOWN"
        ]
        for value in valid_values:
            with self.subTest(value=value):
                self.assertTrue(
                    self.registry.validate_feature_value("rated_value_configuration", value)
                )
        self.assertFalse(
            self.registry.validate_feature_value("rated_value_configuration", "VARIABLE")
        )

    def test_34_pollution_degree_enum_validation(self) -> None:
        valid_values = [
            "POLLUTION_DEGREE_1", "POLLUTION_DEGREE_2", "POLLUTION_DEGREE_3",
            "POLLUTION_DEGREE_4", "UNKNOWN",
        ]
        for value in valid_values:
            with self.subTest(value=value):
                self.assertTrue(self.registry.validate_feature_value("pollution_degree", value))
        self.assertFalse(
            self.registry.validate_feature_value("pollution_degree", "POLLUTION_DEGREE_5")
        )

    def test_35_controlled_update_aliases_work(self) -> None:
        alias_to_key = {
            "range of rated values": "rated_value_configuration",
            "symbols are used": "uses_standard_symbols",
            "figures are used for indicating the different positions":
                "uses_numeric_control_position_markings",
            "precautions during user maintenance":
                "requires_user_maintenance_precautions",
            "precautions during installation": "requires_installation_precautions",
            "protective impedance": "has_protective_impedance",
            "compartment accessible without a tool":
                "has_tool_free_accessible_compartment",
            "pollution degree 1": "pollution_degree",
            "operated while attended": "requires_attended_operation",
            "ventilation openings in the base": "has_base_ventilation_openings",
            "filter compartment can be opened": "has_openable_filter_compartment",
            "first numeral of the IP code": "ip_rating",
        }
        for alias, expected_key in alias_to_key.items():
            with self.subTest(alias=alias):
                keys = {feature.key for feature in self.registry.search_alias(alias)}
                self.assertIn(expected_key, keys)

    def test_36_controlled_update_features_are_applicability_and_report_enabled(self) -> None:
        keys = [
            "rated_value_configuration",
            "uses_standard_symbols",
            "uses_numeric_control_position_markings",
            "requires_user_maintenance_precautions",
            "requires_installation_precautions",
            "has_protective_impedance",
            "has_tool_free_accessible_compartment",
            "pollution_degree",
            "requires_attended_operation",
            "has_base_ventilation_openings",
            "has_openable_filter_compartment",
        ]
        for key in keys:
            with self.subTest(key=key):
                feature = self.registry.get(key)
                self.assertTrue(feature.applicability_relevant)
                self.assertTrue(feature.report_extractable)


if __name__ == "__main__":
    unittest.main(verbosity=2)
