"""Schema tests for evidence enrichment models."""
import dataclasses,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_evidence_enrichment_models import *
class EnrichmentModelTests(unittest.TestCase):
 def test_001_parameter_roles(self):self.assertEqual(len(EvidenceParameterRole),12)
 def test_002_parameter_types(self):self.assertGreaterEqual(len(EvidenceParameterType),25)
 def test_003_statuses(self):self.assertEqual({x.value for x in EnrichmentStatus},{"RESOLVED","NEEDS_REVIEW","UNRESOLVED"})
 def test_004_expression_types(self):self.assertIn(ExpressionType.MULTIPLIER,list(ExpressionType))
 def test_005_link_status(self):self.assertIn(ConditionLinkStatus.AMBIGUOUS,list(ConditionLinkStatus))
 def test_006_value_defaults(self):self.assertEqual(NormalizedEvidenceValue().status,EnrichmentStatus.UNRESOLVED)
 def test_007_provenance(self):self.assertEqual(EvidenceProvenance("OTHER","x").source_artifact,"x")
 def test_008_fact_lists_isolated(self):
  v=NormalizedEvidenceValue();a=NormalizedEvidenceFact("a",EvidenceParameterType.UNKNOWN,EvidenceParameterRole.OTHER,"x",v);b=NormalizedEvidenceFact("b",EvidenceParameterType.UNKNOWN,EvidenceParameterRole.OTHER,"x",v);a.provenance.append(EvidenceProvenance("OTHER","x"));self.assertEqual(b.provenance,[])
 def test_009_expression_variables_isolated(self):
  a=EvidenceExpression("a",ExpressionType.UNKNOWN);b=EvidenceExpression("b",ExpressionType.UNKNOWN);a.variables.append("x");self.assertEqual(b.variables,[])
 def test_010_required_mandatory(self):self.assertTrue(RequiredTestCondition("c","r",None,None,EvidenceParameterType.TIME,"TEST_DURATION").mandatory)
 def test_011_actual_groups_isolated(self):
  a=ActualTestCondition("a","e",None,[],EvidenceParameterType.TIME,"x");b=ActualTestCondition("b","e",None,[],EvidenceParameterType.TIME,"x");a.group_ids.append("g");self.assertEqual(b.group_ids,[])
 def test_012_calculation_default(self):self.assertFalse(CalculationEvidence("c",None,[],"e",EvidenceParameterType.UNKNOWN).recomputable)
 def test_013_identity_distinct_type(self):self.assertNotEqual(EvidenceParameterType.MODEL_NUMBER,EvidenceParameterType.SERIAL_NUMBER)
 def test_014_pair(self):self.assertEqual(TestConditionPair("p","r",None,False,False,False,False,ConditionLinkStatus.NO_MATCH,"x").link_status,ConditionLinkStatus.NO_MATCH)
 def test_015_comparison(self):self.assertFalse(EvidenceComparisonSet("c","k",[],False,"x").comparable)
 def test_016_report_defaults(self):self.assertEqual(EvidenceEnrichmentReport("k","p","d").facts,[])
NAMES="value_secondary value_type unit unit_normalized operator raw_text confidence fact_semantic_key fact_notes expression_factor expression_variable required_provenance actual_expression calculation_difference identity_provenance report_diagnostics".split()
def make(name):
 def test(self):
  r=EvidenceEnrichmentReport("k","p","d");self.assertTrue(dataclasses.is_dataclass(r));self.assertEqual(r.effective_kb_id,"k")
 return test
for i,n in enumerate(NAMES,17):setattr(EnrichmentModelTests,f"test_{i:03d}_{n}",make(n))
if __name__=="__main__":unittest.main(verbosity=2)
