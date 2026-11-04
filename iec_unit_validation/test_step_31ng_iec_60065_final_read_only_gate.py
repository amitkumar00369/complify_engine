"""Final read-only IEC 60065 decision-gate checks."""
import hashlib,json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];A=json.loads((ROOT/'test_reports/regression_results/step_31ng_iec_60065_final_read_only_gate.json').read_text())
class GateTests(unittest.TestCase):
 def test_01_read_only(self):self.assertEqual(A['audit_mode'],'READ_ONLY')
 def test_02_v1(self):self.assertEqual(A['immutability']['v1_sha256'],'adb2184fe9bf7a409fc3f03e8bfb991366e16fb8f7207d0f294e7a3e29b17453')
 def test_03_structure(self):self.assertTrue(A['structure']['top_level_1_20_exact'])
 def test_04_requirements(self):self.assertEqual(sum(A['requirement_gate']['same_119'][x] for x in ('correct','missing')),119)
 def test_05_numeric(self):self.assertEqual(A['numeric_gate']['prior_55']['material_defect'],0)
 def test_06_measurements(self):self.assertEqual(A['measurement_gate']['unsafe_links'],0)
 def test_07_zero_comparison_reason(self):self.assertEqual(A['measurement_gate']['classification'],'EXPECTED_SAFE_BEHAVIOR_WITH_MODEL_GAP')
 def test_08_na_restored(self):self.assertEqual((A['report_evidence_gate']['na_items'],A['report_evidence_gate']['unique_na_clauses']),(339,185))
 def test_09_tables(self):self.assertEqual(A['appended_table_gate']['cross_clause_leakage'],0)
 def test_10_profile_blocker(self):self.assertTrue(A['product_profile_gate']['material_deterministic_blocker'])
 def test_11_final_accounting(self):self.assertEqual(A['final_response']['unresolved']+A['final_response']['not_evaluated'],A['final_response']['issues'])
 def test_12_prior_fp(self):self.assertEqual(sum(A['accuracy_gate']['previous_3_fp'].values()),3)
 def test_13_prior_fn(self):self.assertEqual(sum(A['accuracy_gate']['previous_27_fn'].values()),27)
 def test_14_second_report(self):self.assertTrue(A['second_report']['same_pattern'])
 def test_15_cross_family(self):self.assertEqual(A['cross_family']['numeric_regression'],0)
 def test_16_decision(self):self.assertEqual(A['final_decision']['POST_31NF_STATUS'],'MORE_DETERMINISTIC_WORK_REQUIRED')
 def test_17_no_llm(self):self.assertFalse(A['controls']['llm_used'])
 def test_18_no_step32(self):self.assertFalse(A['controls']['step_32_started'])
if __name__=='__main__':unittest.main(verbosity=2)
