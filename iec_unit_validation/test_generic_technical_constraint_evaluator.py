"""Tests for measurement-only technical constraint evaluation."""
from __future__ import annotations
import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_technical_constraint_evaluator import *

class TechnicalConstraintEvaluatorTests(unittest.TestCase):
 def setUp(self):self.e=GenericTechnicalConstraintEvaluator()
 def req(self,status="ACTIVE"):return {"effective_requirement_id":"ER-1","clause_id":"1","effective_status":status}
 def con(self,op="less_than_or_equal",value=10,unit="mA",parameter="leakage_current",ctype="CURRENT_LIMIT",status="RESOLVED",secondary=None,expression=None,tolerance=None):return {"constraint_id":"C1","parameter":parameter,"parameter_text":parameter.replace("_"," "),"operator":op,"value":value,"value_secondary":secondary,"unit":unit,"unit_normalized":unit,"constraint_type":ctype,"status":status,"expression":expression,"tolerance":tolerance,"condition_text":None,"raw_text":"constraint"}
 def meas(self,value=5,unit="mA",parameter="leakage_current",role="OBSERVED_VALUE",mid="M1",page=1):return {"measurement_id":mid,"parameter":parameter,"parameter_text":parameter.replace("_"," "),"value":value,"value_secondary":None,"unit":unit,"unit_normalized":unit,"raw_text":"measurement","page":page,"notes":"Measurement role: "+role}
 def evalc(self,c=None,ms=None,app="APPLICABLE",status="ACTIVE",facts=None,match=True):
  ms=ms or []; idx={m["measurement_id"]:m for m in ms}; mat={"evidence_refs":[{"measurement_ids":list(idx)}]} if match else None
  return self.e.evaluate_constraint(self.req(status),c or self.con(),app,mat,idx,facts or {},"EC")

 def test_01_inactive(self):self.assertIs(self.evalc(status="INACTIVE").decision,TechnicalConstraintDecision.INACTIVE)
 def test_02_not_applicable(self):self.assertIs(self.evalc(app="NOT_APPLICABLE").decision,TechnicalConstraintDecision.NOT_APPLICABLE)
 def test_03_app_unknown(self):self.assertIs(self.evalc(app="UNKNOWN").decision,TechnicalConstraintDecision.UNKNOWN)
 def test_04_app_review(self):self.assertIs(self.evalc(app="NEEDS_REVIEW").decision,TechnicalConstraintDecision.NEEDS_REVIEW)
 def test_05_applicable_proceeds(self):self.assertIs(self.evalc(ms=[self.meas()]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_06_le_pass(self):self.assertIs(self.evalc(ms=[self.meas(10)]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_07_le_fail(self):self.assertIs(self.evalc(ms=[self.meas(11)]).decision,TechnicalConstraintDecision.VIOLATES)
 def test_08_lt_pass(self):self.assertIs(self.evalc(self.con("less_than"),[self.meas(9)]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_09_gt_pass(self):self.assertIs(self.evalc(self.con("greater_than"),[self.meas(11)]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_10_ge_fail(self):self.assertIs(self.evalc(self.con("greater_than_or_equal"),[self.meas(9)]).decision,TechnicalConstraintDecision.VIOLATES)
 def test_11_equals(self):self.assertIs(self.evalc(self.con("equals"),[self.meas(10)]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_12_not_equals(self):self.assertIs(self.evalc(self.con("not_equals"),[self.meas(9)]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_13_between_pass(self):self.assertIs(self.evalc(self.con("between",5,secondary=10),[self.meas(7)]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_14_between_fail(self):self.assertIs(self.evalc(self.con("between",5,secondary=10),[self.meas(12)]).decision,TechnicalConstraintDecision.VIOLATES)
 def test_15_not_between(self):self.assertIs(self.evalc(self.con("not_between",5,secondary=10),[self.meas(12)]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_16_a_to_ma(self):self.assertIs(self.evalc(self.con(value=1000),[self.meas(1,"A")]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_17_ma_to_a(self):self.assertIs(self.evalc(self.con(value=1,unit="A"),[self.meas(1000,"mA")]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_18_kv_to_v(self):self.assertIs(self.evalc(self.con(value=1000,unit="V",parameter="voltage"),[self.meas(1,"kV","voltage")]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_19_w_to_kw(self):self.assertIs(self.evalc(self.con(value=1,unit="kW",parameter="power_input"),[self.meas(1000,"W","power_input")]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_20_mm_to_cm(self):self.assertIs(self.evalc(self.con(value=1,unit="cm",parameter="opening_distance"),[self.meas(10,"mm","opening_distance")]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_21_flow_conversion(self):self.assertIs(self.evalc(self.con(value=1000,unit="mL/min",parameter="water_flow_rate"),[self.meas(1,"L/min","water_flow_rate")]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_22_time_conversion(self):self.assertIs(self.evalc(self.con(value=1,unit="min",parameter="test_duration"),[self.meas(60,"s","test_duration")]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_23_incompatible_units(self):self.assertIs(self.evalc(ms=[self.meas(5,"V")]).decision,TechnicalConstraintDecision.INCOMPARABLE)
 def test_24_k_not_c(self):self.assertIs(self.evalc(self.con(unit="°C",parameter="temperature"),[self.meas(10,"K","temperature")]).decision,TechnicalConstraintDecision.INCOMPARABLE)
 def test_25_exact_parameter(self):self.assertIs(self.evalc(ms=[self.meas()]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_26_text_alias(self):self.assertIs(self.evalc(self.con(parameter="water_flow_rate"),[self.meas(5,"mA","flow of water")]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_27_parameter_mismatch(self):self.assertEqual(self.evalc(ms=[self.meas(parameter="drum_speed")]).reason_code,"TECH_PARAMETER_MISMATCH")
 def test_28_observed_accepted(self):self.assertIs(self.evalc(ms=[self.meas(role="OBSERVED_VALUE")]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_29_test_parameter_rejected_for_limit(self):self.assertIs(self.evalc(ms=[self.meas(role="TEST_PARAMETER")]).decision,TechnicalConstraintDecision.INCOMPARABLE)
 def test_30_reference_rejected(self):self.assertIs(self.evalc(ms=[self.meas(role="REFERENCE_VALUE")]).decision,TechnicalConstraintDecision.INCOMPARABLE)
 def test_31_unknown_role(self):self.assertIs(self.evalc(ms=[self.meas(role="UNKNOWN")]).decision,TechnicalConstraintDecision.INCOMPARABLE)
 def test_32_pass_no_value(self):self.assertIs(self.evalc(ms=[]).decision,TechnicalConstraintDecision.NO_MEASUREMENT)
 def test_33_na_applicable_no_value(self):self.assertIs(self.evalc(ms=[]).decision,TechnicalConstraintDecision.NO_MEASUREMENT)
 def test_34_max_worst_case(self):self.assertIs(self.evalc(ms=[self.meas(9,mid="A"),self.meas(11,mid="B")]).decision,TechnicalConstraintDecision.VIOLATES)
 def test_35_min_worst_case(self):self.assertIs(self.evalc(self.con("greater_than_or_equal"),[self.meas(11,mid="A"),self.meas(9,mid="B")]).decision,TechnicalConstraintDecision.VIOLATES)
 def test_36_ambiguous_context(self):self.assertIs(self.evalc(ms=[self.meas(9,mid="A",page=1),self.meas(11,mid="B",page=2)]).decision,TechnicalConstraintDecision.NEEDS_REVIEW)
 def formula(self):return {"selection":"MAX","operands":[{"type":"CONSTANT","value":3.5,"unit":"mA"},{"type":"FORMULA","coefficient":1,"coefficient_unit":"mA/kW","variable":"rated_power_input","cap":{"operator":"less_than_or_equal","value":5,"unit":"mA"}}]}
 def fc(self):return self.con(value=None,ctype="FORMULA",expression=self.formula())
 def fact(self,v,status="CONFIRMED",unit="W"):return {"value":{"value":v,"unit":unit},"status":status}
 def test_37_formula_400w(self):self.assertEqual(self.evalc(self.fc(),[self.meas(3)],facts={"rated_power_input":self.fact(400)}).computed_limit,3.5)
 def test_38_formula_4kw(self):self.assertEqual(self.evalc(self.fc(),[self.meas(3)],facts={"rated_power_input":self.fact(4,unit="kW")}).computed_limit,4)
 def test_39_formula_cap(self):self.assertEqual(self.evalc(self.fc(),[self.meas(4)],facts={"rated_power_input":self.fact(10,unit="kW")}).computed_limit,5)
 def test_40_formula_max(self):self.assertIs(self.evalc(self.fc(),[self.meas(3.6)],facts={"rated_power_input":self.fact(400)}).decision,TechnicalConstraintDecision.VIOLATES)
 def test_41_formula_fact_missing(self):self.assertEqual(self.evalc(self.fc(),[self.meas(3)]).reason_code,"TECH_FORMULA_INPUT_MISSING")
 def test_42_formula_bad_status(self):self.assertEqual(self.evalc(self.fc(),[self.meas(3)],facts={"rated_power_input":self.fact(400,"INFERRED")}).reason_code,"TECH_FORMULA_INPUT_MISSING")
 def test_43_formula_measurement_missing(self):self.assertIs(self.evalc(self.fc(),facts={"rated_power_input":self.fact(400)}).decision,TechnicalConstraintDecision.NO_MEASUREMENT)
 def test_44_formula_unchanged(self):
  c=self.fc();before=copy.deepcopy(c);self.evalc(c,[self.meas(3)],facts={"rated_power_input":self.fact(400)});self.assertEqual(c,before)
 def cc(self,expr):return self.con(value=None,unit=None,parameter="aperture",ctype="COMPOUND",expression=expr)
 def test_45_any_first(self):self.assertIs(self.evalc(self.cc({"any":[{"field":"aperture_diameter","operator":"greater_than_or_equal","value":5,"unit":"mm"},{"field":"aperture_width","operator":"greater_than_or_equal","value":3,"unit":"mm"}]}),[self.meas(5,"mm","aperture_diameter")]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_46_any_second(self):self.assertIs(self.evalc(self.cc({"any":[{"field":"aperture_diameter","operator":"greater_than_or_equal","value":5,"unit":"mm"},{"field":"aperture_width","operator":"greater_than_or_equal","value":3,"unit":"mm"}]}),[self.meas(3,"mm","aperture_width")]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_47_any_all_fail(self):self.assertIs(self.evalc(self.cc({"any":[{"field":"aperture_diameter","operator":"greater_than_or_equal","value":5,"unit":"mm"},{"field":"aperture_width","operator":"greater_than_or_equal","value":3,"unit":"mm"}]}),[self.meas(4,"mm","aperture_diameter",mid="A"),self.meas(2,"mm","aperture_width",mid="B")]).decision,TechnicalConstraintDecision.VIOLATES)
 def test_48_all_pass(self):self.assertIs(self.evalc(self.cc({"all":[{"field":"aperture_area","operator":"greater_than_or_equal","value":20,"unit":"mm²"},{"field":"aperture_width","operator":"greater_than_or_equal","value":3,"unit":"mm"}]}),[self.meas(20,"mm²","aperture_area",mid="A"),self.meas(3,"mm","aperture_width",mid="B")]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_49_all_fail(self):self.assertIs(self.evalc(self.cc({"all":[{"field":"aperture_area","operator":"greater_than_or_equal","value":20,"unit":"mm²"},{"field":"aperture_width","operator":"greater_than_or_equal","value":3,"unit":"mm"}]}),[self.meas(19,"mm²","aperture_area",mid="A"),self.meas(3,"mm","aperture_width",mid="B")]).decision,TechnicalConstraintDecision.VIOLATES)
 def test_50_compound_missing(self):self.assertIs(self.evalc(self.cc({"all":[{"field":"aperture_area","operator":"greater_than_or_equal","value":20,"unit":"mm²"}]})).decision,TechnicalConstraintDecision.UNKNOWN)
 def test_51_nested(self):self.assertIs(self.evalc(self.cc({"any":[{"all":[{"field":"aperture_area","operator":"greater_than_or_equal","value":20,"unit":"mm²"},{"field":"aperture_width","operator":"greater_than_or_equal","value":3,"unit":"mm"}]}]}),[self.meas(20,"mm²","aperture_area",mid="A"),self.meas(3,"mm","aperture_width",mid="B")]).decision,TechnicalConstraintDecision.SATISFIES)
 def tc(self):return self.con(value=60,unit="r/min",parameter="drum_speed",ctype="COMPOUND",expression={"time_window":{"operator":"less_than_or_equal","value":7,"unit":"s"},"trigger":{"parameter":"opening_distance","operator":"equals","value":50,"unit":"mm"}})
 def tms(self,s=60,t=7,o=50):return [self.meas(s,"r/min","drum_speed",mid="S"),self.meas(t,"s","test_duration",mid="T"),self.meas(o,"mm","opening_distance",mid="O")]
 def test_52_time_complete(self):self.assertIs(self.evalc(self.tc(),self.tms()).decision,TechnicalConstraintDecision.SATISFIES)
 def test_53_speed_violation(self):self.assertIs(self.evalc(self.tc(),self.tms(61)).decision,TechnicalConstraintDecision.VIOLATES)
 def test_54_time_violation(self):self.assertIs(self.evalc(self.tc(),self.tms(t=8)).decision,TechnicalConstraintDecision.VIOLATES)
 def test_55_trigger_missing(self):self.assertIs(self.evalc(self.tc(),self.tms()[:2]).decision,TechnicalConstraintDecision.UNKNOWN)
 def test_56_partial_not_pass(self):self.assertIsNot(self.evalc(self.tc(),self.tms()[:1]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_57_test_parameter_correct(self):self.assertIs(self.evalc(self.con("equals",30,"N","applied_force","TEST_PARAMETER"),[self.meas(30,"N","applied_force","TEST_PARAMETER")]).decision,TechnicalConstraintDecision.SATISFIES)
 def test_58_test_parameter_wrong(self):self.assertIs(self.evalc(self.con("equals",30,"N","applied_force","TEST_PARAMETER"),[self.meas(20,"N","applied_force","TEST_PARAMETER")]).decision,TechnicalConstraintDecision.VIOLATES)
 def test_59_no_product_compliance(self):self.assertNotIn("compliance",self.e.to_json(self.evalc(ms=[self.meas()])))
 def test_60_constraint_snapshot(self):self.assertEqual(self.evalc(ms=[self.meas()]).constraint.constraint_id,"C1")
 def test_61_measurement_snapshot(self):self.assertEqual(self.evalc(ms=[self.meas()]).matched_measurements[0].measurement_id,"M1")
 def test_62_selected_measurement(self):self.assertEqual(self.evalc(ms=[self.meas()]).selected_measurement_id,"M1")
 def test_63_comparison_details(self):self.assertEqual(self.evalc(ms=[self.meas()]).comparison_details["operator"],"less_than_or_equal")
 def test_64_deterministic_id(self):self.assertEqual(self.evalc(ms=[self.meas()]).evaluation_id,self.evalc(ms=[self.meas()]).evaluation_id)
 def test_65_no_duplicate_ids(self):self.assertNotEqual(self.e._id("A B","C"),self.e._id("A_B","C"))
 def test_66_requirement_unchanged(self):
  r=self.req();b=copy.deepcopy(r);self.e.evaluate_constraint(r,self.con(),"APPLICABLE",None,{},{});self.assertEqual(r,b)
 def test_67_app_unchanged(self):self.test_66_requirement_unchanged()
 def test_68_match_unchanged(self):
  m={"evidence_refs":[]};b=copy.deepcopy(m);self.e.evaluate_constraint(self.req(),self.con(),"APPLICABLE",m,{},{});self.assertEqual(m,b)
 def test_69_evidence_unchanged(self):
  m=self.meas();b=copy.deepcopy(m);self.evalc(ms=[m]);self.assertEqual(m,b)
 def test_70_profile_unchanged(self):
  f={"rated_power_input":self.fact(400)};b=copy.deepcopy(f);self.evalc(self.fc(),[self.meas()],facts=f);self.assertEqual(f,b)
 def test_71_valid_json(self):json.loads(self.e.to_json(self.evalc(ms=[self.meas()])))
 def test_72_plain_enum(self):self.assertIn('"decision": "SATISFIES"',self.e.to_json(self.evalc(ms=[self.meas()])))
 def test_73_deterministic_json(self):
  r=self.evalc(ms=[self.meas()]);self.assertEqual(self.e.to_json(r),self.e.to_json(r))
 def test_74_no_requirement_pass_fail(self):self.assertNotIn('"PASS"',self.e.to_json(self.evalc(ms=[self.meas()])))
 def test_75_no_clause_pass_fail(self):self.assertNotIn('"FAIL"',self.e.to_json(self.evalc(ms=[self.meas()])))
 def test_76_no_na_validation(self):self.assertNotIn("N/A",self.e.to_json(self.evalc(ms=[self.meas()])))
 def test_77_no_readiness(self):self.assertNotIn("readiness",self.e.to_json(self.evalc(ms=[self.meas()])))

if __name__=="__main__":unittest.main(verbosity=2)
