import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iec_par.generic_compliance_summary_models import *

class SummaryModelTests(unittest.TestCase):
 def test_statuses(self):self.assertEqual(len(FinalComplianceStatus),7)
 def test_issue_taxonomy(self):self.assertGreaterEqual(len(IssueType),19)
 def test_action_taxonomy(self):self.assertGreaterEqual(len(ActionType),15)
 def test_optional_issue_id(self):self.assertIsNone(ComplianceIssue(IssueType.OTHER_REVIEW_REQUIRED,IssueSeverity.LOW,False,"s","r").issue_id)
 def test_no_id_invention(self):self.assertNotIn("issue_id\": \"",ComplianceSummarySerializer.to_json(ComplianceIssue(IssueType.OTHER_REVIEW_REQUIRED,IssueSeverity.LOW,False,"s","r")))
 def test_mutable_isolation(self):
  a=SourceTraceability();b=SourceTraceability();a.report_evidence_ids.append("x");self.assertEqual(b.report_evidence_ids,[])
 def test_serialization(self):json.loads(ComplianceSummarySerializer.to_json(ClauseEvaluationSummary("x",FinalComplianceStatus.UNRESOLVED)))
 def test_deterministic(self):
  x=ClauseEvaluationSummary("x",FinalComplianceStatus.UNRESOLVED);self.assertEqual(ComplianceSummarySerializer.to_json(x),ComplianceSummarySerializer.to_json(x))
 def test_traceability(self):
  t=SourceTraceability(effective_requirement_ids=["r"],evidence_match_ids=["m"]);self.assertEqual(t.evidence_match_ids,["m"])
 def test_presentation_complete(self):self.assertEqual(set(STATUS_PRESENTATION),set(FinalComplianceStatus))
 def test_rejected_label(self):self.assertEqual(STATUS_PRESENTATION[FinalComplianceStatus.REJECTED].label,"Rejected")
 def test_report_optional(self):self.assertIsNone(ReportEvaluationSummary(FinalComplianceStatus.UNRESOLVED).report_document_id)
 def test_frozen(self):
  x=EvidenceReference("e")
  with self.assertRaises(Exception):x.evidence_id="z"
 def test_type_error(self):
  with self.assertRaises(TypeError):ComplianceSummarySerializer.to_dict({})
 def test_genericity(self):
  s=Path(__file__).parents[1].joinpath("iec_par/generic_compliance_summary_models.py").read_text().casefold();self.assertNotIn("washing machine",s);self.assertNotIn("60335",s)

if __name__=="__main__":unittest.main(verbosity=2)
