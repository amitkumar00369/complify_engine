"""Focused tests for logical report-row extraction and ownership."""
from __future__ import annotations
import unittest
from iec_par.generic_report_evidence_extractor import GenericReportEvidenceExtractor

class EvidenceGranularityTests(unittest.TestCase):
 def extract(self,text):return GenericReportEvidenceExtractor().extract_from_pages([text])
 def items(self,text):return self.extract(text).clauses[0].evidence_items
 def test_01_wrapped_line_is_one_row(self):
  x=self.items("7.1\nLong requirement text wrapped\nonto another visual line\nP");self.assertFalse(any(i.evidence_type.value=="SUBROW" for i in x))
 def test_02_two_independent_verdict_rows(self):
  x=self.items("7.1\nFirst independent assertion\nP\nSecond independent assertion\nN/A");self.assertEqual(sum(i.evidence_type.value=="SUBROW" for i in x),2)
 def test_03_sibling_verdicts_preserved(self):
  x=[i for i in self.items("7.1\nFirst assertion text\nP\nSecond assertion text\nN/A") if i.evidence_type.value=="SUBROW"];self.assertEqual([i.reported_verdict.value for i in x],["PASS","NA"])
 def test_04_parent_has_no_child_verdict(self):
  x=self.items("7.1\nFirst assertion text\nP\nSecond assertion text\nN/A");self.assertEqual(x[0].reported_verdict.value,"NOT_STATED")
 def test_05_logical_ids_deterministic(self):
  a=[i.logical_row_id for i in self.items("7.1\nFirst assertion text\nP\nSecond assertion text\nN/A")];b=[i.logical_row_id for i in self.items("7.1\nFirst assertion text\nP\nSecond assertion text\nN/A")];self.assertEqual(a,b)
 def test_06_unique_evidence_ids(self):
  ids=[i.evidence_id for i in self.items("7.1\nFirst assertion text\nP\nSecond assertion text\nN/A")];self.assertEqual(len(ids),len(set(ids)))
 def test_07_parent_references_resolve(self):
  items=self.items("7.1\nFirst assertion text\nP\nSecond assertion text\nN/A");ids={i.evidence_id for i in items};self.assertTrue(all(not i.parent_evidence_id or i.parent_evidence_id in ids for i in items))
 def test_08_layout_chrome_not_subrow_text(self):
  x=[i for i in self.items("7.1\nFirst assertion text\nP\nPage 2 of 5 Report No. R\nClause Requirement + Test Result - Remark Verdict\nSecond assertion text\nN/A") if i.evidence_type.value=="SUBROW"];self.assertTrue(all("Page 2" not in (i.raw_text or "") for i in x))
 def test_09_verdict_owner_is_child(self):
  x=[i for i in self.items("7.1\nFirst assertion text\nP\nSecond assertion text\nN/A") if i.evidence_type.value=="SUBROW"];self.assertTrue(all(i.verdict_owner_evidence_id==i.evidence_id for i in x))
 def test_10_round_trip_metadata(self):
  doc=self.extract("7.1\nFirst assertion text\nP\nSecond assertion text\nN/A");clone=type(doc).from_dict(doc.to_dict());self.assertEqual(doc.to_json(),clone.to_json())

if __name__=="__main__":unittest.main(verbosity=2)
