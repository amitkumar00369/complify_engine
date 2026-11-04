"""Execute eligible contexts one at a time through a configured local adapter."""
import argparse,asyncio,json
from iec_parser1.generic_llm_orchestrator import GenericStreamingLLMOrchestrator
from iec_parser1.generic_llm_provider_models import LLMProviderConfig
from iec_parser1.generic_ollama_llm_adapter import OllamaLLMAdapter

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--run-directory",required=True);parser.add_argument("--limit",type=int);parser.add_argument("--no-resume",action="store_true");args=parser.parse_args();config=LLMProviderConfig.from_env()
    if config.provider.casefold()!="ollama":raise SystemExit("configured provider has no installed adapter")
    result=asyncio.run(GenericStreamingLLMOrchestrator(OllamaLLMAdapter()).execute_run(args.run_directory,config,limit=args.limit,resume=not args.no_resume));print(json.dumps(result,sort_keys=True,indent=2))
