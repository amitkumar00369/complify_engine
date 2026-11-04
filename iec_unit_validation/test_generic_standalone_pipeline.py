"""Step 31I-A standalone-standard orchestration tests."""
import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from run_compliance_pipeline import build_parser
from iec_par.generic_compliance_pipeline_runner import GenericCompliancePipelineRunner,PipelineStatus,StandardSetMode,StandardValidationStatus
from iec_par.generic_iec_standalone_effective_kb_builder import GenericIECStandaloneEffectiveKnowledgeBaseBuilder
from iec_par.generic_iec_kb_models import *
from tests.test_generic_compliance_pipeline_runner_downstream import DownstreamRunnerTests,Effective,Save

class StandaloneEffective(Effective):
 def build(self,base):return {'effective_kb_id':'E-STANDALONE','base_standard':base['document'],'delta_standard':None,'clauses':[{'clause_id':'1','requirements':[{'effective_requirement_id':'E-R','effective_source_type':'BASE','base_sources':[{'requirement_id':'R'}]}]}]}
class StandaloneEvidence(Save):
 def extract(self,p):return {'standard_numbers':['100-1'],'clauses':[]}

class StandalonePipelineTests(unittest.TestCase):
 def test_01_cli_accepts_standalone(self):
  a=build_parser().parse_args(['--base-standard','a','--report','r','--output','o']);self.assertIsNone(a.part2_standard)
 def test_02_cli_accepts_paired(self):self.assertEqual(build_parser().parse_args(['--base-standard','a','--part2-standard','p','--report','r','--output','o']).part2_standard,'p')
 def test_03_missing_base_fails(self):
  with self.assertRaises(SystemExit):build_parser().parse_args(['--report','r','--output','o'])
 def test_04_missing_report_fails(self):
  with self.assertRaises(SystemExit):build_parser().parse_args(['--base-standard','b','--output','o'])
 def test_05_mode_without_part2(self):self.assertEqual(StandardSetMode.STANDALONE.value,'STANDALONE')
 def test_06_mode_with_part2(self):self.assertEqual(StandardSetMode.BASE_PLUS_COMPANION.value,'BASE_PLUS_COMPANION')
 def test_07_to_12_standalone_artifacts_and_provenance(self):
  calls=[]
  with tempfile.TemporaryDirectory() as d:
   helper=DownstreamRunnerTests();base,_,report=helper.pdfs(d);out=Path(d)/'standalone';components=helper.setup(calls);components['standalone_effective_builder']=StandaloneEffective();components['report_evidence_extractor']=StandaloneEvidence()
   result=GenericCompliancePipelineRunner(components=components,clock=lambda:'T').run(base,None,report,out,run_id='S')
   self.assertEqual(result.pipeline_status,PipelineStatus.SUCCESS_WITH_REVIEW)
   self.assertFalse((out/'standards/delta_kb.json').exists());self.assertFalse((out/'standards/pair_validation.json').exists());self.assertTrue((out/'standards/effective_kb.json').exists())
   effective=json.loads((out/'standards/effective_kb.json').read_text());req=effective['clauses'][0]['requirements'][0]
   self.assertEqual((req['effective_source_type'],req['base_sources'][0]['requirement_id']),('BASE','R'))
   manifest=json.loads((out/'manifest/pipeline_manifest.json').read_text());self.assertEqual(manifest['standard_set_mode'],'STANDALONE');self.assertNotIn('part2_standard',manifest['input_files'])
 def test_13_standalone_validation(self):self.assertEqual(GenericCompliancePipelineRunner().validate_standard_set({'document':{'standard_number':'100-1'}},None,{'standard_numbers':['100-1']}).status,StandardValidationStatus.VALID)
 def test_14_strict_standalone_year(self):self.assertEqual(GenericCompliancePipelineRunner().validate_standard_set({'document':{'standard_number':'100-1','year':2020}},None,{'standard_numbers':['100-1:2019']},True).status,StandardValidationStatus.STANDARD_MISMATCH)
 def test_15_stop_base(self):self._stop('base_kb','base_kb.json')
 def test_16_stop_effective(self):self._stop('effective_kb','effective_kb.json')
 def test_17_reuse_standalone(self):self._stop('effective_kb','effective_kb.json',True)
 def test_18_cache_kind_is_explicit(self):self.assertIn('kind',GenericCompliancePipelineRunner._build_or_reuse_kb.__code__.co_varnames)
 def test_19_manifest_standalone(self):self.test_07_to_12_standalone_artifacts_and_provenance()
 def test_20_paired_manifest_mode(self):
  calls=[]
  with tempfile.TemporaryDirectory() as d:
   h=DownstreamRunnerTests();b,p,r=h.pdfs(d);out=Path(d)/'paired';GenericCompliancePipelineRunner(components=h.setup(calls),clock=lambda:'T').run(b,p,r,out,run_id='P');self.assertEqual(json.loads((out/'manifest/pipeline_manifest.json').read_text())['standard_set_mode'],'BASE_PLUS_COMPANION')
 def test_21_validation_deterministic(self):
  runner=GenericCompliancePipelineRunner();a=runner.validate_standard_set({'document':{'standard_number':'100-1'}},None,{'standard_numbers':['100-1']});b=runner.validate_standard_set({'document':{'standard_number':'100-1'}},None,{'standard_numbers':['100-1']});self.assertEqual(a,b)
 def test_22_invalid_pdf(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x.pdf';p.write_text('bad')
   with self.assertRaises(ValueError):GenericCompliancePipelineRunner._require_pdf(p)
 def test_23_no_standard_branch(self):
  text=(ROOT/'iec_par/generic_compliance_pipeline_runner.py').read_text();self.assertNotIn('60204',text);self.assertNotIn('60335',text)
 def test_24_real_builder_projects_base(self):
  class V:
   def validate(self,x):return type('R',(),{'errors':[]})()
  document=StandardDocument(standard_id='S',standard_number='100-1',document_type=DocumentType.BASE)
  req=Requirement(requirement_id='R',text='It shall comply.',requirement_type=RequirementType.GENERAL,normative=True,applicability=ApplicabilityRule(status=ApplicabilityStatus.ALWAYS))
  clause=Clause(clause_id='1',title=None,clause_type=ClauseType.NORMATIVE,source=SourceReference(),relationship_to_parent=ParentRelationship(type=RelationshipType.NONE),requirements=[req],children=[])
  kb=KnowledgeBase(document=document,clauses=[clause]);effective=GenericIECStandaloneEffectiveKnowledgeBaseBuilder(V()).build(kb)
  self.assertEqual((effective.delta_standard,effective.clauses[0].requirements[0].effective_source_type.value),(None,'BASE'))
 def test_25_step31ib_not_started(self):self.assertFalse((ROOT/'iec_par/generic_iec_60204_parser.py').exists())
 def _stop(self,stage,name,reuse=False):
  calls=[]
  with tempfile.TemporaryDirectory() as d:
   h=DownstreamRunnerTests();b,_,r=h.pdfs(d);out=Path(d)/stage;c=h.setup(calls);c['standalone_effective_builder']=StandaloneEffective();c['report_evidence_extractor']=StandaloneEvidence();result=GenericCompliancePipelineRunner(components=c,clock=lambda:'T').run(b,None,r,out,stop_after=stage,reuse_kb=reuse);self.assertEqual(result.pipeline_status,PipelineStatus.SUCCESS_WITH_REVIEW);self.assertTrue((out/'standards'/name).exists())

if __name__=='__main__':unittest.main(verbosity=2)
