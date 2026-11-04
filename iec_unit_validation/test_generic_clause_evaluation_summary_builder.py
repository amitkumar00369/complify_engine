import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_clause_evaluation_summary_builder import GenericClauseEvaluationSummaryBuilder as B
from iec_par.generic_compliance_summary_models import *

class BuilderTests(unittest.TestCase):
 def fixture(self,decision="COMPLIANT",gap="NO_GAP",match="EXACT_CLAUSE",eids=None,app="APPLICABLE",technical=None,scope=None):
  eids=eids if eids is not None else ["E"]
  kb={"clauses":[{"clause_id":"X","title":"Title","requirements":[{"effective_requirement_id":"R","text":"Requirement","requirement_type":"GENERAL","effective_status":"ACTIVE","effective_source_type":"BASE","technical_constraints":[]}],"children":[]}]}
  profile={"facts":{"feature":{"fact_id":"F","value":True,"status":"KNOWN","evidence":[]}}}
  evidence={"clauses":[{"clause_id":"X","evidence_items":[{"evidence_id":"E","evidence_type":"CLAUSE_RESULT","reported_verdict":"PASS","page_start":1,"raw_text":"proof"}],"children":[]}]}
  applicability={"results":[{"effective_requirement_id":"R","evaluation_id":"A","decision":app,"condition_text":"If feature applies","facts_used":["feature"],"required_features":["feature"],"missing_features":[],"review_features":[],"conflicting_features":[]}]}
  matches={"matches":[{"effective_requirement_id":"R","match_id":"M","match_status":match,"evidence_refs":[{"evidence_id":x} for x in eids]}]}
  grouping={"groups":[{"group_id":"G","clause_id":"X","members":[{"effective_requirement_id":"R"}]}]}
  final={"results":[{"effective_requirement_id":"R","decision_id":"D","group_id":"G","final_decision":decision,"supporting_evidence_ids":eids,"report_verdicts":["PASS"],"reason":"reason"}],"group_decisions":[{"group_id":"G","group_decision":decision,"reason":"group reason"}]}
  coverage={"requirement_gaps":[{"effective_requirement_id":"R","gap_id":"GAP","group_id":"G","primary_gap_type":gap,"secondary_gap_types":[],"supporting_evidence_ids":eids}],"group_gaps":[{"group_id":"G","primary_gap_type":gap,"secondary_gap_types":[]}]}
  return [kb,profile,evidence,applicability,matches,grouping,final,coverage,technical,scope,None,None,None]
 def runx(self,**kw):return B().build(*self.fixture(**kw))
 def test_001_compliant(self):self.assertEqual(self.runx()[0].final_status,FinalComplianceStatus.COMPLIANT)
 def test_002_insufficient(self):self.assertEqual(self.runx(decision="INSUFFICIENT_EVIDENCE",gap="EVIDENCE_GAP")[0].final_status,FinalComplianceStatus.INSUFFICIENT_EVIDENCE)
 def test_003_unknown(self):self.assertEqual(self.runx(decision="UNKNOWN_APPLICABILITY",gap="APPLICABILITY_GAP",app="UNKNOWN")[0].final_status,FinalComplianceStatus.UNRESOLVED)
 def test_004_na(self):self.assertEqual(self.runx(decision="NOT_APPLICABLE",gap="NOT_APPLICABLE")[0].final_status,FinalComplianceStatus.NOT_APPLICABLE)
 def test_005_inactive(self):self.assertEqual(self.runx(decision="INACTIVE",gap="INACTIVE")[0].final_status,FinalComplianceStatus.INACTIVE)
 def test_006_conflict_not_rejected(self):self.assertEqual(self.runx(decision="NEEDS_REVIEW",gap="CONFLICTING_EVIDENCE_GAP")[0].final_status,FinalComplianceStatus.UNRESOLVED)
 def test_007_evidence_resolved(self):self.assertEqual(self.runx()[0].group_summaries[0].report_evidence[0]["evidence_id"],"E")
 def test_008_recover_from_match(self):
  f=self.fixture(eids=[]);f[4]["matches"][0]["evidence_refs"]=[{"evidence_id":"E"}];self.assertEqual(len(B().build(*f)[0].group_summaries[0].report_evidence),1)
 def test_009_no_clause_fabrication(self):self.assertEqual(self.runx(eids=[])[0].group_summaries[0].report_evidence,[])
 def test_010_missing_measurement(self):
  tech={"results":[{"effective_requirement_id":"R","evaluation_id":"T","constraint_id":"C","decision":"NO_MEASUREMENT"}]};g=self.runx(decision="NEEDS_REVIEW",gap="TECHNICAL_MEASUREMENT_GAP",technical=tech)[0].group_summaries[0];self.assertIn(IssueType.MISSING_MEASUREMENT,{x.issue_type for x in g.issues})
 def test_011_product_context(self):self.assertEqual(self.runx()[0].group_summaries[0].product_context[0]["fact_id"],"F")
 def test_012_traceability(self):self.assertEqual(self.runx()[0].group_summaries[0].source_traceability.evidence_match_ids,["M"])
 def test_013_deterministic(self):self.assertEqual(B.to_json(self.runx()),B.to_json(self.runx()))
 def test_014_immutable(self):
  f=self.fixture();b=copy.deepcopy(f);B().build(*f);self.assertEqual(f,b)
 def test_015_optional_absent(self):self.assertEqual(len(self.runx()),1)
 def test_016_malformed_reference(self):self.assertEqual(self.runx(eids=["MISSING"])[0].group_summaries[0].report_evidence,[])
 def test_017_issue_dedup(self):self.assertEqual(len(self.runx(decision="INSUFFICIENT_EVIDENCE",gap="EVIDENCE_GAP")[0].issues),1)
 def test_018_action_dedup(self):self.assertEqual(len(self.runx(decision="INSUFFICIENT_EVIDENCE",gap="EVIDENCE_GAP")[0].next_actions),1)
 def test_019_serialization(self):json.loads(B.to_json(self.runx()))
 def test_020_save(self):
  with tempfile.TemporaryDirectory() as d:self.assertTrue(B.save_json(self.runx(),Path(d)/"x.json").exists())
 def test_021_summary(self):self.assertEqual(B.get_summary(self.runx())["logical_groups_summarized"],1)
 def test_022_standard_view(self):self.assertEqual(self.runx()[0].group_summaries[0].standard_requirements[0]["effective_requirement_id"],"R")
 def test_023_evidence_match_view(self):self.assertEqual(self.runx()[0].group_summaries[0].evidence_match["statuses"],["EXACT_CLAUSE"])
 def test_024_no_recompute(self):self.assertEqual(self.runx()[0].group_summaries[0].applicability["member_decisions"][0]["decision"],"APPLICABLE")
 def test_025_genericity(self):
  s=Path(__file__).parents[1].joinpath("iec_par/generic_clause_evaluation_summary_builder.py").read_text().casefold();self.assertNotIn("washing machine",s);self.assertNotIn("60335",s);self.assertNotIn("10.1",s)
 def test_026_multiple_groups_aggregate(self):
  f=self.fixture();g=copy.deepcopy(f[5]["groups"][0]);g["group_id"]="G2";f[5]["groups"].append(g);f[6]["group_decisions"].append({"group_id":"G2","group_decision":"INSUFFICIENT_EVIDENCE"});self.assertEqual(B().build(*f)[0].final_status,FinalComplianceStatus.INSUFFICIENT_EVIDENCE)

if __name__=="__main__":unittest.main(verbosity=2)
