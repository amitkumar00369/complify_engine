"""Tests for independent report-evidence schemas."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from iec_par.generic_report_evidence_models import *


class GenericReportEvidenceModelsTests(unittest.TestCase):
    def test_01_verdict_values(self): self.assertEqual(ReportedVerdict.NA.value,"NA")
    def test_02_evidence_type_values(self): self.assertEqual(ReportEvidenceType.MEASUREMENT.value,"MEASUREMENT")
    def test_03_measurement_defaults(self): self.assertIsNone(ReportMeasurement("M").value)
    def test_04_evidence_measurement_default_isolated(self):
        a=ReportEvidenceItem("A",ReportEvidenceType.OTHER); b=ReportEvidenceItem("B",ReportEvidenceType.OTHER); a.measurements.append(ReportMeasurement("M")); self.assertEqual(b.measurements,[])
    def test_05_clause_children_default_isolated(self):
        a=ReportClauseResult("A","1"); b=ReportClauseResult("B","2"); a.children.append(b); self.assertEqual(b.children,[])
    def test_06_document_defaults(self): self.assertEqual(ReportEvidenceDocument("D").schema_version,"1.0")
    def test_07_plain_enum_serialization(self): self.assertIn('"reported_verdict": "PASS"',ReportClauseResult("R","1",reported_verdict=ReportedVerdict.PASS).to_json())
    def test_08_unicode_serialization(self): self.assertIn("µA",ReportMeasurement("M",unit="µA").to_json(ensure_ascii=False))
    def test_09_document_round_trip(self):
        d=ReportEvidenceDocument("D",clauses=[ReportClauseResult("R","1",reported_verdict=ReportedVerdict.PASS)]); self.assertEqual(ReportEvidenceDocument.from_dict(json.loads(d.to_json())).to_dict(),d.to_dict())
    def test_10_nested_measurement_round_trip(self):
        m=ReportMeasurement("M",value=1.2,unit="mA"); ev=ReportEvidenceItem("E",ReportEvidenceType.MEASUREMENT,measurements=[m]); d=ReportEvidenceDocument("D",unmapped_sections=[ev]); self.assertEqual(ReportEvidenceDocument.from_dict(d.to_dict()).to_dict(),d.to_dict())


if __name__=="__main__": unittest.main(verbosity=2)
