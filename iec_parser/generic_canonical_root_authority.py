"""Canonical root-cause, N/A, and product-relevance authority (Step 48-G)."""
from __future__ import annotations
import hashlib,json
from collections import Counter
from dataclasses import asdict,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Mapping

ROOT_SCHEMA="CANONICAL_ROOT_CAUSE_AUTHORITY_V1"
NA_SCHEMA="CANONICAL_NA_AUTHORITY_V1"
RELEVANCE_SCHEMA="CANONICAL_PRODUCT_RELEVANCE_V1"
ROOT_POLICY="STEP50E_ROOT_CAUSE_POLICY_V1"
NA_POLICY="STEP50E_NA_LIFECYCLE_POLICY_V1"
RELEVANCE_POLICY="STEP48G_PRODUCT_RELEVANCE_POLICY_V1"
INTEGRITY_SCHEMA="STEP48G_INTEGRITY_V1"
PRODUCT_SPECIFIC_BRANCHES_ADDED=MODEL_SPECIFIC_BRANCHES_ADDED=REPORT_SPECIFIC_BRANCHES_ADDED=0
STANDARD_SPECIFIC_BRANCHES_ADDED=CLAUSE_SPECIFIC_BRANCHES_ADDED=GOLDEN_SPECIFIC_BRANCHES_ADDED=0

ROOTS={
 "SOURCE_PRODUCT_DATA_MISSING":("PRODUCT_INFORMATION","REQUIRES_PRODUCT_INFORMATION","PROVIDE_PRODUCT_INFORMATION"),
 "ENGINE_CLASSIFICATION_GAP":("CLASSIFICATION","BLOCKS_EVALUATION","CONFIRM_PRODUCT_CLASSIFICATION"),
 "CLASSIFICATION_AUTHORITY_GAP":("CLASSIFICATION","BLOCKS_EVALUATION","CONFIRM_CLASSIFICATION_AUTHORITY"),
 "STANDARD_SCOPE_MAPPING_GAP":("STANDARD_SCOPE","BLOCKS_EVALUATION","CONFIRM_STANDARD_SCOPE_MAPPING"),
 "ENGINE_APPLICABILITY_GAP":("APPLICABILITY","REQUIRES_PRODUCT_INFORMATION","RESOLVE_APPLICABILITY"),
 "KB_PREDICATE_GAP":("KNOWLEDGE_BASE","REQUIRES_KB_REVIEW","KB_REVIEW_REQUIRED"),
 "SEMANTIC_NORMALIZATION_GAP":("SOURCE_DOCUMENT","REQUIRES_LAB_CLARIFICATION","CLARIFY_SOURCE_DOCUMENT"),
 "EVIDENCE_GAP":("LAB_EVIDENCE","REQUIRES_EVIDENCE","PROVIDE_TEST_EVIDENCE"),
 "REPORT_STRUCTURE_MISMATCH":("REPORT_STRUCTURE","BLOCKS_EVALUATION","REPORT_REPLACEMENT_REQUIRED"),
 "IDENTITY_RELATIONSHIP_GAP":("IDENTITY_RELATIONSHIP","REQUIRES_IDENTITY_CONFIRMATION","CONFIRM_MODEL_RELATIONSHIP"),
 "STANDARD_VERSION_AUTHORITY_GAP":("STANDARD_AUTHORITY","BLOCKS_EVALUATION","RESOLVE_STANDARD_VERSION_AUTHORITY"),
 "KB_MATURITY_AUTHORITY_GAP":("KB_AUTHORITY","BLOCKS_EVALUATION","AUTHORIZE_KB_FOR_COMPLIANCE_EVALUATION"),
 "TECHNICAL_NON_COMPLIANCE":("TECHNICAL_FAILURE","FORCES_NON_COMPLIANT","CORRECT_PRODUCT_OR_RETEST"),
}
DIAGNOSTICS=("TECHNICAL_FAILURE_NOT_PRIMARY","INVALID_NA_PRIMARY_OVER_TECHNICAL_FAILURE","STRUCTURE_MISMATCH_NOT_PRIMARY","STRUCTURE_MISMATCH_EXPLODED_INTO_DUPLICATE_ROOTS","IDENTITY_GAP_ASSIGNED_TO_PRODUCT_INFORMATION","LAB_EVIDENCE_GAP_ASSIGNED_TO_PRODUCT_INFORMATION","UNKNOWN_APPLICABILITY_MARKED_INVALID_NA","NEEDS_REVIEW_APPLICABILITY_MARKED_INVALID_NA","CONFIRMED_INVALID_NA_WITHOUT_AUTHORITATIVE_ATOMIC_APPLICABILITY","VALID_NA_WITHOUT_JUSTIFICATION","DIRECT_PRODUCT_WITHOUT_CLASSIFICATION_AUTHORITY","FEATURE_REQUIREMENT_WITHOUT_FEATURE_PREDICATE","MISSING_FEATURE_TREATED_AS_FALSE","GENERAL_REQUIREMENT_BLOCKED_BY_MISSING_SUBTYPE","MATERIAL_ROOT_WITH_NULL_DECISION_EFFECT","MATERIAL_ROOT_WITHOUT_RESOLUTION_ACTION","ROOT_SOURCE_TRACE_MISSING","LEGACY_ROOT_OVERRIDE","LEGACY_NA_OVERRIDE","LEGACY_RELEVANCE_OVERRIDE","STALE_ROOT_VERSION")

class GenericCanonicalRootAuthority:
 def build_authority_blocked(self,state,standard_authority,kb_maturity_authority=None):
  state=self._plain(state or {});authority=self._plain(standard_authority or {});maturity=self._plain(kb_maturity_authority or {});status=self._get(authority,"standard_authority_status");authority_reason=self._get(authority,"authority_reason")
  standard_blocked=status not in {"AUTHORITATIVE_MATCH","AUTHORITATIVE_VIA_VALIDATED_MAPPING","AUTHORITATIVE_VIA_GOVERNED_OVERRIDE"};root_type="STANDARD_VERSION_AUTHORITY_GAP" if standard_blocked else "KB_MATURITY_AUTHORITY_GAP";reason_code="STANDARD_AUTHORITY_BLOCKED" if standard_blocked else "KB_MATURITY_BLOCKED"
  rows=[];nas=[];relevance=[]
  for canonical in state.get("records") or []:
   if canonical.get("current") is False:continue
   rid=str(canonical.get("requirement_id") or "")
   if canonical.get("state")!="AUTHORITY_BLOCKED":continue
   app={"evaluation_id":None};e={};root=self._root(root_type,rid,canonical,app,e,[],"PRIMARY")
   root.update({"authority_reason":authority_reason if standard_blocked else maturity.get("authorization_reason"),"standard_authority_status":status,"kb_maturity_authorization_status":maturity.get("authorization_status"),"canonical_state_sha256":state.get("store_sha256")})
   product_relevance={"status":"UNKNOWN_RELEVANCE","reason_codes":[reason_code],"source_state_sha256":state.get("store_sha256")}
   rows.append({"requirement_id":rid,"canonical_state_reference":rid,"canonical_state_sha256":state.get("store_sha256"),"requirement_state":canonical.get("state"),"primary_root_cause":root,"secondary_root_causes":[],"na_assessment":None,"product_relevance":product_relevance,"dependency_ids":[rid],"source_trace":{"requirement_id":rid,"canonical_state_reference":rid,"canonical_state_sha256":state.get("store_sha256"),"standard_authority_reference":status,"standard_authority_reason":authority_reason,"standard_authority_sha256":authority.get("authority_sha256"),"kb_maturity_authority_reference":"standards/canonical_kb_maturity_authority.json","kb_maturity_authority_sha256":maturity.get("authority_sha256"),"kb_maturity_authorization_status":maturity.get("authorization_status"),"state_decision_ids":canonical.get("source_decision_ids") or [],"technical_execution_ids":[]},"policy_version":ROOT_POLICY})
   relevance.append({"requirement_id":rid,**product_relevance,"dependency_ids":[rid],"policy_version":RELEVANCE_POLICY})
  return self._artifact(ROOT_SCHEMA,ROOT_POLICY,"results",rows,state),self._artifact(NA_SCHEMA,NA_POLICY,"results",nas,state),self._artifact(RELEVANCE_SCHEMA,RELEVANCE_POLICY,"results",relevance,state)
 def build(self,state,applicability,evidence,technical,classification,scope_na,structure,effective_kb=None):
  states=self._index(self._get(state,"records",[]));apps=self._index(self._get(applicability,"results",[]));evs=self._index(self._get(evidence,"results",[]));nas=self._index(self._get(scope_na,"member_results",[]));tech={}
  for x in self._get(technical,"results",[]) or []:tech.setdefault(str(self._get(x,"requirement_id")),[]).append(self._plain(x))
  subtype=self._plain(self._get(classification,"product_subtype",{}));standard=self._plain(self._get(classification,"standard_scope",{}));mismatch=self._enum(self._get(structure,"overall_compatibility"))=="STRUCTURE_MISMATCH"
  roots=[];na_rows=[];rel_rows=[]
  for rid,s in sorted(states.items()):
   a=apps.get(rid,{});e=evs.get(rid,{});n=nas.get(rid,{});trs=tech.get(rid,[]);app=self._enum(a.get("status") or a.get("decision")) or "UNKNOWN";claim=bool(n.get("reported_na") or n.get("report_na") or n.get("na_evidence_ids") or n.get("evidence_ids") or self._enum(n.get("group_na_status")) not in {None,"NOT_REPORTED_NA","INACTIVE"})
   na=self.assess_na(app,claim,n,a.get("authority_status"),mismatch,a.get("atomic_applicability_authoritative"),a.get("atomic_predicate_state"),a.get("atomic_predicate_contract"),a.get("evaluation_id"),a.get("source_ids"));rel=self.assess_relevance(a,subtype,standard);primary,secondary=self._causes(s,a,e,trs,na,mismatch)
   root={"requirement_id":rid,"canonical_state_reference":rid,"requirement_state":s.get("state"),"primary_root_cause":self._root(primary,rid,s,a,e,trs,"PRIMARY"),"secondary_root_causes":[self._root(x,rid,s,a,e,trs,"SECONDARY") for x in secondary],"na_assessment":na,"product_relevance":rel,"dependency_ids":sorted(set([rid]+list(a.get("dependency_ids") or [])+list(e.get("dependency_ids") or [])+[v for t in trs for v in t.get("dependency_ids",[])])),"source_trace":{"requirement_id":rid,"canonical_state_reference":rid,"state_decision_ids":s.get("source_decision_ids") or [],"applicability_evaluation_id":a.get("evaluation_id"),"evidence_evaluation_id":e.get("evaluation_id"),"technical_execution_ids":[t.get("execution_id") or t.get("technical_evaluation_id") for t in trs if t.get("execution_id") or t.get("technical_evaluation_id")],"na_validation_reference":n.get("evaluation_id") or n.get("group_id")},"policy_version":ROOT_POLICY}
   roots.append(root);na_rows.append({"requirement_id":rid,**na,"dependency_ids":root["dependency_ids"],"policy_version":NA_POLICY});rel_rows.append({"requirement_id":rid,**rel,"dependency_ids":root["dependency_ids"],"policy_version":RELEVANCE_POLICY})
  return self._artifact(ROOT_SCHEMA,ROOT_POLICY,"results",roots,state),self._artifact(NA_SCHEMA,NA_POLICY,"results",na_rows,state),self._artifact(RELEVANCE_SCHEMA,RELEVANCE_POLICY,"results",rel_rows,state)
 def assess_na(self,app,claim,legacy=None,authority_status=None,structure_mismatch=False,atomic_applicability_authoritative=None,atomic_predicate_state=None,atomic_predicate_contract=None,applicability_evaluation_id=None,applicability_source_ids=None):
  legacy=self._plain(legacy or {});refs=legacy.get("na_evidence_ids") or legacy.get("scope_evidence_ids") or legacy.get("evidence_ids") or []
  contract=self._plain(atomic_predicate_contract or {});true_atomic=bool(atomic_applicability_authoritative) and atomic_predicate_state=="TRUE" and contract.get("predicate_authority")=="AUTHORITATIVE" and bool(contract.get("predicate_id")) and bool(contract.get("fact_id"))
  base={"report_claim":"N/A" if claim else None,"reported_na":bool(claim),"canonical_applicability":app,"applicability_authority":authority_status,"authoritative_atomic_applicability":true_atomic,"atomic_predicate_state":atomic_predicate_state,"atomic_predicate_contract":contract or None,"applicability_evaluation_id":applicability_evaluation_id,"applicability_source_refs":list(applicability_source_ids or []),"justification":None,"source_refs":refs}
  if not claim:return {**base,"status":"NOT_REPORTED_NA","reason_codes":["REPORT_NA_NOT_CLAIMED"]}
  authoritative=authority_status=="AUTHORITATIVE"
  if app=="NOT_APPLICABLE" and authoritative:return {**base,"status":"JUSTIFIED_NA","justification":"Authoritative canonical applicability establishes NOT_APPLICABLE.","reason_codes":["CANONICAL_NOT_APPLICABLE"]}
  if app=="APPLICABLE" and authoritative and true_atomic and refs and not structure_mismatch:return {**base,"status":"CONFIRMED_INVALID_NA","reason_codes":["AUTHORITATIVE_ATOMIC_APPLICABILITY_CONTRADICTS_REPORTED_NA"]}
  if app=="APPLICABLE":return {**base,"status":"POTENTIAL_CONFLICT","reason_codes":["APPLICABILITY_CONFLICT_NOT_AUTHORITATIVE"]}
  return {**base,"status":"UNRESOLVED_NA","reason_codes":["APPLICABILITY_UNRESOLVED_WITH_REPORTED_NA"]}
 def assess_relevance(self,a,subtype,standard):
  app=self._enum(a.get("status") or a.get("decision")) or "UNKNOWN";features=list(a.get("feature_predicates") or a.get("required_features") or []);scope=str(a.get("requirement_scope") or "").upper();required=a.get("required_product_class");sat=str(subtype.get("authority_tier") or "NONE");sta=str(standard.get("authority_tier") or "NONE")
  if app=="NOT_APPLICABLE":status="NOT_PRODUCT_RELEVANT";reason="CANONICAL_NOT_APPLICABLE"
  elif features:status="FEATURE_DEPENDENT" if app=="APPLICABLE" else "UNKNOWN_RELEVANCE";reason="FEATURE_PREDICATE_REQUIRED"
  elif scope in {"CONDITIONAL","CONSTRUCTION","SUPPORTING"} and app!="APPLICABLE":status="CONDITIONAL";reason="CONDITIONAL_SCOPE"
  elif required and sat=="HIGH" and app=="APPLICABLE":status="DIRECT_PRODUCT";reason="AUTHORITATIVE_SUBTYPE_MATCH"
  elif not required and sta=="HIGH":status="GENERAL_STANDARD";reason="AUTHORITATIVE_STANDARD_SCOPE"
  elif app=="APPLICABLE" and sat=="HIGH" and self._get(a,"classification_evidence",{}).get("product_subtype_status")=="MATCH":status="DIRECT_PRODUCT";reason="AUTHORITATIVE_SUBTYPE_APPLICABILITY"
  else:status="UNKNOWN_RELEVANCE";reason="RELEVANCE_AUTHORITY_INCOMPLETE"
  return {"status":status,"standard_scope_class":standard.get("canonical_class"),"classification_level":"PRODUCT_SUBTYPE" if status in {"DIRECT_PRODUCT","FEATURE_DEPENDENT"} else "STANDARD_SCOPE","classification_authority":sat if status in {"DIRECT_PRODUCT","FEATURE_DEPENDENT"} else sta,"applicability":app,"feature_predicates":features,"fact_ids":sorted({str(x.get("fact_id") or x.get("source_fact_id")) for x in a.get("feature_evaluations",[]) if x.get("fact_id") or x.get("source_fact_id")}),"kb_relationship":a.get("requirement_scope"),"reason_codes":[reason]}
 def _causes(self,s,a,e,trs,na,mismatch):
  state=s.get("state");app=self._enum(a.get("status") or a.get("decision"));suff=self._get(e.get("sufficiency",{}),"status");usable=self._get(e.get("identity_usability",{}),"status");tech_fail=any(x.get("execution_result")=="VIOLATES" for x in trs);secondary=[]
  reason=str(a.get("decision_reason") or a.get("reason_code") or "")
  if tech_fail:primary="TECHNICAL_NON_COMPLIANCE"
  elif mismatch and state not in {"COMPLIANT","NOT_APPLICABLE","INACTIVE"}:primary="REPORT_STRUCTURE_MISMATCH"
  elif usable in {"RESTRICTED","NOT_USABLE"}:primary="IDENTITY_RELATIONSHIP_GAP"
  elif app in {"UNKNOWN","NEEDS_REVIEW"}:
   if a.get("missing_features"):primary="SOURCE_PRODUCT_DATA_MISSING"
   elif "STANDARD_SCOPE" in reason:primary="STANDARD_SCOPE_MAPPING_GAP"
   elif "SUBTYPE_LOW_AUTHORITY" in reason or "CLASSIFICATION_AUTHORITY" in reason:primary="CLASSIFICATION_AUTHORITY_GAP"
   elif "SUBTYPE" in reason or "CLASSIFICATION" in reason:primary="ENGINE_CLASSIFICATION_GAP"
   elif "PREDICATE" in reason or "KB_" in reason:primary="KB_PREDICATE_GAP"
   else:primary="ENGINE_APPLICABILITY_GAP"
  elif suff=="NOT_COMPARABLE":primary="SEMANTIC_NORMALIZATION_GAP"
  elif suff in {"INSUFFICIENT","NEEDS_REVIEW"} or state=="NEEDS_REVIEW":primary="EVIDENCE_GAP"
  else:primary=None
  if primary=="REPORT_STRUCTURE_MISMATCH" and suff in {"INSUFFICIENT","NOT_COMPARABLE"}:secondary.append("EVIDENCE_GAP")
  return primary,list(dict.fromkeys(secondary))
 def _root(self,t,rid,s,a,e,trs,role):
  if not t:return None
  owner,effect,action=ROOTS[t];root_trs=[x for x in trs if x.get("execution_result")=="VIOLATES"] if t=="TECHNICAL_NON_COMPLIANCE" else trs;executions=sorted({x.get("execution_id") or x.get("technical_evaluation_id") for x in root_trs if x.get("execution_id") or x.get("technical_evaluation_id")})
  return {"root_id":"CANONICAL-ROOT-"+self._hash(f"{rid}|{t}|{role}")[:20].upper(),"requirement_id":rid,"type":t,"root_type":t,"role":role,"authority_status":"AUTHORITATIVE","owner":owner,"decision_effect":effect,"resolution_action":action,"reason":t,"reason_codes":[t],"source_authority":"CANONICAL_DEPENDENCY_CHAIN","canonical_state_reference":rid,"applicability_reference":a.get("evaluation_id"),"evidence_reference":e.get("evaluation_id"),"technical_execution_ids":executions,"source_refs":sorted(set([rid]+list(s.get("source_decision_ids") or [])+executions))}
 def validate(self,root,na,relevance):
  ds=[];nmap=self._index(na.get("results",[]));rmap=self._index(relevance.get("results",[]))
  for x in root.get("results",[]):
   rid=x["requirement_id"];p=x.get("primary_root_cause");n=nmap.get(rid);r=rmap.get(rid,{})
   def add(c):ds.append({"code":c,"requirement_id":rid})
   if p and not p.get("decision_effect"):add("MATERIAL_ROOT_WITH_NULL_DECISION_EFFECT")
   if p and not p.get("resolution_action"):add("MATERIAL_ROOT_WITHOUT_RESOLUTION_ACTION")
   if p and not p.get("source_refs"):add("ROOT_SOURCE_TRACE_MISSING")
   if n and n["status"]=="CONFIRMED_INVALID_NA" and n["canonical_applicability"]=="UNKNOWN":add("UNKNOWN_APPLICABILITY_MARKED_INVALID_NA")
   if n and n["status"]=="CONFIRMED_INVALID_NA" and n["canonical_applicability"]=="NEEDS_REVIEW":add("NEEDS_REVIEW_APPLICABILITY_MARKED_INVALID_NA")
   if n and n["status"]=="CONFIRMED_INVALID_NA" and not n.get("authoritative_atomic_applicability"):add("CONFIRMED_INVALID_NA_WITHOUT_AUTHORITATIVE_ATOMIC_APPLICABILITY")
   if n and n["status"]=="JUSTIFIED_NA" and not n.get("justification"):add("VALID_NA_WITHOUT_JUSTIFICATION")
   if r["status"]=="DIRECT_PRODUCT" and r.get("classification_authority")!="HIGH":add("DIRECT_PRODUCT_WITHOUT_CLASSIFICATION_AUTHORITY")
   if r["status"]=="FEATURE_DEPENDENT" and not r.get("feature_predicates"):add("FEATURE_REQUIREMENT_WITHOUT_FEATURE_PREDICATE")
   if x.get("requirement_state")=="NON_COMPLIANT" and p and p.get("technical_execution_ids") and p["type"]!="TECHNICAL_NON_COMPLIANCE":add("TECHNICAL_FAILURE_NOT_PRIMARY")
   if x.get("policy_version")!=ROOT_POLICY:add("STALE_ROOT_VERSION")
  c=Counter(x["code"] for x in ds);return {"schema_version":INTEGRITY_SCHEMA,"policy_version":ROOT_POLICY,"valid":not ds,"total_errors":len(ds),"diagnostic_counts":{x:c[x] for x in DIAGNOSTICS},"diagnostics":ds}
 def _artifact(self,schema,policy,key,rows,state=None):
  state=self._plain(state or {});counts=Counter((x.get("primary_root_cause") or {}).get("type") if schema==ROOT_SCHEMA else x.get("status") for x in rows);out={"schema_version":schema,"policy_version":policy,"authoritative":True,"legacy_artifact_role":"COMPATIBILITY_ONLY",key:rows,"summary":{"record_count":len(rows),"status_counts":dict(sorted((str(k),v) for k,v in counts.items()))},"traceability":{"source_state_store":"decisions/canonical_requirement_state_store.json","source_state_sha256":state.get("store_sha256"),"state_schema_version":state.get("schema_version")}};out["artifact_sha256"]=self._hash(out);return out
 @classmethod
 def _index(cls,rows):return {str(cls._get(x,"requirement_id") or cls._get(x,"effective_requirement_id")):cls._plain(x) for x in rows or []}
 @classmethod
 def _plain(cls,v):
  if is_dataclass(v):return cls._plain(asdict(v))
  if isinstance(v,Enum):return v.value
  if isinstance(v,Mapping):return {str(k):cls._plain(x) for k,x in v.items()}
  if isinstance(v,(list,tuple)):return [cls._plain(x) for x in v]
  return v
 @staticmethod
 def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
 @staticmethod
 def _enum(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
 @classmethod
 def _hash(cls,v):return hashlib.sha256(json.dumps(cls._plain(v),sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
 @classmethod
 def save_json(cls,v,p):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(cls._plain(v),sort_keys=True,indent=2)+"\n");return p
