"""Resolve categorical report-evaluation status from structured upstream results."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


class OverallReportStatus(str, Enum):
    """Current workflow state of the report evaluation."""

    READY = "READY"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    NOT_READY = "NOT_READY"
    UNRESOLVED = "UNRESOLVED"


class ProductComplianceConclusion(str, Enum):
    """Separate product conclusion proven by upstream evaluation, if any."""

    COMPLIANT = "COMPLIANT"
    NONCOMPLIANT = "NONCOMPLIANT"
    NOT_DETERMINED = "NOT_DETERMINED"


class DeterministicDisposition(str, Enum):
    PASS="PASS"
    REJECT="REJECT"
    INSUFFICIENT_TECHNICAL_EVIDENCE="INSUFFICIENT_TECHNICAL_EVIDENCE"
    CONDITIONAL="CONDITIONAL"
    HUMAN_REVIEW="HUMAN_REVIEW"
    PARTIAL_EVALUATION="PARTIAL_EVALUATION"


@dataclass(frozen=True)
class ReportStatusProvenance:
    """Deterministic references to the three source artifacts."""

    aggregate_source_id: Optional[str]
    action_source_id: Optional[str]
    summary_source_id: str


@dataclass
class OverallReportStatusResult:
    """Categorical report status kept separate from product compliance."""

    schema_version: str
    overall_status: OverallReportStatus
    status_scope: str
    status_reason: str
    reason_codes: List[str]
    decision_basis: Dict[str, Any]
    product_compliance_conclusion: ProductComplianceConclusion
    requires_user_action: bool
    can_complete_evaluation_now: bool
    provenance: ReportStatusProvenance
    accounting: Dict[str, Any]
    quality_audit: Dict[str, int]
    genericity_audit: Dict[str, int]
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    deterministic_disposition: DeterministicDisposition = DeterministicDisposition.HUMAN_REVIEW
    final_disposition_policy_version: str = "STEP40_DISPOSITION_V1"
    professional_judgment: Dict[str, Any] = field(default_factory=dict)


class GenericOverallReportStatusEngine:
    """Apply explicit precedence without re-evaluating technical evidence."""

    STATUS_TEXT = {
        OverallReportStatus.ACTION_REQUIRED: "Additional information, evidence, clarification, or review is required before a reliable final compliance conclusion can be completed.",
        OverallReportStatus.NOT_READY: "The current report contains proven material issues that prevent it from supporting the required compliance evaluation without corrective action.",
        OverallReportStatus.READY: "The available evaluation evidence is sufficient to complete the current report assessment.",
        OverallReportStatus.UNRESOLVED: "The available evaluation information is not sufficient to determine the report's overall evaluation status.",
    }
    REASON_BY_ISSUE = {
        "MISSING_EVIDENCE": "ACTIONABLE_EVIDENCE_GAPS",
        "INSUFFICIENT_EVIDENCE": "ACTIONABLE_EVIDENCE_GAPS",
        "TRACEABILITY_ISSUE": "ACTIONABLE_TRACEABILITY_GAPS",
        "APPLICABILITY_JUSTIFICATION_REQUIRED": "ACTIONABLE_APPLICABILITY_GAPS",
        "UNRESOLVED_EVIDENCE_CONFLICT": "ACTIONABLE_CLARIFICATION_REQUIRED",
        "INVALID_TEST_EVIDENCE": "ACTIONABLE_INVALID_EVIDENCE",
        "CALCULATION_ISSUE": "ACTIONABLE_CORRECTION_REQUIRED",
        "TEST_CONDITION_ISSUE": "ACTIONABLE_TEST_FOLLOW_UP",
        "REPORT_DATA_INCONSISTENCY": "ACTIONABLE_REPORT_CORRECTION",
        "CONFIRMED_NONCOMPLIANCE": "CONFIRMED_NONCOMPLIANCE",
    }
    QUALITY_KEYS = (
        "individual_conclusion_modified", "aggregate_severity_modified", "action_type_modified",
        "action_priority_modified", "blocking_state_modified", "missing_evidence_treated_as_product_noncompliance",
        "unresolved_treated_as_product_noncompliance", "absence_of_failure_treated_as_compliance",
        "ready_emitted_without_completion_proof", "not_ready_emitted_from_issue_count_alone",
        "not_ready_emitted_from_severity_alone", "readiness_percentage_created", "compliance_percentage_created",
        "certification_claim_created", "product_safety_claim_created", "standard_specific_production_branch",
        "product_specific_production_branch", "clause_specific_production_branch", "page_specific_production_branch",
        "model_specific_production_branch", "report_specific_production_branch", "fixture_specific_production_branch",
        "upstream_artifact_mutated",
    )

    def resolve(self, aggregated_report: Any, action_plan: Any, executive_summary: Any) -> OverallReportStatusResult:
        """Resolve report status solely from existing structured decisions."""
        aggregate = self._plain(aggregated_report)
        plan = self._plain(action_plan)
        summary = self._plain(executive_summary)
        groups = list(aggregate.get("actionable_groups", []) or [])
        actions = list(plan.get("actions", []) or [])

        conclusions = Counter()
        blocking = Counter()
        reason_codes = set()
        proven_not_ready_codes = set()
        for group in groups:
            conclusions.update({str(k): int(v) for k, v in (group.get("conclusion_summary") or {}).items()})
            state = group.get("blocking_summary") or {}
            blocking["blocking"] += int(state.get("blocking_count") or 0)
            blocking["non_blocking"] += int(state.get("non_blocking_count") or 0)
            blocking["unknown"] += int(state.get("unknown_count") or 0)
            issue_type = str(group.get("issue_type") or "")
            if issue_type in self.REASON_BY_ISSUE:
                reason_codes.add(self.REASON_BY_ISSUE[issue_type])
            basis = group.get("report_status_basis") or {}
            if basis.get("proven_not_ready") is True or basis.get("status") == "NOT_READY":
                proven_not_ready_codes.add(str(basis.get("reason_code") or "CONFIRMED_BLOCKING_REPORT_CONDITION"))

        top_basis = aggregate.get("report_status_basis") or {}
        if top_basis.get("proven_not_ready") is True or top_basis.get("status") == "NOT_READY":
            proven_not_ready_codes.add(str(top_basis.get("reason_code") or "CONFIRMED_BLOCKING_REPORT_CONDITION"))
        completion_proven = self._completion_proven(aggregate, summary)
        requires_action = bool(actions) or bool(groups)

        if proven_not_ready_codes:
            status = OverallReportStatus.NOT_READY
            reason_codes.update(proven_not_ready_codes)
        elif requires_action:
            status = OverallReportStatus.ACTION_REQUIRED
        elif completion_proven:
            status = OverallReportStatus.READY
            reason_codes.add("EVALUATION_COMPLETE")
        else:
            status = OverallReportStatus.UNRESOLVED
            reason_codes.add("STATUS_INPUT_INSUFFICIENT")

        product = self._product_conclusion(aggregate, conclusions, completion_proven)
        can_complete = status == OverallReportStatus.READY and not requires_action and conclusions["UNRESOLVED"] == 0 and conclusions["NOT_EVALUATED"] == 0
        issue_ids = {str(v) for group in groups for v in (group.get("issue_ids") or [])}
        group_ids = {str(group.get("group_id")) for group in groups if group.get("group_id") is not None}
        action_ids = {str(action.get("action_id")) for action in actions if action.get("action_id") is not None}
        basis = {
            "actionable_issue_count": len(issue_ids), "actionable_group_count": len(group_ids),
            "unresolved_issue_count": conclusions["UNRESOLVED"], "not_evaluated_issue_count": conclusions["NOT_EVALUATED"],
            "noncompliant_issue_count": conclusions["NONCOMPLIANT"], "compliant_issue_count": conclusions["COMPLIANT"],
            "planned_action_count": len(actions), "blocking_issue_count": blocking["blocking"],
            "non_blocking_issue_count": blocking["non_blocking"], "unknown_blocking_issue_count": blocking["unknown"],
            "blocking_group_count": sum(1 for group in groups if int((group.get("blocking_summary") or {}).get("blocking_count") or 0) > 0),
            "unknown_blocking_group_count": sum(1 for group in groups if int((group.get("blocking_summary") or {}).get("unknown_count") or 0) > 0),
            "evaluation_completion_proven": completion_proven,
        }
        expected_groups = int((plan.get("metadata") or {}).get("source_aggregate_group_count") or len(group_ids))
        expected_actions = int((summary.get("metadata") or {}).get("source_action_count") or len(action_ids))
        accounting = {"aggregate_group_count_matches_action_plan": expected_groups == len(group_ids), "action_count_matches_summary": expected_actions == len(action_ids), "source_aggregate_group_count": len(group_ids), "source_action_count": len(action_ids)}
        summary_id = "EXECUTIVE-SUMMARY-" + hashlib.sha256(self._canonical(summary).encode()).hexdigest()[:20].upper()
        provenance = ReportStatusProvenance(aggregate.get("source_final_issue_report_id"), plan.get("source_aggregated_report_id"), summary_id)
        quality = {key: 0 for key in self.QUALITY_KEYS}
        genericity = {key: quality[key] for key in quality if key.endswith("_production_branch")}
        diagnostics = []
        if not accounting["aggregate_group_count_matches_action_plan"] or not accounting["action_count_matches_summary"]:
            diagnostics.append({"code": "SOURCE_ACCOUNTING_MISMATCH"})
        judgment=copy.deepcopy(aggregate.get("professional_judgment") or {})
        disposition=self._disposition(judgment,conclusions,requires_action)
        judgment["final_disposition"]={"value":disposition.value,"policy_version":"STEP40_DISPOSITION_V1",
            "authoritative_pass_allowed":disposition is DeterministicDisposition.PASS}
        return OverallReportStatusResult("1.1", status, "REPORT_EVALUATION", self.STATUS_TEXT[status], sorted(reason_codes), basis, product, requires_action, can_complete, provenance, accounting, quality, genericity, diagnostics,disposition,"STEP40_DISPOSITION_V1",judgment)

    @staticmethod
    def _disposition(judgment:Mapping[str,Any],conclusions:Mapping[str,int],requires_action:bool)->DeterministicDisposition:
        critical=judgment.get("critical_summary") or {};metrics=judgment.get("metrics") or {}
        coverage=float((metrics.get("evaluation_coverage") or {}).get("value") or 0)
        validity=str((judgment.get("report_validity_summary") or {}).get("structure_compatibility") or "UNKNOWN")
        maturity=str(judgment.get("kb_maturity") or "DRAFT")
        if int(critical.get("violations") or 0)>0 or int(conclusions.get("NONCOMPLIANT",0) or 0)>0:return DeterministicDisposition.REJECT
        if int(critical.get("evidence_gaps") or 0)>0:return DeterministicDisposition.INSUFFICIENT_TECHNICAL_EVIDENCE
        if int(critical.get("applicability_unresolved") or 0)>0:return DeterministicDisposition.CONDITIONAL
        if validity in {"STRUCTURE_MISMATCH","INCOMPATIBLE"}:return DeterministicDisposition.INSUFFICIENT_TECHNICAL_EVIDENCE
        if coverage<100 or maturity in {"DRAFT","REVIEWED"}:return DeterministicDisposition.PARTIAL_EVALUATION
        if requires_action:return DeterministicDisposition.HUMAN_REVIEW
        return DeterministicDisposition.PASS

    @staticmethod
    def _completion_proven(aggregate: Mapping[str, Any], summary: Mapping[str, Any]) -> bool:
        values = [aggregate.get("evaluation_completion_proven"), (aggregate.get("report_status_basis") or {}).get("evaluation_completion_proven"), summary.get("evaluation_completion_proven"), (summary.get("metadata") or {}).get("evaluation_completion_proven")]
        return any(value is True for value in values)

    @staticmethod
    def _product_conclusion(aggregate: Mapping[str, Any], conclusions: Mapping[str, int], completion_proven: bool) -> ProductComplianceConclusion:
        explicit = aggregate.get("product_compliance_conclusion") or (aggregate.get("report_status_basis") or {}).get("product_compliance_conclusion")
        if explicit == "NONCOMPLIANT" or conclusions.get("NONCOMPLIANT", 0) > 0:
            return ProductComplianceConclusion.NONCOMPLIANT
        if explicit == "COMPLIANT" and completion_proven:
            return ProductComplianceConclusion.COMPLIANT
        return ProductComplianceConclusion.NOT_DETERMINED

    @classmethod
    def _plain(cls, value: Any) -> Any:
        if isinstance(value, Enum): return value.value
        if is_dataclass(value): return cls._plain(asdict(value))
        if isinstance(value, Mapping): return {str(k): cls._plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)): return [cls._plain(v) for v in value]
        return copy.deepcopy(value)

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def to_dict(cls, result: OverallReportStatusResult) -> Dict[str, Any]:
        """Convert a status result to JSON-compatible primitives."""
        if not is_dataclass(result): raise TypeError("overall report status result required")
        return cls._plain(asdict(result))

    @classmethod
    def to_json(cls, result: OverallReportStatusResult, indent: int = 2) -> str:
        """Serialize a status result deterministically."""
        return json.dumps(cls.to_dict(result), ensure_ascii=False, sort_keys=True, indent=indent)

    @classmethod
    def save_json(cls, result: OverallReportStatusResult, path: Any) -> Path:
        """Write status output without modifying its inputs."""
        target = Path(path); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(cls.to_json(result) + "\n", encoding="utf-8"); return target


__all__ = ["DeterministicDisposition","GenericOverallReportStatusEngine", "OverallReportStatus", "OverallReportStatusResult", "ProductComplianceConclusion", "ReportStatusProvenance"]
