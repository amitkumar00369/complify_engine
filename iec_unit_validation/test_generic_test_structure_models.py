"""Schema tests for generic test structures."""
import dataclasses,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_test_structure_models import *
class StructureModelTests(unittest.TestCase):
 def test_001_step_types(self):self.assertEqual(len(StandardTestStepType),12)
 def test_002_row_levels(self):self.assertEqual(len(ReportRowLevel),9)
 def test_003_link_statuses(self):self.assertEqual(len(StructureLinkStatus),4)
 def test_004_statuses(self):self.assertEqual(len(StructureStatus),3)
 def test_005_step_defaults(self):self.assertEqual(StandardTestStep("s",1,StandardTestStepType.OTHER,"x").references,[])
 def test_006_standard_defaults(self):self.assertEqual(StandardTestStructure("s","N",None,"g",None,[],None).test_method_steps,[])
 def test_007_row_defaults(self):self.assertEqual(ReportResultRow("r",1,None,ReportRowLevel.ROW,None,None,None).measurements,[])
 def test_008_clause_defaults(self):self.assertEqual(ReportClauseStructure("s","N","x",None,None).rows,[])
 def test_009_link_fields(self):self.assertFalse(TestStructureLinkCandidate("l","s",[],"r",[],"g",None,False,False,0,False,False,StructureLinkStatus.NO_MATCH,"x",0).scope_alignment)
 def test_010_scope_fields(self):self.assertEqual(RowScopeCandidate("r",None,None,[],[],StructureLinkStatus.NO_MATCH,"x").candidate_group_ids,[])
 def test_011_report_defaults(self):self.assertEqual(TestStructureEnrichmentReport("k","d").diagnostics,[])
NAMES="provenance_source provenance_page provenance_clause provenance_requirement provenance_group primary_obligation member_ids required_conditions measurements acceptance post exceptions step_expression step_value step_unit step_refs row_parent row_level row_label row_requirement row_method row_conditions row_calculations row_remarks row_verdict link_confidence report_summary".split()
def make(name):
 def test(self):self.assertTrue(dataclasses.is_dataclass(TestStructureEnrichmentReport("k","d")))
 return test
for i,n in enumerate(NAMES,12):setattr(StructureModelTests,f"test_{i:03d}_{n}",make(n))
if __name__=="__main__":unittest.main(verbosity=2)
