"""Models for the deterministic Step 32-B LLM routing policy."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class LLMRoute(str, Enum):
    DETERMINISTIC_ONLY = "DETERMINISTIC_ONLY"
    LLM_CANDIDATE = "LLM_CANDIDATE"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class AllowedLLMTask(str, Enum):
    NO_LLM_TASK = "NO_LLM_TASK"
    CLIENT_EXPLANATION = "CLIENT_EXPLANATION"
    APPLICABILITY_INTERPRETATION = "APPLICABILITY_INTERPRETATION"
    NA_JUSTIFICATION_INTERPRETATION = "NA_JUSTIFICATION_INTERPRETATION"
    EVIDENCE_SEMANTIC_INTERPRETATION = "EVIDENCE_SEMANTIC_INTERPRETATION"
    REPORT_SCOPE_INTERPRETATION = "REPORT_SCOPE_INTERPRETATION"
    GROUPED_EVIDENCE_INTERPRETATION = "GROUPED_EVIDENCE_INTERPRETATION"
    KB_SEMANTIC_INTERPRETATION = "KB_SEMANTIC_INTERPRETATION"
    NEXT_ACTION_EXPLANATION = "NEXT_ACTION_EXPLANATION"


class LLMDecisionAuthority(str, Enum):
    NO_DECISION_AUTHORITY = "NO_DECISION_AUTHORITY"
    INTERPRETATION_ONLY = "INTERPRETATION_ONLY"
    EXPLANATION_ONLY = "EXPLANATION_ONLY"


@dataclass(frozen=True)
class LLMRoutingDecision:
    context_id: str
    final_issue_id: str
    route: LLMRoute
    primary_reason_code: str
    secondary_reason_codes: List[str]
    context_integrity: str
    allowed_llm_tasks: List[AllowedLLMTask]
    prohibited_llm_tasks: List[AllowedLLMTask]
    llm_decision_authority: LLMDecisionAuthority
    human_review_required: bool
    deterministic_result_locked: bool
    source_gap_locked: bool
    numeric_result_locked: bool
    confidence_policy: str
    policy_version: str


@dataclass
class LLMRoutingResult:
    schema_version: str
    run_id: Optional[str]
    policy_version: str
    accounting: Dict[str, Any]
    routes: List[LLMRoutingDecision] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


__all__ = ["AllowedLLMTask", "LLMDecisionAuthority", "LLMRoute", "LLMRoutingDecision", "LLMRoutingResult"]
