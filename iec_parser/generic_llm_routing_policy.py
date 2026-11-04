"""Deterministic policy for routing resolved compliance contexts (Step 32-B)."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence, Set

from .generic_llm_routing_models import (
    AllowedLLMTask as Task, LLMDecisionAuthority as Authority, LLMRoute as Route,
    LLMRoutingDecision, LLMRoutingResult,
)


class GenericLLMRoutingPolicy:
    """Assign exactly one auditable route without invoking or prompting a model."""

    POLICY_VERSION = "LLM_ROUTING_POLICY_V1"
    SCHEMA_VERSION = "1.0"
    CONFIDENCE_POLICY = "ADVISORY_OUTPUT_REQUIRES_DOWNSTREAM_VALIDATION"
    ALL_TASKS = tuple(Task)

    SOURCE_GAPS = {"STANDARD_SOURCE_GAP", "AMENDMENT_MISSING", "STANDARD_SET_INCOMPLETE", "STANDARD_MISMATCH"}
    MISSING_EVIDENCE = {"MISSING_EVIDENCE", "MISSING_REPORT_EVIDENCE", "MISSING_MEASUREMENT", "TEST_METHOD_EVIDENCE_GAP", "TEST_METHOD_INCOMPLETE", "INSUFFICIENT_EVIDENCE"}
    MISSING_PRODUCT = {"MISSING_PRODUCT_INFORMATION", "PRODUCT_DATA_GAP"}
    UNKNOWN_APPLICABILITY = {"UNKNOWN_APPLICABILITY"}
    NA_AMBIGUITY = {"NA_APPLICABILITY_CONFLICT", "NA_CONFLICT_GAP", "APPLICABILITY_JUSTIFICATION_REQUIRED", "INVALID_NA"}
    KB_AMBIGUITY = {"KB_SEMANTIC_UNRESOLVED", "KB_REVIEW_GAP"}
    SCOPE_AMBIGUITY = {"AMBIGUOUS_REPORT_SCOPE", "REPORT_SCOPE_GAP"}
    CONFLICTING_EVIDENCE = {"CONFLICTING_REPORT_VERDICT", "CONFLICTING_EVIDENCE", "CONFLICTING_EVIDENCE_GAP", "UNRESOLVED_EVIDENCE_CONFLICT"}
    EVIDENCE_AMBIGUITY = {"EVIDENCE_SEMANTIC_AMBIGUITY", "EVIDENCE_MATCH_AMBIGUOUS", "EVIDENCE_NOT_LINKED"}
    GROUPED_AMBIGUITY = {"GROUPED_EVIDENCE_AMBIGUITY", "GROUPED_EVIDENCE_UNRESOLVED"}
    CONFIRMED_ISSUES = {"CONFIRMED_NONCOMPLIANCE", "TECHNICAL_VIOLATION"}
    COMPLIANCE_STATES = {"COMPLIANT", "NON_COMPLIANT", "NONCOMPLIANT", "CONFIRMED_NONCOMPLIANCE"}
    NUMERIC_STATES = {"SATISFIES", "VIOLATES"}

    def route_run(self, run_directory: str | Path, output_path: str | Path | None = None) -> LLMRoutingResult:
        root = Path(run_directory)
        source = root / "llm/resolved_compliance_context.json"
        if not source.is_file(): raise ValueError(f"missing Step 32-A artifact: {source}")
        bundle = json.loads(source.read_text(encoding="utf-8"))
        result = self.route_bundle(bundle)
        self.save_json(result, output_path or root / "llm/llm_routing_result.json")
        return result

    def route_bundle(self, resolved_context_bundle: Any) -> LLMRoutingResult:
        bundle = self._plain(resolved_context_bundle)
        routes = [self.route_context(context) for context in (bundle.get("contexts") or [])]
        accounting = self._accounting(routes)
        return LLMRoutingResult(self.SCHEMA_VERSION, bundle.get("run_id"), self.POLICY_VERSION, accounting, routes)

    def route_context(self, context: Any) -> LLMRoutingDecision:
        c = self._plain(context); integrity_record = c.get("resolution_integrity") or {}
        integrity = str(integrity_record.get("status") or "INVALID_REFERENCE").upper()
        semantics = self._semantic_codes(c)
        values = self._scalar_values(c)
        secondary = []

        if integrity == "INVALID_REFERENCE":
            secondary = self._integrity_reasons(integrity_record)
            return self._decision(c, integrity, Route.HUMAN_REVIEW, "INVALID_REFERENCE_CONTEXT", [], Authority.NO_DECISION_AUTHORITY, secondary=secondary)
        if integrity == "PARTIAL":
            return self._decision(c, integrity, Route.HUMAN_REVIEW, "PARTIAL_CONTEXT", [], Authority.NO_DECISION_AUTHORITY, secondary=self._integrity_reasons(integrity_record))
        if integrity != "COMPLETE" or integrity_record.get("duplicate_ids") or integrity_record.get("ambiguous_references") or integrity_record.get("cross_scope_conflicts"):
            secondary = self._integrity_reasons(integrity_record)
            return self._decision(c, integrity, Route.HUMAN_REVIEW, secondary[0] if secondary else "INVALID_REFERENCE_CONTEXT", [], Authority.NO_DECISION_AUTHORITY, secondary=secondary[1:])

        if semantics & self.SOURCE_GAPS:
            return self._decision(c, integrity, Route.DETERMINISTIC_ONLY, "STANDARD_SOURCE_GAP", [Task.CLIENT_EXPLANATION, Task.NEXT_ACTION_EXPLANATION], Authority.EXPLANATION_ONLY, deterministic=True, source=True)
        if values & self.NUMERIC_STATES:
            return self._decision(c, integrity, Route.DETERMINISTIC_ONLY, "CONFIRMED_NUMERIC_RESULT", [Task.CLIENT_EXPLANATION], Authority.EXPLANATION_ONLY, deterministic=True, numeric=True)
        if values & self.COMPLIANCE_STATES or semantics & self.CONFIRMED_ISSUES:
            return self._decision(c, integrity, Route.DETERMINISTIC_ONLY, "COMPLETE_DETERMINISTIC_RESULT", [Task.CLIENT_EXPLANATION], Authority.EXPLANATION_ONLY, deterministic=True)
        if semantics & self.MISSING_EVIDENCE:
            return self._decision(c, integrity, Route.DETERMINISTIC_ONLY, "TRUE_MISSING_EVIDENCE", [Task.CLIENT_EXPLANATION, Task.NEXT_ACTION_EXPLANATION], Authority.EXPLANATION_ONLY, deterministic=True)
        if semantics & self.MISSING_PRODUCT:
            return self._decision(c, integrity, Route.DETERMINISTIC_ONLY, "TRUE_MISSING_PRODUCT_DATA", [Task.CLIENT_EXPLANATION, Task.NEXT_ACTION_EXPLANATION], Authority.EXPLANATION_ONLY, deterministic=True)
        if semantics & self.UNKNOWN_APPLICABILITY:
            return self._candidate(c, integrity, "UNKNOWN_APPLICABILITY", [Task.APPLICABILITY_INTERPRETATION, Task.CLIENT_EXPLANATION])
        if semantics & self.NA_AMBIGUITY:
            return self._candidate(c, integrity, "NA_JUSTIFICATION_AMBIGUITY", [Task.NA_JUSTIFICATION_INTERPRETATION, Task.APPLICABILITY_INTERPRETATION, Task.CLIENT_EXPLANATION])
        if semantics & self.KB_AMBIGUITY:
            return self._candidate(c, integrity, "KB_SEMANTIC_AMBIGUITY", [Task.KB_SEMANTIC_INTERPRETATION, Task.CLIENT_EXPLANATION])
        if semantics & self.SCOPE_AMBIGUITY:
            return self._candidate(c, integrity, "REPORT_SCOPE_AMBIGUITY", [Task.REPORT_SCOPE_INTERPRETATION, Task.EVIDENCE_SEMANTIC_INTERPRETATION, Task.CLIENT_EXPLANATION])
        if semantics & self.CONFLICTING_EVIDENCE:
            return self._candidate(c, integrity, "CONFLICTING_EVIDENCE", [Task.GROUPED_EVIDENCE_INTERPRETATION, Task.EVIDENCE_SEMANTIC_INTERPRETATION, Task.CLIENT_EXPLANATION])
        if semantics & self.EVIDENCE_AMBIGUITY:
            return self._candidate(c, integrity, "EVIDENCE_SEMANTIC_AMBIGUITY", [Task.EVIDENCE_SEMANTIC_INTERPRETATION])
        if semantics & self.GROUPED_AMBIGUITY:
            return self._candidate(c, integrity, "GROUPED_EVIDENCE_AMBIGUITY", [Task.GROUPED_EVIDENCE_INTERPRETATION])
        return self._decision(c, integrity, Route.HUMAN_REVIEW, "UNRECOGNIZED_ROUTING_SEMANTICS", [], Authority.NO_DECISION_AUTHORITY)

    def _candidate(self, c, integrity, reason, tasks):
        return self._decision(c, integrity, Route.LLM_CANDIDATE, reason, tasks, Authority.INTERPRETATION_ONLY)

    def _decision(self, c, integrity, route, reason, tasks, authority, deterministic=False, source=False, numeric=False, secondary=None):
        allowed = sorted(set(tasks), key=lambda x: x.value)
        prohibited = [x for x in self.ALL_TASKS if x != Task.NO_LLM_TASK and x not in allowed]
        return LLMRoutingDecision(str(c.get("context_id") or ""), str(c.get("final_issue_id") or ""), route, reason,
            sorted(set(secondary or [])), integrity, allowed, prohibited, authority, route == Route.HUMAN_REVIEW,
            deterministic, source, numeric, self.CONFIDENCE_POLICY, self.POLICY_VERSION)

    @staticmethod
    def _integrity_reasons(record):
        reasons = []
        if record.get("duplicate_ids"): reasons.append("DUPLICATE_REFERENCE")
        if record.get("ambiguous_references"): reasons.append("AMBIGUOUS_REFERENCE")
        if record.get("missing_references"): reasons.append("UNRESOLVED_MANDATORY_REFERENCE")
        if record.get("cross_scope_conflicts"): reasons.append("CROSS_SCOPE_INTEGRITY_CONFLICT")
        return reasons

    @classmethod
    def _semantic_codes(cls, context: Mapping[str, Any]) -> Set[str]:
        result = set()
        interesting = {"issue_type", "originating_issue_type", "finding_type", "reason_code", "gap_type", "action_type"}
        def visit(value):
            if isinstance(value, Mapping):
                for key, child in value.items():
                    if key in interesting and child is not None and not isinstance(child, (dict, list)): result.add(str(child).upper())
                    visit(child)
            elif isinstance(value, list):
                for child in value: visit(child)
        visit(context)
        return result

    @staticmethod
    def _scalar_values(value: Any) -> Set[str]:
        result = set()
        def visit(item):
            if isinstance(item, Mapping):
                for child in item.values(): visit(child)
            elif isinstance(item, list):
                for child in item: visit(child)
            elif isinstance(item, (str, Enum)): result.add(str(item.value if isinstance(item, Enum) else item).upper())
        visit(value); return result

    @staticmethod
    def _accounting(routes: Sequence[LLMRoutingDecision]) -> Dict[str, Any]:
        by_route = Counter(x.route.value for x in routes); by_reason = Counter(x.primary_reason_code for x in routes)
        by_task = Counter(task.value for x in routes for task in x.allowed_llm_tasks); by_integrity = Counter(x.context_integrity for x in routes)
        return {"total_contexts": len(routes), "deterministic_only_count": by_route[Route.DETERMINISTIC_ONLY.value],
            "llm_candidate_count": by_route[Route.LLM_CANDIDATE.value], "human_review_count": by_route[Route.HUMAN_REVIEW.value],
            "by_reason_code": dict(sorted(by_reason.items())), "by_allowed_task": dict(sorted(by_task.items())),
            "by_context_integrity": dict(sorted(by_integrity.items())), "locked_numeric_count": sum(x.numeric_result_locked for x in routes),
            "locked_compliance_count": sum(x.primary_reason_code == "COMPLETE_DETERMINISTIC_RESULT" for x in routes), "source_gap_count": sum(x.source_gap_locked for x in routes),
            "invalid_reference_count": by_integrity["INVALID_REFERENCE"], "partial_context_count": by_integrity["PARTIAL"]}

    @classmethod
    def _plain(cls, value):
        if isinstance(value, Enum): return value.value
        if is_dataclass(value): return cls._plain(asdict(value))
        if isinstance(value, Mapping): return {str(k): cls._plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)): return [cls._plain(x) for x in value]
        return value

    @classmethod
    def to_dict(cls, result): return cls._plain(result)
    @classmethod
    def to_json(cls, result, indent=2): return json.dumps(cls.to_dict(result), ensure_ascii=False, sort_keys=True, indent=indent)
    @classmethod
    def save_json(cls, result, path):
        target = Path(path); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(cls.to_json(result) + "\n", encoding="utf-8"); return target


__all__ = ["GenericLLMRoutingPolicy"]
