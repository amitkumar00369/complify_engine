"""Tests for generic product-profile schemas and registry compatibility."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iec_par.generic_iec_feature_registry import CanonicalProductFeatureRegistry
from iec_par.generic_product_profile_models import (
    EvidenceSourceType, ProductFact, ProductFactEvidence, ProductFactStatus,
    ProductIdentity, ProductIdentityValue, ProductProfile, ProductProfileSource,
)


class ProductProfileModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = CanonicalProductFeatureRegistry()
        cls.boolean_feature = next(
            item for item in cls.registry.get_all() if item.data_type.value == "BOOLEAN"
        )
        cls.enum_feature = next(
            item for item in cls.registry.get_all() if item.data_type.value == "ENUM"
        )
        cls.measurement_feature = next(
            item for item in cls.registry.get_all() if item.data_type.value == "MEASUREMENT"
        )

    def evidence(self, evidence_id="EV-1", verdict=None):
        return ProductFactEvidence(
            evidence_id=evidence_id, source_type=EvidenceSourceType.REPORT_CLAUSE,
            source_document_id="REPORT-X", page=4, raw_text="Observed report text.",
            reported_verdict=verdict,
        )

    def test_01_empty_product_profile(self):
        profile=ProductProfile("PROFILE-1"); self.assertEqual(profile.facts,{})

    def test_02_confirmed_boolean_fact(self):
        fact=ProductFact(self.boolean_feature.key,True,ProductFactStatus.CONFIRMED)
        self.assertIs(fact.value,True)

    def test_03_confirmed_enum_fact(self):
        fact=ProductFact(self.enum_feature.key,self.enum_feature.allowed_values[0],ProductFactStatus.CONFIRMED)
        self.assertEqual(fact.status,ProductFactStatus.CONFIRMED)

    def test_04_measurement_compatible_value(self):
        fact=ProductFact(self.measurement_feature.key,{"value":230,"unit":self.measurement_feature.unit},ProductFactStatus.CONFIRMED)
        self.assertIsInstance(fact.value,dict)

    def test_05_unknown_fact_allows_none(self):
        self.assertIsNone(ProductFact(self.boolean_feature.key,None,ProductFactStatus.UNKNOWN).value)

    def test_06_inferred_fact(self):
        self.assertEqual(ProductFact(self.boolean_feature.key,True,ProductFactStatus.INFERRED,.6).confidence,.6)

    def test_07_inferred_strong_fact(self):
        self.assertIs(ProductFact(self.boolean_feature.key,True,ProductFactStatus.INFERRED_STRONG).status,ProductFactStatus.INFERRED_STRONG)

    def test_08_inferred_from_na_none(self):
        fact=ProductFact(self.boolean_feature.key,None,ProductFactStatus.INFERRED_FROM_NA,.5)
        self.assertIsNone(fact.value)

    def test_09_conflict_without_chosen_value(self):
        self.assertIsNone(ProductFact(self.boolean_feature.key,None,ProductFactStatus.CONFLICT).value)

    def test_10_multiple_evidence_records(self):
        fact=ProductFact(self.boolean_feature.key,True,ProductFactStatus.CONFIRMED,evidence=[self.evidence(),self.evidence("EV-2")])
        self.assertEqual(len(fact.evidence),2)

    def test_11_model_number_and_type_reference_separate(self):
        identity=ProductIdentity(model_numbers=["MODEL-X"],type_references=["TYPE-Y"])
        self.assertNotEqual(identity.model_numbers,identity.type_references)

    def test_12_identity_mutable_default_isolation(self):
        first=ProductIdentity(); second=ProductIdentity(); first.model_numbers.append("X")
        self.assertEqual(second.model_numbers,[])

    def test_13_fact_evidence_mutable_default_isolation(self):
        first=ProductFact("a",None,ProductFactStatus.UNKNOWN); second=ProductFact("b",None,ProductFactStatus.UNKNOWN); first.evidence.append(self.evidence())
        self.assertEqual(second.evidence,[])

    def test_14_profile_mutable_default_isolation(self):
        first=ProductProfile("1"); second=ProductProfile("2"); first.unknown_features.append("x")
        self.assertEqual(second.unknown_features,[])

    def test_15_invalid_confidence_below_zero(self):
        with self.assertRaises(ValueError): ProductFact("x",None,ProductFactStatus.UNKNOWN,-.1)

    def test_16_invalid_confidence_above_one(self):
        with self.assertRaises(ValueError): ProductFact("x",None,ProductFactStatus.UNKNOWN,1.1)

    def test_17_fact_dictionary_key_mismatch(self):
        with self.assertRaises(ValueError): ProductProfile("1",facts={"wrong":ProductFact("right",None,ProductFactStatus.UNKNOWN)})

    def test_18_duplicate_evidence_ids(self):
        with self.assertRaises(ValueError): ProductFact("x",None,ProductFactStatus.UNKNOWN,evidence=[self.evidence(),self.evidence()])

    def test_19_valid_canonical_registry_feature(self):
        fact=ProductFact(self.boolean_feature.key,True,ProductFactStatus.CONFIRMED); profile=ProductProfile("1",facts={fact.feature_id:fact})
        self.assertEqual(profile.validate_against_registry(self.registry),[])

    def test_20_invalid_unregistered_feature(self):
        fact=ProductFact("not_registered_feature",None,ProductFactStatus.UNKNOWN); profile=ProductProfile("1",facts={fact.feature_id:fact})
        self.assertEqual(profile.validate_against_registry(self.registry),["not_registered_feature"])

    def test_21_invalid_feature_controlled_error(self):
        fact=ProductFact("not_registered_feature",None,ProductFactStatus.UNKNOWN); profile=ProductProfile("1",facts={fact.feature_id:fact})
        with self.assertRaises(ValueError): profile.validate_against_registry(self.registry,raise_on_error=True)

    def test_22_deterministic_serialization(self):
        fact=ProductFact(self.boolean_feature.key,True,ProductFactStatus.CONFIRMED)
        first=ProductProfile("1",facts={fact.feature_id:fact}); second=ProductProfile("1",facts={fact.feature_id:fact})
        self.assertEqual(first.to_json(),second.to_json())

    def test_23_enum_serialization(self):
        fact=ProductFact(self.boolean_feature.key,True,ProductFactStatus.CONFIRMED,evidence=[self.evidence()])
        data=json.loads(ProductProfile("1",facts={fact.feature_id:fact}).to_json())
        self.assertEqual(data["facts"][fact.feature_id]["status"],"CONFIRMED")
        self.assertEqual(data["facts"][fact.feature_id]["evidence"][0]["source_type"],"REPORT_CLAUSE")

    def test_24_round_trip_serialization(self):
        fact=ProductFact(self.boolean_feature.key,True,ProductFactStatus.CONFIRMED,.9,[self.evidence()])
        original=ProductProfile("1",ProductIdentity(model_numbers=["M"]),ProductProfileSource(document_id="D"),{fact.feature_id:fact})
        self.assertEqual(ProductProfile.from_dict(json.loads(original.to_json())).to_dict(),original.to_dict())

    def test_25_na_evidence_does_not_imply_false(self):
        evidence=self.evidence(verdict="N/A")
        fact=ProductFact(self.boolean_feature.key,None,ProductFactStatus.INFERRED_FROM_NA,.5,[evidence])
        data=json.loads(ProductProfile("1",facts={fact.feature_id:fact}).to_json())
        self.assertEqual(data["facts"][fact.feature_id]["evidence"][0]["reported_verdict"],"N/A")
        self.assertIsNone(data["facts"][fact.feature_id]["value"])

    def test_26_source_lists_isolated(self):
        first=ProductProfileSource(); second=ProductProfileSource(); first.standard_numbers.append("IEC X")
        self.assertEqual(second.standard_numbers,[])

    def test_27_conflicting_features_isolated(self):
        first=ProductProfile("1"); second=ProductProfile("2"); first.conflicting_features.append("x")
        self.assertEqual(second.conflicting_features,[])

    def test_28_sample_identifiers_optional(self):
        self.assertEqual(ProductIdentity().sample_identifiers, [])

    def test_29_rich_sample_identifier(self):
        value=ProductIdentityValue("SAMPLE-X",EvidenceSourceType.REPORT_METADATA,"EV",1,1,.9,ProductFactStatus.CONFIRMED)
        self.assertEqual(ProductIdentity(sample_identifiers=[value]).sample_identifiers[0].value,"SAMPLE-X")

    def test_30_old_serial_string_compatible(self):
        profile=ProductProfile.from_dict({"profile_id":"P","identity":{"serial_numbers":["SERIAL-X"]}})
        self.assertEqual(profile.identity.serial_numbers,["SERIAL-X"])

    def test_31_rich_serial_round_trip(self):
        value=ProductIdentityValue("SERIAL-X",status=ProductFactStatus.CONFIRMED)
        profile=ProductProfile("P",identity=ProductIdentity(serial_numbers=[value]))
        self.assertEqual(ProductProfile.from_dict(json.loads(profile.to_json())).to_dict(),profile.to_dict())

    def test_32_identity_types_not_merged(self):
        identity=ProductIdentity(model_numbers=["M"],type_references=["T"],serial_numbers=["S"],sample_identifiers=[ProductIdentityValue("I")])
        self.assertEqual((identity.model_numbers,identity.type_references,identity.serial_numbers,identity.sample_identifiers[0].value),(["M"],["T"],["S"],"I"))

    def test_33_identity_defaults_isolated(self):
        first=ProductIdentity();second=ProductIdentity();first.sample_identifiers.append(ProductIdentityValue("X"));self.assertEqual(second.sample_identifiers,[])

    def test_34_identity_confidence_validation(self):
        with self.assertRaises(ValueError):ProductIdentityValue("X",confidence=2)


if __name__ == "__main__": unittest.main(verbosity=2)
