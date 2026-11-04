"""Step 31N regression tests for generic primary-standard role handling."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from iec_par.generic_compliance_pipeline_runner import (
    GenericCompliancePipelineRunner, StandardValidationStatus,
)
from iec_par.generic_iec_document_parser import GenericIECDocumentParser
from iec_par.generic_iec_kb_builder import GenericIECKnowledgeBaseBuilder
from iec_par.generic_iec_kb_models import DocumentType, StandardDocument


class _State:
    document = StandardDocument(standard_id="IEC_12345_2020", standard_number="IEC 12345",
                                year=2020, document_type=DocumentType.OTHER)


class _DocumentParser:
    def __init__(self, path): self.path = path
    def parse(self): return _State.document


class _StructuralParser:
    def __init__(self, path): self.path = path
    def parse(self): return []


class PrimaryStandardRoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.pdf = Path(self.temp.name) / "standard.pdf"
        self.pdf.write_bytes(b"%PDF-stub")
        self.builder = GenericIECKnowledgeBaseBuilder(
            document_parser_cls=_DocumentParser, structural_parser_cls=_StructuralParser
        )

    def tearDown(self): self.temp.cleanup()

    def test_01_standalone_primary_without_part_suffix(self):
        doc = GenericIECDocumentParser.parse_text("IEC 12345:2020 Edition 1.0")
        self.assertEqual((doc.part_number, doc.document_type), (None, DocumentType.OTHER))

    def test_02_standalone_part_one_still_classifies_base(self):
        doc = GenericIECDocumentParser.parse_text("IEC 12345-1:2020 Edition 1.0")
        self.assertEqual((doc.part_number, doc.document_type), ("1", DocumentType.BASE))

    def test_03_paired_base_builder_remains_strict(self):
        with self.assertRaisesRegex(ValueError, "BASE standard"):
            self.builder.build_base_kb(self.pdf)

    def test_04_companion_role_remains_part_two(self):
        doc = GenericIECDocumentParser.parse_text("IEC 12345-2-7:2020 Edition 1.0")
        self.assertEqual((doc.document_type, doc.parent_standard),
                         (DocumentType.PART_2, "IEC 12345-1"))

    def test_05_no_fixture_specific_production_branch(self):
        files = ["generic_iec_document_parser.py", "generic_iec_kb_builder.py",
                 "generic_iec_kb_validator.py", "generic_compliance_pipeline_runner.py"]
        text = "\n".join((ROOT / "iec_par" / name).read_text().lower()
                         for name in files)
        self.assertNotIn("60065", text)
        self.assertNotIn("speaker", text)

    def test_06_primary_builder_accepts_other_identified_standard(self):
        kb = self.builder.build_primary_kb(self.pdf)
        self.assertEqual(kb.document.document_type, DocumentType.OTHER)

    def test_07_primary_builder_rejects_companion(self):
        _State.document = StandardDocument(standard_id="S", standard_number="IEC 12345-2-7",
            document_type=DocumentType.PART_2, parent_standard="IEC 12345-1")
        with self.assertRaisesRegex(ValueError, "non-companion"):
            self.builder.build_primary_kb(self.pdf)
        _State.document = StandardDocument(standard_id="IEC_12345_2020",
            standard_number="IEC 12345", year=2020, document_type=DocumentType.OTHER)

    def test_08_bare_and_year_suffixed_identity_align(self):
        result = GenericCompliancePipelineRunner().validate_standard_set(
            {"document": {"standard_number": "IEC 12345", "year": 2020}}, None,
            {"standard_numbers": ["IEC 12345-2020", "IEC 12345"]}, True)
        self.assertEqual(result.status, StandardValidationStatus.VALID)

    def test_09_edition_validation_remains_strict(self):
        result = GenericCompliancePipelineRunner().validate_standard_set(
            {"document": {"standard_number": "IEC 12345", "year": 2020}}, None,
            {"standard_numbers": ["IEC 12345-2019"]}, True)
        self.assertEqual(result.status, StandardValidationStatus.STANDARD_MISMATCH)

    def test_10_first_run_passed_original_base_kb_failure(self):
        manifest = self._artifact("iec_60065_speaker_post_31n", "manifest/pipeline_manifest.json")
        record = next(x for x in manifest["step_execution_records"] if x["step_name"] == "base_kb")
        self.assertEqual(record["status"], "PASS")

    def test_11_v1_structural_architecture_preserved(self):
        validation = self._artifact("iec_60065_speaker_post_31n", "standards/base_validation.json")
        self.assertTrue(validation["summary"]["valid"])
        self.assertGreater(validation["summary"]["structural"]["clauses"], 0)

    def test_12_v1_accepted_family_regressions_completed(self):
        names = ["washing_machine_post_31n", "submersible_pump_post_31n",
                 "plastic_tube_welding_tools_post_31n", "iec_60204_1_post_31n",
                 "iec_62841_impact_drill_post_31n", "iec_61427_1_battery_post_31n"]
        self.assertTrue(all(self._artifact(n, "manifest/pipeline_manifest.json")
                            ["pipeline_status"] == "SUCCESS_WITH_REVIEW" for n in names))

    def test_13_second_report_keeps_standard_kb_deterministic(self):
        first = ROOT / "test_reports/output/iec_60065_speaker_post_31n/standards/base_kb.json"
        second = ROOT / "test_reports/output/iec_60065_speaker_radio_post_31n/standards/base_kb.json"
        digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(digest(first), digest(second))

    def test_14_historical_v1_freeze_artifact_unchanged(self):
        path = ROOT / "test_reports/regression_results/step_31me_deterministic_compliance_engine_v1_freeze.json"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         "adb2184fe9bf7a409fc3f03e8bfb991366e16fb8f7207d0f294e7a3e29b17453")

    @staticmethod
    def _artifact(run, relative):
        return json.loads((ROOT / "test_reports/output" / run / relative).read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
