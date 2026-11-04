"""Versioned cross-family controlled-pilot freeze tests."""
import hashlib
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FREEZE=ROOT/'test_reports/regression_results/step_31id_cross_family_controlled_pilot_freeze.json'


class CrossFamilyFreezeV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.data=json.loads(FREEZE.read_text())
    def test_01_baseline_name(self): self.assertEqual(self.data['baseline'],'CROSS_FAMILY_CONTROLLED_PILOT_BASELINE_V2')
    def test_02_frozen(self): self.assertEqual(self.data['engine_state'],'FROZEN')
    def test_03_families(self): self.assertEqual(set(self.data['accepted_families']),{'IEC_60335_FAMILY','IEC_60204_FAMILY'})
    def test_04_hashes(self):
        for rel,want in self.data['module_hash_manifest'].items():self.assertEqual(hashlib.sha256((ROOT/rel).read_bytes()).hexdigest(),want)
    def test_05_artifacts_exist(self):
        mapping={'iec_60204':'iec_60204_1_post_31id','washing_machine':'washing_machine_post_31id','submersible_pump':'submersible_pump_post_31id','plastic_tube_welding_tools':'plastic_tube_welding_tools_post_31id'}
        for key,run in mapping.items():
            p=ROOT/'test_reports/output'/run/'decisions/final_compliance_response.json';self.assertTrue(p.is_file());self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),self.data['accepted_run_artifacts'][key]['final_response_sha256'])
    def test_06_historical_preserved(self):
        h=self.data['historical_baseline'];p=ROOT/h['artifact'];self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),h['sha256']);self.assertEqual(h['status'],'SUPERSEDED_BY_AUTHORIZED_BASELINE_V2')
    def test_07_genericity_zero(self): self.assertTrue(all(v==0 for v in self.data['genericity_audit'].values()))
    def test_08_reaudit_complete(self): self.assertEqual(self.data['audit_recheck']['probe_count'],33)
    def test_09_false_negatives_zero(self): self.assertEqual(self.data['audit_recheck']['known_false_negatives_after'],0)
    def test_10_false_positives_zero(self): self.assertEqual(self.data['audit_recheck']['known_false_positives_after'],0)
    def test_11_no_true_positive_lost(self): self.assertEqual(self.data['audit_recheck']['true_positives_lost'],0)
    def test_12_step_31ie_not_started(self): self.assertFalse(self.data['step_31ie_started'])
    def test_13_deterministic_json(self): self.assertEqual(json.dumps(self.data,sort_keys=True),json.dumps(json.loads(FREEZE.read_text()),sort_keys=True))


if __name__=='__main__':unittest.main(verbosity=2)
