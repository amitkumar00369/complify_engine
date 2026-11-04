"""Acceptance checks for the read-only Step 31N-E reassessment."""

import hashlib
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ARTIFACT=ROOT/"test_reports/regression_results/step_31ne_iec_60065_final_accuracy_reassessment.json"
V1=ROOT/"test_reports/regression_results/step_31me_deterministic_compliance_engine_v1_freeze.json"

class Step31NEAccuracyTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.a=json.loads(ARTIFACT.read_text())
 def test_01_read_only(self):self.assertEqual(self.a['audit_mode'],'READ_ONLY')
 def test_02_v1_immutable(self):self.assertEqual(hashlib.sha256(V1.read_bytes()).hexdigest(),'adb2184fe9bf7a409fc3f03e8bfb991366e16fb8f7207d0f294e7a3e29b17453')
 def test_03_structure(self):self.assertTrue(self.a['structural_reconfirmation']['clauses_1_20_exactly_once'])
 def test_04_requirement_accounting(self):
  x=self.a['requirement_coverage']['same_119_probes'];self.assertEqual(sum(x[k] for k in ('CORRECT','MISSING','OVER_MERGED','OVER_SPLIT','SEMANTICALLY_INCOMPLETE','SOURCE_GAP')),119)
 def test_05_prior_fn_accounting(self):self.assertEqual(sum(self.a['previous_75_fn_reconstruction'][k] for k in ('RESOLVED','STILL_FALSE_NEGATIVE','SOURCE_GAP','LEGITIMATELY_NOT_EVALUABLE','CONSERVATIVE_REVIEW')),75)
 def test_06_numeric_accounting(self):
  x=self.a['numeric_correction_validation'];self.assertEqual(x['CORRECT']+x['LEGITIMATELY_UNRESOLVED']+x['MATERIAL_DEFECT'],55)
 def test_07_zero_comparison_classified(self):self.assertIn(self.a['zero_comparison_audit']['finding'],('EXPECTED_SAFE_BEHAVIOR','MATERIAL_MATCHING_DEFECT'))
 def test_08_appended_tables(self):self.assertEqual(sum(self.a['appended_table_audit']['classification'].values()),22)
 def test_09_evidence(self):self.assertEqual(sum(self.a['evidence_coverage']['classification'].values()),120)
 def test_10_na(self):self.assertEqual(sum(self.a['na_audit']['classification'].values()),100)
 def test_11_profile(self):self.assertEqual(self.a['product_profile_audit']['fabricated_fact_count'],0)
 def test_12_applicability(self):self.assertEqual(sum(self.a['applicability_audit']['classification'].values()),80)
 def test_13_final_response(self):self.assertEqual(self.a['final_response_audit']['issue_count'],508)
 def test_14_fp(self):self.assertGreaterEqual(self.a['false_positive_audit']['issues_sampled'],150)
 def test_15_fn(self):self.assertGreaterEqual(self.a['independent_false_negative_audit']['probes'],150)
 def test_16_prior_fp(self):
  x=self.a['previous_fp_fn_reconstruction']['prior_3_fp'];self.assertEqual(x['resolved']+x['remaining'],3)
 def test_17_prior_fn(self):
  x=self.a['previous_fp_fn_reconstruction']['prior_27_fn'];self.assertEqual(x['resolved']+x['remaining'],27)
 def test_18_second_report(self):
  x=self.a['second_report_audit'];self.assertGreaterEqual((x['evidence_rows'],x['na_rows'],x['numeric_cases'],x['final_findings_or_probes']),(50,40,20,40))
 def test_19_isolation(self):self.assertTrue(self.a['cross_report_isolation']['separate_report_hashes'] and self.a['cross_report_isolation']['identical_standard_kb'])
 def test_20_cross_family(self):self.assertEqual(self.a['cross_family_review']['numeric_regression'],0)
 def test_21_root_causes(self):self.assertTrue(all(x['first_incorrect_stage'] for x in self.a['root_cause_classification']))
 def test_22_boundary(self):self.assertTrue(self.a['deterministic_llm_boundary']['DETERMINISTIC_MUST_FIX'])
 def test_23_client_readiness(self):self.assertEqual(self.a['client_readiness']['status'],'NOT_READY')
 def test_24_no_production_mutation(self):self.assertEqual(self.a['immutability']['production_mutation_count'],0)
 def test_25_no_llm(self):self.assertFalse(self.a['controls']['llm_used'])
 def test_26_no_step32(self):self.assertFalse(self.a['controls']['step_32_started'])

if __name__=='__main__':unittest.main(verbosity=2)
