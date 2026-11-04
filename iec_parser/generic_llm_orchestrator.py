"""Sequential-by-default, resumable provider-neutral LLM orchestrator."""
from __future__ import annotations
import asyncio,gc,json
from dataclasses import asdict
from pathlib import Path
from typing import Any,Optional
from .generic_llm_execution_store import GenericLLMExecutionStore
from .generic_llm_provider_models import LLMProviderConfig,ProviderAdapterError
from .generic_llm_request_builder import GenericLLMRequestBuilder,LLMRequestContractError

class GenericStreamingLLMOrchestrator:
    VERSION="LLM_ORCHESTRATOR_V1"
    def __init__(self,adapter,request_builder=None):self.adapter=adapter;self.request_builder=request_builder or GenericLLMRequestBuilder()
    async def execute_run(self,run_directory,config:LLMProviderConfig,*,limit:Optional[int]=None,resume=True):
        root=Path(run_directory);bundle=json.loads((root/"llm/llm_context_bundle.json").read_text(encoding="utf-8"));store=GenericLLMExecutionStore(root/"llm");completed=store.completed_request_ids() if resume else set();accounting={"source_contexts":len(bundle.get("contexts",[])),"attempted":0,"completed":0,"resumed_skips":0,"request_invalid":0,"request_too_large":0,"adapter_errors":0,"response_invalid":0,"retries":0}
        processed=0
        for context in bundle.get("contexts",[]):
            if limit is not None and processed>=limit:break
            request=None;provider_result=None
            try:
                request=self.request_builder.build_request(context)
                if request.request_id in completed:accounting["resumed_skips"]+=1;continue
                if request.size_metrics.get("status")=="REQUEST_TOO_LARGE":
                    accounting["request_too_large"]+=1;store.append_audit(self._audit(request,"REQUEST_TOO_LARGE",0));continue
                processed+=1;accounting["attempted"]+=1
                for attempt in range(config.max_retries+1):
                    try:provider_result=await self.adapter.invoke(request,config);break
                    except ProviderAdapterError as exc:
                        if exc.retryable and attempt<config.max_retries:accounting["retries"]+=1;await asyncio.sleep(min(2**attempt,4));continue
                        accounting["adapter_errors"]+=1;store.append_audit(self._audit(request,exc.code,attempt+1,str(exc)));provider_result=None;break
                if provider_result is None:continue
                response_data=self._strict_json(provider_result.content)
                response_data["model_metadata"]={"provider":provider_result.provider,"model_name":provider_result.model_name,"model_version":provider_result.model_version,"inference_id":provider_result.inference_id,"latency_ms":provider_result.latency_ms,"input_tokens":provider_result.input_tokens,"output_tokens":provider_result.output_tokens,"generation_config_hash":provider_result.generation_config_hash}
                validated=self.request_builder.validate_response(request,response_data)
                store.append_result({"schema_version":"1.0","orchestrator_version":self.VERSION,"response":self.request_builder._plain(validated)})
                completed.add(request.request_id);store.checkpoint(completed);accounting["completed"]+=1;store.append_audit(self._audit(request,"COMPLETED",attempt+1))
            except LLMRequestContractError as exc:
                key="response_invalid" if request is not None and provider_result is not None else "request_invalid";accounting[key]+=1;store.append_audit({"request_id":getattr(request,"request_id",None),"llm_context_id":context.get("llm_context_id"),"status":exc.code,"details":exc.details})
            finally:request=None;provider_result=None;gc.collect()
        summary={"schema_version":"1.0","orchestrator_version":self.VERSION,"provider":config.provider,"model_name":config.model_name,"max_concurrency":config.max_concurrency,"resume_enabled":resume,"accounting":accounting};(root/"llm/llm_execution_summary.json").write_text(json.dumps(summary,sort_keys=True,indent=2)+"\n",encoding="utf-8");return summary
    @staticmethod
    def _strict_json(content):
        if not isinstance(content,str):raise LLMRequestContractError("MODEL_RESPONSE_INVALID",{"reason":"CONTENT_NOT_TEXT"})
        stripped=content.strip()
        if not stripped.startswith("{") or not stripped.endswith("}"):raise LLMRequestContractError("MODEL_RESPONSE_INVALID",{"reason":"STRICT_JSON_REQUIRED"})
        try:value=json.loads(stripped)
        except json.JSONDecodeError as exc:raise LLMRequestContractError("MODEL_RESPONSE_INVALID",{"reason":"INVALID_JSON","line":exc.lineno,"column":exc.colno}) from exc
        if not isinstance(value,dict):raise LLMRequestContractError("MODEL_RESPONSE_INVALID",{"reason":"JSON_OBJECT_REQUIRED"})
        return value
    @staticmethod
    def _audit(request,status,attempts,message=None):return {"request_id":request.request_id,"llm_context_id":request.llm_context_id,"final_issue_id":request.final_issue_id,"task":request.task,"status":status,"attempts":attempts,"message":message}

__all__=["GenericStreamingLLMOrchestrator"]
