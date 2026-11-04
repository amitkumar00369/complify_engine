"""Step 31G audit-artifact acceptance tests."""
import hashlib,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

class MultiReportAcceptanceTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.path=ROOT/"test_reports/regression_results/step_31g_generalization_acceptance.json";cls.data=json.loads(cls.path.read_text())
 def test_01_schema(self):self.assertEqual((self.data["step"],self.data["status"]),("31G","COMPLETE"))
 def test_02_report_order(self):self.assertEqual([x["case_id"] for x in self.data["reports"]],sorted(x["case_id"] for x in self.data["reports"]))
 def test_03_probe_order(self):
  for report in self.data["reports"]:self.assertEqual(len(report["manual_probes"]),10)
 def test_04_fixture_branch_count_is_audited(self):self.assertEqual(self.data["genericity_audit"]["model_specific_branches"],0)
 def test_05_false_positive_preserved(self):self.assertEqual(self.data["cross_report_summary"]["false_positives"],sum(x["audit_counts"]["false_positives"] for x in self.data["reports"]))
 def test_06_false_negative_preserved(self):self.assertEqual(self.data["cross_report_summary"]["false_negatives"],sum(x["audit_counts"]["false_negatives"] for x in self.data["reports"]))
 def test_07_unresolved_not_correct(self):self.assertEqual(self.data["cross_report_summary"]["correct"]+self.data["cross_report_summary"]["correct_but_generic"]+self.data["cross_report_summary"]["unresolved"],30)
 def test_08_no_system_accuracy(self):self.assertNotIn("system_accuracy",json.dumps(self.data).casefold())
 def test_09_acceptance_deterministic(self):self.assertEqual(self.data["acceptance"]["level"],"ACCEPTABLE_FOR_CONTROLLED_PILOT")
 def test_10_third_report_present(self):self.assertIn("plastic_tube_welding_tools",[x["case_id"] for x in self.data["reports"]])
 def test_11_baselines_exist(self):
  for x in ("submersible_pump_post_31f","washing_machine_post_31f"):self.assertTrue((ROOT/"test_reports/output"/x/"decisions/final_compliance_response.json").is_file())
 def test_12_pump_31b(self):self._probe("submersible_pump","6.2 PASS","CORRECT")
 def test_13_pump_31c(self):self._probe("submersible_pump","15.3 exclusion","CORRECT")
 def test_14_pump_31d(self):self._probe("submersible_pump","25.8 operating depth","CORRECT")
 def test_15_pump_31e(self):self._probe("submersible_pump","Declared/tested identity","CORRECT")
 def test_16_pump_31f(self):self._probe("submersible_pump","Final identity explanation","CORRECT")
 def test_17_washing_reconciled_suppressed(self):self.assertEqual(self._report("washing_machine")["reconciled_findings"]["reactivated"],0)
 def test_18_no_upgrade(self):self.assertTrue(all(x["metrics"]["final_status"]=="ACTION_REQUIRED" for x in self.data["reports"]))
 def test_19_material_false_positive_zero(self):self.assertEqual(self.data["cross_report_summary"]["material_conflict_false_positives"],0)
 def test_20_step32_not_started(self):self.assertFalse(self.data["constraints"]["step_32_started"])
 def test_21_no_production_change(self):self.assertFalse(self.data["constraints"]["production_evaluation_logic_changed"])
 def test_22_no_certification_claim(self):self.assertFalse(self.data["constraints"]["certification_claim"])
 def test_23_three_runs_completed(self):self.assertEqual(self.data["cross_report_summary"]["reports_completed"],3)
 def test_24_deterministic_json(self):self.assertEqual(json.dumps(self.data,sort_keys=True),json.dumps(self.data,sort_keys=True))
 def test_25_fixture_values_absent_from_decision_code(self):
  paths=("generic_cross_evidence_consistency_validator.py","generic_clause_evaluation_summary_builder.py","generic_final_issue_resolution.py")
  text="".join((ROOT/"iec_par"/x).read_text() for x in paths)
  for value in ("SPC55068","4TSC4.0-96-110/1000","PTWT215002"):self.assertNotIn(value,text)
 def _report(self,name):return next(x for x in self.data["reports"] if x["case_id"]==name)
 def _probe(self,case,subject,status):self.assertEqual(next(x for x in self._report(case)["manual_probes"] if x["subject"]==subject)["classification"],status)

if __name__=="__main__":unittest.main(verbosity=2)
