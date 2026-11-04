"""Generic schemas for client-facing compliance summaries and traceability."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class FinalComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    REJECTED = "REJECTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNRESOLVED = "UNRESOLVED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INACTIVE = "INACTIVE"


class IssueType(str, Enum):
    TECHNICAL_VIOLATION = "TECHNICAL_VIOLATION"
    CONFLICTING_REPORT_VERDICT = "CONFLICTING_REPORT_VERDICT"
    CROSS_EVIDENCE_VALUE_CONFLICT = "CROSS_EVIDENCE_VALUE_CONFLICT"
    PRODUCT_INFORMATION_CONFLICT = "PRODUCT_INFORMATION_CONFLICT"
    SAMPLE_IDENTITY_CONFLICT = "SAMPLE_IDENTITY_CONFLICT"
    TEST_CONDITION_MISMATCH = "TEST_CONDITION_MISMATCH"
    CALCULATION_MISMATCH = "CALCULATION_MISMATCH"
    INVALID_NA = "INVALID_NA"
    NA_APPLICABILITY_CONFLICT = "NA_APPLICABILITY_CONFLICT"
    MISSING_REPORT_EVIDENCE = "MISSING_REPORT_EVIDENCE"
    MISSING_MEASUREMENT = "MISSING_MEASUREMENT"
    MISSING_PRODUCT_INFORMATION = "MISSING_PRODUCT_INFORMATION"
    UNKNOWN_APPLICABILITY = "UNKNOWN_APPLICABILITY"
    AMBIGUOUS_REPORT_SCOPE = "AMBIGUOUS_REPORT_SCOPE"
    KB_SEMANTIC_UNRESOLVED = "KB_SEMANTIC_UNRESOLVED"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    TEST_METHOD_INCOMPLETE = "TEST_METHOD_INCOMPLETE"
    EVIDENCE_NOT_LINKED = "EVIDENCE_NOT_LINKED"
    OTHER_REVIEW_REQUIRED = "OTHER_REVIEW_REQUIRED"


class IssueSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFORMATIONAL = "INFORMATIONAL"


class ActionType(str, Enum):
    NONE = "NONE"
    VERIFY_PRODUCT_INFORMATION = "VERIFY_PRODUCT_INFORMATION"
    VERIFY_SAMPLE_IDENTITY = "VERIFY_SAMPLE_IDENTITY"
    VERIFY_RATING_OR_SPECIFICATION = "VERIFY_RATING_OR_SPECIFICATION"
    REVIEW_APPLICABILITY = "REVIEW_APPLICABILITY"
    REVIEW_REPORT_SCOPE = "REVIEW_REPORT_SCOPE"
    REVIEW_REPORTED_NA = "REVIEW_REPORTED_NA"
    REVIEW_CONFLICTING_EVIDENCE = "REVIEW_CONFLICTING_EVIDENCE"
    PROVIDE_REPORT_EVIDENCE = "PROVIDE_REPORT_EVIDENCE"
    PROVIDE_MEASUREMENT = "PROVIDE_MEASUREMENT"
    VERIFY_TEST_CONDITION = "VERIFY_TEST_CONDITION"
    VERIFY_CALCULATION = "VERIFY_CALCULATION"
    REPEAT_OR_VERIFY_TEST = "REPEAT_OR_VERIFY_TEST"
    SUBMIT_CORRECTED_REPORT = "SUBMIT_CORRECTED_REPORT"
    MANUAL_TECHNICAL_REVIEW = "MANUAL_TECHNICAL_REVIEW"
    REVIEW_KB_REQUIREMENT = "REVIEW_KB_REQUIREMENT"


class EvaluationConfidenceStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    RESOLVED = "RESOLVED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class SourceTraceability:
    effective_requirement_ids: List[str] = field(default_factory=list)
    logical_group_ids: List[str] = field(default_factory=list)
    report_evidence_ids: List[str] = field(default_factory=list)
    product_fact_ids: List[str] = field(default_factory=list)
    feature_keys: List[str] = field(default_factory=list)
    applicability_evaluation_ids: List[str] = field(default_factory=list)
    evidence_match_ids: List[str] = field(default_factory=list)
    na_validation_ids: List[str] = field(default_factory=list)
    technical_constraint_result_ids: List[str] = field(default_factory=list)
    final_requirement_decision_ids: List[str] = field(default_factory=list)
    coverage_gap_ids: List[str] = field(default_factory=list)
    provenance: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceReference:
    evidence_id: str
    evidence_type: Optional[str] = None
    clause_id: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    source_artifact: Optional[str] = None
    raw_excerpt: Optional[str] = None


@dataclass(frozen=True)
class ProductFactReference:
    fact_id: str
    feature_key: Optional[str] = None
    source_evidence_ids: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class StandardRequirementReference:
    effective_requirement_id: str
    clause_id: Optional[str] = None
    logical_group_id: Optional[str] = None
    source_standard_id: Optional[str] = None
    source_requirement_id: Optional[str] = None


@dataclass(frozen=True)
class NextAction:
    action_type: ActionType
    summary: Optional[str] = None
    reason: Optional[str] = None
    priority: Optional[IssueSeverity] = None
    related_issue_ids: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ComplianceIssue:
    issue_type: IssueType
    severity: IssueSeverity
    blocking: bool
    summary: str
    reason: str
    issue_id: Optional[str] = None
    clause_id: Optional[str] = None
    logical_group_id: Optional[str] = None
    requirement_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    product_fact_ids: List[str] = field(default_factory=list)
    technical_constraint_ids: List[str] = field(default_factory=list)
    source_artifacts: List[str] = field(default_factory=list)
    confidence: Optional[float] = None
    status: EvaluationConfidenceStatus = EvaluationConfidenceStatus.UNRESOLVED
    notes: Optional[str] = None
    traceability: SourceTraceability = field(default_factory=SourceTraceability)
    diagnostic: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class LogicalGroupEvaluationSummary:
    clause_id: str
    group_id: str
    final_status: FinalComplianceStatus
    title: Optional[str] = None
    severity: Optional[IssueSeverity] = None
    effective_requirement_ids: List[str] = field(default_factory=list)
    standard_requirements: List[Dict[str, Any]] = field(default_factory=list)
    product_context: List[Dict[str, Any]] = field(default_factory=list)
    report_evidence: List[Dict[str, Any]] = field(default_factory=list)
    applicability: Dict[str, Any] = field(default_factory=dict)
    evidence_match: Dict[str, Any] = field(default_factory=dict)
    na_validation: Dict[str, Any] = field(default_factory=dict)
    technical_evaluation: List[Dict[str, Any]] = field(default_factory=list)
    issues: List[ComplianceIssue] = field(default_factory=list)
    next_actions: List[NextAction] = field(default_factory=list)
    decision_reason: Optional[str] = None
    source_traceability: SourceTraceability = field(default_factory=SourceTraceability)


@dataclass(frozen=True)
class ClauseEvaluationSummary:
    clause_id: str
    final_status: FinalComplianceStatus
    title: Optional[str] = None
    severity: Optional[IssueSeverity] = None
    logical_group_ids: List[str] = field(default_factory=list)
    requirement_ids: List[str] = field(default_factory=list)
    standard_requirements: List[StandardRequirementReference] = field(default_factory=list)
    product_context: List[ProductFactReference] = field(default_factory=list)
    report_evidence: List[EvidenceReference] = field(default_factory=list)
    issues: List[ComplianceIssue] = field(default_factory=list)
    next_actions: List[NextAction] = field(default_factory=list)
    decision_reason: Optional[str] = None
    source_traceability: SourceTraceability = field(default_factory=SourceTraceability)
    group_summaries: List[LogicalGroupEvaluationSummary] = field(default_factory=list)
    issue_count: int = 0


@dataclass(frozen=True)
class ReportEvaluationSummary:
    final_status: FinalComplianceStatus
    report_document_id: Optional[str] = None
    effective_kb_id: Optional[str] = None
    profile_id: Optional[str] = None
    clause_summaries: List[ClauseEvaluationSummary] = field(default_factory=list)
    issues: List[ComplianceIssue] = field(default_factory=list)
    next_actions: List[NextAction] = field(default_factory=list)
    decision_reason: Optional[str] = None
    source_traceability: SourceTraceability = field(default_factory=SourceTraceability)


@dataclass(frozen=True)
class StatusPresentation:
    label: str
    description: str


STATUS_PRESENTATION: Dict[FinalComplianceStatus, StatusPresentation] = {
    FinalComplianceStatus.COMPLIANT: StatusPresentation("Compliant", "Reliable evidence supports the applicable requirement."),
    FinalComplianceStatus.NON_COMPLIANT: StatusPresentation("Non-Compliant", "Reliable evidence shows that an applicable requirement is not satisfied."),
    FinalComplianceStatus.REJECTED: StatusPresentation("Rejected", "The submitted report or evidence contains a material inconsistency that prevents reliable acceptance."),
    FinalComplianceStatus.INSUFFICIENT_EVIDENCE: StatusPresentation("Insufficient Evidence", "Required evidence is missing or incomplete."),
    FinalComplianceStatus.UNRESOLVED: StatusPresentation("Unresolved", "Available information cannot yet be interpreted or scoped safely."),
    FinalComplianceStatus.NOT_APPLICABLE: StatusPresentation("Not Applicable", "The requirement is deterministically not applicable."),
    FinalComplianceStatus.INACTIVE: StatusPresentation("Inactive", "The requirement is inactive in the effective standard."),
}


class ComplianceSummarySerializer:
    """Serialize summary models deterministically."""
    @classmethod
    def to_dict(cls, value: Any) -> Dict[str, Any]:
        if not is_dataclass(value): raise TypeError("compliance summary dataclass required")
        return cls._plain(asdict(value))
    @classmethod
    def to_json(cls, value: Any, indent: Optional[int] = 2) -> str:
        return json.dumps(cls.to_dict(value), ensure_ascii=False, sort_keys=True, indent=indent)
    @classmethod
    def _plain(cls, value: Any) -> Any:
        if isinstance(value, Enum): return value.value
        if isinstance(value, dict): return {k: cls._plain(v) for k, v in value.items()}
        if isinstance(value, list): return [cls._plain(v) for v in value]
        return value


__all__ = ["ActionType", "ClauseEvaluationSummary", "ComplianceIssue",
 "ComplianceSummarySerializer", "EvaluationConfidenceStatus", "EvidenceReference",
 "FinalComplianceStatus", "IssueSeverity", "IssueType", "LogicalGroupEvaluationSummary", "NextAction",
 "ProductFactReference", "ReportEvaluationSummary", "SourceTraceability",
 "StandardRequirementReference", "STATUS_PRESENTATION", "StatusPresentation"]
