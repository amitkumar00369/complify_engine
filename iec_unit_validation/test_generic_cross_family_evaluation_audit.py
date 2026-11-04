"""Tests for the read-only cross-family evaluation tracer."""
import json
import inspect
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iec_par.generic_cross_family_evaluation_audit import (
    AuditClassification,
    GenericCrossFamilyEvaluationAudit,
)


class GenericCrossFamilyEvaluationAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        payloads = {
            "standards/base_kb.json": {"clauses": [{"clause_id": "5.1", "requirements": [{"requirement_id": "5.1-R1", "text": "shall"}], "children": []}], "annexes": []},
            "standards/effective_kb.json": {"clauses": [{"clause_id": "5.1", "requirements": [{"effective_requirement_id": "E-5.1-R1", "text": "shall", "base_sources": [{"clause_id": "5.1"}]}], "children": []}], "annexes": []},
            "report/report_evidence.json": {"clauses": [{"clause_id": "5.1", "evidence_items": [{"evidence_id": "EV-1", "clause_id": "5.1"}], "children": []}], "unmapped_sections": []},
            "report/applicability_result.json": {"results": [{"clause_id": "5.1", "effective_requirement_id": "E-5.1-R1"}]},
            "report/evidence_match_result.json": {"matches": [{"clause_id": "5.1", "effective_requirement_id": "E-5.1-R1", "evidence_refs": [{"evidence_id": "EV-1"}]}]},
            "decisions/final_requirement_decision.json": {"results": [{"clause_id": "5.1", "effective_requirement_id": "E-5.1-R1"}]},
            "decisions/final_compliance_issues.json": {"issues": [{"issue_id": "I-1", "clause_id": "5.1", "requirement_ids": ["E-5.1-R1"], "evidence_refs": ["EV-1"]}]},
        }
        for relative, payload in payloads.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload), encoding="utf-8")
        self.audit = GenericCrossFamilyEvaluationAudit(root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_loads_all_required_artifacts(self): self.assertEqual(7, len(self.audit.artifacts))
    def test_trace_by_clause(self): self.assertEqual(1, len(self.audit.trace(clause_id="5.1").standard_requirements))
    def test_trace_by_requirement(self): self.assertEqual(1, len(self.audit.trace(requirement_id="E-5.1-R1").effective_requirements))
    def test_trace_by_evidence(self): self.assertEqual("EV-1", self.audit.trace(evidence_id="EV-1").report_evidence[0]["evidence_id"])
    def test_trace_by_issue(self): self.assertEqual("I-1", self.audit.trace(final_issue_id="I-1").final_issues[0]["issue_id"])
    def test_trace_infers_requirement_from_issue(self): self.assertEqual(1, len(self.audit.trace(final_issue_id="I-1").effective_requirements))
    def test_trace_infers_evidence_from_issue(self): self.assertEqual(1, len(self.audit.trace(final_issue_id="I-1").report_evidence))
    def test_trace_includes_applicability(self): self.assertEqual(1, len(self.audit.trace(clause_id="5.1").applicability))
    def test_trace_includes_matches(self): self.assertEqual(1, len(self.audit.trace(clause_id="5.1").evidence_matches))
    def test_trace_includes_decisions(self): self.assertEqual(1, len(self.audit.trace(clause_id="5.1").final_decisions))
    def test_trace_includes_source_references(self): self.assertEqual("5.1", self.audit.trace(clause_id="5.1").source_references[0]["clause_id"])
    def test_unknown_clause_is_empty(self): self.assertFalse(self.audit.trace(clause_id="99").effective_requirements)
    def test_classify_true_positive(self): self.assertEqual(AuditClassification.TRUE_POSITIVE, self.audit.classify("TRUE_POSITIVE"))
    def test_classify_false_positive(self): self.assertEqual(AuditClassification.FALSE_POSITIVE, self.audit.classify("FALSE_POSITIVE"))
    def test_classify_false_negative(self): self.assertEqual(AuditClassification.FALSE_NEGATIVE, self.audit.classify("FALSE_NEGATIVE"))
    def test_classify_correct_but_too_generic(self): self.assertEqual(AuditClassification.CORRECT_BUT_TOO_GENERIC, self.audit.classify("CORRECT_BUT_TOO_GENERIC"))
    def test_classify_unresolved(self): self.assertEqual(AuditClassification.UNRESOLVED_AUDIT, self.audit.classify("UNRESOLVED_AUDIT"))
    def test_classify_enum(self): self.assertEqual(AuditClassification.FALSE_NEGATIVE, self.audit.classify(AuditClassification.FALSE_NEGATIVE))
    def test_invalid_classification_rejected(self): self.assertRaises(ValueError, self.audit.classify, "INVALID")
    def test_first_incorrect_stage(self): self.assertEqual("match", self.audit.first_incorrect_stage({"parse": True, "match": False, "decision": False}))
    def test_no_incorrect_stage(self): self.assertIsNone(self.audit.first_incorrect_stage({"parse": True}))
    def test_hashes_cover_inputs(self): self.assertEqual(set(self.audit.PATHS), set(self.audit.artifact_hashes()))
    def test_json_is_deterministic(self):
        trace = self.audit.trace(clause_id="5.1")
        self.assertEqual(self.audit.to_json(trace), self.audit.to_json(trace))
    def test_trace_result_does_not_mutate_artifacts(self):
        before = self.audit.artifact_hashes()
        trace = self.audit.trace(clause_id="5.1")
        trace.report_evidence[0]["evidence_id"] = "changed"
        self.assertEqual("EV-1", self.audit.trace(clause_id="5.1").report_evidence[0]["evidence_id"])
        self.assertEqual(before, self.audit.artifact_hashes())
    def test_tracer_has_no_production_evaluation_imports(self):
        source = inspect.getsource(__import__("iec_par.generic_cross_family_evaluation_audit", fromlist=["*"]))
        self.assertNotIn("generic_compliance_pipeline_runner", source)
        self.assertNotIn("generic_final_requirement_decision", source)
    def test_tracer_has_no_fixture_specific_branches(self):
        source = inspect.getsource(__import__("iec_par.generic_cross_family_evaluation_audit", fromlist=["*"]))
        for forbidden in ("60204", "9.2.3.1", "TST2025", "BABY/4BU"):
            self.assertNotIn(forbidden, source)
    def test_missing_run_directory_rejected(self):
        self.assertRaises(FileNotFoundError, GenericCrossFamilyEvaluationAudit, Path(self.tmp.name) / "missing")
    def test_missing_artifact_rejected(self):
        (Path(self.tmp.name) / "standards/base_kb.json").unlink()
        self.assertRaises(FileNotFoundError, GenericCrossFamilyEvaluationAudit, self.tmp.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
