"""Deterministic request construction and strict future-response validation."""
from __future__ import annotations
import hashlib,json,math,statistics
from collections import Counter
from dataclasses import asdict,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Dict,Mapping,Sequence
from .generic_llm_request_models import EvidenceAssessment,LLMRequestBundle,LLMRequestContext,ResponseStatus,StructuredLLMResponse,SuggestedApplicability

class LLMRequestContractError(ValueError):
    def __init__(self,code,details=None):self.code=code;self.details=details or {};super().__init__(json.dumps({"code":code,"details":self.details},sort_keys=True))

class GenericLLMRequestBuilder:
    VERSION="LLM_REQUEST_BUILDER_V1";SCHEMA_VERSION="1.0";RECOMMENDED_REQUEST_CHARS=24000
    PROHIBITED_RESPONSE_FIELDS={"compliance_decision","final_compliance_status","modified_numeric_limit","invented_measurement","replacement_requirement_text","source_gap_resolved"}
    TASK_OBJECTIVES={
      "APPLICABILITY_INTERPRETATION":"Assess applicability using only supplied requirements, evidence, and product facts.",
      "NA_JUSTIFICATION_INTERPRETATION":"Assess whether supplied context supports the reported not-applicable justification.",
      "EVIDENCE_SEMANTIC_INTERPRETATION":"Assess semantic support between supplied evidence and requirements.",
      "REPORT_SCOPE_INTERPRETATION":"Assess ownership and scope using supplied structural evidence.",
      "GROUPED_EVIDENCE_INTERPRETATION":"Assess supplied grouped evidence without promoting one verdict across requirements.",
      "KB_SEMANTIC_INTERPRETATION":"Interpret supplied requirement semantics without rewriting the knowledge base.",
      "CLIENT_EXPLANATION":"Explain the supplied deterministic state without changing it.",
      "NEXT_ACTION_EXPLANATION":"Explain the supplied next action without creating a new action."}

    def build_run(self,run_directory,output_path=None,**selection):
        root=Path(run_directory);bundle=self._load(root/"llm/llm_context_bundle.json");result=self.build_bundle(bundle,**selection);self.save_json(result,output_path or root/"llm/llm_request_bundle.json");return result
    def select(self,bundle,*,llm_context_id=None,final_issue_id=None,task=None,clause_id=None):
        values=self._plain(bundle).get("contexts",[])
        if llm_context_id is not None:values=[x for x in values if x.get("llm_context_id")==llm_context_id]
        if final_issue_id is not None:values=[x for x in values if x.get("final_issue_id")==final_issue_id]
        if task is not None:values=[x for x in values if task in (x.get("allowed_tasks") or [])]
        if clause_id is not None:values=[x for x in values if str((x.get("standard_context") or {}).get("clause_id"))==str(clause_id)]
        if any(x is not None for x in (llm_context_id,final_issue_id,task,clause_id)):
            if not values:raise LLMRequestContractError("NO_MATCH")
            if len(values)>1:raise LLMRequestContractError("MULTIPLE_MATCHES",{"matches":[{"llm_context_id":x.get("llm_context_id"),"final_issue_id":x.get("final_issue_id"),"primary_task":x.get("primary_task")} for x in values]})
        return values
    def build_bundle(self,context_bundle,**selection):
        bundle=self._plain(context_bundle);requests=[];rejections=[]
        try:selected=self.select(bundle,**selection)
        except LLMRequestContractError:raise
        for context in selected:
            try:requests.append(self.build_request(context))
            except LLMRequestContractError as exc:rejections.append({"llm_context_id":context.get("llm_context_id"),"final_issue_id":context.get("final_issue_id"),"code":exc.code,"details":exc.details})
        accounting=self._accounting(len(selected),requests,rejections)
        return LLMRequestBundle(self.SCHEMA_VERSION,self.VERSION,bundle.get("run_id"),accounting,requests,rejections)
    def build_request(self,context):
        c=self._plain(context);integrity=c.get("integrity") or {};locks=c.get("policy_locks") or {};authority=c.get("decision_authority")
        failures=[]
        if integrity.get("pre_llm_eligible") is not True:failures.append("PRE_LLM_NOT_ELIGIBLE")
        if integrity.get("source_context_integrity")!="COMPLETE":failures.append("SOURCE_CONTEXT_NOT_COMPLETE")
        if integrity.get("contamination_findings"):failures.append("CONTAMINATION_FINDING")
        if authority not in {"INTERPRETATION_ONLY","EXPLANATION_ONLY"}:failures.append("INVALID_AUTHORITY")
        if locks.get("human_review_required") is not False:failures.append("HUMAN_REVIEW_REQUIRED")
        if not isinstance(c.get("allowed_ids"),Mapping):failures.append("MISSING_ALLOWED_IDS")
        if not isinstance(c.get("output_contract"),Mapping):failures.append("MISSING_OUTPUT_CONTRACT")
        if failures:raise LLMRequestContractError("REQUEST_INVALID",{"reasons":failures})
        self._validate_request_ids(c)
        task=str(c.get("primary_task"));allowed_tasks=list(c.get("allowed_tasks") or [])
        if task not in allowed_tasks:raise LLMRequestContractError("REQUEST_INVALID",{"reasons":["PRIMARY_TASK_NOT_ALLOWED"]})
        model_authority={"decision_authority":authority,"may_change_compliance_decision":False,"may_change_numeric_limit":False,"may_invent_evidence":False,"may_invent_product_fact":False,"may_use_unknown_ids":False,"may_resolve_missing_source":False}
        task_contract={"task_type":task,"objective":self.TASK_OBJECTIVES.get(task,"Perform only the routed structured task."),"allowed_analysis_scope":allowed_tasks,"prohibited_actions":list(c["output_contract"].get("prohibited_effects") or []),"required_output_fields":["request_id","llm_context_id","final_issue_id","task","response_status","interpretation","confidence","supporting_requirement_ids","supporting_evidence_ids","supporting_product_fact_ids"]}
        content={"llm_context_id":c["llm_context_id"],"final_issue_id":c["final_issue_id"],"task":task,"allowed_tasks":allowed_tasks,"decision_authority":authority,"model_facing_authority":model_authority,"policy_locks":locks,"task_contract":task_contract,"standard_context":c.get("standard_context") or {},"requirement_context":c.get("requirement_context") or {},"product_context":c.get("product_context") or {},"report_context":c.get("report_context") or {},"deterministic_context":c.get("deterministic_context") or {},"allowed_ids":c["allowed_ids"],"output_contract":c["output_contract"],"source_context_signature":c.get("context_signature"),"request_schema_version":self.SCHEMA_VERSION}
        rid="LLM-REQUEST-"+hashlib.sha256(json.dumps(content,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()[:20].upper()
        base_chars=len(json.dumps(content,sort_keys=True,separators=(",",":"),ensure_ascii=False));source_chars=int((c.get("size_metrics") or {}).get("serialized_char_count") or base_chars)
        size={"serialized_char_count":base_chars,"approximate_token_count":math.ceil(base_chars/4),"requirement_count":len((c.get("requirement_context") or {}).get("requirements") or []),"evidence_count":len((c.get("report_context") or {}).get("evidence") or []),"product_fact_count":len((c.get("product_context") or {}).get("facts") or []),"measurement_count":sum(len(x.get("measurements") or []) for x in (c.get("report_context") or {}).get("evidence") or []),"source_context_char_count":source_chars,"size_reduction_percent":round((source_chars-base_chars)*100/source_chars,2) if source_chars else 0,"status":"REQUEST_TOO_LARGE" if base_chars>self.RECOMMENDED_REQUEST_CHARS else "READY"}
        return LLMRequestContext(rid,content["llm_context_id"],content["final_issue_id"],task,allowed_tasks,authority,model_authority,locks,task_contract,content["standard_context"],content["requirement_context"],content["product_context"],content["report_context"],content["deterministic_context"],content["allowed_ids"],content["output_contract"],{"status":"VALID","whitelist_validated":True,"source_context_integrity":"COMPLETE"},size,content["source_context_signature"],self.SCHEMA_VERSION)
    @staticmethod
    def _validate_request_ids(c):
        allowed=c["allowed_ids"];req=set(map(str,allowed.get("allowed_requirement_ids") or []));ev=set(map(str,allowed.get("allowed_evidence_ids") or []));facts=set(map(str,allowed.get("allowed_product_fact_ids") or []))
        actual_req={str(x.get("effective_requirement_id")) for x in (c.get("requirement_context") or {}).get("requirements") or [] if x.get("effective_requirement_id") is not None}
        actual_ev={str(x.get("evidence_id")) for x in (c.get("report_context") or {}).get("evidence") or [] if x.get("evidence_id") is not None}
        actual_facts={str(x.get("fact_id") or x.get("product_fact_id")) for x in (c.get("product_context") or {}).get("facts") or [] if x.get("fact_id") or x.get("product_fact_id")}
        unknown={"requirement_ids":sorted(actual_req-req),"evidence_ids":sorted(actual_ev-ev),"product_fact_ids":sorted(actual_facts-facts)}
        if any(unknown.values()):raise LLMRequestContractError("REQUEST_WHITELIST_VIOLATION",unknown)
    def validate_response(self,request,response):
        r=self._plain(response);known={x.name for x in StructuredLLMResponse.__dataclass_fields__.values()}
        forbidden=sorted(self.PROHIBITED_RESPONSE_FIELDS.intersection(r))
        if forbidden:raise LLMRequestContractError("PROHIBITED_RESPONSE_FIELD",{"fields":forbidden})
        unknown=sorted(set(r)-known)
        if unknown:raise LLMRequestContractError("INVALID_RESPONSE_FIELD",{"fields":unknown})
        for field in ("request_id","llm_context_id","final_issue_id","task"):
            if r.get(field)!=getattr(request,field):raise LLMRequestContractError("RESPONSE_ID_MISMATCH",{"field":field})
        try:status=ResponseStatus(r.get("response_status"));app=SuggestedApplicability(r.get("suggested_applicability","NOT_APPLICABLE_TO_TASK"));assessment=EvidenceAssessment(r.get("evidence_assessment","NOT_APPLICABLE_TO_TASK"))
        except ValueError as exc:raise LLMRequestContractError("INVALID_RESPONSE_ENUM") from exc
        confidence=r.get("confidence");
        if not isinstance(confidence,(int,float)) or isinstance(confidence,bool) or not 0<=confidence<=1:raise LLMRequestContractError("INVALID_CONFIDENCE")
        allowed=request.allowed_ids
        for field,key in (("supporting_requirement_ids","allowed_requirement_ids"),("supporting_evidence_ids","allowed_evidence_ids"),("supporting_product_fact_ids","allowed_product_fact_ids")):
            bad=sorted(set(map(str,r.get(field) or []))-set(map(str,allowed.get(key) or [])))
            if bad:raise LLMRequestContractError("RESPONSE_WHITELIST_VIOLATION",{"field":field,"ids":bad})
        allowed_fields=set(request.output_contract.get("allowed_fields") or [])
        semantic={"interpretation","suggested_applicability","evidence_assessment","missing_information","recommended_action","user_explanation"}
        disallowed=sorted(k for k in semantic if k in r and r[k] not in (None,[],"NOT_APPLICABLE_TO_TASK") and k not in allowed_fields)
        if disallowed:raise LLMRequestContractError("OUTPUT_CONTRACT_VIOLATION",{"fields":disallowed})
        return StructuredLLMResponse(request.request_id,request.llm_context_id,request.final_issue_id,request.task,status,r.get("interpretation"),app,assessment,float(confidence),list(r.get("supporting_requirement_ids") or []),list(r.get("supporting_evidence_ids") or []),list(r.get("supporting_product_fact_ids") or []),list(r.get("missing_information") or []),r.get("recommended_action"),r.get("user_explanation"),dict(r.get("model_metadata") or {}),{"validated":True,"validator_version":self.VERSION})
    def _accounting(self,total,requests,rejections):
        tokens=[x.size_metrics["approximate_token_count"] for x in requests];pct=[x.size_metrics["size_reduction_percent"] for x in requests];p95=lambda xs:sorted(xs)[min(len(xs)-1,math.ceil(.95*len(xs))-1)] if xs else 0
        return {"source_llm_contexts":total,"requests_generated":len(requests),"requests_rejected":len(rejections),"oversized_requests":sum(x.size_metrics["status"]=="REQUEST_TOO_LARGE" for x in requests),"average_request_tokens":round(sum(tokens)/len(tokens),2) if tokens else 0,"p95_request_tokens":p95(tokens),"max_request_tokens":max(tokens,default=0),"average_size_reduction_percent":round(sum(pct)/len(pct),2) if pct else 0,"by_task":dict(sorted(Counter(x.task for x in requests).items()))}
    @staticmethod
    def _load(path):return json.loads(path.read_text(encoding="utf-8"))
    @classmethod
    def _plain(cls,v):
        if isinstance(v,Enum):return v.value
        if is_dataclass(v):return cls._plain(asdict(v))
        if isinstance(v,Mapping):return {str(k):cls._plain(x) for k,x in v.items()}
        if isinstance(v,(list,tuple)):return [cls._plain(x) for x in v]
        return v
    @classmethod
    def to_json(cls,v,indent=2):return json.dumps(cls._plain(v),ensure_ascii=False,sort_keys=True,indent=indent)
    @classmethod
    def save_json(cls,v,path):p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(cls.to_json(v)+"\n",encoding="utf-8");return p

__all__=["GenericLLMRequestBuilder","LLMRequestContractError"]
