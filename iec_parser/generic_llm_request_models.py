"""Provider-neutral request, response, and adapter contracts for Step 32-D1."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

class ResponseStatus(str,Enum):
    VALID_RESPONSE="VALID_RESPONSE";MODEL_REFUSAL="MODEL_REFUSAL";INVALID_STRUCTURE="INVALID_STRUCTURE";INCOMPLETE_RESPONSE="INCOMPLETE_RESPONSE";ADAPTER_ERROR="ADAPTER_ERROR"
class SuggestedApplicability(str,Enum):
    APPLICABLE="APPLICABLE";NOT_APPLICABLE="NOT_APPLICABLE";REVIEW_REQUIRED="REVIEW_REQUIRED";UNKNOWN="UNKNOWN";NOT_APPLICABLE_TO_TASK="NOT_APPLICABLE_TO_TASK"
class EvidenceAssessment(str,Enum):
    SUPPORTS="SUPPORTS";DOES_NOT_SUPPORT="DOES_NOT_SUPPORT";PARTIAL_SUPPORT="PARTIAL_SUPPORT";CONFLICTING="CONFLICTING";INSUFFICIENT="INSUFFICIENT";NOT_APPLICABLE_TO_TASK="NOT_APPLICABLE_TO_TASK"
class AdapterErrorCode(str,Enum):
    REQUEST_INVALID="REQUEST_INVALID";REQUEST_TOO_LARGE="REQUEST_TOO_LARGE";TIMEOUT="TIMEOUT";MODEL_UNAVAILABLE="MODEL_UNAVAILABLE";MODEL_RESPONSE_INVALID="MODEL_RESPONSE_INVALID";MODEL_REFUSAL="MODEL_REFUSAL";ADAPTER_INTERNAL_ERROR="ADAPTER_INTERNAL_ERROR"

@dataclass(frozen=True)
class RetryPolicy:
    max_retries:int=2
    retryable_errors:List[str]=field(default_factory=lambda:["TIMEOUT","MODEL_UNAVAILABLE"])
    non_retryable_errors:List[str]=field(default_factory=lambda:["REQUEST_INVALID","REQUEST_TOO_LARGE","MODEL_RESPONSE_INVALID","MODEL_REFUSAL"])
@dataclass
class LLMRequestContext:
    request_id:str;llm_context_id:str;final_issue_id:str;task:str;allowed_tasks:List[str];decision_authority:str;model_facing_authority:Dict[str,Any];policy_locks:Dict[str,Any];task_contract:Dict[str,Any];standard_context:Dict[str,Any];requirement_context:Dict[str,Any];product_context:Dict[str,Any];report_context:Dict[str,Any];deterministic_context:Dict[str,Any];allowed_ids:Dict[str,List[str]];output_contract:Dict[str,Any];request_integrity:Dict[str,Any];size_metrics:Dict[str,Any];source_context_signature:str;request_schema_version:str
@dataclass
class LLMRequestBundle:
    schema_version:str;request_builder_version:str;run_id:Optional[str];accounting:Dict[str,Any];requests:List[LLMRequestContext];rejections:List[Dict[str,Any]]
    def to_dict(self):return asdict(self)
@dataclass
class StructuredLLMResponse:
    request_id:str;llm_context_id:str;final_issue_id:str;task:str;response_status:ResponseStatus;interpretation:Optional[str]=None;suggested_applicability:SuggestedApplicability=SuggestedApplicability.NOT_APPLICABLE_TO_TASK;evidence_assessment:EvidenceAssessment=EvidenceAssessment.NOT_APPLICABLE_TO_TASK;confidence:float=0.0;supporting_requirement_ids:List[str]=field(default_factory=list);supporting_evidence_ids:List[str]=field(default_factory=list);supporting_product_fact_ids:List[str]=field(default_factory=list);missing_information:List[str]=field(default_factory=list);recommended_action:Optional[str]=None;user_explanation:Optional[str]=None;model_metadata:Dict[str,Any]=field(default_factory=dict);validation_metadata:Dict[str,Any]=field(default_factory=dict)
class GenericLLMAdapter(Protocol):
    def invoke(self,request:LLMRequestContext)->StructuredLLMResponse:...

__all__=["AdapterErrorCode","EvidenceAssessment","GenericLLMAdapter","LLMRequestBundle","LLMRequestContext","ResponseStatus","RetryPolicy","StructuredLLMResponse","SuggestedApplicability"]
