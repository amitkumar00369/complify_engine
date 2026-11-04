"""Canonical deterministic metrics authority (Step 48-H)."""
from __future__ import annotations
import hashlib,json
from collections import Counter
from pathlib import Path

SCHEMA_VERSION="CANONICAL_COMPLIANCE_METRICS_V1"
METRICS_POLICY="STEP49E_CLIENT_METRICS_POLICY_V1"
COVERAGE_POLICY="STEP48H_COVERAGE_POLICY_V1"
COMPLIANCE_POLICY="STEP48H_COMPLIANCE_SCORE_POLICY_V1"
CONFIDENCE_POLICY="STEP48H_CONFIDENCE_POLICY_V1"
VALIDITY_POLICY="STEP48H_REPORT_VALIDITY_POLICY_V1"
INTEGRITY_SCHEMA="CANONICAL_COMPLIANCE_METRICS_INTEGRITY_V1"
PRODUCT_SPECIFIC_BRANCHES_ADDED=MODEL_SPECIFIC_BRANCHES_ADDED=REPORT_SPECIFIC_BRANCHES_ADDED=0
STANDARD_SPECIFIC_BRANCHES_ADDED=CLAUSE_SPECIFIC_BRANCHES_ADDED=GOLDEN_SPECIFIC_BRANCHES_ADDED=0
EVALUATED={"COMPLIANT","NON_COMPLIANT","INSUFFICIENT_EVIDENCE"}
DIAGNOSTICS=("COVERAGE_EQUALS_COMPLIANCE_BY_FORMULA","COVERAGE_NUMERATOR_EXCEEDS_DENOMINATOR","COVERAGE_POPULATION_NOT_RECONCILED","INACTIVE_COUNTED_AS_MISSING_COVERAGE","NOT_APPLICABLE_COUNTED_AS_FAILURE","INSUFFICIENT_EVIDENCE_COUNTED_AS_COMPLIANT","NEEDS_REVIEW_COUNTED_AS_COMPLIANT","UNKNOWN_APPLICABILITY_COUNTED_AS_COMPLIANT","ZERO_DENOMINATOR_REPORTED_AS_ZERO_PERCENT_COMPLIANCE","CONFIDENCE_EQUALS_COVERAGE_BY_FORMULA","CONFIDENCE_EQUALS_COMPLIANCE_BY_FORMULA","CONFIDENCE_WITHOUT_COMPONENT_BASIS","BLOCKING_ROOT_NOT_REFLECTED_IN_CONFIDENCE","REPORT_VALIDITY_DERIVED_FROM_COMPLIANCE","STRUCTURE_MISMATCH_REPORTED_VALID_WITHOUT_LIMITATION","RESTRICTED_IDENTITY_NOT_REFLECTED_IN_VALIDITY","INVALID_REPORT_WITHOUT_REASON","METRIC_SOURCE_TRACE_MISSING","LEGACY_METRIC_OVERRIDE","STALE_METRIC_VERSION")

class GenericCanonicalMetricsAuthority:
 def build(self,state,facts,classification,applicability,evidence,technical,roots,na,relevance,structure,identity=None,standard_authority=None,run_id=None,kb_maturity_authority=None):
  rows=state.get("records",[]);sc=Counter(x.get("state") for x in rows);total=len(rows);inactive=sc["INACTIVE"];not_app=sc["NOT_APPLICABLE"];authority_blocked=sc["AUTHORITY_BLOCKED"];den=total-inactive-not_app-authority_blocked;evaluated=sum(sc[x] for x in EVALUATED);unknown=sc["UNKNOWN_APPLICABILITY"];unevaluated=den-evaluated
  root_rows=roots.get("results",[]);block=self._blockers(root_rows,rows);coverage={"total_requirements":total,"active_requirements":total-inactive,"inactive_requirements":inactive,"authority_blocked_requirements":authority_blocked,"applicable_requirements":sum(sc[x] for x in EVALUATED),"not_applicable_requirements":not_app,"unknown_applicability":unknown,"needs_review_applicability":sc["NEEDS_REVIEW"],"evaluation_scope_denominator":den,"evaluated_requirements":evaluated,"unevaluated_requirements":unevaluated,"evaluated_compliant":sc["COMPLIANT"],"evaluated_non_compliant":sc["NON_COMPLIANT"],"evaluated_insufficient_evidence":sc["INSUFFICIENT_EVIDENCE"],"evaluated_needs_review":sc["NEEDS_REVIEW"],"coverage_ratio":self._ratio(evaluated,den),"coverage_percentage":self._pct(evaluated,den),**block,"policy_version":COVERAGE_POLICY}
  cden=sc["COMPLIANT"]+sc["NON_COMPLIANT"];score={"authoritatively_compliant":sc["COMPLIANT"],"authoritatively_non_compliant":sc["NON_COMPLIANT"],"compliance_denominator":cden,"unresolved_insufficient_evidence":sc["INSUFFICIENT_EVIDENCE"],"unresolved_needs_review":sc["NEEDS_REVIEW"],"unresolved_unknown_applicability":unknown,"compliance_score":self._ratio(sc["COMPLIANT"],cden) if cden else None,"compliance_percentage":self._pct(sc["COMPLIANT"],cden) if cden else None,"score_status":"DETERMINABLE" if cden else "NOT_DETERMINABLE","policy_version":COMPLIANCE_POLICY}
  components,penalties=self._confidence(rows,facts,classification,applicability,evidence,technical,roots,structure);weights={"classification_confidence":.10,"product_fact_confidence":.10,"identity_confidence":.15,"applicability_confidence":.15,"evidence_confidence":.20,"technical_confidence":.10,"structure_confidence":.15,"traceability_confidence":.05};overall=round(sum(components[k]["score"]*v for k,v in weights.items()),2);confidence={"components":components,"weights":weights,"penalties":penalties,"overall_evaluation_confidence":overall,"policy_version":CONFIDENCE_POLICY}
  validity=self._validity(structure,evidence,root_rows,components,score)
  client=self._client_metrics(sc,standard_authority,rows,run_id,state.get("store_sha256") or state.get("source_state_sha256"),kb_maturity_authority)
  out={"schema_version":SCHEMA_VERSION,"policy_version":METRICS_POLICY,"metrics_policy_version":METRICS_POLICY,"policy_versions":{"metrics":METRICS_POLICY,"coverage":COVERAGE_POLICY,"compliance_score":COMPLIANCE_POLICY,"confidence":CONFIDENCE_POLICY,"report_validity":VALIDITY_POLICY},"client_metrics":client,"evaluation_coverage":coverage,"compliance_score":score,"evaluation_confidence":confidence,"report_validity":validity,"traceability":{"canonical_requirement_state_schema":state.get("schema_version"),"source_state_sha256":state.get("store_sha256"),"standard_authority_status":(standard_authority or {}).get("standard_authority_status"),"kb_maturity_authorization_status":(kb_maturity_authority or {}).get("authorization_status"),"kb_maturity_authority_sha256":(kb_maturity_authority or {}).get("authority_sha256"),"source_artifact_schemas":[x.get("schema_version") for x in (facts,classification,applicability,evidence,technical,roots,na,relevance,standard_authority,kb_maturity_authority) if x],"dependency_ids":sorted(x.get("requirement_id") for x in rows if x.get("requirement_id"))},"authoritative":client["metrics_status"]!="AUTHORITY_BLOCKED","legacy_metrics_role":"COMPATIBILITY_PROJECTION_ONLY"};out["metrics_sha256"]=self._hash(out);return out
 def _client_metrics(self,sc,standard_authority,rows,run_id=None,state_sha256=None,kb_maturity_authority=None):
  standard_blocked=str((standard_authority or {}).get("standard_authority_status") or "") in {"BLOCKED_STANDARD_MISMATCH","BLOCKED_EDITION_MISMATCH","NEEDS_REVIEW","NOT_DETERMINABLE"};maturity_blocked=bool(kb_maturity_authority) and (kb_maturity_authority or {}).get("authorization_status")!="AUTHORIZED" and not standard_blocked
  compliant=sc["COMPLIANT"];noncompliant=sc["NON_COMPLIANT"];insufficient=sc["INSUFFICIENT_EVIDENCE"];review=sc["NEEDS_REVIEW"];unknown=sc["UNKNOWN_APPLICABILITY"];not_app=sc["NOT_APPLICABLE"];authority_blocked=sc["AUTHORITY_BLOCKED"]
  blocked=bool(authority_blocked or standard_blocked or maturity_blocked);relevant=0 if blocked else compliant+noncompliant+insufficient+review;evaluated=0 if blocked else compliant+noncompliant+insufficient;cden=0 if blocked else compliant+noncompliant
  limitations=[]
  if standard_blocked:limitations.append("STANDARD_AUTHORITY_BLOCKED")
  elif maturity_blocked:limitations.append("KB_MATURITY_AUTHORIZATION_BLOCKED")
  if review and not blocked:limitations.append("REVIEW_BACKLOG_PRESENT")
  if unknown and not blocked:limitations.append("UNRESOLVED_APPLICABILITY_PRESENT")
  if not cden:limitations.append("AUTHORITATIVE_COMPLIANCE_DENOMINATOR_EMPTY")
  coverage_value=self._pct(evaluated,relevant);pass_rate=self._pct(compliant,cden) if cden else None;source={"source_state_store":"decisions/canonical_requirement_state_store.json","source_state_sha256":state_sha256,"run_id":run_id}
  records=[{"metric_policy_id":METRICS_POLICY,"metric_name":"evaluation_coverage_percentage","numerator":evaluated,"denominator":relevant,"value":coverage_value,"formula":"(COMPLIANT + NON_COMPLIANT + terminal INSUFFICIENT_EVIDENCE) / relevant_requirement_count * 100","scope":"RELEVANT_REQUIREMENTS","authority":"CANONICAL_REQUIREMENT_STATE","provenance":source},{"metric_policy_id":METRICS_POLICY,"metric_name":"evaluated_decision_pass_rate","numerator":0 if blocked else compliant,"denominator":cden,"value":pass_rate,"formula":"COMPLIANT / (COMPLIANT + NON_COMPLIANT) * 100","scope":"AUTHORITATIVE_DECISIONS_ONLY","authority":"CANONICAL_REQUIREMENT_STATE","provenance":source}]
  return {"metrics_policy_version":METRICS_POLICY,"metric_policy_id":METRICS_POLICY,"relevant_requirement_count":relevant,"compliant_count":0 if blocked else compliant,"non_compliant_count":0 if blocked else noncompliant,"terminal_insufficient_evidence_count":0 if blocked else insufficient,"needs_review_count":0 if blocked else review,"unresolved_applicability_count":0 if blocked else unknown,"authority_blocked_count":authority_blocked,"not_applicable_count":0 if blocked else not_app,"evaluated_requirement_count":evaluated,"evaluation_coverage_numerator":evaluated,"evaluation_coverage_denominator":relevant,"evaluation_coverage_percentage":coverage_value,"evaluated_decision_count":cden,"evaluated_decision_pass_rate":pass_rate,"metric_records":records,"review_backlog_count":0 if blocked else review,"review_backlog_percentage":self._pct(review,relevant),"metrics_status":"AUTHORITY_BLOCKED" if blocked else "DETERMINABLE" if relevant else "NOT_DETERMINABLE","metrics_limitations":limitations,"source_state_store":source,"source_authority":{"canonical_requirement_state":True,"canonical_applicability":True,"canonical_standard_authority":True,"canonical_kb_maturity_authority":bool(kb_maturity_authority),"legacy_metrics_consumed":False}}
 def build_authority_blocked(self,state,standard_authority,run_id=None,kb_maturity_authority=None):
  rows=list((state or {}).get("records") or []);sc=Counter(x.get("state") for x in rows);blocked=sc["AUTHORITY_BLOCKED"];state_hash=(state or {}).get("store_sha256") or (state or {}).get("source_state_sha256");client=self._client_metrics(sc,standard_authority,rows,run_id,state_hash,kb_maturity_authority)
  standard_blocked=standard_authority.get("standard_authority_status") not in {"AUTHORITATIVE_MATCH","AUTHORITATIVE_VIA_VALIDATED_MAPPING","AUTHORITATIVE_VIA_GOVERNED_OVERRIDE"}
  coverage={"total_requirements":len(rows),"active_requirements":len(rows),"inactive_requirements":0,"authority_blocked_requirements":blocked,"applicable_requirements":0,"not_applicable_requirements":0,"unknown_applicability":0,"needs_review_applicability":0,"evaluation_scope_denominator":0,"evaluated_requirements":0,"unevaluated_requirements":0,"evaluated_compliant":0,"evaluated_non_compliant":0,"evaluated_insufficient_evidence":0,"evaluated_needs_review":0,"coverage_ratio":None,"coverage_percentage":None,"blocked_by_standard_authority":blocked if standard_blocked else 0,"blocked_by_kb_maturity_authority":0 if standard_blocked else blocked,"policy_version":COVERAGE_POLICY}
  score={"authoritatively_compliant":0,"authoritatively_non_compliant":0,"compliance_denominator":0,"unresolved_insufficient_evidence":0,"unresolved_needs_review":0,"unresolved_unknown_applicability":0,"authority_blocked":blocked,"compliance_score":None,"compliance_percentage":None,"score_status":"NOT_DETERMINABLE","policy_version":COMPLIANCE_POLICY}
  reason="STANDARD_AUTHORITY_BLOCKED" if standard_blocked else "KB_MATURITY_AUTHORIZATION_BLOCKED";validity_status="INVALID_STANDARD_AUTHORITY" if standard_blocked else "NOT_EVALUATED_KB_MATURITY_AUTHORITY";source="canonical_standard_authority" if standard_blocked else "canonical_kb_maturity_authority"
  out={"schema_version":SCHEMA_VERSION,"policy_version":METRICS_POLICY,"metrics_policy_version":METRICS_POLICY,"policy_versions":{"metrics":METRICS_POLICY,"coverage":COVERAGE_POLICY,"compliance_score":COMPLIANCE_POLICY,"confidence":CONFIDENCE_POLICY,"report_validity":VALIDITY_POLICY},"client_metrics":client,"evaluation_coverage":coverage,"compliance_score":score,"evaluation_confidence":{"authority_status":"BLOCKED_NOT_EVALUATED","policy_version":CONFIDENCE_POLICY},"report_validity":{"status":validity_status,"reason_codes":[reason],"authority_source":source,"policy_version":VALIDITY_POLICY},"authoritative":False,"legacy_metrics_role":"COMPATIBILITY_PROJECTION_ONLY","traceability":{"canonical_requirement_state_schema":(state or {}).get("schema_version"),"source_state_sha256":state_hash,"standard_authority_status":standard_authority.get("standard_authority_status"),"kb_maturity_authorization_status":(kb_maturity_authority or {}).get("authorization_status"),"kb_maturity_authority_sha256":(kb_maturity_authority or {}).get("authority_sha256"),"dependency_ids":sorted(x.get("requirement_id") for x in rows if x.get("requirement_id")),"legacy_metrics_consumed":False}}
  out["metrics_sha256"]=self._hash(out);return out
 def _blockers(self,root_rows,state_rows):
  precedence=[("blocked_by_structure",{"REPORT_STRUCTURE_MISMATCH"}),("blocked_by_identity",{"IDENTITY_RELATIONSHIP_GAP"}),("blocked_by_applicability",{"ENGINE_APPLICABILITY_GAP","ENGINE_CLASSIFICATION_GAP","CLASSIFICATION_AUTHORITY_GAP","STANDARD_SCOPE_MAPPING_GAP","KB_PREDICATE_GAP","SOURCE_PRODUCT_DATA_MISSING"}),("blocked_by_evidence",{"EVIDENCE_GAP","SEMANTIC_NORMALIZATION_GAP"}),("blocked_by_technical_input",set())];counts=Counter();seen=set()
  for key,types in precedence:
   for x in root_rows:
    if x.get("requirement_id") not in seen and (x.get("primary_root_cause") or {}).get("type") in types:seen.add(x.get("requirement_id"));counts[key]+=1
  return {**{x:counts[x] for x,_ in precedence},"blocked_by_review":0,"blocked_by_other":0,"blocker_precedence":[x for x,_ in precedence]}
 def _confidence(self,rows,facts,classification,applicability,evidence,technical,roots,structure):
  n=max(1,len(rows));fact_rows=facts.get("facts",[]);confirmed=sum(x.get("status")=="CONFIRMED" for x in fact_rows);app_rows=applicability.get("results",[]);ev_rows=evidence.get("results",[]);tr=technical.get("results",[]);rr=roots.get("results",[])
  subtype=classification.get("product_subtype",{});standard=classification.get("standard_scope",{});class_score=100 if standard.get("authority_tier")=="HIGH" else 70 if standard.get("authority_tier")=="MEDIUM" else 40
  compatibility=self._enum(self._get(structure,"overall_compatibility"));vals={"classification_confidence":class_score,"product_fact_confidence":100*confirmed/max(1,len(fact_rows)),"identity_confidence":100*sum((x.get("identity_usability") or {}).get("status")=="USABLE" for x in ev_rows)/max(1,len(ev_rows)),"applicability_confidence":100*sum(x.get("status") in {"APPLICABLE","NOT_APPLICABLE"} for x in app_rows)/max(1,len(app_rows)),"evidence_confidence":100*sum((x.get("sufficiency") or {}).get("status")=="SUFFICIENT" for x in ev_rows)/max(1,len(ev_rows)),"technical_confidence":100*sum(x.get("execution_result") in {"SATISFIES","VIOLATES","NOT_REQUIRED"} for x in tr)/max(1,len(tr)),"structure_confidence":0 if compatibility=="STRUCTURE_MISMATCH" else 70 if compatibility=="PARTIALLY_COMPATIBLE" else 100,"traceability_confidence":100*sum(bool(x.get("source_trace",{}).get("requirement_id")) for x in rr)/max(1,len(rr))}
  components={k:{"score":round(v,2),"population":len(rows),"affected_requirement_count":round(n*(100-v)/100),"penalty_reasons":[] if v==100 else [k.upper()+"_LIMITATION"]} for k,v in vals.items()};pen=[]
  for x in rr:
   p=x.get("primary_root_cause") or {};effect=p.get("decision_effect")
   if effect and effect!="NON_BLOCKING":pen.append({"reason_code":p.get("type"),"authority_source":"CANONICAL_ROOT_CAUSE_AUTHORITY_V1","affected_requirements":1,"affected_direct_product_requirements":int((x.get("product_relevance") or {}).get("status")=="DIRECT_PRODUCT"),"affected_general_requirements":int((x.get("product_relevance") or {}).get("status")=="GENERAL_STANDARD"),"decision_effect":effect,"weight":1,"penalty":round(100/n,4),"source_refs":p.get("source_refs") or []})
  return components,pen
 def _validity(self,structure,evidence,roots,components,score):
  compatibility=self._enum(self._get(structure,"overall_compatibility"));restricted=sum((x.get("identity_usability") or {}).get("status") in {"RESTRICTED","NOT_USABLE"} for x in evidence.get("results",[]));blocked=[x for x in roots if (x.get("primary_root_cause") or {}).get("decision_effect") in {"BLOCKS_EVALUATION","REQUIRES_IDENTITY_CONFIRMATION"}];reasons=[];actions=[]
  if compatibility=="STRUCTURE_MISMATCH":status="INVALID";reasons=["GLOBAL_STRUCTURE_MISMATCH"];actions=["REPORT_REPLACEMENT_REQUIRED"]
  elif restricted:status="VALID_WITH_LIMITATIONS";reasons=["IDENTITY_RELATIONSHIP_RESTRICTS_EVIDENCE"];actions=["CONFIRM_MODEL_RELATIONSHIP"]
  elif components["evidence_confidence"]["score"]<100:status="VALID_WITH_LIMITATIONS";reasons=["EVIDENCE_INCOMPLETE"];actions=["PROVIDE_TEST_EVIDENCE"]
  else:status="VALID";actions=[]
  return {"status":status,"reason_codes":reasons,"blocking_roots":sorted({(x.get("primary_root_cause") or {}).get("type") for x in blocked if x.get("primary_root_cause")}),"affected_requirement_count":len(blocked) or restricted,"resolution_actions":actions,"source_trace":{"structure_compatibility":compatibility,"identity_restricted_count":restricted},"derived_from_compliance":False,"policy_version":VALIDITY_POLICY}
 def validate(self,m):
  ds=[];c=m["evaluation_coverage"];s=m["compliance_score"];q=m["evaluation_confidence"];v=m["report_validity"];client=m.get("client_metrics") or {}
  def add(x):ds.append({"code":x})
  if c["evaluated_requirements"]>c["evaluation_scope_denominator"]:add("COVERAGE_NUMERATOR_EXCEEDS_DENOMINATOR")
  if c["evaluated_requirements"]+c["unevaluated_requirements"]!=c["evaluation_scope_denominator"]:add("COVERAGE_POPULATION_NOT_RECONCILED")
  if s["compliance_denominator"]!=s["authoritatively_compliant"]+s["authoritatively_non_compliant"]:add("NOT_APPLICABLE_COUNTED_AS_FAILURE")
  if not s["compliance_denominator"] and s["compliance_percentage"]==0:add("ZERO_DENOMINATOR_REPORTED_AS_ZERO_PERCENT_COMPLIANCE")
  if not q.get("components") and client.get("metrics_status")!="AUTHORITY_BLOCKED":add("CONFIDENCE_WITHOUT_COMPONENT_BASIS")
  if v["status"]!="VALID" and not v["reason_codes"]:add("INVALID_REPORT_WITHOUT_REASON")
  if not m.get("traceability",{}).get("canonical_requirement_state_schema"):add("METRIC_SOURCE_TRACE_MISSING")
  if m.get("schema_version")!=SCHEMA_VERSION:add("STALE_METRIC_VERSION")
  relevant=client.get("relevant_requirement_count",0);evaluated=client.get("evaluated_requirement_count",0);expected=client.get("compliant_count",0)+client.get("non_compliant_count",0)+client.get("terminal_insufficient_evidence_count",0)
  if evaluated!=expected:add("COVERAGE_POPULATION_NOT_RECONCILED")
  if evaluated>relevant:add("COVERAGE_NUMERATOR_EXCEEDS_DENOMINATOR")
  if client.get("evaluated_decision_count",0)!=client.get("compliant_count",0)+client.get("non_compliant_count",0):add("NOT_APPLICABLE_COUNTED_AS_FAILURE")
  z=Counter(x["code"] for x in ds);return {"schema_version":INTEGRITY_SCHEMA,"policy_version":METRICS_POLICY,"valid":not ds,"total_errors":len(ds),"diagnostic_counts":{x:z[x] for x in DIAGNOSTICS},"diagnostics":ds}
 @staticmethod
 def _ratio(a,b):return round(a/b,6) if b else None
 @staticmethod
 def _pct(a,b):return round(100*a/b,2) if b else None
 @staticmethod
 def _enum(v):return None if v is None else str(getattr(v,"value",v))
 @staticmethod
 def _get(v,n,d=None):return v.get(n,d) if isinstance(v,dict) else getattr(v,n,d) if v is not None else d
 @staticmethod
 def _hash(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
 @staticmethod
 def save_json(v,p):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,sort_keys=True,indent=2)+"\n");return p
