import asyncio,json
from pathlib import Path
from iec_par.generic_llm_orchestrator import GenericStreamingLLMOrchestrator
from iec_par.generic_llm_provider_models import LLMProviderConfig,ProviderAdapterError,ProviderInvocationResult

def context():
 return {"llm_context_id":"LC","context_signature":"SIG","final_issue_id":"F","primary_task":"APPLICABILITY_INTERPRETATION","allowed_tasks":["APPLICABILITY_INTERPRETATION"],"decision_authority":"INTERPRETATION_ONLY","policy_locks":{"human_review_required":False},"standard_context":{},"requirement_context":{"requirements":[{"effective_requirement_id":"R","text":"shall"}]},"product_context":{"facts":[]},"report_context":{"evidence":[{"evidence_id":"E"}]},"deterministic_context":{},"allowed_ids":{"allowed_requirement_ids":["R"],"allowed_evidence_ids":["E"],"allowed_product_fact_ids":[]},"output_contract":{"allowed_fields":["interpretation","suggested_applicability"],"prohibited_effects":[]},"integrity":{"pre_llm_eligible":True,"source_context_integrity":"COMPLETE","contamination_findings":[]},"size_metrics":{"serialized_char_count":1000}}
class FakeAdapter:
 def __init__(self,failures=0):self.calls=0;self.failures=failures
 async def invoke(self,request,config):
  self.calls+=1
  if self.calls<=self.failures:raise ProviderAdapterError("MODEL_UNAVAILABLE","temporary",True)
  content={"request_id":request.request_id,"llm_context_id":request.llm_context_id,"final_issue_id":request.final_issue_id,"task":request.task,"response_status":"VALID_RESPONSE","interpretation":"test","suggested_applicability":"REVIEW_REQUIRED","confidence":0.0,"supporting_requirement_ids":["R"],"supporting_evidence_ids":["E"],"supporting_product_fact_ids":[]}
  return ProviderInvocationResult(json.dumps(content),"FAKE","STUB")
def setup(tmp_path):
 root=tmp_path/"run";p=root/"llm/llm_context_bundle.json";p.parent.mkdir(parents=True);p.write_text(json.dumps({"run_id":"RUN","contexts":[context()]}));return root
def test_sequential_execution_checkpoint_and_resume(tmp_path):
 root=setup(tmp_path);adapter=FakeAdapter();runner=GenericStreamingLLMOrchestrator(adapter);config=LLMProviderConfig(provider="fake",model_name="stub",max_retries=0)
 first=asyncio.run(runner.execute_run(root,config));second=asyncio.run(runner.execute_run(root,config))
 assert first["accounting"]["completed"]==1 and second["accounting"]["resumed_skips"]==1 and adapter.calls==1
 assert len((root/"llm/llm_interpretation_results.jsonl").read_text().splitlines())==1
def test_retry_and_strict_json():
 adapter=FakeAdapter(1);request=None
 assert GenericStreamingLLMOrchestrator._strict_json('{"x":1}')=={"x":1}
 for bad in ('```json\n{}\n```','text {}','[]'):
  try:GenericStreamingLLMOrchestrator._strict_json(bad);raise AssertionError(bad)
  except Exception:pass
