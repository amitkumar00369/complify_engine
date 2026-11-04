"""Tests for evidence-driven generic report product-profile extraction."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iec_par.generic_iec_feature_registry import CanonicalProductFeatureRegistry
from iec_par.generic_product_profile_models import (
    ProductFactStatus, ProductIdentityRole, ProductIdentityType, ProductProfile,
)
from iec_par.generic_report_product_profile_builder import (
    GenericReportProductProfileBuilder, ProfileDiagnosticCategory,
)


class GenericReportProductProfileBuilderTests(unittest.TestCase):
    def setUp(self): self.registry=CanonicalProductFeatureRegistry(); self.builder=GenericReportProductProfileBuilder(self.registry)
    def build(self,*pages): return self.builder.build_from_pages(list(pages),file_name="synthetic-report.pdf")
    def fact(self,profile,key): return profile.facts[key]

    # METADATA
    def test_01_report_number(self): self.assertEqual(self.build("Report No.: R-123\nText").source.report_number,"R-123")
    def test_02_report_date(self): self.assertEqual(self.build("Report No.: R\nDate of issue: 2026-01-02").source.report_date,"2026-01-02")
    def test_03_laboratory(self): self.assertEqual(self.build("Report No.: R\nTesting laboratory: Example Lab").source.laboratory,"Example Lab")
    def test_04_standard_numbers(self): self.assertEqual(self.build("Report No.: R\nIEC 61010-1:2020 and IEC 60204-1:2016").source.standard_numbers,["IEC 61010-1:2020","IEC 60204-1:2016"])
    def test_05_missing_metadata_safe(self): self.assertIsNone(self.build("Some report text").source.report_number)

    # IDENTITY
    def test_06_product_name(self): self.assertEqual(self.build("Report No.: R\nProduct: Generic appliance").identity.product_name,"Generic appliance")
    def test_07_manufacturer(self): self.assertEqual(self.build("Report No.: R\nManufacturer: Example Industries").identity.manufacturer,"Example Industries")
    def test_08_brand(self): self.assertEqual(self.build("Report No.: R\nBrand: EXAMPLE").identity.brand,"EXAMPLE")
    def test_09_one_model(self): self.assertEqual(self.build("Report No.: R\nModel No.: M-1").identity.model_numbers,["M-1"])
    def test_10_multiple_models(self): self.assertEqual(self.build("Report No.: R\nModel number: M-1, M-2").identity.model_numbers,["M-1","M-2"])
    def test_11_type_reference_separate(self):
        p=self.build("Report No.: R\nModel: M-1\nType reference: T-2"); self.assertEqual(p.identity.model_numbers,["M-1"]); self.assertEqual(p.identity.type_references,["T-2"])
    def test_12_serial_number(self): self.assertEqual(self.build("Report No.: R\nSerial No.: S-9").identity.serial_numbers,["S-9"])

    # BOOLEAN
    def test_13_positive_explicit_boolean(self):
        p=self.build("Report No.: R\nThe test item is provided with a timer."); self.assertIs(self.fact(p,"has_timer").value,True)
    def test_14_explicit_negative_boolean(self):
        p=self.build("Report No.: R\nThe test item is not provided with a heating element."); self.assertIs(self.fact(p,"has_heating_element").value,False)
    def test_15_absence_does_not_become_false(self): self.assertNotIn("has_heating_element",self.build("Report No.: R\nNo relevant description.").facts)

    # ENUM
    def test_16_class_i(self): self.assertEqual(self.fact(self.build("Report No.: R\nClassification: Class I"),"protection_class").value,"CLASS_I")
    def test_17_class_ii(self): self.assertEqual(self.fact(self.build("Report No.: R\nProtection class: Class II"),"protection_class").value,"CLASS_II")
    def test_18_type_y(self): self.assertEqual(self.fact(self.build("Report No.: R\nSupply connection: Type Y"),"attachment_type").value,"TYPE_Y")
    def test_19_invalid_enum_not_mapped(self): self.assertNotIn("protection_class",self.build("Report No.: R\nClassification: Class IX").facts)
    def test_20_front_loading(self): self.assertEqual(self.fact(self.build("Report No.: R\nLoading type: front loading"),"loading_type").value,"FRONT")
    def test_21_top_loading(self): self.assertEqual(self.fact(self.build("Report No.: R\nLoading type: top loaded"),"loading_type").value,"TOP")

    # MEASUREMENTS
    def test_22_rated_voltage(self): self.assertEqual(self.fact(self.build("Report No.: R\nRated voltage: 230 V"),"rated_voltage").value,{"value":230,"unit":"V"})
    def test_23_rated_frequency(self): self.assertEqual(self.fact(self.build("Report No.: R\nRated frequency: 50 Hz"),"rated_frequency").value,{"value":50,"unit":"Hz"})
    def test_24_rated_current(self): self.assertEqual(self.fact(self.build("Report No.: R\nRated current: 2.5 A"),"rated_current").value,{"value":2.5,"unit":"A"})
    def test_25_rated_power_input(self): self.assertEqual(self.fact(self.build("Report No.: R\nRated power input: 400 W"),"rated_power_input").value,{"value":400,"unit":"W"})
    def test_26_decimal_comma(self): self.assertEqual(self.fact(self.build("Report No.: R\nRated current: 2,5 A"),"rated_current").value["value"],2.5)
    def test_27_range_preserved_safely(self): self.assertEqual(self.fact(self.build("Report No.: R\nRated voltage: 220-240 V"),"rated_voltage").value,{"min":220,"max":240,"unit":"V"})

    # EVIDENCE
    def test_28_page_traceability(self): self.assertEqual(self.fact(self.build("Report No.: R","Rated voltage: 230 V"),"rated_voltage").evidence[0].page,2)
    def test_29_raw_text_preserved(self): self.assertIn("Rated voltage",self.fact(self.build("Report No.: R\nRated voltage: 230 V"),"rated_voltage").evidence[0].raw_text)
    def test_30_clause_id(self): self.assertEqual(self.fact(self.build("Report No.: R\n9\nThe test item is provided with a timer."),"has_timer").evidence[0].clause_id,"9")
    def test_31_deterministic_evidence_id(self): self.assertEqual(self.fact(self.build("Report No.: R\nRated voltage: 230 V"),"rated_voltage").evidence[0].evidence_id,self.fact(self.build("Report No.: R\nRated voltage: 230 V"),"rated_voltage").evidence[0].evidence_id)
    def test_32_multiple_evidence_records(self):
        p=self.build("Report No.: R\nThe test item is provided with a timer.","The product has a timer."); self.assertEqual(len(self.fact(p,"has_timer").evidence),2)

    # N/A
    def na_profile(self): return self.build("Report No.: R\n17\nTransformer not provided\nN/A")
    def test_33_explicit_absence_evidence_retained(self): self.assertIn("not provided",self.fact(self.na_profile(),"has_transformer").evidence[0].raw_text.casefold())
    def test_34_explicit_absence_sets_false_independently_of_na(self): self.assertIs(self.fact(self.na_profile(),"has_transformer").value,False)
    def test_35_explicit_absence_is_confirmed(self):
        f=self.fact(self.na_profile(),"has_transformer"); self.assertIs(f.status,ProductFactStatus.CONFIRMED); self.assertIs(f.value,False)

    # CONFLICT
    def test_36_conflicting_explicit_enum_values(self):
        f=self.fact(self.build("Report No.: R\nClassification: Class I","Protection class: Class II"),"protection_class"); self.assertIs(f.status,ProductFactStatus.CONFLICT); self.assertIsNone(f.value)
    def test_37_conflicting_boolean_evidence(self):
        f=self.fact(self.build("Report No.: R\nThe product has a timer.","The product is not provided with a timer."),"has_timer"); self.assertIs(f.status,ProductFactStatus.CONFLICT)

    # REGISTRY
    def test_38_all_output_features_exist(self):
        p=self.build("Report No.: R\nRated voltage: 230 V\nThe product has a timer."); self.assertTrue(all(self.registry.exists(k) for k in p.facts))
    def test_39_unknown_term_does_not_create_feature(self): self.assertEqual(self.build("Report No.: R\nNovel actuator: present").facts,{})
    def test_40_ambiguous_alias_safe(self):
        p=self.build("Report No.: R\nMotor capacitor not provided\nN/A"); self.assertNotIn("has_motor",p.facts); self.assertTrue(any(d.category is ProfileDiagnosticCategory.AMBIGUOUS_FEATURE_MAPPING for d in self.builder.get_diagnostics()))

    def test_negation_applies_to_feature_noun_not_its_component(self):
        self.assertNotIn("has_motor", self.build(
            "Report No.: R\nNo motor winding is open-circuited."
        ).facts)

    def test_direct_feature_negation_is_retained(self):
        self.assertFalse(self.fact(self.build(
            "Report No.: R\nNo motor is provided."
        ), "has_motor").value)

    def test_component_scoped_switch_negation_is_not_global(self):
        self.assertNotIn("has_switch", self.build(
            "Report No.: R\nThe cord is not fitted with a switch."
        ).facts)

    def test_test_state_does_not_become_feature_absence(self):
        self.assertNotIn("has_laser", self.build(
            "Report No.: R\nLaser test not performed."
        ).facts)

    def test_compact_product_specifications_are_structured(self):
        p = self.build(
            "Report No.: R\nProduct Specifications: 220-240 V~, 50/60 Hz, "
            "680 W, IPX0, n0: 0-3000/min, Chuck capacity: 13 mm"
        )
        self.assertEqual(self.fact(p, "rated_frequency").value,
                         {"min": 50, "max": 60, "unit": "Hz"})
        self.assertEqual(self.fact(p, "rated_power_input").value,
                         {"value": 680, "unit": "W"})
        self.assertEqual(self.fact(p, "ip_rating").value, "IPX0")
        self.assertEqual(self.fact(p, "no_load_speed").value,
                         {"min": 0, "max": 3000, "unit": "min-1"})
        self.assertEqual(self.fact(p, "tool_capacity").value,
                         {"value": 13, "unit": "mm"})

    # MODELS
    def test_41_multiple_model_numbers_again(self): self.assertEqual(len(self.build("Report No.: R\nModel: A-1; A-2").identity.model_numbers),2)
    def test_42_model_type_separation_again(self):
        i=self.build("Report No.: R\nModel: A-1\nType: B-2").identity; self.assertFalse(set(i.model_numbers)&set(i.type_references))
    def test_43_per_model_variation_diagnostic(self):
        self.build("Report No.: R\nModel: A-1, B-2\nModel A-1: Class I\nModel B-2: Class II"); self.assertTrue(any(d.category is ProfileDiagnosticCategory.PER_MODEL_VARIATION for d in self.builder.get_diagnostics()))

    # SERIALIZATION
    def test_44_deterministic_serialization(self):
        a=self.build("Report No.: R\nRated voltage: 230 V"); aj=self.builder.to_json(a); b=self.build("Report No.: R\nRated voltage: 230 V"); self.assertEqual(aj,self.builder.to_json(b))
    def test_45_round_trip(self):
        p=self.build("Report No.: R\nRated voltage: 230 V"); self.assertEqual(ProductProfile.from_dict(json.loads(self.builder.to_json(p))).to_dict(),p.to_dict())
    def test_46_enum_values_plain(self): self.assertNotIn("ProductFactStatus.",self.builder.to_json(self.build("Report No.: R\nRated voltage: 230 V")))

    # IMMUTABILITY / SAFETY
    def test_47_registry_unchanged(self):
        before=copy.deepcopy([vars(x) for x in self.registry.get_all()]); self.build("Report No.: R\nRated voltage: 230 V"); self.assertEqual(before,[vars(x) for x in self.registry.get_all()])
    def test_48_report_file_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"report.txt"; p.write_text("Report No.: R"); before=hashlib.sha256(p.read_bytes()).hexdigest(); self.builder.build_from_pages([p.read_text()],file_name=p.name); self.assertEqual(before,hashlib.sha256(p.read_bytes()).hexdigest())
    def test_49_no_effective_kb_modification(self):
        import iec_par.generic_report_product_profile_builder as module
        self.assertFalse(any("effective_kb" in name for name in vars(module)))
    def test_50_no_pass_fail_na_validation(self):
        p=self.build("Report No.: R\nClause result: FAIL"); data=self.builder.to_dict(p); self.assertNotIn("compliance",data); self.assertNotIn("result",data)

    def test_51_labels_first_pdf_table_identity(self):
        p=self.build("Report No.: R\nTest item ........:\nTrade Mark........\nwashing machine\nEXAMPLE")
        self.assertEqual(p.identity.product_name,"washing machine"); self.assertEqual(p.identity.brand,"EXAMPLE")

    def test_52_test_item_verdict_label_is_not_product_name(self):
        p=self.build("Report No.: R\nTest item does meet the requirement:\nP(Pass)")
        self.assertIsNone(p.identity.product_name)

    def test_53_labels_first_report_date_table(self):
        p=self.build("Date of Test:\nDate of Report:\nReport Number:\nApr.1.2026~Apr.2.2026\nApr.1.2026\nR-1")
        self.assertEqual(p.source.report_date,"Apr.1.2026")

    # STEP 31D IDENTITY / OBSERVATION ENRICHMENT
    def test_54_declared_model_observation(self):
        i=self.build("Report No.: R\nModel No.: AB-1").identity.product_identities[0];self.assertIs(i.role,ProductIdentityRole.DECLARED_MODEL)
    def test_55_declared_and_tested_models(self):
        p=self.build("Report No.: R\nModel: AB-1\nFull tests performed on model CD/2 and passed.");self.assertEqual({i.role for i in p.identity.product_identities},{ProductIdentityRole.DECLARED_MODEL,ProductIdentityRole.TESTED_MODEL})
    def test_56_same_value_different_roles_retained(self):
        p=self.build("Report No.: R\nModel: AB-1\nTested model: AB-1");self.assertEqual(len([i for i in p.identity.product_identities if i.value=="AB-1"]),2)
    def test_57_different_model_roles_retained(self):
        p=self.build("Report No.: R\nModel: AB-1\nTested model: CD-2");self.assertEqual({i.value for i in p.identity.product_identities},{"AB-1","CD-2"})
    def test_58_unknown_role_preserved(self):
        i=self.build("Report No.: R\nProduct designation: PX-7").identity.product_identities[0];self.assertIs(i.role,ProductIdentityRole.UNKNOWN_MODEL_ROLE)
    def test_59_type_reference_distinct(self):
        p=self.build("Report No.: R\nModel: M-1\nType reference: T/2");self.assertIn(ProductIdentityType.TYPE_REFERENCE,{i.identity_type for i in p.identity.product_identities})
    def test_60_sample_id_distinct(self):
        i=self.build("Report No.: R\nSample identification: SAMPLE-7").identity.product_identities[0];self.assertIs(i.identity_type,ProductIdentityType.SAMPLE_ID)
    def test_61_raw_and_normalized_identity(self):
        i=self.build("Report No.: R\nTested model: AB-1/2").identity.product_identities[0];self.assertEqual((i.value,i.normalized_value),("AB-1/2","AB-1/2"))
    def test_62_identity_provenance(self):
        i=self.build("Report No.: R","Tested model: AB-1").identity.product_identities[0];self.assertEqual(i.evidence[0].page,2);self.assertTrue(i.source_evidence_ids)
    def test_63_maximum_operating_depth(self):
        f=self.fact(self.build("Report No.: R\nMaximum operating depth: 12 m"),"maximum_operating_depth");self.assertEqual(f.value,{"value":12,"unit":"m"})
    def test_64_operating_depth_absent(self): self.assertNotIn("maximum_operating_depth",self.build("Report No.: R\nProduct: Generic device").facts)
    def test_65_na_depth_not_invented(self): self.assertNotIn("maximum_operating_depth",self.build("Report No.: R\nMaximum operating depth: N/A").facts)
    def test_66_fact_observation_retained(self):
        f=self.fact(self.build("Report No.: R\nRated voltage: 230 V"),"rated_voltage");self.assertEqual(f.observations[0].parameter,"rated_voltage");self.assertTrue(f.observations[0].evidence)
    def test_67_different_source_observations_retained(self):
        f=self.fact(self.build("Report No.: R\nRated voltage: 230 V","Rated voltage: 230 V"),"rated_voltage");self.assertEqual(len(f.observations),2)
    def test_68_identity_ids_deterministic(self):
        a=self.build("Report No.: R\nTested model: AB-1").identity.product_identities[0].identity_id;b=self.build("Report No.: R\nTested model: AB-1").identity.product_identities[0].identity_id;self.assertEqual(a,b)
    def test_69_no_mismatch_conclusion(self): self.assertNotIn("mismatch",self.builder.to_json(self.build("Report No.: R\nModel: A\nTested model: B")).casefold())
    def test_70_wrapped_multiple_models(self):
        p=self.build("Report No.: R\nModel/Type reference ........ :\nA-1；B/2；C-3\nRating ........ :\n230 V")
        self.assertEqual(p.identity.model_numbers,["A-1","B/2","C-3"])
    def test_71_all_tests_performed_model(self):
        p=self.build("Report No.: R\nModel: A-1; B-2\nAll tests are performed on the model A-1.")
        self.assertIn((ProductIdentityRole.TESTED_MODEL,"A-1"),{(i.role,i.value) for i in p.identity.product_identities})
    def test_72_source_supported_representative_role(self):
        p=self.build("Report No.: R\nModel: A-1; B-2\nAll tests are performed on model A-1. All models are same except colour.")
        self.assertIn(ProductIdentityRole.REPRESENTATIVE_MODEL,{i.role for i in p.identity.product_identities})
    def test_73_model_punctuation_retained(self):
        p=self.build("Report No.: R\nModel: AB/4-BU; XY_2")
        self.assertEqual(p.identity.model_numbers,["AB/4-BU","XY_2"])
    def test_74_unrelated_model_not_merged(self):
        p=self.build("Report No.: R\nModel: A-1\nSupplier model mentioned in note: Z-9")
        self.assertEqual(p.identity.model_numbers,["A-1"])


if __name__ == "__main__": unittest.main(verbosity=2)
