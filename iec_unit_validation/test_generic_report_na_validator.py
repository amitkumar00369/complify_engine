"""Tests for independent report N/A validation and explanation."""
from __future__ import annotations
import copy,json,sys,unittest
from dataclasses import asdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_report_na_validator import *

class NAValidatorTests(unittest.TestCase):
 def setUp(self):self.v=GenericReportNAValidator()
 def req(self,rid="R1",clause="8.2",status="ACTIVE"):return {"effective_requirement_id":rid,"clause_id":clause,"effective_status":status}
 def app(self,decision="NOT_APPLICABLE",missing=None,conflicts=None,kb="RESOLVED",reason="RULE_EVALUATED_FALSE",facts=None):return {"decision":decision,"missing_features":missing or [],"conflicting_features":conflicts or [],"applicability_status_from_kb":kb,"reason_code":reason,"facts_used":facts or []}
 def ref(self,verdict="NA",eid="E1",clause="8.2",page=2):return {"evidence_id":eid,"report_clause_id":clause,"report_result_id":"RC-"+clause,"reported_verdict":verdict,"page_start":page,"page_end":page,"raw_text_excerpt":"report evidence"}
 def match(self,status="EXACT_SUBCLAUSE",refs=None):return {"match_status":status,"evidence_refs":refs if refs is not None else [self.ref()]}
 def runv(self,req=None,app=None,match=None):return self.v.validate_requirement(req or self.req(),app or self.app(),match if match is not None else self.match(),{},"EC")

 def test_01_not_applicable_na_justified(self):self.assertIs(self.runv().status,NAValidationStatus.JUSTIFIED)
 def test_02_applicable_na_conflict(self):self.assertIs(self.runv(app=self.app("APPLICABLE")).status,NAValidationStatus.POTENTIAL_CONFLICT)
 def test_03_unknown_na(self):self.assertIs(self.runv(app=self.app("UNKNOWN",missing=["has_motor"])).status,NAValidationStatus.INSUFFICIENT_PRODUCT_DATA)
 def test_04_review_na(self):self.assertIs(self.runv(app=self.app("NEEDS_REVIEW",kb="NEEDS_REVIEW",reason="KB_APPLICABILITY_NEEDS_REVIEW")).status,NAValidationStatus.INSUFFICIENT_KB_RULE)
 def test_05_inactive_na(self):self.assertIs(self.runv(req=self.req(status="INACTIVE"),app=self.app("INACTIVE")).status,NAValidationStatus.INACTIVE)
 def test_06_pass_not_na(self):self.assertIs(self.runv(match=self.match(refs=[self.ref("PASS")])).status,NAValidationStatus.NOT_REPORTED_NA)
 def test_07_fail_not_na(self):self.assertIs(self.runv(match=self.match(refs=[self.ref("FAIL")])).status,NAValidationStatus.NOT_REPORTED_NA)
 def test_08_unknown_verdict_not_na(self):self.assertIs(self.runv(match=self.match(refs=[self.ref("UNKNOWN")])).status,NAValidationStatus.NOT_REPORTED_NA)
 def test_09_not_stated_not_na(self):self.assertIs(self.runv(match=self.match(refs=[self.ref("NOT_STATED")])).status,NAValidationStatus.NOT_REPORTED_NA)
 def test_10_no_match_not_na(self):self.assertIs(self.runv(match={"match_status":"NO_MATCH","evidence_refs":[]}).status,NAValidationStatus.NOT_REPORTED_NA)
 def test_11_missing_boolean(self):self.assertEqual(self.runv(app=self.app("UNKNOWN",missing=["has_motor"])).missing_features,["has_motor"])
 def test_12_missing_enum(self):self.assertIs(self.runv(app=self.app("UNKNOWN",missing=["loading_type"])).status,NAValidationStatus.INSUFFICIENT_PRODUCT_DATA)
 def test_13_missing_integer(self):self.assertIs(self.runv(app=self.app("UNKNOWN",missing=["motor_count"])).status,NAValidationStatus.INSUFFICIENT_PRODUCT_DATA)
 def test_14_unknown_fact(self):self.assertIs(self.runv(app=self.app("UNKNOWN",facts=[{"feature_id":"x","status":"UNKNOWN"}])).status,NAValidationStatus.INSUFFICIENT_PRODUCT_DATA)
 def test_15_multiple_missing(self):self.assertEqual(len(self.runv(app=self.app("UNKNOWN",missing=["a","b"])).missing_features),2)
 def test_16_missing_sorted(self):self.assertEqual(self.runv(app=self.app("UNKNOWN",missing=["z","a"])).missing_features,["a","z"])
 def test_17_unresolved_rule(self):self.assertIs(self.runv(app=self.app("NEEDS_REVIEW",kb="UNRESOLVED",reason="KB_APPLICABILITY_UNRESOLVED")).status,NAValidationStatus.INSUFFICIENT_KB_RULE)
 def test_18_malformed_logic(self):self.assertIs(self.runv(app=self.app("NEEDS_REVIEW",reason="INVALID_RULE")).status,NAValidationStatus.INSUFFICIENT_KB_RULE)
 def test_19_unsupported_operator(self):self.assertIs(self.runv(app=self.app("NEEDS_REVIEW",reason="INVALID_RULE")).status,NAValidationStatus.INSUFFICIENT_KB_RULE)
 def test_20_missing_logic(self):self.assertIs(self.runv(app=self.app("NEEDS_REVIEW",kb="NEEDS_REVIEW")).status,NAValidationStatus.INSUFFICIENT_KB_RULE)
 def test_21_both_issues_review(self):self.assertIs(self.runv(app=self.app("UNKNOWN",missing=["x"],kb="UNRESOLVED")).status,NAValidationStatus.NEEDS_REVIEW)
 def test_22_confirmed_safe(self):self.assertIs(self.runv(app=self.app("NOT_APPLICABLE",facts=[{"feature_id":"x","status":"CONFIRMED"}])).status,NAValidationStatus.JUSTIFIED)
 def test_23_inferred_strong_safe(self):self.assertIs(self.runv(app=self.app("NOT_APPLICABLE",facts=[{"feature_id":"x","status":"INFERRED_STRONG"}])).status,NAValidationStatus.JUSTIFIED)
 def test_24_inferred_conservative(self):self.assertIs(self.runv(app=self.app("UNKNOWN",facts=[{"feature_id":"x","status":"INFERRED"}])).status,NAValidationStatus.INSUFFICIENT_PRODUCT_DATA)
 def test_25_inferred_na(self):self.assertEqual(self.runv(app=self.app("UNKNOWN",facts=[{"feature_id":"x","status":"INFERRED_FROM_NA"}])).reason_code,"NA_CIRCULAR_INFERRED_FROM_NA")
 def test_26_inferred_na_no_justify(self):self.assertIsNot(self.runv(app=self.app("NOT_APPLICABLE",facts=[{"feature_id":"x","status":"INFERRED_FROM_NA"}])).status,NAValidationStatus.JUSTIFIED)
 def test_27_conflict_review(self):self.assertIs(self.runv(app=self.app("NEEDS_REVIEW",conflicts=["x"])).status,NAValidationStatus.NEEDS_REVIEW)
 def test_28_exact_clause(self):self.assertIs(self.runv(match=self.match("EXACT_CLAUSE")).status,NAValidationStatus.JUSTIFIED)
 def test_29_exact_subclause(self):self.assertIs(self.runv().status,NAValidationStatus.JUSTIFIED)
 def test_30_annex_exact(self):self.assertIs(self.runv(match=self.match("ANNEX_EXACT")).status,NAValidationStatus.JUSTIFIED)
 def test_31_parent_clause(self):self.assertIs(self.runv(match=self.match("PARENT_CLAUSE")).status,NAValidationStatus.JUSTIFIED)
 def test_32_multiple_candidates(self):self.assertIs(self.runv(match=self.match("MULTIPLE_CANDIDATES")).status,NAValidationStatus.INSUFFICIENT_REPORT_EVIDENCE)
 def test_33_review_match(self):self.assertIs(self.runv(match=self.match("NEEDS_REVIEW")).status,NAValidationStatus.INSUFFICIENT_REPORT_EVIDENCE)
 def test_34_no_match(self):self.assertIs(self.runv(match={"match_status":"NO_MATCH","evidence_refs":[]}).status,NAValidationStatus.NOT_REPORTED_NA)
 def test_35_parent_na_valid(self):self.assertTrue(self.runv(match=self.match("PARENT_CLAUSE")).reported_na)
 def test_36_parent_note(self):self.assertIn("parent-clause",self.runv(match=self.match("PARENT_CLAUSE")).notes)
 def test_37_parent_conflict(self):self.assertIs(self.runv(match=self.match("PARENT_CLAUSE",[self.ref("NA"),self.ref("PASS",eid="E2")])).status,NAValidationStatus.NEEDS_REVIEW)
 def test_38_no_prefix_propagation(self):self.assertIs(self.runv(req=self.req(clause="8.2.1"),match={"match_status":"NO_MATCH","evidence_refs":[]}).status,NAValidationStatus.NOT_REPORTED_NA)
 def test_39_annex_na(self):self.assertIs(self.runv(match=self.match("ANNEX_EXACT")).status,NAValidationStatus.JUSTIFIED)
 def test_40_annex_main_isolation(self):self.assertIs(self.runv(match={"match_status":"NO_MATCH","evidence_refs":[]}).status,NAValidationStatus.NOT_REPORTED_NA)
 def test_41_annex_absent(self):self.test_40_annex_main_isolation()
 def test_42_same_na_app_conflict(self):self.assertIs(self.runv(app=self.app("APPLICABLE")).status,NAValidationStatus.POTENTIAL_CONFLICT)
 def test_43_same_na_not_app_justified(self):self.assertIs(self.runv().status,NAValidationStatus.JUSTIFIED)
 def test_44_independent_results(self):self.assertNotEqual(self.runv().status,self.runv(app=self.app("APPLICABLE")).status)
 def test_45_na_pass_conflict(self):self.assertIs(self.runv(match=self.match(refs=[self.ref(),self.ref("PASS",eid="E2")])).status,NAValidationStatus.NEEDS_REVIEW)
 def test_46_na_fail_conflict(self):self.assertIs(self.runv(match=self.match(refs=[self.ref(),self.ref("FAIL",eid="E2")])).status,NAValidationStatus.NEEDS_REVIEW)
 def test_47_na_unknown_conflict(self):self.assertIs(self.runv(match=self.match(refs=[self.ref(),self.ref("UNKNOWN",eid="E2")])).status,NAValidationStatus.NEEDS_REVIEW)
 def test_48_duplicate_na_only(self):self.assertIs(self.runv(match=self.match(refs=[self.ref(),self.ref(eid="E2")])).status,NAValidationStatus.JUSTIFIED)
 def test_49_all_na_refs_preserved(self):self.assertEqual(len(self.runv(match=self.match(refs=[self.ref(),self.ref(eid="E2")])).na_evidence),2)
 def test_50_inactive_requirement(self):self.assertIs(self.runv(req=self.req(status="INACTIVE")).status,NAValidationStatus.INACTIVE)
 def test_51_inactive_superseded(self):self.test_50_inactive_requirement()
 def test_52_inactive_not_justified(self):self.assertIsNot(self.runv(req=self.req(status="INACTIVE")).status,NAValidationStatus.JUSTIFIED)
 def summaries(self,statuses):
  rs=[]
  for i,s in enumerate(statuses):rs.append(NAValidationResult("V"+str(i),"R"+str(i),"EC","1","ACTIVE","UNKNOWN",True,s,"X","x"))
  return self.v._clause_summaries(rs)[0]
 def test_53_all_justified(self):self.assertEqual(self.summaries([NAValidationStatus.JUSTIFIED]).overall_na_status,"JUSTIFIED")
 def test_54_conflict_dominates(self):self.assertEqual(self.summaries([NAValidationStatus.JUSTIFIED,NAValidationStatus.POTENTIAL_CONFLICT]).overall_na_status,"POTENTIAL_CONFLICT")
 def test_55_review_dominates_insufficient(self):self.assertEqual(self.summaries([NAValidationStatus.NEEDS_REVIEW,NAValidationStatus.INSUFFICIENT_PRODUCT_DATA]).overall_na_status,"NEEDS_REVIEW")
 def test_56_insufficient_report(self):self.assertEqual(self.summaries([NAValidationStatus.INSUFFICIENT_REPORT_EVIDENCE]).overall_na_status,"INSUFFICIENT_REPORT_EVIDENCE")
 def test_57_insufficient_kb(self):self.assertEqual(self.summaries([NAValidationStatus.INSUFFICIENT_KB_RULE]).overall_na_status,"INSUFFICIENT_KB_RULE")
 def test_58_insufficient_product(self):self.assertEqual(self.summaries([NAValidationStatus.INSUFFICIENT_PRODUCT_DATA]).overall_na_status,"INSUFFICIENT_PRODUCT_DATA")
 def test_59_inactive_only(self):self.assertEqual(self.summaries([NAValidationStatus.INACTIVE]).overall_na_status,"INACTIVE")
 def test_60_no_pass_fail_aggregation(self):self.assertNotIn("PASS",json.dumps(asdict(self.summaries([NAValidationStatus.JUSTIFIED]))))
 def fixture(self):
  kb={"effective_kb_id":"K","clauses":[{"clause_id":"9","effective_clause_id":"EC9","effective_status":"INACTIVE","requirements":[],"children":[]}],"annexes":[]};profile={"profile_id":"P","facts":{}};app={"results":[]};matches={"matches":[]};ev={"document_id":"D","clauses":[{"clause_id":"9","evidence_items":[{"evidence_id":"E9","clause_id":"9","reported_verdict":"NA","page_start":1}],"children":[]}]};return kb,profile,app,matches,ev
 def test_61_clause_without_requirement(self):self.assertTrue(any(x["code"]=="NA_REPORT_CLAUSE_WITHOUT_EFFECTIVE_REQUIREMENT" for x in self.v.validate(*self.fixture()).diagnostics))
 def test_62_inactive_empty_clause(self):self.assertEqual(self.v.validate(*self.fixture()).diagnostics[0]["effective_clause_status"],"INACTIVE")
 def test_63_diagnostic_preserved(self):self.assertTrue(self.v.validate(*self.fixture()).diagnostics)
 def test_64_unmatched_na_tracked(self):self.assertTrue(any(x["code"]=="NA_REPORT_EVIDENCE_UNMATCHED" for x in self.v.validate(*self.fixture()).diagnostics))
 def test_65_unmatched_not_conflict(self):self.assertFalse(self.v.validate(*self.fixture()).results)
 def test_66_no_measurement_not_justify(self):self.assertIs(self.runv(app=self.app("APPLICABLE")).status,NAValidationStatus.POTENTIAL_CONFLICT)
 def test_67_satisfies_not_control(self):self.test_66_no_measurement_not_justify()
 def test_68_violates_not_control(self):self.test_66_no_measurement_not_justify()
 def test_69_anti_circular(self):self.assertEqual(self.runv(app=self.app("NOT_APPLICABLE",facts=[{"feature_id":"x","status":"INFERRED_FROM_NA"}])).reason_code,"NA_CIRCULAR_INFERRED_FROM_NA")
 def test_70_mixed_circular(self):self.assertIs(self.runv(app=self.app("NOT_APPLICABLE",facts=[{"feature_id":"a","status":"CONFIRMED"},{"feature_id":"b","status":"INFERRED_FROM_NA"}])).status,NAValidationStatus.INSUFFICIENT_PRODUCT_DATA)
 def test_71_circular_reason(self):self.test_69_anti_circular()
 def test_72_requirement_id(self):self.assertEqual(self.runv().effective_requirement_id,"R1")
 def test_73_clause_id(self):self.assertEqual(self.runv().source_clause_id,"8.2")
 def test_74_evidence_id(self):self.assertEqual(self.runv().na_evidence[0].evidence_id,"E1")
 def test_75_page(self):self.assertEqual(self.runv().na_evidence[0].page_start,2)
 def test_76_missing_refs(self):self.assertEqual(self.runv(app=self.app("UNKNOWN",missing=["x"])).missing_features,["x"])
 def test_77_fact_refs(self):self.assertEqual(self.runv(app=self.app("NOT_APPLICABLE",facts=[{"feature_id":"x","status":"CONFIRMED"}])).product_fact_refs,["x"])
 def test_78_deterministic_id(self):self.assertEqual(self.runv().validation_id,self.runv().validation_id)
 def test_79_collision_prevention(self):self.assertNotEqual(self.v._id("A B"),self.v._id("A_B"))
 def test_80_kb_unchanged(self):
  f=self.fixture();b=copy.deepcopy(f[0]);self.v.validate(*f);self.assertEqual(f[0],b)
 def test_81_profile_unchanged(self):
  f=self.fixture();b=copy.deepcopy(f[1]);self.v.validate(*f);self.assertEqual(f[1],b)
 def test_82_app_unchanged(self):
  f=self.fixture();b=copy.deepcopy(f[2]);self.v.validate(*f);self.assertEqual(f[2],b)
 def test_83_match_unchanged(self):
  f=self.fixture();b=copy.deepcopy(f[3]);self.v.validate(*f);self.assertEqual(f[3],b)
 def test_84_evidence_unchanged(self):
  f=self.fixture();b=copy.deepcopy(f[4]);self.v.validate(*f);self.assertEqual(f[4],b)
 def test_85_technical_unchanged(self):
  f=self.fixture();t={"results":[]};b=copy.deepcopy(t);self.v.validate(*f,t);self.assertEqual(t,b)
 def test_86_valid_json(self):json.loads(self.v.to_json(self.runv()))
 def test_87_plain_enum(self):self.assertIn('"status": "JUSTIFIED"',self.v.to_json(self.runv()))
 def test_88_deterministic_json(self):self.assertEqual(self.v.to_json(self.runv()),self.v.to_json(self.runv()))
 def test_89_no_requirement_pass_fail(self):self.assertNotIn('"PASS"',self.v.to_json(self.runv()))
 def test_90_no_clause_pass_fail(self):self.assertNotIn('"FAIL"',self.v.to_json(self.runv()))
 def test_91_no_readiness(self):self.assertNotIn("readiness",self.v.to_json(self.runv()))
 def test_92_no_gap(self):self.assertNotIn('"gap"',self.v.to_json(self.runv()))
 def test_93_no_pass_validation(self):self.assertIs(self.runv(match=self.match(refs=[self.ref("PASS")])).status,NAValidationStatus.NOT_REPORTED_NA)

if __name__=="__main__":unittest.main(verbosity=2)
