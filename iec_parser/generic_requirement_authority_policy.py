"""Step 39 deterministic criticality, evidence-state, and KB authority policy."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .generic_iec_kb_models import (KBMaturityMetadata, KBMaturityState,
    RequirementCriticality, RequirementCriticalityLevel, RequirementDecisionEffect)


class RequirementEvidenceState(str, Enum):
    CONFIRMED_SATISFIED="CONFIRMED_SATISFIED"
    CONFIRMED_VIOLATION="CONFIRMED_VIOLATION"
    MISSING_REQUIRED_EVIDENCE="MISSING_REQUIRED_EVIDENCE"
    INVALID_EVIDENCE="INVALID_EVIDENCE"
    SEMANTICALLY_REJECTED="SEMANTICALLY_REJECTED"
    UNKNOWN_APPLICABILITY="UNKNOWN_APPLICABILITY"
    KB_RULE_UNSUPPORTED="KB_RULE_UNSUPPORTED"
    COVERAGE_INCOMPLETE="COVERAGE_INCOMPLETE"
    NOT_APPLICABLE="NOT_APPLICABLE"


class RequirementPolicyConclusion(str, Enum):
    SATISFIED="SATISFIED"
    CONFIRMED_NONCOMPLIANCE_CANDIDATE="CONFIRMED_NONCOMPLIANCE_CANDIDATE"
    CRITICAL_EVIDENCE_GAP="CRITICAL_EVIDENCE_GAP"
    EVALUATION_GAP="EVALUATION_GAP"
    NOT_APPLICABLE="NOT_APPLICABLE"


@dataclass(frozen=True)
class KBAuthorityDecision:
    maturity: KBMaturityState
    authoritative_pass_allowed: bool
    scope_limited: bool
    reason: str


@dataclass(frozen=True)
class RequirementPolicyResult:
    evidence_state: RequirementEvidenceState
    conclusion: RequirementPolicyConclusion
    criticality: Optional[RequirementCriticalityLevel]
    decision_effect: Optional[RequirementDecisionEffect]
    product_failure: bool
    parser_confidence: Optional[float] = None
    evidence_confidence: Optional[float] = None


class GenericRequirementAuthorityPolicy:
    """Interpret upstream facts without re-evaluating their semantics."""

    GAP_STATES={RequirementEvidenceState.MISSING_REQUIRED_EVIDENCE,
        RequirementEvidenceState.INVALID_EVIDENCE, RequirementEvidenceState.SEMANTICALLY_REJECTED,
        RequirementEvidenceState.UNKNOWN_APPLICABILITY, RequirementEvidenceState.KB_RULE_UNSUPPORTED,
        RequirementEvidenceState.COVERAGE_INCOMPLETE}

    @staticmethod
    def authority(maturity: KBMaturityMetadata, *, coverage_complete: bool=True) -> KBAuthorityDecision:
        if maturity.state is KBMaturityState.DRAFT:
            return KBAuthorityDecision(maturity.state,False,True,"Draft KB cannot authorize PASS.")
        if maturity.state is KBMaturityState.REVIEWED:
            return KBAuthorityDecision(maturity.state,False,True,"Reviewed KB authority is limited to its recorded review scope.")
        allowed=bool(coverage_complete and maturity.review_scope and maturity.reviewer and maturity.review_date and maturity.version)
        return KBAuthorityDecision(maturity.state,allowed,not allowed,"Production authority requires reviewed metadata and complete in-scope coverage.")

    @classmethod
    def evaluate(cls, evidence_state: RequirementEvidenceState, *,
                 criticality: Optional[RequirementCriticality]=None,
                 decision_effect: Optional[RequirementDecisionEffect]=None,
                 parser_confidence: Optional[float]=None,
                 evidence_confidence: Optional[float]=None) -> RequirementPolicyResult:
        level=criticality.level if criticality else None
        if evidence_state is RequirementEvidenceState.CONFIRMED_VIOLATION:
            conclusion=RequirementPolicyConclusion.CONFIRMED_NONCOMPLIANCE_CANDIDATE;failure=True
        elif evidence_state is RequirementEvidenceState.CONFIRMED_SATISFIED:
            conclusion=RequirementPolicyConclusion.SATISFIED;failure=False
        elif evidence_state is RequirementEvidenceState.NOT_APPLICABLE:
            conclusion=RequirementPolicyConclusion.NOT_APPLICABLE;failure=False
        elif level is RequirementCriticalityLevel.P0_CRITICAL:
            conclusion=RequirementPolicyConclusion.CRITICAL_EVIDENCE_GAP;failure=False
        else:
            conclusion=RequirementPolicyConclusion.EVALUATION_GAP;failure=False
        return RequirementPolicyResult(evidence_state,conclusion,level,decision_effect,failure,
                                       parser_confidence,evidence_confidence)


__all__=["GenericRequirementAuthorityPolicy","KBAuthorityDecision","RequirementEvidenceState",
         "RequirementPolicyConclusion","RequirementPolicyResult"]
