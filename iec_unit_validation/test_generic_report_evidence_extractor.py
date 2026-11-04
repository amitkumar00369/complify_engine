"""Tests for generic report clause and evidence extraction."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from iec_par.generic_report_evidence_extractor import GenericReportEvidenceExtractor
from iec_par.generic_report_evidence_models import ReportEvidenceDocument, ReportedVerdict


class GenericReportEvidenceExtractorTests(unittest.TestCase):
    def setUp(self): self.e=GenericReportEvidenceExtractor()
    def doc(self,*pages): return self.e.extract_from_pages(pages,file_name="report.pdf")
    def flat(self,d):
        out=[]
        def walk(xs):
            for x in xs: out.append(x); walk(x.children)
        walk(d.clauses); return out
    def clause(self,d,key): return next(x for x in self.flat(d) if x.clause_id==key)
    def measured(self,text): return self.clause(self.doc("1\n"+text+"\nP"),"1").measurements

    # VERDICTS
    def test_01_p(self): self.assertIs(self.e.normalize_verdict("P"),ReportedVerdict.PASS)
    def test_02_pass(self): self.assertIs(self.e.normalize_verdict("PASS"),ReportedVerdict.PASS)
    def test_03_f(self): self.assertIs(self.e.normalize_verdict("F"),ReportedVerdict.FAIL)
    def test_04_fail(self): self.assertIs(self.e.normalize_verdict("FAIL"),ReportedVerdict.FAIL)
    def test_05_n_slash_a(self): self.assertIs(self.e.normalize_verdict("N/A"),ReportedVerdict.NA)
    def test_06_na(self): self.assertIs(self.e.normalize_verdict("NA"),ReportedVerdict.NA)
    def test_07_n_dot_a(self): self.assertIs(self.e.normalize_verdict("N.A."),ReportedVerdict.NA)
    def test_08_not_applicable(self): self.assertIs(self.e.normalize_verdict("Not applicable"),ReportedVerdict.NA)
    def test_09_blank(self): self.assertIs(self.e.normalize_verdict(""),ReportedVerdict.NOT_STATED)
    def test_10_random_p_not_verdict(self): self.assertIs(self.e.normalize_verdict("P",result_context=False),ReportedVerdict.UNKNOWN)

    # CLAUSE IDS
    def test_11_clause_7(self): self.assertTrue(self.e.is_clause_id("7"))
    def test_12_clause_7_1(self): self.assertTrue(self.e.is_clause_id("7.1"))
    def test_13_clause_19_11_4(self): self.assertTrue(self.e.is_clause_id("19.11.4"))
    def test_14_clause_20_101(self): self.assertTrue(self.e.is_clause_id("20.101"))
    def test_15_iec_not_clause(self): self.assertFalse(self.e.is_clause_id("IEC 60335-1"))
    def test_16_voltage_not_clause(self): self.assertFalse(self.e.is_clause_id("240 V"))
    def test_17_date_not_clause(self): self.assertFalse(self.e.is_clause_id("2026-04-10"))

    # CLAUSE CONTENT
    def test_18_single_clause(self): self.assertEqual(len(self.flat(self.doc("7.1\nRequirement\nP"))),1)
    def test_19_multiline_clause(self): self.assertIn("second line",self.clause(self.doc("7.1\nfirst line\nsecond line\nP"),"7.1").raw_text)
    def test_20_continuation_lines(self): self.assertIn("continued",self.clause(self.doc("7.1\ntext","continued\nP"),"7.1").raw_text)
    def test_21_next_clause_boundary(self):
        d=self.doc("7.1\nfirst\nP\n7.2\nsecond\nN/A"); self.assertNotIn("second",self.clause(d,"7.1").raw_text)
    def test_22_source_order(self):
        d=self.doc("7.1\na\nP\n7.2\nb\nP"); self.assertLess(self.clause(d,"7.1").source_order,self.clause(d,"7.2").source_order)

    # MEASUREMENTS
    def test_23_milliamps(self): self.assertEqual(self.measured("Measured leakage current: 1.2 mA")[0].value,1.2)
    def test_24_decimal_comma_flow(self): self.assertEqual(self.measured("Observed flow: 0,5 L/min")[0].value,.5)
    def test_25_voltage(self): self.assertEqual(self.measured("Test voltage: 240 V")[0].unit_normalized,"V")
    def test_26_frequency(self): self.assertEqual(self.measured("Measured frequency: 50 Hz")[0].value,50)
    def test_27_temperature_rise(self): self.assertEqual(self.measured("Observed temperature rise: 32 K")[0].unit,"K")
    def test_28_speed(self): self.assertEqual(self.measured("Measured drum speed: 45 r/min")[0].unit_normalized,"r/min")
    def test_29_force(self): self.assertEqual(self.measured("Applied test force: 15 N")[0].value,15)
    def test_30_distance(self): self.assertEqual(self.measured("Measured distance: 25 mm")[0].value,25)
    def test_31_time(self): self.assertEqual(self.measured("Test duration: 5 s")[0].value,5)
    def test_32_decimal_comma_normalized(self): self.assertIsInstance(self.measured("Measured value: 0,5 mA")[0].value,float)
    def test_33_unit_normalization(self): self.assertEqual(self.measured("Observed flow: 1 l/min")[0].unit_normalized,"L/min")

    # SAFETY
    def test_34_limit_not_measurement(self): self.assertEqual(self.measured("Leakage current shall not exceed 3.5 mA"),[])
    def test_35_copied_requirement_not_measurement(self): self.assertEqual(self.measured("Requirement: voltage must be 240 V"),[])
    def test_36_iec_not_measurement(self): self.assertEqual(self.measured("Standard IEC 60335-1"),[])
    def test_37_clause_reference_not_measurement(self): self.assertEqual(self.measured("See clause 7.1"),[])

    # N/A
    def test_38_na_retained(self): self.assertIs(self.clause(self.doc("19.9\nText\nN/A"),"19.9").reported_verdict,ReportedVerdict.NA)
    def test_39_no_feature_inference(self): self.assertNotIn("feature",self.e.to_dict(self.doc("1\nN/A")))
    def test_40_no_applicability_decision(self): self.assertNotIn("decision",self.e.to_json(self.doc("1\nN/A")).casefold())
    def test_41_no_false_value(self): self.assertNotIn('"value": false',self.e.to_json(self.doc("1\nN/A")).casefold())

    # PASS / FAIL
    def test_42_pass_report_only(self): self.assertIs(self.clause(self.doc("1\nP"),"1").reported_verdict,ReportedVerdict.PASS)
    def test_43_no_compliance_evaluation(self): self.assertNotIn("compliance",self.e.to_json(self.doc("1\nP")).casefold())
    def test_44_fail_report_only(self): self.assertIs(self.clause(self.doc("1\nFAIL"),"1").reported_verdict,ReportedVerdict.FAIL)

    # REMARKS
    def test_45_remark_extraction(self): self.assertIn("See remark 2",self.clause(self.doc("1\nSee remark 2\nP"),"1").remarks)
    def test_46_table_reference(self): self.assertEqual(self.clause(self.doc("1\nSee table 3\nP"),"1").evidence_items[0].table_reference,"Table 3")
    def test_47_inspection_remark(self): self.assertIn("Complies by inspection",self.clause(self.doc("1\nComplies by inspection\nP"),"1").remarks)

    # DUPLICATES
    def test_48_repeated_clause_combined(self): self.assertEqual(len(self.clause(self.doc("1\na\nP\n2\nb\nP\n1\nc\nP"),"1").evidence_items),2)
    def test_49_duplicate_no_evidence_loss(self):
        c=self.clause(self.doc("1\na\nP\n2\nb\nP\n1\nc\nP"),"1"); self.assertIn("a",c.raw_text); self.assertIn("c",c.raw_text)

    # HIERARCHY
    def test_50_explicit_parent_child(self): self.assertEqual(self.doc("7\nTitle\n7.1\nText\nP").clauses[0].children[0].clause_id,"7.1")
    def test_51_no_synthetic_parent(self): self.assertEqual(self.doc("7.1\nText\nP").clauses[0].clause_id,"7.1")

    # SERIALIZATION
    def test_52_deterministic_ids(self): self.assertEqual(self.clause(self.doc("7.1\nP"),"7.1").result_id,self.clause(self.doc("7.1\nP"),"7.1").result_id)
    def test_53_deterministic_json(self):
        a=self.e.to_json(self.doc("1\nP")); b=self.e.to_json(self.doc("1\nP")); self.assertEqual(a,b)
    def test_54_plain_enum(self): self.assertIn('"reported_verdict": "PASS"',self.e.to_json(self.doc("1\nP")))
    def test_55_round_trip(self):
        d=self.doc("1\nMeasured voltage: 240 V\nP"); self.assertEqual(ReportEvidenceDocument.from_dict(json.loads(self.e.to_json(d))).to_dict(),d.to_dict())

    # IMMUTABILITY
    def test_56_report_file_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"r.txt"; p.write_text("1\nP"); before=hashlib.sha256(p.read_bytes()).hexdigest(); self.e.extract_from_pages([p.read_text()],file_name=p.name); self.assertEqual(before,hashlib.sha256(p.read_bytes()).hexdigest())
    def test_57_product_profile_not_imported(self):
        import iec_par.generic_report_evidence_extractor as m; self.assertFalse(any("ProductProfile" in str(v) for v in vars(m).values()))
    def test_58_effective_kb_not_imported(self):
        import iec_par.generic_report_evidence_extractor as m; self.assertFalse(any("effective_kb" in k.casefold() for k in vars(m)))

    # DIAGNOSTICS
    def test_59_ambiguous_verdict(self): self.assertTrue(any(d["code"]=="REPORT_VERDICT_AMBIGUOUS" for d in self.doc("1\nP\nN/A").diagnostics))
    def test_60_ambiguous_measurement(self): self.assertTrue(any(d["code"]=="REPORT_MEASUREMENT_AMBIGUOUS" for d in self.doc("1\nMeasured value: 1.2 mA or 1.3 mA\nP").diagnostics))
    def test_61_unmapped_section(self): self.assertEqual(len(self.doc("Metadata only").unmapped_sections),1)
    def test_62_per_model_variation(self): self.assertTrue(any(d["code"]=="PER_MODEL_RESULT_VARIATION" for d in self.doc("1\nModel A: P\nModel B: F").diagnostics))

    # NO SCOPE CREEP
    def test_63_no_engine_pass_fail(self): self.assertNotIn("engine",self.e.to_json(self.doc("1\nP")))
    def test_64_no_na_validation(self): self.assertNotIn("correct",self.e.to_json(self.doc("1\nN/A")).casefold())
    def test_65_no_applicability_evaluation(self): self.assertNotIn("applicability",self.e.to_json(self.doc("1\nP")).casefold())
    def test_66_no_constraint_comparison(self): self.assertNotIn("constraint",self.e.to_json(self.doc("1\nMeasured voltage: 240 V\nP")).casefold())

    # STEP 31B STRUCTURAL REGRESSIONS
    def test_67_row_pass_preserved(self): self.assertIs(self.clause(self.doc("6.2\nRequirement row\nP\nOther row\nN/A"),"6.2").reported_verdict,ReportedVerdict.PASS)
    def test_68_missing_verdict_unknown_or_not_stated(self): self.assertIn(self.clause(self.doc("6.2\nRequirement row"),"6.2").reported_verdict,{ReportedVerdict.UNKNOWN,ReportedVerdict.NOT_STATED})
    def test_69_incidental_p_not_pass(self): self.assertIsNot(self.clause(self.doc("6.2\nPump construction"),"6.2").reported_verdict,ReportedVerdict.PASS)
    def test_70_page_header_number_not_clause(self): self.assertNotIn("96",[x.clause_id for x in self.flat(self.doc("96\nP\nTRF No.: X\nPage 6 of 88\n6.2\nRequirement\nP"))])
    def test_71_table_row_number_not_clause(self): self.assertNotIn("75",[x.clause_id for x in self.flat(self.doc("6.2\nTABLE: results\n75\n125\nP"))])
    def test_72_deep_boundary(self): self.assertEqual(self.clause(self.doc("19.11.4.2\nRequirement\nP"),"19.11.4.2").clause_id,"19.11.4.2")
    def test_73_table_child_link(self):
        item=self.clause(self.doc("16.2\nSee appended table\nP\nTABLE: leakage current\nMeasured current: 0.2 mA\nP"),"16.2").evidence_items;self.assertTrue(item[0].child_evidence_ids);self.assertEqual(item[1].parent_evidence_id,item[0].evidence_id);self.assertEqual(item[1].clause_id,"16.2")
    def test_74_multiple_tables_distinct(self):
        items=self.clause(self.doc("16.2\nSee appended table\nP\nTABLE: one\nP\nTABLE: two\nP"),"16.2").evidence_items;self.assertEqual(len({x.evidence_id for x in items}),3)
    def test_75_table_continuation_header_not_clause(self): self.assertNotIn("44",[x.clause_id for x in self.flat(self.doc("16.2\nTABLE: result","44\nTRF No.: X\nPage 44 of 80\ncontinued\nP"))])
    def test_76_duplicate_ids_absent(self):
        d=self.doc("1\nTABLE: one\nP\n2\nTABLE: two\nP");ids=[e.evidence_id for c in self.flat(d) for e in c.evidence_items];self.assertEqual(len(ids),len(set(ids)))
    def test_77_raw_verdict_preserved(self): self.assertEqual(self.clause(self.doc("6.2\nRequirement\nPASS"),"6.2").evidence_items[0].raw_verdict_text,"PASS")
    def test_78_no_fixture_branch(self):
        source=Path(__file__).parents[1].joinpath("iec_par/generic_report_evidence_extractor.py").read_text().casefold()
        for value in ("submersible","washing machine","60335","report-ev-96-001","clause_id == \"6.2\""):self.assertNotIn(value,source)
    def test_79_appended_table_value_label_not_clause(self):
        d=self.doc("14\nTABLE: heating test\nThermocouple locations\n35\nEnclosure inside\n15.5\nFor another row")
        self.assertEqual([x.clause_id for x in self.flat(d)],["14"])
    def test_80_labelled_table_clause_in_table_region_preserved(self):
        d=self.doc("14\nTABLE: first\nvalues\n16.2\nTABLE: leakage current\nP")
        self.assertIn("16.2",[x.clause_id for x in self.flat(d)])
    def test_81_table_value_on_continuation_page_not_clause(self):
        d=self.doc("14\nTABLE: heating test\nvalues","continued rows\n1.2\nEnclosure\n3.92\nClass II")
        self.assertEqual([x.clause_id for x in self.flat(d)],["14"])


if __name__=="__main__": unittest.main(verbosity=2)
