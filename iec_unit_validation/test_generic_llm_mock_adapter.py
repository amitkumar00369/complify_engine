from iec_par.generic_llm_mock_adapter import DeterministicMockLLMAdapter
from iec_par.generic_llm_request_builder import GenericLLMRequestBuilder
from tests.test_generic_llm_request_builder import ctx

def test_mock_is_deterministic_and_unmistakable():
 request=GenericLLMRequestBuilder().build_request(ctx());adapter=DeterministicMockLLMAdapter();a=adapter.invoke(request);b=adapter.invoke(request)
 assert a==b and a.model_metadata["provider"]=="MOCK" and a.model_metadata["model_name"]=="DETERMINISTIC_TEST_STUB"
 assert a.confidence==0 and "NOT_FOR_COMPLIANCE_USE" in a.interpretation
