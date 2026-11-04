"""Provider-neutral runtime contracts for streaming LLM execution."""
from __future__ import annotations
import os
from dataclasses import dataclass,field
from typing import Any,Dict,Optional,Protocol
from .generic_llm_request_models import LLMRequestContext

@dataclass(frozen=True)
class LLMProviderConfig:
    provider:str="ollama";model_name:str="";base_url:str="http://localhost:11434";timeout_seconds:float=120.0;max_retries:int=2;max_concurrency:int=1;context_window:Optional[int]=None;temperature:float=0.0;max_output_tokens:Optional[int]=None
    @classmethod
    def from_env(cls):
        integer=lambda name: int(os.environ[name]) if os.environ.get(name) else None
        return cls(os.environ.get("LLM_PROVIDER","ollama"),os.environ.get("LLM_MODEL",""),os.environ.get("LLM_BASE_URL","http://localhost:11434").rstrip("/"),float(os.environ.get("LLM_TIMEOUT_SECONDS","120")),int(os.environ.get("LLM_MAX_RETRIES","2")),max(1,int(os.environ.get("LLM_MAX_CONCURRENCY","1"))),integer("LLM_CONTEXT_WINDOW"),float(os.environ.get("LLM_TEMPERATURE","0")),integer("LLM_MAX_OUTPUT_TOKENS"))
@dataclass
class ProviderInvocationResult:
    content:str;provider:str;model_name:str;model_version:Optional[str]=None;inference_id:Optional[str]=None;latency_ms:int=0;input_tokens:Optional[int]=None;output_tokens:Optional[int]=None;generation_config_hash:Optional[str]=None;raw_metadata:Dict[str,Any]=field(default_factory=dict)
class AsyncGenericLLMAdapter(Protocol):
    async def invoke(self,request:LLMRequestContext,config:LLMProviderConfig)->ProviderInvocationResult:...
class ProviderAdapterError(RuntimeError):
    def __init__(self,code:str,message:str,retryable:bool=False):self.code=code;self.retryable=retryable;super().__init__(message)

__all__=["AsyncGenericLLMAdapter","LLMProviderConfig","ProviderAdapterError","ProviderInvocationResult"]
