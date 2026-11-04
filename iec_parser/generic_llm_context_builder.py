"""Build compact, source-grounded payloads for eligible routed contexts."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .generic_llm_context_models import GenericLLMContext, GenericLLMContextBundle


class GenericLLMContextBuilder:
    VERSION = "LLM_CONTEXT_BUILDER_V1"
    SCHEMA_VERSION = "1.0"
    RAW_TEXT_INLINE_LIMIT = 2000
    RECOMMENDED_CONTEXT_CHARS = 24000
    TASK_PRIORITY = ("APPLICABILITY_INTERPRETATION", "NA_JUSTIFICATION_INTERPRETATION", "EVIDENCE_SEMANTIC_INTERPRETATION", "REPORT_SCOPE_INTERPRETATION", "GROUPED_EVIDENCE_INTERPRETATION", "KB_SEMANTIC_INTERPRETATION", "CLIENT_EXPLANATION", "NEXT_ACTION_EXPLANATION")

    def build_run(self, run_directory: str | Path, output_path: str | Path | None = None):
        root=Path(run_directory); llm=root/"llm"
        resolved=self._load(llm/"resolved_compliance_context.json"); routing=self._load(llm/"llm_routing_result.json")
        integrity=self._load(llm/"pre_llm_integrity_result.json") if (llm/"pre_llm_integrity_result.json").is_file() else None
        result=self.build_bundle(resolved,routing,integrity); self.save_json(result,output_path or llm/"llm_context_bundle.json"); return result

    def build_bundle(self, resolved_bundle: Any, routing_result: Any, integrity_result: Any = None):
        resolved,routing,integrity=map(self._plain,(resolved_bundle,routing_result,integrity_result))
        route_by_id={str(x.get("context_id")):x for x in routing.get("routes",[])}
        permit_by_id={str(x.get("context_id")):x for x in (integrity or {}).get("contexts",[])}
        contexts=[]; exclusions=[]
        for source in resolved.get("contexts",[]):
            cid=str(source.get("context_id") or ""); route=route_by_id.get(cid)
            reasons=self._exclusion_reasons(source,route,permit_by_id.get(cid),integrity is not None)
            if reasons:
                exclusions.append({"context_id":cid,"final_issue_id":source.get("final_issue_id"),"reason":reasons[0],"reason_codes":reasons}); continue
            contexts.append(self._build_context(source,route,permit_by_id.get(cid)))
        accounting=self._accounting(len(resolved.get("contexts",[])),contexts,exclusions)
        return GenericLLMContextBundle(self.SCHEMA_VERSION,self.VERSION,resolved.get("run_id"),accounting,contexts,exclusions)

    @staticmethod
    def _exclusion_reasons(source,route,permit,gate_present):
        reasons=[]; integrity=source.get("resolution_integrity") or {}
        if not route: return ["MISSING_ROUTING_DECISION"]
        if route.get("route")!="LLM_CANDIDATE": reasons.append(str(route.get("route") or "UNKNOWN_ROUTE"))
        if integrity.get("status")!="COMPLETE": reasons.append(str(integrity.get("status") or "INVALID_REFERENCE"))
        for field,reason in (("duplicate_ids","DUPLICATE_REFERENCE"),("ambiguous_references","AMBIGUOUS_REFERENCE"),("missing_references","MISSING_REFERENCE"),("cross_scope_conflicts","CROSS_SCOPE_CONFLICT")):
            if integrity.get(field): reasons.append(reason)
        if route.get("source_gap_locked"): reasons.append("SOURCE_GAP_BLOCKED")
        if gate_present:
            if not permit: reasons.append("MISSING_INTEGRITY_DECISION")
            elif not permit.get("eligible_for_step_32c"):
                reasons.extend(permit.get("blocking_reason_codes") or ["INTEGRITY_BLOCKED"])
            if permit and permit.get("contamination_findings"): reasons.append("CONTAMINATION_BLOCKED")
        return list(dict.fromkeys(reasons))

    def _build_context(self,c,r,g):
        tasks=sorted(set(map(str,r.get("allowed_llm_tasks") or [])),key=lambda x:self.TASK_PRIORITY.index(x) if x in self.TASK_PRIORITY else len(self.TASK_PRIORITY))
        primary=tasks[0] if tasks else "NO_LLM_TASK"
        requirements=[self._requirement(x) for x in c.get("requirements") or []]
        group=self._group(c.get("requirement_group"))
        facts=[self._pick(x,("fact_id","product_fact_id","canonical_feature","feature_key","normalized_value","value","raw_value","source_value","confidence","status","scope","source_evidence_ids","evidence_refs","conflict_state")) for x in c.get("product_facts") or []]
        identities=[self._pick(x,("identity_id","product_identity_id","identity_type","value","normalized_value","role","confidence","status","source_evidence_ids","scope")) for x in c.get("product_identity") or []]
        evidence=[self._evidence(x) for x in c.get("report_evidence") or []]
        requirement_ids=sorted({str(x.get("effective_requirement_id")) for x in requirements if x.get("effective_requirement_id")})
        evidence_ids=sorted({str(x.get("evidence_id")) for x in evidence if x.get("evidence_id")})
        fact_ids=sorted({str(x.get("fact_id") or x.get("product_fact_id")) for x in facts if x.get("fact_id") or x.get("product_fact_id")})
        locks={k:r.get(k) for k in ("deterministic_result_locked","numeric_result_locked","source_gap_locked","human_review_required")}
        standard=self._standard(c,requirements)
        report={"evidence":evidence,"evidence_match":self._compact_stages(c.get("evidence_resolution") or []),"applicability":self._compact_stages(c.get("applicability_results") or []),"na_progression":self._na_summary(c.get("na_results") or []),"scope":self._compact_stages(c.get("scope_results") or [])}
        deterministic={"issue":self._pick(c.get("final_issue") or {},("issue_type","compliance_conclusion","severity","blocking","next_action","secondary_actions","provenance","diagnostic")),"originating_issue":self._pick(c.get("originating_issue") or {},("issue_id","issue_type","reason","status","severity","blocking","diagnostic")),"final_requirement_decisions":self._compact_stages(c.get("final_requirement_decisions") or []),"technical_results":self._compact_stages(c.get("technical_results") or [])}
        projection={"source_context_id":c.get("context_id"),"primary_task":primary,"allowed_tasks":tasks,"standard_context":standard,"requirement_context":{"requirements":requirements,"group":group},"product_context":{"facts":facts,"identities":identities},"report_context":report,"deterministic_context":deterministic,"locks":locks}
        signature_input={"primary_task":primary,"requirement_ids":requirement_ids,"evidence_ids":evidence_ids,"product_fact_ids":fact_ids,"reason":r.get("primary_reason_code"),"locks":locks}
        signature=self._hash("LLM-CONTEXT-SIGNATURE",signature_input); llm_id=self._hash("LLM-CONTEXT",{"projection":projection,"route":r})
        output_contract=self._output_contract(tasks)
        obj=GenericLLMContext(llm_id,signature,str(c.get("context_id")),str(c.get("final_issue_id")),primary,tasks,str(r.get("primary_reason_code")),str(r.get("llm_decision_authority")),locks,standard,{"requirements":requirements,"group":group},{"facts":facts,"identities":identities},report,deterministic,self._provenance(c),{"allowed_requirement_ids":requirement_ids,"allowed_evidence_ids":evidence_ids,"allowed_product_fact_ids":fact_ids},output_contract,{"source_context_integrity":(c.get("resolution_integrity") or {}).get("status"),"pre_llm_eligible":True,"contamination_findings":[]})
        plain=self._plain(obj); chars=len(json.dumps(plain,sort_keys=True,separators=(",",":"),ensure_ascii=False)); measurements=sum(len(x.get("measurements") or []) for x in evidence)
        obj.size_metrics={"serialized_char_count":chars,"approximate_token_count":math.ceil(chars/4),"requirement_count":len(requirements),"evidence_count":len(evidence),"product_fact_count":len(facts),"measurement_count":measurements,"inlined_raw_text_chars":sum(len(x.get("raw_text") or "") for x in evidence)}
        return obj

    def _evidence(self,x):
        fields=("evidence_id","evidence_type","clause_id","subclause_id","parent_evidence_id","child_evidence_ids","reported_verdict","raw_verdict_text","raw_requirement_text","raw_result_text","remarks","measurements","page_start","page_end","page","table_reference","evidence_scope_type","verdict_scope","row_group_id","logical_row_id","measurement_owner_evidence_id","verdict_owner_evidence_id","result_owner_evidence_id","source_order","notes")
        out=self._pick(x,fields); raw=x.get("raw_text")
        if "measurements" in out:
            measurement_fields=("measurement_id","parameter","parameter_text","operator","value","value_secondary","unit","unit_normalized","column_label","row_label","table_id","page","comparison","state","limit")
            out["measurements"]=[self._pick(item,measurement_fields) for item in out["measurements"] if isinstance(item,Mapping)]
        if isinstance(raw,str) and len(raw)<=self.RAW_TEXT_INLINE_LIMIT: out["raw_text"]=raw; out["raw_text_policy"]="SMALL_TEXT_INLINE"
        elif isinstance(raw,str): out["raw_text_ref"]={"evidence_id":x.get("evidence_id"),"field":"raw_text","character_count":len(raw)}; out["raw_text_policy"]="LARGE_TEXT_REFERENCE"
        return out

    def _requirement(self,x):
        out=self._pick(x,("effective_requirement_id","clause_id","text","normative","effective_status","effective_source_type","condition_text","applicability","requirement_type","semantic_type","technical_constraints","references","base_sources","delta_sources","review_reason"))
        if x.get("canonical_resolution"): out["canonical_source_locations"]=(x["canonical_resolution"].get("source_locations") or [])
        return out

    def _group(self,x):
        if not x:return {}
        out=self._pick(x,("group_id","primary_requirement_id","member_requirement_ids","requirement_ids","status","group_status","grouping_reason","grouping_type","shared_condition","applicability","clause_id"))
        if "member_requirement_ids" not in out: out["member_requirement_ids"]=sorted({str(m.get("effective_requirement_id") or m.get("requirement_id")) for m in x.get("members",[]) if isinstance(m,Mapping) and (m.get("effective_requirement_id") or m.get("requirement_id"))})
        return out

    def _standard(self,c,requirements):
        source=((c.get("source_provenance") or {}).get("standard") or [{}])[0]
        return {"effective_kb_id":source.get("effective_kb_id"),"base_standard":self._pick(source.get("base_standard") or {},("standard_id","standard_number","edition","year","document_type")),"companion_standard":self._pick(source.get("delta_standard") or {},("standard_id","standard_number","edition","year","document_type","parent_standard")),"clause_id":c.get("clause_id"),"source_pages":sorted({p for x in requirements for s in (x.get("base_sources") or [])+(x.get("delta_sources") or []) for p in (s.get("page_start"),s.get("page_end")) if p is not None})}

    @staticmethod
    def _pick(x,fields): return {k:x[k] for k in fields if k in x and x[k] is not None}
    def _compact_stages(self,values):
        fields=("source_stage","effective_requirement_id","requirement_id","group_id","decision","state","status","reason_code","reason","condition","confidence","evidence_ids","evidence_refs","selected_evidence_ids","match_status","match_reason","scope_state","scope_reason","comparison","measured_value","measured_unit","operator","limit","unit","compliance_conclusion","decision_basis","unresolved_reason")
        return [self._pick(x,fields) for x in values]
    def _na_summary(self,values): return [{**self._pick(x,("source_stage","effective_requirement_id","requirement_id","group_id","state","status","decision","reason_code","reason","reported_verdict","evidence_ids","conflicting_verdicts"))} for x in values]
    def _provenance(self,c):
        p=c.get("source_provenance") or {}; return {"standard":p.get("standard",[]),"report":p.get("report",[]),"product":p.get("product",[]),"deterministic_artifacts":p.get("deterministic_artifacts",[])}
    @staticmethod
    def _output_contract(tasks):
        allowed={"interpretation","confidence","supporting_requirement_ids","supporting_evidence_ids","missing_information","user_explanation","recommended_action"}
        if "APPLICABILITY_INTERPRETATION" in tasks: allowed.add("suggested_applicability")
        if any("EVIDENCE" in x or "SCOPE" in x for x in tasks): allowed.add("evidence_assessment")
        return {"allowed_fields":sorted(allowed),"prohibited_effects":["change_numeric_limit","invent_evidence","invent_product_fact","override_locked_result","resolve_missing_source","use_unknown_ids","change_compliance_decision"]}

    def _accounting(self,total,contexts,exclusions):
        chars=[x.size_metrics["serialized_char_count"] for x in contexts]; tokens=[x.size_metrics["approximate_token_count"] for x in contexts]; signatures=Counter(x.context_signature for x in contexts)
        percentile=lambda xs,p: sorted(xs)[min(len(xs)-1,math.ceil(len(xs)*p)-1)] if xs else 0
        return {"source_contexts":total,"eligible_contexts":len(contexts),"contexts_built":len(contexts),"excluded_contexts":len(exclusions),"by_primary_task":dict(sorted(Counter(x.primary_task for x in contexts).items())),"by_exclusion_reason":dict(sorted(Counter(x["reason"] for x in exclusions).items())),"size_metrics":{"token_estimate_method":"ceil(serialized_chars / 4)","average_chars_per_context":round(sum(chars)/len(chars),2) if chars else 0,"median_chars_per_context":statistics.median(chars) if chars else 0,"p95_chars_per_context":percentile(chars,.95),"max_chars_per_context":max(chars,default=0),"approximate_total_tokens":sum(tokens),"average_approximate_tokens":round(sum(tokens)/len(tokens),2) if tokens else 0,"p95_approximate_tokens":percentile(tokens,.95),"max_approximate_tokens":max(tokens,default=0),"contexts_exceeding_recommended_threshold":sum(x>self.RECOMMENDED_CONTEXT_CHARS for x in chars),"recommended_context_char_threshold":self.RECOMMENDED_CONTEXT_CHARS},"deduplication_metrics":{"unique_requirement_sets":len({tuple(x.allowed_ids["allowed_requirement_ids"]) for x in contexts}),"unique_evidence_sets":len({tuple(x.allowed_ids["allowed_evidence_ids"]) for x in contexts}),"unique_task_context_signatures":len(signatures),"duplicate_signature_count":sum(n-1 for n in signatures.values() if n>1),"repeated_requirement_evidence_combinations":len(contexts)-len({(tuple(x.allowed_ids["allowed_requirement_ids"]),tuple(x.allowed_ids["allowed_evidence_ids"])) for x in contexts}),"potential_grouping_opportunities":sum(1 for n in signatures.values() if n>1)}}

    @staticmethod
    def _hash(prefix,value): return prefix+"-"+hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()[:20].upper()
    @staticmethod
    def _load(path): return json.loads(path.read_text(encoding="utf-8"))
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


__all__=["GenericLLMContextBuilder"]
