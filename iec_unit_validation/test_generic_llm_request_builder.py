import copy,math
import pytest
from iec_par.generic_llm_request_builder import GenericLLMRequestBuilder,LLMRequestContractError

def ctx():
 return {"llm_context_id":"LC","context_signature":"SIG","final_issue_id":"F","primary_task":"APPLICABILITY_INTERPRETATION","allowed_tasks":["APPLICABILITY_INTERPRETATION","CLIENT_EXPLANATION"],"decision_authority":"INTERPRETATION_ONLY","policy_locks":{"human_review_required":False,"numeric_result_locked":False},"standard_context":{"clause_id":"A"},"requirement_context":{"requirements":[{"effective_requirement_id":"R","text":"shall"}]},"product_context":{"facts":[{"fact_id":"P"}]},"report_context":{"evidence":[{"evidence_id":"E","reported_verdict":"NA"}]},"deterministic_context":{"issue":{"issue_type":"UNKNOWN_APPLICABILITY"}},"allowed_ids":{"allowed_requirement_ids":["R"],"allowed_evidence_ids":["E"],"allowed_product_fact_ids":["P"]},"output_contract":{"allowed_fields":["interpretation","suggested_applicability"],"prohibited_effects":["change_compliance_decision"]},"integrity":{"pre_llm_eligible":True,"source_context_integrity":"COMPLETE","contamination_findings":[]},"size_metrics":{"serialized_char_count":5000}}
def bundle():return {"run_id":"RUN","contexts":[ctx()]}
def test_selection_and_projection():
 b=GenericLLMRequestBuilder();assert b.select(bundle(),llm_context_id="LC")[0]["final_issue_id"]=="F";assert b.select(bundle(),final_issue_id="F")[0]["llm_context_id"]=="LC"
 r=b.build_bundle(bundle()).requests[0];assert r.allowed_ids["allowed_evidence_ids"]==["E"] and not r.model_facing_authority["may_change_compliance_decision"]
 assert r.size_metrics["approximate_token_count"]==math.ceil(r.size_metrics["serialized_char_count"]/4)
def test_multiple_and_ineligible_rejected():
 b=GenericLLMRequestBuilder();d=bundle();d["contexts"].append({**ctx(),"llm_context_id":"LC2","final_issue_id":"F"})
 with pytest.raises(LLMRequestContractError) as e:b.select(d,final_issue_id="F")
 assert e.value.code=="MULTIPLE_MATCHES"
 for change in ({"integrity":{"pre_llm_eligible":False,"source_context_integrity":"COMPLETE"}},{"decision_authority":"NO_DECISION_AUTHORITY"},{"policy_locks":{"human_review_required":True}}):
  c=ctx();c.update(change)
  with pytest.raises(LLMRequestContractError):b.build_request(c)
def test_request_whitelist_and_determinism():
 b=GenericLLMRequestBuilder();one=b.build_request(ctx());two=b.build_request(ctx());assert one.request_id==two.request_id
 bad=ctx();bad["report_context"]["evidence"][0]["evidence_id"]="UNKNOWN"
 with pytest.raises(LLMRequestContractError) as e:b.build_request(bad)
 assert e.value.code=="REQUEST_WHITELIST_VIOLATION"
