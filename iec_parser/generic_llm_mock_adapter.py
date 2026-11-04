"""Deterministic non-semantic adapter stub for contract integration tests only."""
from .generic_llm_request_models import EvidenceAssessment,ResponseStatus,StructuredLLMResponse,SuggestedApplicability

class DeterministicMockLLMAdapter:
    def invoke(self,request):
        return StructuredLLMResponse(request.request_id,request.llm_context_id,request.final_issue_id,request.task,ResponseStatus.VALID_RESPONSE,"MOCK_INTERPRETATION_NOT_FOR_COMPLIANCE_USE",SuggestedApplicability.NOT_APPLICABLE_TO_TASK,EvidenceAssessment.NOT_APPLICABLE_TO_TASK,0.0,[],[],[],["MOCK_ONLY"],"MOCK_ONLY","MOCK_ONLY",{"provider":"MOCK","model_name":"DETERMINISTIC_TEST_STUB","model_version":"1","inference_id":"MOCK-"+request.request_id,"latency_ms":0,"input_tokens":0,"output_tokens":0,"generation_config_hash":"MOCK"},{"mock":True,"not_for_compliance_use":True})

__all__=["DeterministicMockLLMAdapter"]
