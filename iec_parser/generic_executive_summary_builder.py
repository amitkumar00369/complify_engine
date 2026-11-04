"""Create deterministic end-user summaries from structured issue and action data."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ExecutiveFinding:
    """A concise presentation view of one aggregate issue group."""

    finding_type: str
    title: str
    summary: str
    affected_issue_count: int
    affected_clause_count: int
    affected_requirement_group_count: int
    highest_severity: str
    compliance_conclusion_summary: Dict[str, int]
    aggregate_group_ids: List[str]
    diagnostic_categories: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutiveAction:
    """An unchanged presentation view of one prioritized action."""

    action_id: str
    priority_level: str
    action_type: str
    title: str
    reason: str
    expected_outcome: str
    affected_issue_count: int
    affected_clause_count: int
    dependency: Dict[str, Any]


@dataclass
class ExecutiveComplianceSummary:
    """Status-neutral presentation generated from upstream structured results."""

    schema_version: str
    headline: str
    executive_summary: str
    main_findings: List[ExecutiveFinding]
    other_finding_count: int
    all_aggregate_group_ids: List[str]
    unresolved_summary: Dict[str, Any]
    recommended_next_actions: List[ExecutiveAction]
    action_summary_text: str
    affected_scope_summary: Dict[str, int]
    severity_summary: Dict[str, Any]
    issue_category_summary: Dict[str, Dict[str, int]]
    action_summary: Dict[str, Dict[str, int]]
    metadata: Dict[str, Any]
    accounting: Dict[str, Any]
    quality_audit: Dict[str, int]
    genericity_audit: Dict[str, int]
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    professional_judgment: Dict[str, Any] = field(default_factory=dict)


class GenericExecutiveSummaryBuilder:
    """Present existing findings and actions without performing evaluation."""

    SEVERITY_RANK = {"UNKNOWN": 0, "INFO": 1, "LOW": 2, "MEDIUM": 3, "HIGH": 4, "CRITICAL": 5}
    ISSUE_TEXT = {
        "TRACEABILITY_ISSUE": "Product, sample, or evidence traceability is incomplete for some evaluated requirements.",
        "APPLICABILITY_JUSTIFICATION_REQUIRED": "Some requirements treated as not applicable do not yet have sufficient supporting justification.",
        "MISSING_EVIDENCE": "Required evidence was not found for some evaluated requirements.",
        "INSUFFICIENT_EVIDENCE": "Evidence is present for some requirements, but it is not sufficient to support a reliable conclusion.",
        "UNRESOLVED_EVIDENCE_CONFLICT": "Some report evidence remains unresolved and requires clarification from an authoritative source.",
        "CONFIRMED_NONCOMPLIANCE": "Upstream evaluation identified confirmed non-compliant findings requiring attention.",
        "INVALID_TEST_EVIDENCE": "Some submitted test evidence was identified upstream as invalid.",
        "CALCULATION_ISSUE": "Some structured calculations require correction or verification.",
        "TEST_CONDITION_ISSUE": "Some test conditions require review or correction.",
        "REPORT_DATA_INCONSISTENCY": "Some structured report information requires reconciliation or correction.",
    }
    DIAGNOSTIC_TEXT={"IDENTITY_RELATIONSHIP_UNRESOLVED":"The report contains unresolved product-identity relationships between declared and tested models.","APPLICABILITY_EXECUTION_CONFLICT":"At least one test is reported as performed even though the structured applicability result resolves that test as not applicable.","RATING_CONFLICT":"Structured product-rating information remains inconsistent.","TEST_CONDITION_MISMATCH":"At least one reported test condition does not match its structured required basis.","CALCULATION_MISMATCH":"At least one reported calculation is inconsistent with its structured inputs.","LIMIT_EXCEEDED":"At least one structured measured result exceeds its applicable limit.","UNIT_OR_PARAMETER_AMBIGUITY":"Some reported values cannot be compared reliably because their parameter relationship is unresolved."}
    QUALITY_KEYS = (
        "aggregate_conclusion_modified", "aggregate_severity_modified", "action_priority_modified",
        "action_type_modified", "action_dependency_modified", "aggregate_group_lost", "action_lost",
        "unresolved_treated_as_noncompliance", "not_evaluated_treated_as_failure", "new_noncompliance_created",
        "readiness_score_created", "overall_report_status_created", "certification_claim_created",
        "product_safety_claim_created", "standard_specific_production_branch", "product_specific_production_branch",
        "clause_specific_production_branch", "page_specific_production_branch", "model_specific_production_branch",
        "report_specific_production_branch", "fixture_specific_production_branch", "upstream_artifact_mutated",
    )

    def __init__(self, main_finding_limit: int = 5):
        if main_finding_limit < 0:
            raise ValueError("main_finding_limit must be non-negative")
        self.main_finding_limit = main_finding_limit

    def build(self, aggregated_report: Any, action_plan: Any) -> ExecutiveComplianceSummary:
        """Build a concise, repeatable summary from Step 26 and 27 outputs."""
        aggregate = self._plain(aggregated_report)
        plan = self._plain(action_plan)
        groups = list(aggregate.get("actionable_groups", []) or [])
        actions = list(plan.get("actions", []) or [])
        action_tier = {str(gid): int(action.get("priority_level") or 4) for action in actions for gid in (action.get("affected_aggregate_group_ids") or [])}
        ordered_groups = sorted(groups, key=lambda x: self._finding_sort(x, action_tier))
        main = [self._finding(x) for x in ordered_groups[:self.main_finding_limit]]
        all_group_ids = self._unique(x.get("group_id") for x in groups)
        executive_actions = [self._action(x) for x in actions]

        category_summary: Dict[str, Dict[str, int]] = {}
        for group in groups:
            category = str(group.get("issue_type") or "UNKNOWN")
            record = category_summary.setdefault(category, {"aggregate_group_count": 0, "individual_issue_count": 0})
            record["aggregate_group_count"] += 1
            record["individual_issue_count"] += int(group.get("issue_count") or 0)
        category_summary = dict(sorted(category_summary.items()))

        conclusions = Counter()
        individual_severity = Counter()
        group_severity = Counter()
        for group in groups:
            conclusions.update({str(k): int(v) for k, v in (group.get("conclusion_summary") or {}).items()})
            severity = group.get("severity_summary") or {}
            highest = self._severity(severity.get("highest")); group_severity[highest] += 1
            for name in self.SEVERITY_RANK:
                individual_severity[name] += int(severity.get(name.casefold()) or 0)
        highest = max(group_severity, key=lambda x: self.SEVERITY_RANK.get(x, 0)) if group_severity else "UNKNOWN"
        unresolved = {
            "unresolved_issue_count": conclusions["UNRESOLVED"],
            "not_evaluated_issue_count": conclusions["NOT_EVALUATED"],
            "noncompliant_issue_count": conclusions["NONCOMPLIANT"],
            "compliant_issue_count": conclusions["COMPLIANT"],
            "text": self._unresolved_text(conclusions),
        }
        clauses = self._unique(v for x in groups for v in (x.get("affected_clauses") or []))
        requirement_groups = self._unique(v for x in groups for v in (x.get("requirement_group_ids") or []))
        issue_ids = self._unique(v for x in groups for v in (x.get("issue_ids") or []))
        scope = {"aggregate_group_count": len(groups), "actionable_issue_count": len(issue_ids), "unique_clause_count": len(clauses), "unique_requirement_group_count": len(requirement_groups), "planned_action_count": len(actions)}
        severity_summary = {"highest_severity": highest, "aggregate_groups_by_highest_severity": dict(sorted(group_severity.items())), "individual_issues_by_severity": dict(sorted((k, v) for k, v in individual_severity.items() if v))}
        action_summary = {"by_action_type": dict(sorted(Counter(str(x.get("action_type") or "UNKNOWN") for x in actions).items())), "by_priority_level": dict(sorted(Counter(self._priority_label(x) for x in actions).items()))}
        present_types = sorted(category_summary)
        headline = "Additional information and evidence are required" if groups else "No actionable evaluation findings are currently summarized"
        diagnostic_types=self._unique(v for x in groups for v in (x.get("diagnostic_finding_types") or []))
        executive_text = self._executive_text(present_types, bool(groups),diagnostic_types)
        action_text = self._action_text(actions)

        action_ids = self._unique(x.get("action_id") for x in actions)
        represented_action_ids = self._unique(x.action_id for x in executive_actions)
        represented_group_ids = all_group_ids
        group_lost = sorted(set(all_group_ids) - set(represented_group_ids))
        action_lost = sorted(set(action_ids) - set(represented_action_ids))
        accounting = {"aggregate_groups_accounted_for": len(all_group_ids) - len(group_lost), "aggregate_groups_unaccounted_for": len(group_lost), "actions_accounted_for": len(action_ids) - len(action_lost), "actions_unaccounted_for": len(action_lost), "all_aggregate_groups_accounted_for": not group_lost, "all_actions_accounted_for": not action_lost}
        source_ids = {"aggregated_report": aggregate.get("source_final_issue_report_id"), "action_plan": plan.get("source_aggregated_report_id")}
        metadata = {"source_aggregate_group_count": len(groups), "source_action_count": len(actions), "main_finding_limit": self.main_finding_limit, "source_ids": source_ids}
        quality = {key: 0 for key in self.QUALITY_KEYS}; quality["aggregate_group_lost"] = len(group_lost); quality["action_lost"] = len(action_lost)
        genericity = {key: quality[key] for key in quality if key.endswith("_production_branch")}
        diagnostics = ([{"code": "UNACCOUNTED_AGGREGATE_GROUPS", "ids": group_lost}] if group_lost else []) + ([{"code": "UNACCOUNTED_ACTIONS", "ids": action_lost}] if action_lost else [])
        judgment=copy.deepcopy(aggregate.get("professional_judgment") or {})
        return ExecutiveComplianceSummary("1.1", headline, executive_text, main, max(0, len(groups) - len(main)), all_group_ids, unresolved, executive_actions, action_text, scope, severity_summary, category_summary, action_summary, metadata, accounting, quality, genericity, diagnostics,judgment)

    def _finding(self, group: Mapping[str, Any]) -> ExecutiveFinding:
        issue_type = str(group.get("issue_type") or "UNKNOWN")
        diagnostics=self._unique(group.get("diagnostic_finding_types") or [])
        summary=" ".join(self.DIAGNOSTIC_TEXT[x] for x in diagnostics if x in self.DIAGNOSTIC_TEXT) or self.ISSUE_TEXT.get(issue_type, str(group.get("summary") or "A structured evaluation finding requires review."))
        return ExecutiveFinding(issue_type, str(group.get("title") or "Evaluation finding requires review"), summary, int(group.get("issue_count") or 0), int(group.get("affected_clause_count") or 0), int(group.get("affected_requirement_group_count") or 0), self._severity((group.get("severity_summary") or {}).get("highest")), {str(k): int(v) for k, v in (group.get("conclusion_summary") or {}).items()}, self._unique([group.get("group_id")]),diagnostics)

    @staticmethod
    def _action(action: Mapping[str, Any]) -> ExecutiveAction:
        return ExecutiveAction(str(action.get("action_id") or ""), GenericExecutiveSummaryBuilder._priority_label(action), str(action.get("action_type") or ""), str(action.get("title") or ""), str(action.get("reason") or ""), str(action.get("expected_outcome") or ""), int(action.get("affected_issue_count") or 0), int(action.get("unique_clause_count") or 0), copy.deepcopy(action.get("dependency") or {}))

    def _finding_sort(self, group: Mapping[str, Any], action_tier: Mapping[str, int]) -> Tuple[Any, ...]:
        severity = self._severity((group.get("severity_summary") or {}).get("highest"))
        gid = str(group.get("group_id") or "")
        return (-self.SEVERITY_RANK.get(severity, 0), action_tier.get(gid, 4), -int(group.get("issue_count") or 0), str(group.get("issue_type") or ""), gid)

    def _executive_text(self, issue_types: Sequence[str], has_groups: bool,diagnostic_types:Sequence[str]=()) -> str:
        if not has_groups:
            return "The structured inputs contain no actionable aggregate findings to summarize."
        descriptions = [self.ISSUE_TEXT.get(x, "A structured evaluation finding requires review.") for x in issue_types]+[self.DIAGNOSTIC_TEXT[x] for x in diagnostic_types if x in self.DIAGNOSTIC_TEXT]
        return "The report contains unresolved or incomplete evaluation findings. " + " ".join(descriptions) + " Additional information or clarification is required before a reliable final compliance conclusion can be made."

    @staticmethod
    def _unresolved_text(conclusions: Mapping[str, int]) -> str:
        if conclusions.get("UNRESOLVED", 0) or conclusions.get("NOT_EVALUATED", 0):
            return "Some findings remain unresolved or could not yet be evaluated because required information or evidence is incomplete."
        return "No unresolved or not-evaluated findings are represented in the structured input."

    @staticmethod
    def _action_text(actions: Sequence[Mapping[str, Any]]) -> str:
        if not actions: return "No recommended actions are represented in the structured action plan."
        tiers: Dict[str, List[str]] = {}
        for action in actions: tiers.setdefault(GenericExecutiveSummaryBuilder._priority_label(action), []).append(str(action.get("title") or action.get("action_type") or "the stated action"))
        phrases = []
        labels = (("DO_FIRST", "The first actions are"), ("DO_NEXT", "The next actions are"), ("FOLLOW_UP", "Follow-up actions are"), ("OPTIONAL_OR_REVIEW", "Additional review actions are"))
        for level, prefix in labels:
            if level in tiers: phrases.append(prefix + " " + GenericExecutiveSummaryBuilder._join(tiers[level]) + ".")
        return " ".join(phrases)

    @staticmethod
    def _join(values: Sequence[str]) -> str:
        if len(values) == 1: return values[0]
        if len(values) == 2: return values[0] + " and " + values[1]
        return ", ".join(values[:-1]) + ", and " + values[-1]

    @staticmethod
    def _priority_label(action: Mapping[str, Any]) -> str:
        label = action.get("priority_label")
        if label: return str(label)
        value = action.get("priority_level")
        return {1: "DO_FIRST", 2: "DO_NEXT", 3: "FOLLOW_UP", 4: "OPTIONAL_OR_REVIEW"}.get(int(value or 4), str(value or "OPTIONAL_OR_REVIEW"))

    @classmethod
    def _severity(cls, value: Any) -> str:
        result = str(value.value if isinstance(value, Enum) else value or "UNKNOWN")
        return result if result in cls.SEVERITY_RANK else "UNKNOWN"

    @staticmethod
    def _unique(values: Iterable[Any]) -> List[str]:
        return sorted({str(v.value if isinstance(v, Enum) else v) for v in values if v is not None and str(v) != ""})

    @classmethod
    def _plain(cls, value: Any) -> Any:
        if isinstance(value, Enum): return value.value
        if is_dataclass(value): return cls._plain(asdict(value))
        if isinstance(value, Mapping): return {str(k): cls._plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)): return [cls._plain(v) for v in value]
        return copy.deepcopy(value)

    @classmethod
    def to_dict(cls, summary: ExecutiveComplianceSummary) -> Dict[str, Any]:
        """Convert an executive summary to JSON-compatible primitives."""
        if not is_dataclass(summary): raise TypeError("executive compliance summary required")
        return cls._plain(asdict(summary))

    @classmethod
    def to_json(cls, summary: ExecutiveComplianceSummary, indent: int = 2) -> str:
        """Serialize an executive summary deterministically."""
        return json.dumps(cls.to_dict(summary), ensure_ascii=False, sort_keys=True, indent=indent)

    @classmethod
    def save_json(cls, summary: ExecutiveComplianceSummary, path: Any) -> Path:
        """Write a summary without modifying either input artifact."""
        target = Path(path); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(cls.to_json(summary) + "\n", encoding="utf-8"); return target


__all__ = ["ExecutiveAction", "ExecutiveComplianceSummary", "ExecutiveFinding", "GenericExecutiveSummaryBuilder"]
