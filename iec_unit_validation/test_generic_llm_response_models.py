import pytest
from iec_par.generic_llm_request_builder import GenericLLMRequestBuilder,LLMRequestContractError
from tests.test_generic_llm_request_builder import ctx

def valid(request):return {"request_id":request.request_id,"llm_context_id":request.llm_context_id,"final_issue_id":request.final_issue_id,"task":request.task,"response_status":"VALID_RESPONSE","interpretation":"advisory","suggested_applicability":"REVIEW_REQUIRED","confidence":0.5,"supporting_requirement_ids":["R"],"supporting_evidence_ids":["E"],"supporting_product_fact_ids":["P"]}
def test_valid_strict_response():
 b=GenericLLMRequestBuilder();r=b.build_request(ctx());parsed=b.validate_response(r,valid(r));assert parsed.validation_metadata["validated"]
def test_unknown_ids_confidence_and_prohibited_effects_rejected():
 b=GenericLLMRequestBuilder();r=b.build_request(ctx())
 for field,value in (("supporting_requirement_ids",["X"]),("supporting_evidence_ids",["X"]),("supporting_product_fact_ids",["X"]),("confidence",1.1),("confidence",-0.1),("compliance_decision","COMPLIANT")):
  payload=valid(r);payload[field]=value
  with pytest.raises(LLMRequestContractError):b.validate_response(r,payload)
