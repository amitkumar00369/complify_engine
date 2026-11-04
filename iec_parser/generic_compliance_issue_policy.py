"""Configurable generic policy for issue defaults, rejection gates, and statuses."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .generic_compliance_summary_models import ActionType, ComplianceIssue, FinalComplianceStatus, IssueSeverity, IssueType


@dataclass(frozen=True)
class ValueConflictRejectionEvidence:
    same_normalized_parameter: bool = False
    equivalent_product_scope: bool = False
    same_requirement_context: bool = False
    both_sources_reliable: bool = False
    materially_inconsistent: bool = False
    supported_reconciliation_absent: bool = False
    affects_evaluation_validity: bool = False
    scope_ambiguous: bool = False


@dataclass(frozen=True)
class VerdictConflictRejectionEvidence:
    same_logical_scope: bool = False
    same_proven_evidence_scope: bool = False
    verdict_ownership_confirmed: bool = False
    structural_explanation_absent: bool = False
    valid_reconciliation_absent: bool = False
    affects_evaluation_validity: bool = True


@dataclass(frozen=True)
class EvaluationPolicy:
    technical_violation_blocks: bool = True
    material_integrity_conflict_blocks: bool = True
    insufficient_evidence_blocks: bool = True
    unresolved_blocks: bool = True
    not_applicable_blocks: bool = False
    inactive_blocks: bool = False
    one_non_compliant_makes_overall_non_compliant: bool = True
    one_material_rejection_makes_overall_rejected: bool = True
    insufficient_evidence_makes_overall_insufficient: bool = True
    unresolved_only_makes_overall_unresolved: bool = True
    severity_overrides: Mapping[IssueType, IssueSeverity] = field(default_factory=dict)
    action_overrides: Mapping[IssueType, Tuple[ActionType, ...]] = field(default_factory=dict)


DEFAULT_SEVERITY: Dict[IssueType, IssueSeverity] = {
 IssueType.TECHNICAL_VIOLATION:IssueSeverity.CRITICAL,
 IssueType.CONFLICTING_REPORT_VERDICT:IssueSeverity.HIGH,
 IssueType.CROSS_EVIDENCE_VALUE_CONFLICT:IssueSeverity.HIGH,
 IssueType.PRODUCT_INFORMATION_CONFLICT:IssueSeverity.HIGH,
 IssueType.SAMPLE_IDENTITY_CONFLICT:IssueSeverity.HIGH,
 IssueType.TEST_CONDITION_MISMATCH:IssueSeverity.HIGH,
 IssueType.CALCULATION_MISMATCH:IssueSeverity.HIGH,
 IssueType.INVALID_NA:IssueSeverity.HIGH,
 IssueType.NA_APPLICABILITY_CONFLICT:IssueSeverity.HIGH,
 IssueType.MISSING_REPORT_EVIDENCE:IssueSeverity.MEDIUM,
 IssueType.MISSING_MEASUREMENT:IssueSeverity.MEDIUM,
 IssueType.MISSING_PRODUCT_INFORMATION:IssueSeverity.MEDIUM,
 IssueType.UNKNOWN_APPLICABILITY:IssueSeverity.MEDIUM,
 IssueType.AMBIGUOUS_REPORT_SCOPE:IssueSeverity.MEDIUM,
 IssueType.KB_SEMANTIC_UNRESOLVED:IssueSeverity.MEDIUM,
 IssueType.CONFLICTING_EVIDENCE:IssueSeverity.MEDIUM,
 IssueType.TEST_METHOD_INCOMPLETE:IssueSeverity.MEDIUM,
 IssueType.EVIDENCE_NOT_LINKED:IssueSeverity.MEDIUM,
 IssueType.OTHER_REVIEW_REQUIRED:IssueSeverity.LOW,
}

DEFAULT_ACTIONS: Dict[IssueType, Tuple[ActionType, ...]] = {
 IssueType.TECHNICAL_VIOLATION:(ActionType.MANUAL_TECHNICAL_REVIEW,),
 IssueType.CONFLICTING_REPORT_VERDICT:(ActionType.REVIEW_CONFLICTING_EVIDENCE,ActionType.SUBMIT_CORRECTED_REPORT),
 IssueType.CROSS_EVIDENCE_VALUE_CONFLICT:(ActionType.VERIFY_RATING_OR_SPECIFICATION,ActionType.REVIEW_CONFLICTING_EVIDENCE),
 IssueType.PRODUCT_INFORMATION_CONFLICT:(ActionType.VERIFY_PRODUCT_INFORMATION,),
 IssueType.SAMPLE_IDENTITY_CONFLICT:(ActionType.VERIFY_SAMPLE_IDENTITY,),
 IssueType.TEST_CONDITION_MISMATCH:(ActionType.VERIFY_TEST_CONDITION,ActionType.REPEAT_OR_VERIFY_TEST),
 IssueType.CALCULATION_MISMATCH:(ActionType.VERIFY_CALCULATION,),
 IssueType.INVALID_NA:(ActionType.REVIEW_REPORTED_NA,),
 IssueType.NA_APPLICABILITY_CONFLICT:(ActionType.REVIEW_REPORTED_NA,),
 IssueType.MISSING_REPORT_EVIDENCE:(ActionType.PROVIDE_REPORT_EVIDENCE,),
 IssueType.MISSING_MEASUREMENT:(ActionType.PROVIDE_MEASUREMENT,),
 IssueType.MISSING_PRODUCT_INFORMATION:(ActionType.VERIFY_PRODUCT_INFORMATION,),
 IssueType.UNKNOWN_APPLICABILITY:(ActionType.REVIEW_APPLICABILITY,),
 IssueType.AMBIGUOUS_REPORT_SCOPE:(ActionType.REVIEW_REPORT_SCOPE,),
 IssueType.KB_SEMANTIC_UNRESOLVED:(ActionType.REVIEW_KB_REQUIREMENT,),
 IssueType.CONFLICTING_EVIDENCE:(ActionType.REVIEW_CONFLICTING_EVIDENCE,),
 IssueType.TEST_METHOD_INCOMPLETE:(ActionType.REPEAT_OR_VERIFY_TEST,),
 IssueType.EVIDENCE_NOT_LINKED:(ActionType.PROVIDE_REPORT_EVIDENCE,),
 IssueType.OTHER_REVIEW_REQUIRED:(ActionType.MANUAL_TECHNICAL_REVIEW,),
}


class GenericComplianceIssuePolicy:
    """Apply hard safety gates before assigning final client-facing statuses."""
    PRECEDENCE=(FinalComplianceStatus.NON_COMPLIANT,FinalComplianceStatus.REJECTED,
      FinalComplianceStatus.INSUFFICIENT_EVIDENCE,FinalComplianceStatus.UNRESOLVED,
      FinalComplianceStatus.NOT_APPLICABLE,FinalComplianceStatus.COMPLIANT,
      FinalComplianceStatus.INACTIVE)
    INSUFFICIENT_TYPES={IssueType.MISSING_REPORT_EVIDENCE,IssueType.MISSING_MEASUREMENT,IssueType.MISSING_PRODUCT_INFORMATION,IssueType.TEST_METHOD_INCOMPLETE,IssueType.EVIDENCE_NOT_LINKED}
    UNRESOLVED_TYPES={IssueType.UNKNOWN_APPLICABILITY,IssueType.AMBIGUOUS_REPORT_SCOPE,IssueType.KB_SEMANTIC_UNRESOLVED,IssueType.INVALID_NA,IssueType.NA_APPLICABILITY_CONFLICT,IssueType.CONFLICTING_EVIDENCE,IssueType.OTHER_REVIEW_REQUIRED}
    REJECTION_TYPES={IssueType.CONFLICTING_REPORT_VERDICT,IssueType.CROSS_EVIDENCE_VALUE_CONFLICT,IssueType.PRODUCT_INFORMATION_CONFLICT,IssueType.SAMPLE_IDENTITY_CONFLICT,IssueType.TEST_CONDITION_MISMATCH,IssueType.CALCULATION_MISMATCH}
    def __init__(self,policy:EvaluationPolicy=EvaluationPolicy()):self.policy=policy
    def severity_for(self,issue_type):return self.policy.severity_overrides.get(issue_type,DEFAULT_SEVERITY[issue_type])
    def prioritized_severity_for(self,issue_type,criticality=None):
        """Raise review priority only; never reinterpret the underlying issue."""
        base=self.severity_for(issue_type);level=getattr(criticality,"level",criticality);value=getattr(level,"value",level)
        if value=="P0_CRITICAL":return IssueSeverity.CRITICAL
        if value=="P1_HIGH" and base in {IssueSeverity.LOW,IssueSeverity.MEDIUM}:return IssueSeverity.HIGH
        return base
    def actions_for(self,issue_type):return list(self.policy.action_overrides.get(issue_type,DEFAULT_ACTIONS[issue_type]))
    @staticmethod
    def value_conflict_rejected(evidence:ValueConflictRejectionEvidence)->bool:
        return not evidence.scope_ambiguous and all((evidence.same_normalized_parameter,evidence.equivalent_product_scope,evidence.same_requirement_context,evidence.both_sources_reliable,evidence.materially_inconsistent,evidence.supported_reconciliation_absent,evidence.affects_evaluation_validity))
    @staticmethod
    def verdict_conflict_rejected(evidence:VerdictConflictRejectionEvidence)->bool:
        return all((evidence.same_logical_scope,evidence.same_proven_evidence_scope,evidence.verdict_ownership_confirmed,evidence.structural_explanation_absent,evidence.valid_reconciliation_absent,evidence.affects_evaluation_validity))
    def resolve(self,*,issues:Sequence[ComplianceIssue]=(),proven_technical_violation=False,proven_integrity_rejection=False,applicable=True,justified_not_applicable=False,inactive=False,evidence_sufficient=True)->FinalComplianceStatus:
        if proven_technical_violation:return FinalComplianceStatus.NON_COMPLIANT
        if proven_integrity_rejection:return FinalComplianceStatus.REJECTED
        issue_types={x.issue_type for x in issues}
        if not evidence_sufficient or issue_types & self.INSUFFICIENT_TYPES:return FinalComplianceStatus.INSUFFICIENT_EVIDENCE
        if issue_types & (self.UNRESOLVED_TYPES|self.REJECTION_TYPES):return FinalComplianceStatus.UNRESOLVED
        if justified_not_applicable:return FinalComplianceStatus.NOT_APPLICABLE
        if inactive:return FinalComplianceStatus.INACTIVE
        return FinalComplianceStatus.COMPLIANT if applicable else FinalComplianceStatus.UNRESOLVED
    def aggregate_same_scope(self,statuses:Sequence[FinalComplianceStatus])->FinalComplianceStatus:
        present=set(statuses)
        return next((x for x in self.PRECEDENCE if x in present),FinalComplianceStatus.UNRESOLVED)
    def blocks(self,status:FinalComplianceStatus)->bool:
        return {FinalComplianceStatus.NON_COMPLIANT:self.policy.technical_violation_blocks,FinalComplianceStatus.REJECTED:self.policy.material_integrity_conflict_blocks,FinalComplianceStatus.INSUFFICIENT_EVIDENCE:self.policy.insufficient_evidence_blocks,FinalComplianceStatus.UNRESOLVED:self.policy.unresolved_blocks,FinalComplianceStatus.NOT_APPLICABLE:self.policy.not_applicable_blocks,FinalComplianceStatus.INACTIVE:self.policy.inactive_blocks,FinalComplianceStatus.COMPLIANT:False}[status]


__all__=["DEFAULT_ACTIONS","DEFAULT_SEVERITY","EvaluationPolicy","GenericComplianceIssuePolicy","ValueConflictRejectionEvidence","VerdictConflictRejectionEvidence"]
