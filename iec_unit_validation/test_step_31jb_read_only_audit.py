"""Read-only acceptance checks for the Step 31J-B audit artifact."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from iec_par.generic_cross_family_evaluation_audit import (
    AuditClassification,
    GenericCrossFamilyEvaluationAudit,
)


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "test_reports/output/iec_62841_impact_drill_post_31ja"
AUDIT_PATH = ROOT / "test_reports/regression_results/step_31jb_iec_62841_accuracy_root_cause_audit.json"
V2_PATH = ROOT / "test_reports/regression_results/step_31id_cross_family_controlled_pilot_freeze.json"
STEP_31JA_PATH = ROOT / "test_reports/regression_results/step_31ja_qualified_delta_operation_handling.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def aggregate_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


class Step31JBAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.audit = load(AUDIT_PATH)
        cls.tracer = GenericCrossFamilyEvaluationAudit(RUN)

    def test_01_read_only_mode(self) -> None:
        self.assertEqual(self.audit["mode"], "READ_ONLY_AUDIT")

    def test_02_sample_size(self) -> None:
        self.assertGreaterEqual(self.audit["sample"]["generated_issue_probes"], 35)

    def test_03_all_major_categories(self) -> None:
        for key in ("applicability", "traceability", "missing_evidence", "insufficient_evidence", "conflicts"):
            self.assertGreater(self.audit["sample"][key], 0)

    def test_04_every_generated_probe_classified_once(self) -> None:
        groups = self.audit["classification"]["generated_issue_ids"]
        identifiers = [item for values in groups.values() for item in values]
        self.assertEqual(len(identifiers), 64)
        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_05_classification_values_valid(self) -> None:
        for value in self.audit["classification"]["generated_issue_ids"]:
            self.assertIsInstance(self.tracer.classify(value), AuditClassification)

    def test_06_qualified_replacement_trace(self) -> None:
        trace = self.tracer.trace(clause_id="17.2")
        self.assertTrue(trace.effective_requirements)
        self.assertEqual(self.audit["effective_kb_probes"]["17.2"]["source_directive"], "Replacement for impact drills")

    def test_07_table_replacement_trace(self) -> None:
        self.assertEqual(self.audit["effective_kb_probes"]["18.8"]["target_scope"], "TABLE")

    def test_08_partial_replacement_trace(self) -> None:
        probe = self.audit["effective_kb_probes"]["23.3"]
        self.assertTrue(probe["later_base_content_retained"])
        self.assertFalse(probe["full_clause_replacement_occurred"])

    def test_09_101_series_trace(self) -> None:
        self.assertEqual(self.audit["series_101_audit"]["19.102"]["effective_descendants_present"], [])

    def test_10_report_evidence_trace(self) -> None:
        trace = self.tracer.trace(final_issue_id="FINAL-ISSUE-EEEFA74A1730AE9BFB0D")
        self.assertGreaterEqual(len(trace.report_evidence), 2)

    def test_11_model_identity_trace(self) -> None:
        profile = self.audit["product_profile_audit"]
        self.assertEqual(profile["tested_model"], "ID6808")
        self.assertTrue(profile["tested_model_role_captured"])

    def test_12_numeric_constraint_trace(self) -> None:
        raw = {item["raw"] for item in self.audit["technical_measurement_audit"]["unresolved_constraints"]}
        self.assertEqual(raw, {"12 h", "120 V", "100 Nm", "25 mm"})

    def test_13_amendment_alignment(self) -> None:
        self.assertEqual(self.audit["amendment_alignment"]["status"], "AMENDMENT_MISSING")

    def test_14_all_classification_categories_exercised(self) -> None:
        counts = self.audit["classification"]
        for key in ("true_positive", "false_positive", "false_negative", "correct_but_too_generic", "unresolved"):
            self.assertGreater(counts[key], 0)

    def test_15_deterministic_first_fault(self) -> None:
        result = self.tracer.first_incorrect_stage({"base_kb": True, "delta_kb": False, "effective_kb": False})
        self.assertEqual(result, "delta_kb")

    def test_16_run_artifacts_immutable(self) -> None:
        self.assertEqual(aggregate_hash(RUN), self.audit["immutability"]["iec_62841_run_aggregate_sha256_before"])

    def test_17_frozen_artifacts_immutable(self) -> None:
        self.assertEqual(hashlib.sha256(V2_PATH.read_bytes()).hexdigest(), self.audit["immutability"]["v2_freeze_sha256_before"])
        self.assertEqual(hashlib.sha256(STEP_31JA_PATH.read_bytes()).hexdigest(), self.audit["immutability"]["step_31ja_sha256_before"])

    def test_18_no_specific_production_branch(self) -> None:
        paths = [ROOT / "iec_par" / name for name in (
            "generic_cross_family_evaluation_audit.py", "generic_iec_effective_kb_builder.py",
            "generic_report_evidence_extractor.py", "generic_report_product_profile_builder.py",
        )]
        production = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
        for forbidden in ("id6808", "62841", "impact drill"):
            self.assertNotIn(forbidden, production)

    def test_19_deterministic_serialization(self) -> None:
        self.assertEqual(json.dumps(self.audit, sort_keys=True), json.dumps(load(AUDIT_PATH), sort_keys=True))

    def test_20_no_freeze_or_next_step(self) -> None:
        self.assertFalse(self.audit["quality"]["v3_created"])
        self.assertFalse(self.audit["quality"]["step_31jc_started"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
