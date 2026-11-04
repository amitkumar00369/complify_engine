"""Provider-neutral models for deterministic Step 47-B packaging."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

class S(str,Enum): pass
class CandidateType(S):
    TERMINOLOGY_RELATIONSHIP="TERMINOLOGY_RELATIONSHIP"; CLASSIFICATION_INTERPRETATION="CLASSIFICATION_INTERPRETATION"
    APPLICABILITY_INTERPRETATION="APPLICABILITY_INTERPRETATION"; REQUIREMENT_EVIDENCE_RELATIONSHIP="REQUIREMENT_EVIDENCE_RELATIONSHIP"
    STANDARD_REPORT_SEMANTIC_ALIGNMENT="STANDARD_REPORT_SEMANTIC_ALIGNMENT"; CROSS_REFERENCE_INTERPRETATION="CROSS_REFERENCE_INTERPRETATION"
    SEMANTIC_CONFLICT_EXPLANATION="SEMANTIC_CONFLICT_EXPLANATION"; SUMMARY_EXPLANATION="SUMMARY_EXPLANATION"
class Ownership(S):
    DETERMINISTIC_RESOLVED="DETERMINISTIC_RESOLVED"; CLIENT_EVIDENCE_REQUIRED="CLIENT_EVIDENCE_REQUIRED"
    LAB_CLARIFICATION_REQUIRED="LAB_CLARIFICATION_REQUIRED"; TECHNICAL_REVIEW_REQUIRED="TECHNICAL_REVIEW_REQUIRED"
    LLM_ELIGIBLE="LLM_ELIGIBLE"; M3_REQUIRED="M3_REQUIRED"; NON_BLOCKING_LIMITATION="NON_BLOCKING_LIMITATION"
class Sufficiency(S):
    SUFFICIENT="SUFFICIENT"; INSUFFICIENT_CLIENT_EVIDENCE="INSUFFICIENT_CLIENT_EVIDENCE"
    INSUFFICIENT_LAB_EVIDENCE="INSUFFICIENT_LAB_EVIDENCE"; INSUFFICIENT_STANDARD_CONTEXT="INSUFFICIENT_STANDARD_CONTEXT"
    INSUFFICIENT_TRACEABILITY="INSUFFICIENT_TRACEABILITY"; TECHNICAL_REVIEW_REQUIRED="TECHNICAL_REVIEW_REQUIRED"

@dataclass(frozen=True)
class ContextBudget:
    source_issue_count:int=0; affected_requirement_count:int=0; affected_clause_count:int=0
    report_evidence_count:int=0; standard_context_count:int=0; parameter_count:int=0
    traceability_count:int=0; estimated_character_count:int=0; estimated_token_count:int=0
@dataclass(frozen=True)
class CandidateRecord:
    candidate_id:str; candidate_type:CandidateType; ownership:Ownership; source_issue_ids:List[str]
    requirement_ids:List[str]; clause_ids:List[str]; question:str; deterministic_state:Dict[str,Any]
    product_context_refs:List[str]; standard_context_refs:List[str]; report_evidence_refs:List[str]
    parameter_refs:List[str]; na_refs:List[str]; root_cause_refs:List[str]; traceability_refs:List[str]
    why_llm_eligible:List[str]; forbidden_authority_changes:List[str]; requires_deterministic_reevaluation:bool
    deduplication_key:str; priority:str; context_budget:ContextBudget; context_sufficiency:Sufficiency
    parent_candidate_id:Optional[str]=None
    def to_dict(self): return asdict(self)
