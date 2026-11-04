"""Step 49-D canonical client-facing detailed projection."""
from __future__ import annotations
import copy, hashlib, json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION="CANONICAL_CLIENT_DETAILED_PROJECTION_V2"
POLICY_VERSION="STEP50C_CANONICAL_CLIENT_PROJECTION_V1"
REQUIRED_SECTIONS=("run_context","canonical_runtime_status","canonical_identity_authority","standard_context","standard_authority","kb_maturity_authority","report_identity","report_structure_compatibility","product_identity","product_classification","canonical_product_facts","identity_relationships","requirement_population","applicability_results","product_relevance","evidence_inventory","evidence_matches","evidence_sufficiency_results","technical_rule_executions","requirement_decisions","canonical_requirement_state","na_validation","root_causes","metrics","confidence","report_validity","final_disposition","traceability")
PRODUCT_SPECIFIC_BRANCHES=REPORT_SPECIFIC_BRANCHES=STANDARD_SPECIFIC_ENGINE_BRANCHES=CLAUSE_SPECIFIC_ENGINE_BRANCHES=GOLDEN_EXPECTATION_BRANCHES=0

class GenericCanonicalClientProjection:
 def build(self,*,manifest,effective_kb,standard_authority,kb_maturity_authority=None,runtime_status=None,report_evidence,structure,identity_store,identity_relationships,classification,fact_ledger,applicability,evidence_matches,evidence_sufficiency,technical,final_decision,requirement_state,na,roots,relevance,metrics,report_status,identity_authority=None):
  values={k:self._plain(v or {}) for k,v in locals().items() if k not in {"self"}}
  run_id=str(values["manifest"].get("run_id") or "")
  page_index=self._evidence_pages(values["report_evidence"])
  canonical_report=(values["identity_store"].get("report") or {}).get("report_identifier") or values["report_evidence"].get("report_number") or values["report_evidence"].get("document_id")
  executions=[];by_req=defaultdict(list);evidence_ids=set()
  app_index={str(x.get("requirement_id") or x.get("effective_requirement_id")):x for x in values["applicability"].get("results",[]) or []}
  match_index={str(x.get("effective_requirement_id") or x.get("requirement_id")):x for x in values["evidence_matches"].get("matches",[]) or []}
  suff_index={str(x.get("requirement_id") or x.get("effective_requirement_id")):x for x in values["evidence_sufficiency"].get("results",[]) or []}
  requirement_index={str(x.get("effective_requirement_id") or x.get("requirement_id")):x for x in self._requirements(values["effective_kb"])}
  for source in values["technical"].get("results",[]) or []:
   row=copy.deepcopy(source);eid=str(row.get("execution_id") or row.get("technical_evaluation_id") or "")
   row["execution_id"]=eid;row.setdefault("rule_id",row.get("technical_rule_id"));row.setdefault("result",row.get("execution_result"))
   row.setdefault("evidence_id",next(iter((row.get("source_trace") or {}).get("evidence_ids") or []),None));row.setdefault("source_document",canonical_report);row.setdefault("source_page",page_index.get(row.get("evidence_id")))
   row.setdefault("measured_value",next((x.get("value") for x in row.get("input_values",[]) if x.get("semantic_role")=="MEASURED"),None));row.setdefault("limit_value",next((x.get("value") for x in row.get("limits",[]) if x.get("semantic_role")=="LIMIT"),None));row.setdefault("unit",(row.get("normalized_inputs") or {}).get("unit"))
   executions.append(row);by_req[str(row.get("requirement_id"))].append(eid);evidence_ids.update((row.get("source_trace") or {}).get("evidence_ids") or [])
  decisions=[]
  for source in values["final_decision"].get("results",[]) or []:
   row=copy.deepcopy(source);rid=str(row.get("effective_requirement_id"));app_row=app_index.get(rid,{});suff_row=suff_index.get(rid,{});standard_req=copy.deepcopy(requirement_index.get(rid) or {});row["technical_execution_ids"]=sorted(set(by_req[rid]));row["canonical_references"]={"applicability_evaluation_id":app_row.get("evaluation_id"),"applicability_evaluation_basis":"CANONICAL_APPLICABILITY" if app_row else "INACTIVE_REQUIREMENT_NOT_EVALUATED","evidence_match_id":match_index.get(rid,{}).get("match_id"),"evidence_sufficiency_evaluation_id":suff_row.get("evaluation_id"),"evidence_evaluation_basis":"CANONICAL_EVIDENCE_SUFFICIENCY" if suff_row else "NOT_EVALUATED_DUE_TO_NON_APPLICABLE_OR_UNRESOLVED_APPLICABILITY","canonical_requirement_state_key":rid,"standard_requirement":standard_req};decisions.append(row)
  states=[]
  for source in values["requirement_state"].get("records",[]) or []:
   row=copy.deepcopy(source);row["technical_execution_ids"]=sorted(set(by_req[str(row.get("requirement_id"))]));states.append(row)
  root_rows=[]
  for source in values["roots"].get("results",[]) or []:
   row=copy.deepcopy(source);trace=row.setdefault("source_trace",{});trace["technical_execution_ids"]=sorted(set(trace.get("technical_evaluation_ids",[]) or by_req[str(row.get("requirement_id"))]));root_rows.append(row)
  evidence_inventory=copy.deepcopy(values["report_evidence"].get("evidence_items") or values["report_evidence"].get("items") or values["report_evidence"].get("clauses") or [])
  report_identity=copy.deepcopy(values["identity_store"].get("report") or {})
  report_identity["report_identifier"]=report_identity.get("report_identifier") or report_identity.get("report_number") or values["report_evidence"].get("report_number") or values["report_evidence"].get("document_id")
  report_identity["filename"]=report_identity.get("file_name") or report_identity.get("source_file")
  report_identity["display_label"]=report_identity.get("report_title") or report_identity.get("source_file") or report_identity.get("file_name")
  product_identity={"product":copy.deepcopy(values["identity_store"].get("product") or {}),"models":copy.deepcopy(values["identity_store"].get("models") or []),"evidence_usability":copy.deepcopy(values["identity_relationships"].get("evidence_usability") or {})}
  classification_projection=copy.deepcopy(values["classification"])
  classification_projection["standard_scope_class"]=self._classification_level(values["classification"].get("standard_domain"))
  classification_projection["standard_scope_family"]=self._classification_level(values["classification"].get("standard_scope_family") or values["classification"].get("standard_scope"))
  classification_projection["product_subtype"]=self._classification_level(values["classification"].get("product_subtype"))
  classification_projection["candidate_classifications"]=copy.deepcopy(values["classification"].get("candidates") or [])
  classification_projection["downstream_applicability_authority_effect"]="CANONICAL_CLASSIFICATION_CONSUMED_SEPARATELY_BY_SCOPE_LEVEL"
  population=copy.deepcopy(values["requirement_state"].get("summary") or {})
  result={"schema_version":SCHEMA_VERSION,"policy_version":POLICY_VERSION,
   "run_context":{"run_id":run_id,"pipeline_status":values["runtime_status"].get("status")},
   "canonical_runtime_status":values["runtime_status"],"canonical_identity_authority":values["identity_authority"],
   "standard_context":{"effective_kb_id":values["effective_kb"].get("effective_kb_id"),"base_standard":copy.deepcopy(values["effective_kb"].get("base_standard")),"delta_standard":copy.deepcopy(values["effective_kb"].get("delta_standard"))},
   "standard_authority":values["standard_authority"],"kb_maturity_authority":values["kb_maturity_authority"],"report_identity":report_identity,"report_structure_compatibility":values["structure"],"product_identity":product_identity,"product_classification":classification_projection,"canonical_product_facts":values["fact_ledger"],"identity_relationships":values["identity_relationships"],"requirement_population":population,"applicability_results":copy.deepcopy(values["applicability"].get("results") or []),"product_relevance":copy.deepcopy(values["relevance"].get("results") or []),"evidence_inventory":evidence_inventory,"evidence_matches":copy.deepcopy(values["evidence_matches"].get("matches") or []),"evidence_sufficiency_results":copy.deepcopy(values["evidence_sufficiency"].get("results") or []),"technical_rule_executions":executions,"requirement_decisions":decisions,"canonical_requirement_state":states,"na_validation":copy.deepcopy(values["na"].get("results") or []),"root_causes":root_rows,"metrics":copy.deepcopy(values["metrics"].get("client_metrics") or values["metrics"]),"confidence":copy.deepcopy(values["metrics"].get("evaluation_confidence") or {}),"report_validity":copy.deepcopy(values["metrics"].get("report_validity") or {}),"final_disposition":{"value":values["report_status"].get("deterministic_disposition"),"overall_status":values["report_status"].get("overall_status"),"product_compliance_conclusion":values["report_status"].get("product_compliance_conclusion"),"reason_codes":copy.deepcopy(values["report_status"].get("reason_codes") or []),"decision_basis":copy.deepcopy(values["report_status"].get("decision_basis") or []),"authority_source":"overall_report_status"},
   "traceability":{"run_id":run_id,"canonical_requirement_state_sha256":values["requirement_state"].get("store_sha256"),"source_state_sha256":values["requirement_state"].get("store_sha256"),"canonical_runtime_status_sha256":values["runtime_status"].get("runtime_state_sha256"),"canonical_identity_authority_sha256":values["identity_authority"].get("identity_sha256"),"authority_versions":self._versions(values),"technical_execution_ids":sorted(x["execution_id"] for x in executions if x["execution_id"]),"source_document":report_identity.get("report_identifier"),"projection_only":True,"canonical_reinterpretation_performed":False,"legacy_authority_overrides":0}}
  result["final_disposition"]["source_state_sha256"]=values["requirement_state"].get("store_sha256")
  result["projection_sha256"]=self._hash(result);return result
 @staticmethod
 def _classification_level(value):
  value=copy.deepcopy(value or {})
  return {"value":value.get("canonical_class"),"status":value.get("status"),"confidence":value.get("confidence"),"authority":value.get("authority_tier"),"authority_reason":value.get("reason_code"),"basis":value.get("classification_basis"),"source_provenance":{"classification_id":value.get("classification_id"),"source_evidence_ids":value.get("source_evidence_ids") or [],"source_fact_ids":value.get("source_fact_ids") or [],"relationship_path":value.get("relationship_path") or []}}
 def build_blocked(self,*,manifest,effective_kb,standard_authority,kb_maturity_authority=None,runtime_status=None,report_evidence,requirement_state,metrics,report_status,classification=None,roots=None,na=None,relevance=None,identity_authority=None,identity_store=None,identity_relationships=None):
  effective_kb=self._plain(effective_kb or {});standard_authority=self._plain(standard_authority or {});kb_maturity_authority=self._plain(kb_maturity_authority or {});report_evidence=self._plain(report_evidence or {});manifest=self._plain(manifest or {})
  requirement_state=self._plain(requirement_state or {});metrics=self._plain(metrics or {});report_status=self._plain(report_status or {});runtime_status=self._plain(runtime_status or {});roots=self._plain(roots or {});na=self._plain(na or {});relevance=self._plain(relevance or {});identity_authority=self._plain(identity_authority or {});identity_store=self._plain(identity_store or {});identity_relationships=self._plain(identity_relationships or {})
  states=copy.deepcopy(requirement_state.get("records") or [])
  requirements=[{"requirement_id":row.get("requirement_id"),"scope_type":((row.get("requirement_identity") or {}).get("applicability_predicate") or {}).get("scope_type"),"final_applicability":"AUTHORITY_BLOCKED","authority_status":"BLOCKED","predicate_trace":copy.deepcopy((row.get("requirement_identity") or {}).get("applicability_predicate") or {}),"source_trace":{"canonical_state_reference":row.get("requirement_id"),"canonical_state_sha256":requirement_state.get("store_sha256"),"standard_authority_status":row.get("standard_authority_status"),"kb_maturity_authorization_status":row.get("kb_maturity_authorization_status")}} for row in states]
  observed=self._plain(classification or {})
  standard_blocked=standard_authority.get("standard_authority_status") not in {"AUTHORITATIVE_MATCH","AUTHORITATIVE_VIA_VALIDATED_MAPPING","AUTHORITATIVE_VIA_GOVERNED_OVERRIDE"};block_reason="STANDARD_VERSION_AUTHORITY_GAP" if standard_blocked else "KB_MATURITY_AUTHORITY_GAP";block_effect="STANDARD_AUTHORITY_BLOCKED" if standard_blocked else "KB_MATURITY_BLOCKED"
  def blocked_level(level):
   projected=self._classification_level(observed.get(level));projected.update({"observation_status":projected.get("status"),"classification_authority":"BLOCKED","evaluation_usability":"NOT_USABLE","authority":"BLOCKED","authority_reason":block_reason});return projected
  classification={"standard_scope_class":blocked_level("standard_domain"),"standard_scope_family":blocked_level("standard_scope_family"),"product_subtype":blocked_level("product_subtype"),"candidate_classifications":copy.deepcopy(observed.get("candidates") or []),"downstream_applicability_authority_effect":block_effect}
  report_identity=copy.deepcopy(identity_store.get("report") or {});report_identity["filename"]=report_identity.get("source_file") or report_identity.get("file_name");report_identity["display_label"]=report_identity.get("report_title") or report_identity.get("source_file") or report_identity.get("file_name")
  empty={};state_hash=requirement_state.get("store_sha256");result={"schema_version":SCHEMA_VERSION,"policy_version":POLICY_VERSION,"run_context":{"run_id":manifest.get("run_id"),"pipeline_status":runtime_status.get("status")},"canonical_runtime_status":runtime_status,"canonical_identity_authority":identity_authority,"standard_context":{"effective_kb_id":effective_kb.get("effective_kb_id"),"base_standard":copy.deepcopy(effective_kb.get("base_standard")),"delta_standard":copy.deepcopy(effective_kb.get("delta_standard"))},"standard_authority":self._plain(standard_authority),"kb_maturity_authority":self._plain(kb_maturity_authority),"report_identity":report_identity,"report_structure_compatibility":{"authority_status":"BLOCKED"},"product_identity":{"product":copy.deepcopy(identity_store.get("product") or {}),"models":copy.deepcopy(identity_store.get("models") or []),"evidence_usability":copy.deepcopy(identity_relationships.get("evidence_usability") or {})},"product_classification":classification,"canonical_product_facts":empty,"identity_relationships":identity_relationships,"requirement_population":copy.deepcopy(requirement_state.get("summary") or {}),"applicability_results":requirements,"product_relevance":copy.deepcopy(relevance.get("results") or []),"evidence_inventory":copy.deepcopy(report_evidence.get("evidence_items") or report_evidence.get("items") or report_evidence.get("clauses") or []),"evidence_matches":[],"evidence_sufficiency_results":[],"technical_rule_executions":[],"requirement_decisions":[],"canonical_requirement_state":states,"na_validation":copy.deepcopy(na.get("results") or []),"root_causes":copy.deepcopy(roots.get("results") or []),"metrics":copy.deepcopy(metrics.get("client_metrics") or {}),"confidence":copy.deepcopy(metrics.get("evaluation_confidence") or {"authority_status":"BLOCKED_NOT_EVALUATED"}),"report_validity":copy.deepcopy(metrics.get("report_validity") or {"authority_status":"INVALID_STANDARD_AUTHORITY","authority_source":"canonical_standard_authority"}),"final_disposition":{"value":report_status.get("deterministic_disposition"),"overall_status":report_status.get("overall_status"),"product_compliance_conclusion":report_status.get("product_compliance_conclusion"),"reason_codes":copy.deepcopy(report_status.get("reason_codes") or []),"decision_basis":copy.deepcopy(report_status.get("decision_basis") or {}),"authority_source":"canonical_requirement_state"},"traceability":{"run_id":manifest.get("run_id"),"canonical_requirement_state_sha256":state_hash,"source_state_sha256":state_hash,"canonical_runtime_status_sha256":runtime_status.get("runtime_state_sha256"),"canonical_identity_authority_sha256":identity_authority.get("identity_sha256"),"authority_versions":self._versions({"requirement_state":requirement_state,"metrics":metrics,"roots":roots,"na":na,"relevance":relevance,"standard_authority":standard_authority,"kb_maturity_authority":kb_maturity_authority,"runtime_status":runtime_status,"identity_authority":identity_authority}),"technical_execution_ids":[],"projection_only":True,"canonical_reinterpretation_performed":False,"legacy_authority_overrides":0,"standard_authority_status":standard_authority.get("standard_authority_status"),"kb_maturity_authorization_status":kb_maturity_authority.get("authorization_status"),"kb_maturity_authority_sha256":kb_maturity_authority.get("authority_sha256")}}
  result["final_disposition"]["source_state_sha256"]=state_hash
  result["projection_sha256"]=self._hash(result);return result
 def validate(self,data):
  d=self._plain(data);diagnostics=[];execution_ids={x.get("execution_id") for x in d.get("technical_rule_executions",[]) if x.get("execution_id")};refs=set()
  for group in (d.get("requirement_decisions",[]),d.get("canonical_requirement_state",[])):
   for row in group:refs.update(row.get("technical_execution_ids") or [])
  for row in d.get("root_causes",[]):refs.update((row.get("source_trace") or {}).get("technical_execution_ids") or [])
  refs.update((d.get("traceability") or {}).get("technical_execution_ids") or [])
  for name in REQUIRED_SECTIONS:
   if name not in d:diagnostics.append({"code":"MISSING_CLIENT_SECTION","section":name})
  for ref in sorted(refs-execution_ids):diagnostics.append({"code":"DANGLING_EXECUTION_REFERENCE","execution_id":ref})
  for eid in sorted(execution_ids-refs):diagnostics.append({"code":"ORPHAN_TECHNICAL_EXECUTION","execution_id":eid})
  if d.get("traceability",{}).get("run_id")!=d.get("run_context",{}).get("run_id"):diagnostics.append({"code":"RUN_ID_MISMATCH"})
  runtime=d.get("canonical_runtime_status") or {}
  if d.get("run_context",{}).get("pipeline_status")!=runtime.get("status"):diagnostics.append({"code":"RUNTIME_STATUS_PROJECTION_MISMATCH"})
  if d.get("traceability",{}).get("canonical_runtime_status_sha256")!=runtime.get("runtime_state_sha256"):diagnostics.append({"code":"RUNTIME_STATE_HASH_PROJECTION_MISMATCH"})
  identity=d.get("canonical_identity_authority") or {}
  if d.get("traceability",{}).get("canonical_identity_authority_sha256")!=identity.get("identity_sha256"):diagnostics.append({"code":"IDENTITY_AUTHORITY_HASH_PROJECTION_MISMATCH"})
  return {"schema_version":"CANONICAL_CLIENT_PROJECTION_INTEGRITY_V1","valid":not diagnostics,"diagnostic_count":len(diagnostics),"diagnostics":diagnostics}
 @staticmethod
 def _versions(v):return {k:x.get("policy_version") or x.get("state_policy_version") for k,x in v.items() if isinstance(x,dict) and (x.get("policy_version") or x.get("state_policy_version"))}
 @staticmethod
 def _evidence_pages(value):
  result={}
  def walk(v):
   if isinstance(v,dict):
    eid=v.get("evidence_id") or v.get("measurement_id")
    page=v.get("page") if v.get("page") is not None else v.get("page_start")
    if eid and page is not None:result[str(eid)]=page
    for x in v.values():walk(x)
   elif isinstance(v,list):
    for x in v:walk(x)
  walk(value);return result
 @staticmethod
 def _requirements(kb):
  def walk(nodes):
   for node in nodes or []:
    for req in node.get("requirements") or []:yield req
    yield from walk(node.get("children") or [])
  yield from walk(kb.get("clauses") or []);yield from walk(kb.get("annexes") or [])
 @classmethod
 def _plain(cls,v):
  if isinstance(v,Mapping):return {str(k):cls._plain(x) for k,x in v.items()}
  if isinstance(v,(list,tuple)):return [cls._plain(x) for x in v]
  if hasattr(v,"value"):return v.value
  if hasattr(v,"__dict__"):return cls._plain(vars(v))
  return copy.deepcopy(v)
 @classmethod
 def _hash(cls,v):return hashlib.sha256(json.dumps(cls._plain(v),sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
 @classmethod
 def save_json(cls,v,p):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(cls._plain(v),indent=2,sort_keys=True)+"\n");return p

__all__=["GenericCanonicalClientProjection","SCHEMA_VERSION","POLICY_VERSION","REQUIRED_SECTIONS"]
