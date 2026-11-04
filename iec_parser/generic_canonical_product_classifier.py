"""Step 48-C deterministic two-level product classification authority."""
from __future__ import annotations
import copy,hashlib,json,re
from collections import defaultdict
from dataclasses import asdict,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Mapping

CLASSIFICATION_SCHEMA_VERSION="CANONICAL_PRODUCT_CLASSIFICATION_V2"
CLASSIFICATION_POLICY_VERSION="STEP48C_CLASSIFICATION_AUTHORITY_V1"
CLASSIFICATION_HIERARCHY_VERSION="STEP51B_CLASSIFICATION_HIERARCHY_V1"
PRODUCT_SPECIFIC_BRANCHES_ADDED=0
MODEL_SPECIFIC_BRANCHES_ADDED=0
REPORT_SPECIFIC_BRANCHES_ADDED=0
STANDARD_SPECIFIC_BRANCHES_ADDED=0
CLAUSE_SPECIFIC_BRANCHES_ADDED=0
GOLDEN_SPECIFIC_BRANCHES_ADDED=0

class ClassificationLevel(str,Enum):STANDARD_SCOPE="STANDARD_SCOPE";PRODUCT_SUBTYPE="PRODUCT_SUBTYPE"
class ClassificationStatus(str,Enum):MATCH="MATCH";NO_MATCH="NO_MATCH";UNKNOWN="UNKNOWN";NEEDS_REVIEW="NEEDS_REVIEW";CONFLICTING="CONFLICTING"
class AuthorityTier(str,Enum):HIGH="HIGH";MEDIUM="MEDIUM";LOW="LOW";NONE="NONE"

class GenericCanonicalProductClassifier:
    """Classify canonical identity against indexed KB scope and definitions."""
    HIGH_CONFIDENCE=0.90
    MEDIUM_CONFIDENCE=0.70
    RELATIONSHIPS=("IS_A","SUBTYPE_OF","WITHIN_SCOPE_OF","EQUIVALENT_TO","RELATED_TO","NO_RELATION","UNKNOWN")

    def classify(self,effective_kb:Any,fact_ledger:Any,identity_store:Any,identity_relationships:Any=None,legacy_profile:Any=None,standard_validation:Any=None)->dict:
        kb=self._plain(effective_kb or {});facts=self._plain(fact_ledger or {});identity=self._plain(identity_store or {});legacy=self._plain(legacy_profile or {});validation=self._plain(standard_validation or {})
        scope_nodes=self._scope_nodes(kb);definitions=self._definition_index(kb);terms=self._identity_terms(identity)+self._fact_terms(facts);fact_ids=[x.get("fact_id") for x in facts.get("facts",[]) if x.get("fact_id")]
        standard_domain=self._standard_domain(kb)
        level_a=self._standard_scope(scope_nodes,terms,identity,validation,kb)
        level_b,candidates,conflicts=self._product_subtype(definitions,scope_nodes,terms,identity,fact_ids,legacy)
        compatibility=self._compatibility(legacy,level_b)
        result={"schema_version":CLASSIFICATION_SCHEMA_VERSION,"policy_version":CLASSIFICATION_POLICY_VERSION,"hierarchy_policy_version":CLASSIFICATION_HIERARCHY_VERSION,"source_fact_contract":facts.get("schema_version"),"source_identity_contract":identity.get("schema_version"),"standard_domain":standard_domain,"standard_scope":level_a,"standard_scope_family":copy.deepcopy(level_a),"product_subtype":level_b,"candidates":candidates,"conflicts":conflicts,"compatibility_projection":compatibility,"authority_boundary":{"applicability_mutated":False,"requirement_state_mutated":False,"legacy_has_authority":False}}
        result["classification_sha256"]=self._hash(result);return result

    def validate(self,result:Any,effective_kb:Any,fact_ledger:Any,identity_store:Any,downstream_version:str=None)->dict:
        data=self._plain(result or {});kb=self._plain(effective_kb or {});facts=self._plain(fact_ledger or {});identity=self._plain(identity_store or {});diagnostics=[]
        statuses={x.value for x in ClassificationStatus};tiers={x.value for x in AuthorityTier};scope_ids={x["scope_id"] for x in self._scope_nodes(kb)};definition_ids={str(x.get("effective_definition_id") or x.get("definition_id")) for x in kb.get("definitions",[]) or []};fact_ids={x.get("fact_id") for x in facts.get("facts",[])};identity_source_ids={sid for v in (identity.get("product") or {}).values() for sid in v.get("source_ids",[])}|{x.get("identity_id") for x in identity.get("models",[])};terms=self._identity_terms(identity)
        levels=[data.get("standard_domain") or {},data.get("standard_scope") or {},data.get("product_subtype") or {}]
        for item in levels:
            cid=item.get("classification_id")
            if item.get("status") not in statuses:diagnostics.append(self._diag("INVALID_CLASSIFICATION_STATUS",cid))
            if item.get("authority_tier") not in tiers:diagnostics.append(self._diag("INVALID_AUTHORITY_TIER",cid))
            registry_trace=item.get("classification_level")=="STANDARD_DOMAIN" and bool(item.get("source_provenance",{}).get("registry_policy_version"))
            trace=bool(item.get("source_evidence_ids") or item.get("source_identity_ids") or item.get("source_fact_ids") or item.get("kb_definition_ids") or item.get("standard_scope_ids") or registry_trace)
            if item.get("authority_tier") in {"HIGH","MEDIUM"} and not trace:diagnostics.append(self._diag("CLASSIFICATION_SOURCE_TRACE_MISSING",cid))
            strong=registry_trace or (bool(item.get("standard_scope_ids") or item.get("kb_definition_ids")) and bool(item.get("source_evidence_ids") or item.get("source_identity_ids") or item.get("source_fact_ids")))
            if item.get("authority_tier")=="HIGH" and not strong:diagnostics.append(self._diag("UNSUPPORTED_HIGH_AUTHORITY",cid))
            if item.get("classification_level")=="PRODUCT_SUBTYPE" and item.get("status")=="MATCH" and item.get("authority_tier")=="LOW":diagnostics.append(self._diag("LOW_AUTHORITY_CONFIRMED_AS_EXACT",cid))
            if any(x not in scope_ids for x in item.get("standard_scope_ids",[])):diagnostics.append(self._diag("INVALID_HIERARCHY_PATH",cid))
            if any(x not in definition_ids for x in item.get("kb_definition_ids",[])):diagnostics.append(self._diag("INVALID_HIERARCHY_PATH",cid))
            if any(x not in fact_ids for x in item.get("source_fact_ids",[])):diagnostics.append(self._diag("CLASSIFICATION_SOURCE_TRACE_MISSING",cid))
            if any(x not in identity_source_ids for x in item.get("source_identity_ids",[])):diagnostics.append(self._diag("CLASSIFICATION_SOURCE_TRACE_MISSING",cid))
        domain,a,b=levels
        if len({x.get("classification_level") for x in levels})!=3:diagnostics.append(self._diag("CLASSIFICATION_LEVEL_COLLISION",None))
        if data.get("conflicts") and any(x.get("authority_tier")=="HIGH" for x in levels):diagnostics.append(self._diag("INCOMPATIBLE_CLASS_CONFLICT_NOT_RECORDED",None))
        comp=data.get("compatibility_projection") or {}
        if comp.get("legacy_has_authority"):diagnostics.append(self._diag("LEGACY_OVERRIDE",None))
        if downstream_version and downstream_version!=data.get("policy_version"):diagnostics.append(self._diag("STALE_CLASSIFICATION_VERSION",None))
        if b.get("canonical_class") and b.get("reason_code")=="RAW_PRODUCT_TYPE_COPY":diagnostics.append(self._diag("PRODUCT_TYPE_CLASS_COLLAPSE",b.get("classification_id")))
        if scope_ids and a.get("status")=="UNKNOWN" and terms:diagnostics.append(self._diag("MISSING_STANDARD_SCOPE_CLASSIFICATION",a.get("classification_id")))
        counts=defaultdict(int)
        for x in diagnostics:counts[x["code"]]+=1
        return {"schema_version":"CANONICAL_PRODUCT_CLASSIFICATION_INTEGRITY_V1","classification_schema_version":data.get("schema_version"),"classification_policy_version":data.get("policy_version"),"valid":not diagnostics,"diagnostic_count":len(diagnostics),"diagnostic_counts":dict(sorted(counts.items())),"diagnostics":diagnostics}

    def _standard_domain(self,kb):
        registry_path=Path(__file__).with_name("canonical_standard_scope_hierarchy_registry.json")
        registry=json.loads(registry_path.read_text(encoding="utf-8")); base=kb.get("base_standard") or {}; delta=kb.get("delta_standard") or {}
        family=str(delta.get("parent_standard") or base.get("standard_number") or "").strip()
        row=next((x for x in registry.get("families",[]) if str(x.get("standard_family") or "").strip()==family),None)
        if not row:return self._result("STANDARD_DOMAIN",None,"UNKNOWN",0.0,"NONE",[],reason="STANDARD_FAMILY_HIERARCHY_NOT_MAPPED")
        result=self._result("STANDARD_DOMAIN",row["standard_domain"],"MATCH",1.0,"HIGH",["CANONICAL_STANDARD_FAMILY_METADATA"],reason="STANDARD_DOMAIN_INHERITED_FROM_CANONICAL_FAMILY")
        result["standard_family"]=family;result["source_provenance"]={"registry_schema_version":registry.get("schema_version"),"registry_policy_version":registry.get("policy_version"),"standard_family":family,"authority":row.get("authority")};return result

    def _standard_scope(self,nodes,terms,identity,validation,kb):
        evidence_ids=sorted({sid for x in terms for sid in x["source_ids"]});source_fact_ids=sorted({fid for x in terms for fid in x.get("source_fact_ids",[])});available=[(self._scope_class(x["text"]),x) for x in nodes];available=[x for x in available if x[0]];available.sort(key=lambda x:(len(self._tokens(x[0])),len(x[0]),x[1]["scope_id"]));canonical,best=available[0] if available else (None,None)
        if not best:return self._result("STANDARD_SCOPE",None,"UNKNOWN",0.0,"NONE",[],reason="NO_STRUCTURED_STANDARD_SCOPE")
        validation_status=str(validation.get("status") or validation.get("standard_validation_status") or "")
        confidence=.99 if canonical and evidence_ids and validation_status in {"VALID","PARTIAL_MATCH"} else .85 if canonical and evidence_ids else .6
        authority="HIGH" if confidence>=.9 else "MEDIUM" if confidence>=.7 else "LOW"
        status="MATCH" if authority in {"HIGH","MEDIUM"} else "NEEDS_REVIEW"
        hierarchy=[{"relationship":"WITHIN_SCOPE_OF","from_class":canonical,"to_standard":kb.get("effective_kb_id"),"source_ids":[best["scope_id"]]}]
        result=self._result("STANDARD_SCOPE",canonical,status,confidence,authority,["STANDARD_SCOPE","CANONICAL_PRODUCT_IDENTITY","CANONICAL_PRODUCT_FACTS","STANDARD_VALIDATION"],scope_ids=[best["scope_id"]],evidence_ids=evidence_ids,hierarchy=hierarchy,reason="GOVERNING_SCOPE_AND_IDENTITY_SUPPORTED");result["source_fact_ids"]=source_fact_ids;return result

    def _product_subtype(self,definitions,scope_nodes,terms,identity,fact_ids,legacy):
        candidates=[];scope_text=" ".join(x["normalized"] for x in scope_nodes)
        for term in terms:
            normalized=term["normalized"];tokens=self._tokens(normalized)
            for definition_term,defs in definitions.items():
                score=self._similarity(tokens,self._tokens(definition_term))
                if score<=0:continue
                candidates.append(self._candidate(definition_term,score,term,defs[0],"STANDARD_DEFINITION"))
            if normalized and self._phrase_present(normalized,scope_text):candidates.append(self._candidate(normalized,.96,term,None,"STANDARD_SCOPE"))
        legacy_item=next(iter(legacy.get("classifications",[]) or []),None)
        if legacy_item and legacy_item.get("canonical_term"):
            norm=self._normalize(legacy_item["canonical_term"]);definition=next(iter(definitions.get(norm,[])),None);score=float(legacy_item.get("confidence") or 0)
            candidates.append(self._candidate(norm,score,{"source_ids":self._legacy_evidence_ids(legacy_item),"field":"legacy_classification","normalized":norm},definition,"LEGACY_COMPATIBILITY_CANDIDATE"))
        indexed={}
        for x in candidates:
            key=(x["canonical_class"],x["basis"]);current=indexed.get(key)
            if current is None or x["confidence"]>current["confidence"]:indexed[key]=x
        candidates=sorted(indexed.values(),key=lambda x:(-x["confidence"],x["canonical_class"],x["basis"]));best=candidates[0] if candidates else None
        conflicts=[]
        if best:
            same=[x for x in candidates if x["canonical_class"]!=best["canonical_class"] and abs(x["confidence"]-best["confidence"])<.03 and x["confidence"]>=self.MEDIUM_CONFIDENCE]
            conflicts=[{"conflict_id":"CLASS-CONFLICT-"+self._hash([best,same])[:16].upper(),"classification_level":"PRODUCT_SUBTYPE","candidates":[best]+same,"reason_code":"INCOMPATIBLE_EQUAL_AUTHORITY_CANDIDATES"}] if same else []
        if conflicts:return self._result("PRODUCT_SUBTYPE",None,"CONFLICTING",best["confidence"],"NONE",["CONFLICTING_CLASSIFICATION_EVIDENCE"],evidence_ids=best["source_evidence_ids"],reason="SAME_LEVEL_CONFLICT"),candidates,conflicts
        if not best:return self._result("PRODUCT_SUBTYPE",None,"UNKNOWN",0.0,"NONE",[],reason="NO_SUPPORTED_SUBTYPE"),candidates,[]
        definition_supported=bool(best["kb_definition_ids"]);scope_supported=best["basis"]=="STANDARD_SCOPE"
        strong_identity=bool(best["source_evidence_ids"])
        if best["confidence"]>=self.HIGH_CONFIDENCE and strong_identity and (definition_supported or scope_supported):status,authority="MATCH","HIGH"
        elif best["confidence"]>=self.MEDIUM_CONFIDENCE and strong_identity and (definition_supported or scope_supported):status,authority="MATCH","MEDIUM"
        else:status,authority="NEEDS_REVIEW","LOW"
        scope_ids=[scope_nodes[0]["scope_id"]] if scope_supported and scope_nodes else []
        hierarchy=[]
        if definition_supported:hierarchy.append({"relationship":"EQUIVALENT_TO","from_class":best["canonical_class"],"to_definition":best["kb_definition_ids"][0],"source_ids":best["kb_definition_ids"]})
        if scope_supported:hierarchy.append({"relationship":"WITHIN_SCOPE_OF","from_class":best["canonical_class"],"to_scope":scope_ids[0],"source_ids":scope_ids})
        result=self._result("PRODUCT_SUBTYPE",best["canonical_class"],status,best["confidence"],authority,["CANONICAL_PRODUCT_IDENTITY","CANONICAL_PRODUCT_FACTS",best["basis"]],definition_ids=best["kb_definition_ids"],scope_ids=scope_ids,evidence_ids=best["source_evidence_ids"],hierarchy=hierarchy,reason="SUPPORTED_SUBTYPE" if status=="MATCH" else "WEAK_SUBTYPE_INFERENCE");result["source_fact_ids"]=best.get("source_fact_ids",[])
        return result,candidates,[]

    def _candidate(self,canonical,confidence,term,definition,basis):return {"candidate_id":"CLASS-CANDIDATE-"+self._hash([canonical,basis,term.get("field")])[:16].upper(),"classification_level":"PRODUCT_SUBTYPE","canonical_class":self._class_name(canonical),"normalized_term":canonical,"confidence":round(float(confidence),4),"basis":basis,"source_evidence_ids":sorted(set(term.get("source_ids",[]))),"source_fact_ids":sorted(set(term.get("source_fact_ids",[]))),"kb_definition_ids":[str(definition.get("effective_definition_id") or definition.get("definition_id"))] if definition else []}
    def _result(self,level,canonical,status,confidence,authority,basis,definition_ids=None,scope_ids=None,evidence_ids=None,hierarchy=None,reason=None):
        payload={"classification_level":level,"canonical_class":self._class_name(canonical) if canonical else None,"status":status,"confidence":round(float(confidence),4),"authority_tier":authority,"classification_basis":basis,"relationship_path":hierarchy or [],"source_fact_ids":[],"source_identity_ids":[],"source_evidence_ids":evidence_ids or [],"kb_definition_ids":definition_ids or [],"standard_scope_ids":scope_ids or [],"reason_code":reason,"classification_version":CLASSIFICATION_POLICY_VERSION,"traceability":{"authority_policy":CLASSIFICATION_POLICY_VERSION,"hierarchy_policy":CLASSIFICATION_HIERARCHY_VERSION}}
        payload["classification_id"]="CANONICAL-CLASS-"+self._hash(payload)[:20].upper();return payload
    def _compatibility(self,legacy,canonical):
        item=next(iter(legacy.get("classifications",[]) or []),None);term=item.get("canonical_term") if item else None
        relationship="NOT_COMPARABLE" if not term or not canonical.get("canonical_class") else "MATCH" if self._class_name(term)==canonical.get("canonical_class") else "DIFFERENT"
        return {"legacy_classification":term,"legacy_status":item.get("status") if item else None,"legacy_confidence":item.get("confidence") if item else None,"canonical_vs_legacy":relationship,"legacy_has_authority":False,"projection_only":True}
    def _scope_nodes(self,kb):
        result=[]
        def walk(node,in_scope=False):
            cid=str(node.get("clause_id") or "");title=str(node.get("title") or "");scope_node=in_scope or title.strip().casefold()=="scope";text=str(node.get("raw_text") or title)+" "+" ".join(str(x.get("text") or "") for x in node.get("requirements",[]) or [])
            if scope_node:result.append({"scope_id":str(node.get("effective_clause_id") or "SCOPE-"+cid),"text":text.strip(),"normalized":self._normalize(text)})
            for child in node.get("children",[]) or []:walk(child,scope_node)
        for clause in kb.get("clauses",[]) or []:
            walk(clause)
        return [x for x in result if len(x["normalized"])>5]
    def _definition_index(self,kb):
        result=defaultdict(list)
        for item in kb.get("definitions",[]) or []:
            term=self._normalize(item.get("term"));
            if term:result[term].append(item)
        return result
    def _identity_terms(self,identity):
        result=[]
        for field,item in sorted((identity.get("product") or {}).items()):
            value=item.get("value");normalized=self._normalize(value)
            if normalized and item.get("status") in {"CONFIRMED","INFERRED"}:result.append({"field":field,"value":value,"normalized":normalized,"source_ids":copy.deepcopy(item.get("source_ids") or []),"authority":item.get("authority")})
        return result
    def _fact_terms(self,facts):
        result=[]
        for item in facts.get("facts",[]) or []:
            if item.get("fact_name") not in {"product_type","product_name","reported_product_type"}:continue
            value=item.get("canonical_value");normalized=self._normalize(value)
            if normalized and item.get("status") in {"CONFIRMED","INFERRED"}:result.append({"field":item.get("fact_name"),"value":value,"normalized":normalized,"source_ids":copy.deepcopy(item.get("source_evidence_ids") or []),"source_fact_ids":[item.get("fact_id")],"authority":item.get("authority")})
        return result
    def _scope_class(self,text):
        normalized=self._normalize(text)
        stop=r"(?: designed| intended| having| that | which | their | whose | not intended| not portable| this document| this standard| the rated|,|\.|;|$)"
        patterns=(rf"(?:applies|applicable|is applicable) to (?:all types of )?(.+?){stop}",rf"deals with (?:the )?safety of (.+?){stop}",rf"referred to as (.+?){stop}")
        for pattern in patterns:
            match=re.search(pattern,normalized)
            if match:
                phrase=match.group(1).strip(" -:")
                if phrase:return phrase[:100]
        return None
    @staticmethod
    def _similarity(a,b):
        if not a or not b:return 0.0
        if a==b:return 1.0
        return round(len(a&b)/len(a|b),4)
    @staticmethod
    def _phrase_present(term,scope):return bool(term and re.search(r"\b"+re.escape(term)+r"s?\b",scope))
    @staticmethod
    def _tokens(value):return {x for x in str(value).split() if len(x)>2 and x not in {"and","the","for","with","electric","electrical","commercial"}}
    @staticmethod
    def _normalize(value):return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9]+"," ",str(value or "").casefold())).strip()
    @classmethod
    def _class_name(cls,value):return re.sub(r"_+","_",re.sub(r"[^A-Z0-9]+","_",str(value or "").upper())).strip("_")
    @staticmethod
    def _legacy_evidence_ids(item):return sorted({str(x.get("evidence_id")) for x in item.get("evidence",[]) or [] if x.get("evidence_id")})
    @staticmethod
    def _diag(code,subject):return {"code":code,"classification_id":subject}
    @staticmethod
    def _hash(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str,separators=(",",":")).encode()).hexdigest()
    @classmethod
    def _plain(cls,value):
        if isinstance(value,Enum):return value.value
        if is_dataclass(value):return cls._plain(asdict(value))
        if isinstance(value,Mapping):return {str(k):cls._plain(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [cls._plain(x) for x in value]
        return copy.deepcopy(value)
    @classmethod
    def save_json(cls,value,path):
        target=Path(path);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(cls._plain(value),sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");return target

__all__=["ClassificationLevel","ClassificationStatus","AuthorityTier","GenericCanonicalProductClassifier","CLASSIFICATION_SCHEMA_VERSION","CLASSIFICATION_POLICY_VERSION","CLASSIFICATION_HIERARCHY_VERSION"]
