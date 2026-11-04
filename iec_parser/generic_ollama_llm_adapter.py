"""Async Ollama adapter using only the standard library transport."""
from __future__ import annotations
import asyncio,hashlib,json,time,urllib.error,urllib.request
from dataclasses import asdict
from .generic_llm_provider_models import LLMProviderConfig,ProviderAdapterError,ProviderInvocationResult

class OllamaLLMAdapter:
    SYSTEM_INSTRUCTION=("Use only the supplied structured request. Return exactly one JSON object and no markdown. Echo request_id, llm_context_id, final_issue_id, and task exactly. Set response_status to VALID_RESPONSE. Include interpretation, confidence from 0.0 to 1.0, supporting_requirement_ids, supporting_evidence_ids, supporting_product_fact_ids, and missing_information. Emit suggested_applicability only when it is listed in output_contract.allowed_fields; its values are APPLICABLE, NOT_APPLICABLE, REVIEW_REQUIRED, UNKNOWN, or NOT_APPLICABLE_TO_TASK. Emit evidence_assessment only when it is listed in output_contract.allowed_fields; its values are SUPPORTS, DOES_NOT_SUPPORT, PARTIAL_SUPPORT, CONFLICTING, INSUFFICIENT, or NOT_APPLICABLE_TO_TASK. Omit every optional semantic field not listed in output_contract.allowed_fields. Reference only allowed IDs. Do not change compliance decisions or numeric constraints, invent evidence or product facts, resolve missing sources, or exceed the stated decision authority.")
    async def invoke(self,request,config):return await asyncio.to_thread(self._invoke_sync,request,config)
    def _invoke_sync(self,request,config):
        if not config.model_name:raise ProviderAdapterError("REQUEST_INVALID","model_name is required",False)
        generation={"temperature":config.temperature};
        if config.context_window is not None:generation["num_ctx"]=config.context_window
        if config.max_output_tokens is not None:generation["num_predict"]=config.max_output_tokens
        payload={"model":config.model_name,"messages":[{"role":"system","content":self.SYSTEM_INSTRUCTION},{"role":"user","content":json.dumps(asdict(request),ensure_ascii=False,sort_keys=True,separators=(",",":"))}],"stream":False,"format":self._response_schema(request),"options":generation}
        body=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode();started=time.monotonic()
        call=urllib.request.Request(config.base_url+"/api/chat",data=body,headers={"Content-Type":"application/json"},method="POST")
        try:
            with urllib.request.urlopen(call,timeout=config.timeout_seconds) as response:raw=response.read();status=response.status
        except urllib.error.HTTPError as exc:
            detail=exc.read().decode("utf-8",errors="replace")[:1000];code="MODEL_UNAVAILABLE" if exc.code>=500 else "REQUEST_INVALID"
            raise ProviderAdapterError(code,f"provider HTTP {exc.code}: {detail}",exc.code>=500) from exc
        except urllib.error.URLError as exc:
            reason=str(exc.reason);code="TIMEOUT" if "timed out" in reason.lower() else "MODEL_UNAVAILABLE";raise ProviderAdapterError(code,reason,True) from exc
        except TimeoutError as exc:raise ProviderAdapterError("TIMEOUT",str(exc),True) from exc
        try:data=json.loads(raw)
        except json.JSONDecodeError as exc:raise ProviderAdapterError("MODEL_RESPONSE_INVALID","provider envelope is not JSON",False) from exc
        content=((data.get("message") or {}).get("content"));
        if not isinstance(content,str):raise ProviderAdapterError("MODEL_RESPONSE_INVALID","provider response has no message.content",False)
        return ProviderInvocationResult(content,"ollama",config.model_name,data.get("model"),data.get("created_at"),round((time.monotonic()-started)*1000),data.get("prompt_eval_count"),data.get("eval_count"),hashlib.sha256(json.dumps(generation,sort_keys=True).encode()).hexdigest(),{"done_reason":data.get("done_reason"),"http_status":status})
    @staticmethod
    def _response_schema(request):
        allowed=set(request.output_contract.get("allowed_fields") or [])
        array=lambda values:{"type":"array","items":{"type":"string","enum":list(values)}} if values else {"type":"array","maxItems":0,"items":{"type":"string"}}
        properties={"request_id":{"type":"string","const":request.request_id},"llm_context_id":{"type":"string","const":request.llm_context_id},"final_issue_id":{"type":"string","const":request.final_issue_id},"task":{"type":"string","const":request.task},"response_status":{"type":"string","enum":["VALID_RESPONSE","MODEL_REFUSAL"]},"interpretation":{"type":"string"},"confidence":{"type":"number","minimum":0,"maximum":1},"supporting_requirement_ids":array(request.allowed_ids.get("allowed_requirement_ids") or []),"supporting_evidence_ids":array(request.allowed_ids.get("allowed_evidence_ids") or []),"supporting_product_fact_ids":array(request.allowed_ids.get("allowed_product_fact_ids") or []),"missing_information":{"type":"array","items":{"type":"string"}}}
        optional={"suggested_applicability":{"type":"string","enum":["APPLICABLE","NOT_APPLICABLE","REVIEW_REQUIRED","UNKNOWN","NOT_APPLICABLE_TO_TASK"]},"evidence_assessment":{"type":"string","enum":["SUPPORTS","DOES_NOT_SUPPORT","PARTIAL_SUPPORT","CONFLICTING","INSUFFICIENT","NOT_APPLICABLE_TO_TASK"]},"recommended_action":{"type":"string"},"user_explanation":{"type":"string"}}
        for key,schema in optional.items():
            if key in allowed:properties[key]=schema
        required=["request_id","llm_context_id","final_issue_id","task","response_status","interpretation","confidence","supporting_requirement_ids","supporting_evidence_ids","supporting_product_fact_ids","missing_information"]
        return {"type":"object","properties":properties,"required":required,"additionalProperties":False}

__all__=["OllamaLLMAdapter"]
