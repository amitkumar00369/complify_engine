import asyncio,json
from unittest.mock import patch
from iec_par.generic_llm_provider_models import LLMProviderConfig
from iec_par.generic_ollama_llm_adapter import OllamaLLMAdapter
from iec_par.generic_llm_request_builder import GenericLLMRequestBuilder
from tests.test_generic_llm_request_builder import ctx
class Response:
 status=200
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def read(self):return json.dumps({"model":"local","message":{"content":"{}"},"prompt_eval_count":1,"eval_count":2}).encode()
def test_adapter_envelope_and_metadata():
 request=GenericLLMRequestBuilder().build_request(ctx());config=LLMProviderConfig(model_name="local")
 with patch("urllib.request.urlopen",return_value=Response()) as call:result=asyncio.run(OllamaLLMAdapter().invoke(request,config))
 payload=json.loads(call.call_args.args[0].data);assert payload["stream"] is False and payload["format"]["additionalProperties"] is False and payload["model"]=="local"
 assert result.content=="{}" and result.provider=="ollama" and result.input_tokens==1
