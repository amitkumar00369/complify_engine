"""Step 48-B canonical product-fact and identity foundation."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Mapping


class CanonicalFactState(str, Enum):
    CONFIRMED="CONFIRMED";INFERRED="INFERRED";MULTI_STATE="MULTI_STATE";CONFLICTING="CONFLICTING";UNKNOWN="UNKNOWN";INVALID="INVALID"
class ModelIdentityRole(str, Enum):
    DECLARED_MODEL="DECLARED_MODEL";TESTED_MODEL="TESTED_MODEL";REPRESENTATIVE_MODEL="REPRESENTATIVE_MODEL";MODEL_FAMILY="MODEL_FAMILY";TYPE_REFERENCE="TYPE_REFERENCE";VARIANT="VARIANT";SERIES="SERIES"
class IdentityRelationshipState(str, Enum):
    MATCH="MATCH";MISMATCH="MISMATCH";RELATED="RELATED";REPRESENTATIVE_OF="REPRESENTATIVE_OF";VARIANT_OF="VARIANT_OF";FAMILY_MEMBER="FAMILY_MEMBER";UNKNOWN="UNKNOWN";CONFLICTING="CONFLICTING"


FACT_SCHEMA_VERSION="CANONICAL_PRODUCT_FACT_LEDGER_V1"
FACT_POLICY_VERSION="STEP48B_PRODUCT_FACT_POLICY_V1"
IDENTITY_SCHEMA_VERSION="CANONICAL_IDENTITY_STORE_V1"
IDENTITY_POLICY_VERSION="STEP48B_IDENTITY_POLICY_V1"
RELATIONSHIP_SCHEMA_VERSION="CANONICAL_IDENTITY_RELATIONSHIPS_V1"
PRODUCT_SPECIFIC_BRANCHES_ADDED=0
MODEL_SPECIFIC_BRANCHES_ADDED=0
REPORT_SPECIFIC_BRANCHES_ADDED=0
CLAUSE_SPECIFIC_BRANCHES_ADDED=0
STANDARD_SPECIFIC_BRANCHES_ADDED=0


class GenericCanonicalProductFoundation:
    """Canonicalize existing governed observations without changing consumers."""

    VERDICT_TOKENS={"PASS","FAIL","N/A","NA","COMPLIANT","NOT APPLICABLE","VERDICT","RESULT"}

    def build_fact_ledger(self, product_profile: Any, parameter_ledger: Any=None) -> Dict[str,Any]:
        profile=self._plain(product_profile or {});source=profile.get("source") or {};grouped=defaultdict(list)
        for name,fact in sorted((profile.get("facts") or {}).items()):
            observations=fact.get("observations") or []
            status=self._fact_status(fact)
            value=fact.get("normalized_value") if fact.get("normalized_value") is not None else fact.get("value")
            value,profile_unit=self._measurement(value,fact.get("unit"));unit=profile_unit
            observed_values=[]
            for observation in observations:
                observed=observation.get("normalized_value") if observation.get("normalized_value") is not None else observation.get("value")
                if observed is not None and observed not in observed_values:observed_values.append(observed)
            if value is None and len(observed_values)>1:
                value={"representation":"MULTI_STATE","state_semantics":"SOURCE_OBSERVATIONS","unit":fact.get("unit"),"values":observed_values};status="MULTI_STATE"
            elif value is None and len(observed_values)==1:value=observed_values[0]
            role="DECLARED" if name.startswith("rated_") else "OBSERVED"
            evidence=fact.get("evidence") or []
            key=self._fact_key(name,role,unit,None,None,None,None,value)
            grouped[key].append(self._fact_record(name,value,unit,role,status,fact.get("confidence"),observations,evidence,source,{"basis":fact.get("normalization_basis"),"value_type":fact.get("value_type")},fact.get("conflicts") or []))
        ledger=self._plain(parameter_ledger or {})
        rows=ledger.get("parameter_ledger",[]) if isinstance(ledger,dict) else ledger
        for group in rows or []:
            for obs in group.get("observations",[]) or []:
                name=str(obs.get("canonical_parameter") or obs.get("raw_parameter_text") or "unknown_parameter")
                role=str(obs.get("semantic_role") or "OBSERVED")
                unit=obs.get("normalized_unit") or obs.get("unit");value=obs.get("normalized_value")
                # Preserve an explicit source unit when an upstream normalization
                # changed only the unit label and did not convert the value.
                if obs.get("unit") and obs.get("normalized_unit")!=obs.get("unit") and obs.get("normalized_value")==obs.get("raw_value"):unit=obs.get("unit")
                condition=obs.get("conditioning_state");component=obs.get("component_scope");models=obs.get("model_scope") or [];family=obs.get("test_family")
                key=self._fact_key(name,role,unit,condition,component,models,family,value)
                evidence=[{"evidence_id":obs.get("evidence_id"),"page":obs.get("source_page"),"raw_text":obs.get("raw_value"),"source_document_id":source.get("document_id"),"source_authority":obs.get("source_type"),"source_location":obs.get("source_location")}]
                grouped[key].append(self._fact_record(name,value,unit,role,"CONFIRMED" if value is not None else "UNKNOWN",obs.get("confidence"),[obs],evidence,source,{"raw_value":obs.get("raw_value"),"raw_unit":obs.get("unit"),"canonical_unit":unit,"normalization_confidence":obs.get("normalization_confidence")},[],technical_family=family,operating_condition=condition,component=component,model_scope=models,test_stage=obs.get("test_phase")))
        facts=[]
        for key,items in sorted(grouped.items(),key=lambda x:x[0]):
            base=items[0];all_obs={self._observation_id(o):o for item in items for o in item["source_observations"]};all_evidence={str(e.get("evidence_id") or self._hash(e)):e for item in items for e in item["source_evidence"]}
            base["source_observations"]=list(all_obs.values());base["source_observation_ids"]=sorted(all_obs);base["source_evidence"]=list(all_evidence.values());base["source_evidence_ids"]=sorted(all_evidence);base["deduplicated_observation_count"]=sum(len(x["source_observations"]) for x in items)-len(all_obs)
            base["fact_id"]="CANONICAL-FACT-"+self._hash({k:base.get(k) for k in ("fact_name","canonical_value","canonical_unit","semantic_role","technical_family","operating_condition","component","model_scope","test_stage")})[:20].upper();facts.append(base)
        result={"schema_version":FACT_SCHEMA_VERSION,"policy_version":FACT_POLICY_VERSION,"source_profile_id":profile.get("profile_id"),"source_document":source.get("document_id"),"source_report_number":source.get("report_number"),"allowed_states":[x.value for x in CanonicalFactState],"facts":facts}
        result["summary"]={"fact_count":len(facts),"state_counts":dict(sorted(Counter(x["status"] for x in facts).items())),"source_observation_count":sum(len(x["source_observation_ids"]) for x in facts)};result["ledger_sha256"]=self._hash(result);return result

    def build_identity_store(self, product_profile: Any, run_id: str=None) -> Dict[str,Any]:
        profile=self._plain(product_profile or {});identity=profile.get("identity") or {};source=profile.get("source") or {};models=[]
        for item in identity.get("product_identities",[]) or []:
            role=str(item.get("role") or "")
            if role not in {x.value for x in ModelIdentityRole}:continue
            value=item.get("normalized_value") if item.get("normalized_value") is not None else item.get("value")
            if self._identity_safe(value):models.append(self._identity_record(value,role,item))
        existing={(x["value"],x["role"]) for x in models}
        fallback=(("DECLARED_MODEL",identity.get("model_numbers") or []),("MODEL_FAMILY",[identity.get("model_family")] if identity.get("model_family") else []),("TYPE_REFERENCE",identity.get("type_references") or []))
        for role,values in fallback:
            for value in values:
                if self._identity_safe(value) and (value,role) not in existing:models.append(self._identity_record(value,role,{"status":"INFERRED","confidence":0.5,"source_evidence_ids":[]}))
        models.sort(key=lambda x:(x["role"],str(x["value"]),x["identity_id"]))
        def field(value,role):
            prov=(identity.get("selection_provenance") or {}).get(role) or (source.get("selection_provenance") or {}).get(role) or {}
            return {"value":value,"status":"CONFIRMED" if value is not None else "UNKNOWN","confidence":prov.get("confidence"),"authority":prov.get("source_authority") or "PRODUCT_PROFILE","source_document":source.get("document_id"),"page":prov.get("source_page"),"source_text":prov.get("source_text"),"source_ids":[prov.get("candidate_id")] if prov.get("candidate_id") else []}
        report_number=source.get("report_number");report_identifier=report_number or source.get("document_id")
        report={"report_identifier":report_identifier,"report_number":report_number,"document_version":source.get("document_version"),"report_date":source.get("report_date"),"source_file":source.get("file_name"),"laboratory":source.get("laboratory"),"run_id":run_id,"internal_identifier":source.get("internal_identifier"),"authority":"AUTHORITATIVE_REPORT_NUMBER" if report_number else "SOURCE_DOCUMENT_ID","selection_provenance":copy.deepcopy(source.get("selection_provenance") or {})}
        product={"product_name":field(identity.get("product_name"),"PRODUCT_NAME"),"product_type":field(identity.get("product_type"),"PRODUCT_TYPE"),"brand":field(identity.get("brand"),"BRAND"),"manufacturer":field(identity.get("manufacturer"),"MANUFACTURER")}
        result={"schema_version":IDENTITY_SCHEMA_VERSION,"policy_version":IDENTITY_POLICY_VERSION,"source_profile_id":profile.get("profile_id"),"product":product,"models":models,"report":report};result["identity_store_sha256"]=self._hash(result);return result

    def build_relationships(self, identity_store: Any, product_profile: Any=None) -> Dict[str,Any]:
        store=self._plain(identity_store or {});profile=self._plain(product_profile or {});relationships=[]
        model_by_value=defaultdict(list)
        for item in store.get("models",[]) or []:model_by_value[str(item.get("value"))].append(item)
        for value,items in sorted(model_by_value.items()):
            roles={x["role"] for x in items}
            if "DECLARED_MODEL" in roles and "TESTED_MODEL" in roles:
                left=next(x for x in items if x["role"]=="DECLARED_MODEL");right=next(x for x in items if x["role"]=="TESTED_MODEL");relationships.append(self._relationship(left,right,"MATCH","EXACT_NORMALIZED_VALUE",1.0))
        declared=[x for x in store.get("models",[]) if x["role"]=="DECLARED_MODEL"];tested=[x for x in store.get("models",[]) if x["role"]=="TESTED_MODEL"]
        for left in declared:
            for right in tested:
                if left["value"]!=right["value"]:relationships.append(self._relationship(left,right,"UNKNOWN","DISTINCT_VALUES_WITHOUT_RELATIONSHIP_AUTHORITY",0.0))
        for raw in ((profile.get("identity") or {}).get("relationships") or []):
            state=str(raw.get("relationship") or raw.get("relationship_type") or "UNKNOWN")
            if state=="DECLARED_EQUIVALENCE":state="RELATED"
            elif state not in {x.value for x in IdentityRelationshipState}:state="UNKNOWN"
            subject_ids=sorted({item["identity_id"] for value in raw.get("subject_values",[]) or [] for item in model_by_value.get(str(value),[])})
            relationships.append({"relationship_id":raw.get("relationship_id") or "IDENTITY-REL-"+self._hash(raw)[:20].upper(),"left_identity_id":raw.get("left_identity_id") or raw.get("source_identity_id"),"right_identity_id":raw.get("right_identity_id") or raw.get("target_identity_id"),"identity_ids":subject_ids,"relationship":state,"status":raw.get("status") or "INFERRED","confidence":raw.get("confidence"),"basis":raw.get("basis") or raw.get("relationship_type"),"source_ids":copy.deepcopy(raw.get("source_ids") or raw.get("source_evidence_ids") or []),"source_page":raw.get("source_page"),"source_text":raw.get("raw_text")})
        unique={x["relationship_id"]:x for x in relationships};result={"schema_version":RELATIONSHIP_SCHEMA_VERSION,"policy_version":IDENTITY_POLICY_VERSION,"relationships":[unique[k] for k in sorted(unique)]};result["relationships_sha256"]=self._hash(result);return result

    def validate(self, fact_ledger: Any, identity_store: Any, relationships: Any, downstream_fact_version: str=None) -> Dict[str,Any]:
        facts=self._plain(fact_ledger or {});identity=self._plain(identity_store or {});rels=self._plain(relationships or {});diagnostics=[]
        allowed={x.value for x in CanonicalFactState};seen={}
        for fact in facts.get("facts",[]) or []:
            fid=fact.get("fact_id");status=str(fact.get("status"));value=fact.get("canonical_value")
            if status not in allowed:diagnostics.append(self._diag("INVALID_FACT_STATE",fid))
            if status=="CONFIRMED" and value is None:diagnostics.append(self._diag("CONFIRMED_NULL_VALUE",fid))
            key=self._fact_key(fact.get("fact_name"),fact.get("semantic_role"),fact.get("canonical_unit"),fact.get("operating_condition"),fact.get("component"),fact.get("model_scope"),fact.get("technical_family"),value)
            if key in seen:diagnostics.append(self._diag("DUPLICATE_CANONICAL_FACT",fid,{"duplicate_of":seen[key]}))
            seen[key]=fid
            if status=="CONFIRMED" and fact.get("conflicts"):diagnostics.append(self._diag("SILENT_FACT_CONFLICT",fid))
            if isinstance(value,(int,float)) and fact.get("canonical_unit") is not None and not str(fact.get("canonical_unit")).strip():diagnostics.append(self._diag("INVALID_UNIT",fid))
            if status=="CONFIRMED" and not fact.get("source_observation_ids") and not fact.get("source_evidence_ids"):diagnostics.append(self._diag("SOURCE_TRACE_MISSING",fid))
            if status=="CONFIRMED" and str(fact.get("authority")) in {"LOW_AUTHORITY_INFERENCE","UNSUPPORTED"}:diagnostics.append(self._diag("UNSUPPORTED_CONFIRMED_INFERENCE",fid))
        if downstream_fact_version and downstream_fact_version!=facts.get("policy_version"):diagnostics.append(self._diag("STALE_FACT_VERSION",None))
        model_roles=defaultdict(set)
        for item in identity.get("models",[]) or []:
            model_roles[str(item.get("identity_id"))].add(str(item.get("role")))
            if str(item.get("status"))=="CONFIRMED" and not item.get("source_ids"):diagnostics.append(self._diag("IDENTITY_SOURCE_TRACE_MISSING",item.get("identity_id")))
        for iid,roles in model_roles.items():
            if len(roles)>1:diagnostics.append(self._diag("IDENTITY_ROLE_COLLISION",iid,sorted(roles)))
        report=identity.get("report") or {}
        if report.get("report_number") and report.get("report_identifier")!=report.get("report_number"):diagnostics.append(self._diag("INVALID_REPORT_IDENTIFIER",None))
        allowed_rel={x.value for x in IdentityRelationshipState}
        for rel in rels.get("relationships",[]) or []:
            has_subjects=bool(rel.get("left_identity_id") and rel.get("right_identity_id")) or bool(rel.get("identity_ids"))
            if rel.get("relationship") not in allowed_rel or not has_subjects:diagnostics.append(self._diag("INVALID_RELATIONSHIP",rel.get("relationship_id")))
        counts=Counter(x["code"] for x in diagnostics)
        return {"schema_version":"CANONICAL_PRODUCT_FOUNDATION_INTEGRITY_V1","fact_schema_version":facts.get("schema_version"),"fact_policy_version":facts.get("policy_version"),"identity_schema_version":identity.get("schema_version"),"identity_policy_version":identity.get("policy_version"),"valid":not diagnostics,"diagnostic_count":len(diagnostics),"diagnostic_counts":dict(sorted(counts.items())),"diagnostics":diagnostics}

    def _fact_record(self,name,value,unit,role,status,confidence,observations,evidence,source,normalization,conflicts,**context):
        return {"fact_id":None,"fact_name":name,"raw_value":normalization.get("raw_value",value),"raw_unit":normalization.get("raw_unit",unit),"canonical_value":copy.deepcopy(value),"canonical_unit":unit,"semantic_role":role,"status":status,"confidence":confidence,"authority":"EXISTING_DETERMINISTIC_SOURCE_AUTHORITY","source_observations":copy.deepcopy(observations),"source_observation_ids":[],"source_evidence":copy.deepcopy(evidence),"source_evidence_ids":[],"source_document":source.get("document_id"),"source_report_number":source.get("report_number"),"normalization":copy.deepcopy(normalization),"conflicts":copy.deepcopy(conflicts),"canonical_fact_version":FACT_POLICY_VERSION,"traceability":{"source_profile_id":source.get("profile_id"),"policy":"PRESERVE_EXISTING_AUTHORITY"},**context}
    def _identity_record(self,value,role,item):
        sources=item.get("source_evidence_ids") or [x.get("evidence_id") for x in item.get("evidence",[]) or [] if x.get("evidence_id")]
        return {"identity_id":"CANONICAL-IDENTITY-"+self._hash({"value":value,"role":role})[:20].upper(),"value":value,"role":role,"status":str(item.get("status") or "INFERRED"),"confidence":item.get("confidence"),"authority":item.get("source_authority") or item.get("source_context") or "PRODUCT_PROFILE","source_ids":sorted(set(sources)),"source_document":next((x.get("source_document_id") for x in item.get("evidence",[]) or [] if x.get("source_document_id")),None),"page":next((x.get("page") for x in item.get("evidence",[]) or [] if x.get("page") is not None),None),"source_text":next((x.get("raw_text") for x in item.get("evidence",[]) or [] if x.get("raw_text")),None)}
    def _relationship(self,left,right,state,basis,confidence):return {"relationship_id":"IDENTITY-REL-"+self._hash({"left":left["identity_id"],"right":right["identity_id"],"state":state})[:20].upper(),"left_identity_id":left["identity_id"],"right_identity_id":right["identity_id"],"relationship":state,"status":"CONFIRMED" if state=="MATCH" else "UNKNOWN","confidence":confidence,"basis":basis,"source_ids":sorted(set(left.get("source_ids",[])+right.get("source_ids",[])))}
    @staticmethod
    def _fact_status(fact):
        raw=str(fact.get("status") or "UNKNOWN")
        if raw in {"CONFLICT","CONFLICTING"}:return "CONFLICTING"
        if raw in {"INFERRED","INFERRED_STRONG"}:return "INFERRED"
        value=fact.get("normalized_value") if fact.get("normalized_value") is not None else fact.get("value")
        if isinstance(value,dict) and str(value.get("representation"))=="MULTI_STATE":return "MULTI_STATE"
        return raw if raw in {x.value for x in CanonicalFactState} else "INVALID"
    @staticmethod
    def _fact_key(name,role,unit,condition,component,models,family,value):return json.dumps([name,role,unit,condition,component,models or [],family,value],sort_keys=True,default=str,separators=(",",":"))
    @staticmethod
    def _measurement(value,unit):
        if isinstance(value,dict) and set(value).issuperset({"value","unit"}) and len(value)<=3:return value.get("value"),value.get("unit") or unit
        return value,unit
    @classmethod
    def _identity_safe(cls,value):return value is not None and str(value).strip().upper() not in cls.VERDICT_TOKENS
    @classmethod
    def _observation_id(cls,obs):return str(obs.get("fact_id") or obs.get("observation_id") or cls._hash(obs))
    @staticmethod
    def _diag(code,subject,details=None):return {"code":code,"subject_id":subject,"details":details}
    @staticmethod
    def _hash(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str,separators=(",",":")).encode()).hexdigest()
    @classmethod
    def _plain(cls,value):
        if isinstance(value,Enum):return value.value
        if is_dataclass(value):return cls._plain(asdict(value))
        if isinstance(value,Mapping):return {str(k):cls._plain(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [cls._plain(v) for v in value]
        return copy.deepcopy(value)
    @classmethod
    def save_json(cls,value,path):
        target=Path(path);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(cls._plain(value),sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");return target


__all__=["CanonicalFactState","ModelIdentityRole","IdentityRelationshipState","GenericCanonicalProductFoundation","FACT_SCHEMA_VERSION","FACT_POLICY_VERSION","IDENTITY_SCHEMA_VERSION","IDENTITY_POLICY_VERSION"]
