"""Provider-neutral Step 47-A contracts for bounded LLM proposals.

These models do not execute an LLM and never mutate deterministic artifacts.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

LLM_INPUT_VERSION = "COMPLIFY_LLM_INPUT_V1"
LLM_OUTPUT_VERSION = "COMPLIFY_LLM_OUTPUT_V1"
CLIENT_SUMMARY_VERSION = "COMPLIFY_CLIENT_SUMMARY_V1"
FROZEN_BASELINE = "PRE_LLM_DETERMINISTIC_BASELINE_V4"
FROZEN_CONTRACT = "STEP46I_PRE_LLM_FREEZE_V4"


class _StringEnum(str, Enum): pass
class CandidateOwnership(_StringEnum):
    DETERMINISTIC_RESOLVED="DETERMINISTIC_RESOLVED"; CLIENT_EVIDENCE_REQUIRED="CLIENT_EVIDENCE_REQUIRED"
    LAB_CLARIFICATION_REQUIRED="LAB_CLARIFICATION_REQUIRED"; TECHNICAL_REVIEW_REQUIRED="TECHNICAL_REVIEW_REQUIRED"
    LLM_ELIGIBLE="LLM_ELIGIBLE"; M3_REQUIRED="M3_REQUIRED"; NON_BLOCKING_LIMITATION="NON_BLOCKING_LIMITATION"
class CandidateResultStatus(_StringEnum):
    RESOLVED="RESOLVED"; PARTIALLY_RESOLVED="PARTIALLY_RESOLVED"; UNRESOLVED="UNRESOLVED"
    INSUFFICIENT_CONTEXT="INSUFFICIENT_CONTEXT"; CONFLICTING_CONTEXT="CONFLICTING_CONTEXT"
class ProposalType(_StringEnum):
    SEMANTIC_INTERPRETATION="SEMANTIC_INTERPRETATION"; CLASSIFICATION_RELATIONSHIP="CLASSIFICATION_RELATIONSHIP"
    APPLICABILITY_INTERPRETATION="APPLICABILITY_INTERPRETATION"; EVIDENCE_RELATIONSHIP="EVIDENCE_RELATIONSHIP"
class ClientFieldAuthority(_StringEnum):
    DETERMINISTIC="DETERMINISTIC"; LLM_EXPLANATION="LLM_EXPLANATION"
    VALIDATED_LLM_DERIVED="VALIDATED_LLM_DERIVED"; CLIENT_EVIDENCE_REQUIRED="CLIENT_EVIDENCE_REQUIRED"
class AuthorityViolationType(_StringEnum):
    MISSING_SOURCE_PROVENANCE="MISSING_SOURCE_PROVENANCE"; INVALID_CONTRACT_VERSION="INVALID_CONTRACT_VERSION"
    INVALID_CANDIDATE_OWNERSHIP="INVALID_CANDIDATE_OWNERSHIP"; UNSUPPORTED_LLM_PROPOSAL="UNSUPPORTED_LLM_PROPOSAL"
    MISSING_EVIDENCE_REFERENCE="MISSING_EVIDENCE_REFERENCE"; DETERMINISTIC_FACT_OVERRIDE_ATTEMPT="DETERMINISTIC_FACT_OVERRIDE_ATTEMPT"
    TECHNICAL_RESULT_OVERRIDE_ATTEMPT="TECHNICAL_RESULT_OVERRIDE_ATTEMPT"; PARAMETER_AUTHORITY_OVERRIDE_ATTEMPT="PARAMETER_AUTHORITY_OVERRIDE_ATTEMPT"
    NA_STATE_OVERRIDE_ATTEMPT="NA_STATE_OVERRIDE_ATTEMPT"; METRIC_OVERRIDE_ATTEMPT="METRIC_OVERRIDE_ATTEMPT"
    REPORT_VALIDITY_OVERRIDE_ATTEMPT="REPORT_VALIDITY_OVERRIDE_ATTEMPT"; FINAL_DISPOSITION_OVERRIDE_ATTEMPT="FINAL_DISPOSITION_OVERRIDE_ATTEMPT"
    UNTRACEABLE_CLASSIFICATION_PROPOSAL="UNTRACEABLE_CLASSIFICATION_PROPOSAL"; UNTRACEABLE_APPLICABILITY_PROPOSAL="UNTRACEABLE_APPLICABILITY_PROPOSAL"
    LLM_CONFIDENCE_AUTHORITY_LEAK="LLM_CONFIDENCE_AUTHORITY_LEAK"


@dataclass(frozen=True)
class LLMSourceBaseline:
    freeze_id: str; freeze_contract: str; source_schema: str; source_contract: str
    family: str; run_id: str; source_artifact: str; source_sha256: str

@dataclass(frozen=True)
class LLMTraceabilityReference:
    reference_type: str; reference_id: str; source_artifact: Optional[str]=None

@dataclass(frozen=True)
class LLMCandidate:
    candidate_id: str; candidate_type: str; ownership: CandidateOwnership
    question: str; evidence_references: List[LLMTraceabilityReference]=field(default_factory=list)
    deterministic_state: Optional[str]=None

@dataclass(frozen=True)
class LLMAuthorityConstraints:
    protected_fields: List[str]=field(default_factory=list)
    only_llm_eligible_resolvable: bool=True; traceability_required: bool=True
    deterministic_confidence_separate: bool=True

@dataclass(frozen=True)
class LLMInputContract:
    source_baseline: LLMSourceBaseline; product_context: Dict[str,Any]; standard_context: Dict[str,Any]
    report_context: Dict[str,Any]; deterministic_assessment: Dict[str,Any]; findings: Dict[str,Any]
    na_context: Dict[str,Any]; root_causes: List[Dict[str,Any]]; priority_findings: List[Dict[str,Any]]
    required_actions: List[Dict[str,Any]]; unresolved_context: Dict[str,Any]; llm_candidates: List[LLMCandidate]
    supporting_traceability: Dict[str,Any]; authority_constraints: LLMAuthorityConstraints
    contract_version: str=LLM_INPUT_VERSION

@dataclass(frozen=True)
class LLMProposedSemanticFact:
    fact_key: str; proposed_value: Any; proposal_type: ProposalType; source_refs: List[LLMTraceabilityReference]
    confidence: float; authority: str="LLM_PROPOSAL"; requires_validation: bool=True

@dataclass(frozen=True)
class LLMCandidateResult:
    candidate_id: str; candidate_type: str; status: CandidateResultStatus; interpretation: str=""
    proposed_semantic_facts: List[LLMProposedSemanticFact]=field(default_factory=list)
    proposed_classification: Optional[Dict[str,Any]]=None; proposed_applicability: Optional[Dict[str,Any]]=None
    reasoning_summary: str=""; evidence_references: List[LLMTraceabilityReference]=field(default_factory=list)
    standard_references: List[LLMTraceabilityReference]=field(default_factory=list); confidence: float=0.0
    requires_deterministic_reevaluation: bool=False; requires_human_review: bool=False
    cannot_resolve_reason: Optional[str]=None

@dataclass(frozen=True)
class LLMWarning:
    code: str; message: str; candidate_id: Optional[str]=None

@dataclass(frozen=True)
class LLMOutputContract:
    request_id: str; source_baseline: Dict[str,str]; candidate_results: List[LLMCandidateResult]
    summary_synthesis: Dict[str,Any]=field(default_factory=dict); client_explanation: Dict[str,Any]=field(default_factory=dict)
    warnings: List[LLMWarning]=field(default_factory=list); contract_version: str=LLM_OUTPUT_VERSION

@dataclass(frozen=True)
class ClientSummaryFieldProvenance:
    authority: ClientFieldAuthority; source_refs: List[str]; validated: bool

@dataclass(frozen=True)
class ClientSummaryContract:
    product_information: Dict[str,Any]; standard_information: Dict[str,Any]; report_information: Dict[str,Any]
    overall_result: Dict[str,Any]; compliance_metrics: Dict[str,Any]; critical_findings: List[Dict[str,Any]]
    technical_noncompliances: List[Dict[str,Any]]; important_parameter_findings: List[Dict[str,Any]]
    na_concerns: List[Dict[str,Any]]; unresolved_items: List[Dict[str,Any]]; root_causes: List[Dict[str,Any]]
    required_actions: List[Dict[str,Any]]; priority_actions: List[Dict[str,Any]]; limitations: List[Dict[str,Any]]
    conclusion: Dict[str,Any]; field_provenance: Dict[str,ClientSummaryFieldProvenance]
    contract_version: str=CLIENT_SUMMARY_VERSION


class LLMAuthorityContractValidator:
    PROTECTED = {
        "canonical_classification": AuthorityViolationType.DETERMINISTIC_FACT_OVERRIDE_ATTEMPT,
        "classification_status": AuthorityViolationType.DETERMINISTIC_FACT_OVERRIDE_ATTEMPT,
        "classification_confidence": AuthorityViolationType.DETERMINISTIC_FACT_OVERRIDE_ATTEMPT,
        "deterministic_applicability": AuthorityViolationType.DETERMINISTIC_FACT_OVERRIDE_ATTEMPT,
        "technical_result": AuthorityViolationType.TECHNICAL_RESULT_OVERRIDE_ATTEMPT,
        "parameter_role": AuthorityViolationType.PARAMETER_AUTHORITY_OVERRIDE_ATTEMPT,
        "na_status": AuthorityViolationType.NA_STATE_OVERRIDE_ATTEMPT,
        "compliance_score": AuthorityViolationType.METRIC_OVERRIDE_ATTEMPT,
        "evaluation_coverage": AuthorityViolationType.METRIC_OVERRIDE_ATTEMPT,
        "evaluation_confidence": AuthorityViolationType.METRIC_OVERRIDE_ATTEMPT,
        "report_validity": AuthorityViolationType.REPORT_VALIDITY_OVERRIDE_ATTEMPT,
        "final_disposition": AuthorityViolationType.FINAL_DISPOSITION_OVERRIDE_ATTEMPT,
    }
    ABSTENTIONS={"UNRESOLVED","INSUFFICIENT_CONTEXT","CONFLICTING_CONTEXT"}

    @classmethod
    def validate_input(cls, value: LLMInputContract) -> None:
        if value.contract_version != LLM_INPUT_VERSION: raise ValueError(AuthorityViolationType.INVALID_CONTRACT_VERSION.value)
        s=value.source_baseline
        if s.freeze_id != FROZEN_BASELINE or s.freeze_contract != FROZEN_CONTRACT: raise ValueError(AuthorityViolationType.MISSING_SOURCE_PROVENANCE.value)
        if len(s.source_sha256)!=64 or any(c not in "0123456789abcdef" for c in s.source_sha256.lower()): raise ValueError(AuthorityViolationType.MISSING_SOURCE_PROVENANCE.value)
        ids=[x.candidate_id for x in value.llm_candidates]
        if len(ids)!=len(set(ids)): raise ValueError("DUPLICATE_CANDIDATE_ID")

    @classmethod
    def validate_output(cls, value: LLMOutputContract|Dict[str,Any], source: LLMInputContract) -> None:
        raw=asdict(value) if not isinstance(value,dict) else value
        if raw.get("contract_version") != LLM_OUTPUT_VERSION: raise ValueError(AuthorityViolationType.INVALID_CONTRACT_VERSION.value)
        cls._reject_protected(raw)
        owners={x.candidate_id:x.ownership.value for x in source.llm_candidates}
        for result in raw.get("candidate_results",[]):
            cid=result.get("candidate_id"); status=result.get("status")
            if owners.get(cid)!="LLM_ELIGIBLE" and status in {"RESOLVED","PARTIALLY_RESOLVED"}: raise ValueError(AuthorityViolationType.INVALID_CANDIDATE_OWNERSHIP.value)
            confidence=result.get("confidence",0)
            if isinstance(confidence,bool) or not isinstance(confidence,(int,float)) or not 0<=confidence<=1: raise ValueError("INVALID_LLM_CONFIDENCE")
            proposals=result.get("proposed_semantic_facts",[])
            substantive=bool(proposals or result.get("proposed_classification") or result.get("proposed_applicability"))
            refs=result.get("evidence_references",[])+result.get("standard_references",[])
            if substantive and not refs: raise ValueError(AuthorityViolationType.MISSING_EVIDENCE_REFERENCE.value)
            for fact in proposals:
                if fact.get("authority")!="LLM_PROPOSAL" or fact.get("requires_validation") is not True: raise ValueError(AuthorityViolationType.UNSUPPORTED_LLM_PROPOSAL.value)
                if not fact.get("source_refs"): raise ValueError(AuthorityViolationType.MISSING_EVIDENCE_REFERENCE.value)
        if "deterministic_evaluation_confidence" in raw.get("summary_synthesis",{}): raise ValueError(AuthorityViolationType.LLM_CONFIDENCE_AUTHORITY_LEAK.value)

    @classmethod
    def validate_client_summary(cls, value: ClientSummaryContract) -> None:
        if value.contract_version != CLIENT_SUMMARY_VERSION: raise ValueError(AuthorityViolationType.INVALID_CONTRACT_VERSION.value)
        if not value.field_provenance: raise ValueError(AuthorityViolationType.MISSING_SOURCE_PROVENANCE.value)
        for p in value.field_provenance.values():
            if p.authority==ClientFieldAuthority.LLM_EXPLANATION and p.validated: raise ValueError("UNVALIDATED_LLM_PRESENTED_AS_DETERMINISTIC")
            if not p.source_refs: raise ValueError(AuthorityViolationType.MISSING_SOURCE_PROVENANCE.value)

    @classmethod
    def _reject_protected(cls, value: Any) -> None:
        if isinstance(value,dict):
            for key, child in value.items():
                if key in cls.PROTECTED: raise ValueError(cls.PROTECTED[key].value)
                cls._reject_protected(child)
        elif isinstance(value,list):
            for child in value: cls._reject_protected(child)


def deterministic_sha256(value: Any) -> str:
    if hasattr(value,"__dataclass_fields__"): value=asdict(value)
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
