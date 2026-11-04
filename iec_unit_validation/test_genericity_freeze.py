"""Step 31H generic semantic replacement and freeze tests."""
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from iec_par.generic_iec_applicability_normalizer import GenericIECApplicabilityNormalizer
from iec_par.generic_iec_feature_registry import CanonicalProductFeatureRegistry
from iec_par.generic_iec_kb_models import ApplicabilityRule,ApplicabilityStatus,Clause,ClauseType,ParentRelationship,RelationshipType,Requirement,RequirementType,SourceReference
from iec_par.generic_requirement_applicability_evaluator import GenericRequirementApplicabilityEvaluator

class GenericityFreezeTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.freeze_path=ROOT/'test_reports/regression_results/step_31h_genericity_freeze.json';cls.freeze=json.loads(cls.freeze_path.read_text())
  cls.temp=tempfile.TemporaryDirectory();p=Path(cls.temp.name)/'registry.json'
  features=[
   ('is_thermal_category','category','BOOLEAN',[],['thermal cabinet']),('has_cooling_port','construction','BOOLEAN',[],['cooling ports in the base']),
   ('has_carousel','construction','BOOLEAN',[],['carousel type']),('access_orientation','construction','ENUM',['LEFT','RIGHT'],['loading type']),
   ('has_latched_panel','construction','BOOLEAN',[],['latched panel'])]
  p.write_text(json.dumps({'schema_version':'1','features':[{'key':k,'category':c,'data_type':t,'description':k,'allowed_values':v,'aliases':a} for k,c,t,v,a in features]}))
  cls.normalizer=GenericIECApplicabilityNormalizer(CanonicalProductFeatureRegistry(p))
 @classmethod
 def tearDownClass(cls):cls.temp.cleanup()
 @classmethod
 def normalize(cls,text):
  r=Requirement(requirement_id='R',text=text,requirement_type=RequirementType.CONDITIONAL,normative=True,condition_text=text,applicability=ApplicabilityRule(status=ApplicabilityStatus.UNRESOLVED,condition_text=text))
  c=Clause(clause_id='1',title=None,clause_type=ClauseType.NORMATIVE,source=SourceReference(),relationship_to_parent=ParentRelationship(type=RelationshipType.NONE),requirements=[r],children=[])
  return cls.normalizer.parse([c])[0].requirements[0]
 @classmethod
 def evaluate(cls,item,facts):
  req={'effective_requirement_id':'R','effective_status':'ACTIVE','applicability':{'status':item.applicability.status.value,'logic':item.applicability.logic,'effect':'APPLIES'}}
  profile={'profile_id':'P','facts':{k:{'feature_id':k,'value':v,'status':'CONFIRMED'} for k,v in facts.items()}}
  return GenericRequirementApplicabilityEvaluator().evaluate_requirement(req,profile).decision.value
 def test_01_former_product_branches_absent(self):
  text=(ROOT/'iec_par/generic_iec_applicability_normalizer.py').read_text().casefold()
  for token in ('washing machine','washer','laundry appliance','submersible pump','welding tool'):self.assertNotIn(token,text)
 def test_02_matching_generic_features_resolve(self):
  item=self.normalize('For thermal cabinets having cooling ports in the base');self.assertEqual(self.evaluate(item,{'is_thermal_category':True,'has_cooling_port':True}),'APPLICABLE')
 def test_03_unrelated_product_does_not_inherit(self):
  item=self.normalize('For thermal cabinets having cooling ports in the base');self.assertEqual(self.evaluate(item,{'is_thermal_category':False,'has_cooling_port':True}),'NOT_APPLICABLE')
 def test_04_missing_feature_unresolved(self):
  item=self.normalize('For thermal cabinets having cooling ports in the base');self.assertEqual(self.evaluate(item,{'is_thermal_category':True}),'UNKNOWN')
 def test_05_text_name_alone_does_not_decide(self):
  item=self.normalize('For thermal cabinets having cooling ports in the base');self.assertEqual(self.evaluate(item,{}),'UNKNOWN')
 def test_06_source_category_preserved(self):
  item=self.normalize('For thermal cabinets having cooling ports in the base');self.assertIn('is_thermal_category',str(item.applicability.logic))
 def test_07_alternative_enum_generic(self):
  item=self.normalize('For thermal cabinets of the carousel type that are loaded from the left or from the right');self.assertEqual({x['value'] for x in item.applicability.logic['all'][2]['any']},{'LEFT','RIGHT'})
 def test_08_opening_compound_generic(self):
  item=self.normalize('Thermal cabinets of the carousel type that are loaded from the left through an opening with a latched panel');self.assertEqual(len(item.applicability.logic['all']),4)
 def test_09_unknown_category_not_partially_resolved(self):self.assertIsNone(self.normalize('For quantum vessels having cooling ports in the base').applicability.logic)
 def test_10_unknown_enum_not_resolved(self):self.assertIsNone(self.normalize('For thermal cabinets of the carousel type that are loaded from the rear or from the right').applicability.logic)
 def test_11_genericity_counters_zero(self):self.assertTrue(all(v==0 for v in self.freeze['genericity_audit'].values()))
 def test_12_washing_regression(self):self.assertEqual(self.freeze['regression']['washing_machine']['regressions'],[])
 def test_13_pump_regression(self):self.assertEqual(self.freeze['regression']['submersible_pump']['regressions'],[])
 def test_14_welding_regression(self):self.assertEqual(self.freeze['regression']['plastic_tube_welding_tools']['regressions'],[])
 def test_15_no_false_material_conflict(self):self.assertEqual(self.freeze['regression']['submersible_pump']['false_material_conflicts'],0)
 def test_16_reconciled_suppressed(self):self.assertEqual(self.freeze['regression']['washing_machine']['reconciled_findings_reactivated'],0)
 def test_17_diagnostics_preserved(self):self.assertEqual(self.freeze['regression']['submersible_pump']['known_probes']['identity_diagnostic'],'PRESERVED')
 def test_18_semantic_diff_empty(self):self.assertTrue(all(v==0 for k,v in self.freeze['semantic_diff'].items() if k.endswith('_changes') and isinstance(v,int)))
 def test_19_freeze_scope(self):self.assertEqual(self.freeze['freeze']['freeze_scope'],'CONTROLLED_PILOT_BASELINE')
 def test_20_module_hashes(self):
  current={rel:hashlib.sha256((ROOT/rel).read_bytes()).hexdigest() for rel in self.freeze['module_hash_manifest']}
  if current!=self.freeze['module_hash_manifest']:
   v2=json.loads((ROOT/'test_reports/regression_results/step_31id_cross_family_controlled_pilot_freeze.json').read_text())
   self.assertEqual(v2['historical_baseline']['status'],'SUPERSEDED_BY_AUTHORIZED_BASELINE_V2')
   self.assertEqual(v2['historical_baseline']['sha256'],hashlib.sha256((ROOT/'test_reports/regression_results/step_31h_genericity_freeze.json').read_bytes()).hexdigest())
 def test_21_artifact_hashes(self):
  mapping={'washing_machine_final_response':'washing_machine','submersible_pump_final_response':'submersible_pump','plastic_tube_welding_tools_final_response':'plastic_tube_welding_tools'}
  for key,case in mapping.items():self.assertEqual(hashlib.sha256((ROOT/'test_reports/output'/(case+'_post_31h')/'decisions/final_compliance_response.json').read_bytes()).hexdigest(),self.freeze['accepted_artifact_hashes'][key])
 def test_22_baselines_exist(self):
  for case in ('washing_machine','submersible_pump','plastic_tube_welding_tools'):self.assertTrue((ROOT/'test_reports/output'/(case+'_post_31g')).is_dir())
 def test_23_deterministic_normalization(self):
  text='For thermal cabinets having cooling ports in the base';self.assertEqual(self.normalize(text).applicability.logic,self.normalize(text).applicability.logic)
 def test_24_no_certification(self):self.assertFalse(self.freeze['freeze']['certification_claim'])
 def test_25_step32_not_started(self):self.assertFalse(self.freeze['freeze']['step_32_started'])

if __name__=='__main__':unittest.main(verbosity=2)
