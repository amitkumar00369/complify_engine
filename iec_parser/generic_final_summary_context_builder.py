"""Assemble existing deterministic artifacts into one canonical summary context."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter,defaultdict
from dataclasses import asdict,dataclass,field,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Dict,Iterable,List,Mapping,Optional,Sequence

from .generic_executive_summary_builder import GenericExecutiveSummaryBuilder
from .generic_next_action_prioritizer import GenericNextActionPrioritizer
from .generic_overall_report_status import GenericOverallReportStatusEngine
from .generic_report_issue_aggregator import GenericReportIssueAggregator
from .generic_canonical_requirement_state import GenericCanonicalRequirementStateStore

SCHEMA_VERSION="FINAL_SUMMARY_CONTEXT_V1"


@dataclass
class FinalSummaryContext:
 schema_version:str
 run_context:Dict[str,Any]
 standard_context:Dict[str,Any]
 product_context:Dict[str,Any]
 requirement_population:Dict[str,Any]
 applicable_requirements:List[str]
 not_applicable_requirements:List[str]
 unknown_applicability_requirements:List[str]
 requirement_results:List[Dict[str,Any]]
 gap_summary:Dict[str,Any]
 parameter_findings:List[Dict[str,Any]]
 evidence_findings:List[Dict[str,Any]]
 na_findings:List[Dict[str,Any]]
 structure_findings:List[Dict[str,Any]]
 root_causes:List[Dict[str,Any]]
 priority_findings:List[Dict[str,Any]]
 next_actions:List[Dict[str,Any]]
 metrics:Dict[str,Any]
 kb_authority:Dict[str,Any]
 report_validity:Dict[str,Any]
 final_disposition:Dict[str,Any]
 pre_llm_unresolved:Dict[str,Any]
 traceability:Dict[str,Any]
 diagnostics:List[Dict[str,Any]]=field(default_factory=list)


class GenericFinalSummaryContextBuilder:
 """Copy and normalize final artifacts without recomputing compliance semantics."""
 POLICY_VERSION="STEP43_ASSEMBLY_V1"
 SOURCE_PATHS={
  "effective_kb":"standards/effective_kb.json","standard_validation":"standards/standard_validation.json",
  "product_profile":"report/product_profile.json","applicability":"report/group_aware_applicability_result.json",
  "na":"report/group_aware_na_validation_result.json","evidence":"report/evidence_match_result.json",
  "scope":"report/report_evidence_scope_result.json","structure":"report/report_standard_structure_compatibility.json",
  "technical":"report/technical_constraint_result.json","parameters":"decisions/cross_evidence_consistency_result.json",
  "final":"decisions/final_requirement_decision.json","coverage":"decisions/coverage_gap_analysis.json",
  "canonical_requirement_state":"decisions/canonical_requirement_state_store.json",
  "canonical_metrics":"report/canonical_compliance_metrics.json",
  "issues":"decisions/final_compliance_issues.json","aggregated":"decisions/aggregated_compliance_issues.json",
  "actions":"decisions/prioritized_next_actions.json","executive":"decisions/executive_compliance_summary.json",
  "status":"decisions/overall_report_status.json","response":"decisions/final_compliance_response.json",
  "manifest":"manifest/pipeline_manifest.json"}

 def build_from_run_directory(self,run_directory:Any,*,lineage_audit_clause_ids:Sequence[str]=())->FinalSummaryContext:
  run=Path(run_directory);sources={k:self._read(run/v) for k,v in self.SOURCE_PATHS.items()}
  sources["source_paths"]={k:str(v) for k,v in self.SOURCE_PATHS.items() if (run/v).exists()}
  aggregate=sources["aggregated"]
  if not aggregate.get("professional_judgment"):
   aggregate=GenericReportIssueAggregator().aggregate(sources["issues"],final_decision=sources["final"],canonical_requirement_state=sources["canonical_requirement_state"],coverage_gap_analysis=sources["coverage"],effective_kb=sources["effective_kb"],structure_compatibility=sources["structure"],product_profile=sources["product_profile"],technical_constraint_result=sources["technical"])
   actions=GenericNextActionPrioritizer().prioritize(aggregate);executive=GenericExecutiveSummaryBuilder().build(aggregate,actions);status=GenericOverallReportStatusEngine().resolve(aggregate,actions,executive)
   sources.update({"aggregated":aggregate,"actions":actions,"executive":executive,"status":status})
  return self.build(**sources,lineage_audit_clause_ids=lineage_audit_clause_ids)

 def build(self,*,effective_kb:Any,standard_validation:Any=None,product_profile:Any=None,
           applicability:Any=None,na:Any=None,evidence:Any=None,scope:Any=None,structure:Any=None,
           technical:Any=None,parameters:Any=None,final:Any=None,canonical_requirement_state:Any=None,canonical_metrics:Any=None,coverage:Any=None,issues:Any=None,
           aggregated:Any=None,actions:Any=None,executive:Any=None,status:Any=None,response:Any=None,
           manifest:Any=None,source_paths:Optional[Mapping[str,str]]=None,
           lineage_audit_clause_ids:Sequence[str]=())->FinalSummaryContext:
  src={k:self._plain(v or {}) for k,v in locals().items() if k not in {"self","source_paths","lineage_audit_clause_ids"}}
  kb=src["effective_kb"];raw_req_pairs=list(self._requirements(kb));pair_index={}
  for clause,req in raw_req_pairs:pair_index.setdefault(str(req.get("effective_requirement_id") or req.get("requirement_id") or ""),(clause,req))
  req_pairs=list(pair_index.values());duplicate_requirement_ids=sorted(k for k in pair_index if sum(str(r.get("effective_requirement_id") or r.get("requirement_id") or "")==k for _,r in raw_req_pairs)>1)
  apps=self._index(src["applicability"].get("results"),"effective_requirement_id");nas=self._index(src["na"].get("member_results"),"effective_requirement_id");matches=self._index(src["evidence"].get("matches"),"effective_requirement_id");finals=self._index(src["final"].get("results"),"effective_requirement_id");canonical=self._index(src["canonical_requirement_state"].get("records"),"requirement_id");gaps=self._index(src["coverage"].get("requirement_gaps"),"effective_requirement_id")
  tech=defaultdict(list)
  for x in src["technical"].get("results",[]) or []:tech[str(x.get("effective_requirement_id"))].append(x)
  issue_map=defaultdict(list)
  for x in src["issues"].get("issues",[]) or []:
   for rid in x.get("requirement_ids") or []:issue_map[str(rid)].append(x)
  root_map=defaultdict(list);roots=list(src["aggregated"].get("actionable_groups",[]) or [])
  for x in roots:
   for rid in x.get("requirement_ids") or []:root_map[str(rid)].append(x)
  action_map=defaultdict(list);root_ids={str(x.get("group_id")):x for x in roots}
  for action in src["actions"].get("actions",[]) or []:
   for gid in action.get("affected_aggregate_group_ids") or []:
    for rid in (root_ids.get(str(gid)) or {}).get("requirement_ids") or []:action_map[str(rid)].append(action)
  records=[]
  for clause,req in req_pairs:
   rid=str(req.get("effective_requirement_id") or req.get("requirement_id") or "");app=apps.get(rid,{});fin=finals.get(rid,{});state=canonical.get(rid,{});match=matches.get(rid,{});tr=tech.get(rid,[]);gap=gaps.get(rid,{})
   app_state=str(app.get("resolved_decision") or fin.get("applicability_decision") or "UNKNOWN");final_state=str(state.get("state") or fin.get("final_decision") or "");tech_states=sorted({str(x.get("decision")) for x in tr if x.get("decision")})
   gap_class=self._gap_class(app_state,final_state,tech_states,nas.get(rid,{}),issue_map.get(rid,[]));clause_id=str(req.get("clause_id") or clause.get("clause_id") or "")
   record={"requirement_id":rid,"clause_id":clause_id,"parent_clause_id":".".join(clause_id.split(".")[:-1]) or None,"requirement_text":req.get("text"),"requirement_type":req.get("requirement_type"),"source_standard":self._source_standard(req,kb),"effective_source":req.get("effective_source_type"),
    "applicability":{"status":app_state,"reason":app.get("reason"),"trigger_condition":req.get("condition_text"),"product_facts_used":app.get("product_fact_ids") or [],"missing_required_facts":fin.get("missing_features") or [],"scope_evaluation":copy.deepcopy(app.get("scope_evaluation"))},
    "reported_na":{"reported":nas.get(rid,{}).get("reported_na"),"status":nas.get(rid,{}).get("group_na_status") or fin.get("scope_aware_na_status"),"reason":nas.get(rid,{}).get("reason")},
    "evidence":{"status":match.get("match_status"),"summary":[{"evidence_id":x.get("evidence_id"),"match_reason":match.get("match_reason")} for x in (match.get("evidence_refs") or [])[:5]],"rejected_reasons":[x.get("reason") for x in issue_map.get(rid,[]) if str(x.get("issue_type")) in {"INVALID_TEST_EVIDENCE","UNRESOLVED_EVIDENCE_CONFLICT"}]},
    "technical_evaluation":{"rule_families":sorted({str(((x.get("rule_result") or {}).get("rule_family")) or ((x.get("constraint") or {}).get("constraint_type")) or "") for x in tr}-{''}),"results":tech_states,"reasons":[x.get("reason") for x in tr if x.get("reason")],"operands":[x.get("comparison_details") for x in tr if x.get("comparison_details")]},
    "gap":{"is_gap":gap_class!="NO_GAP","gap_type":gap_class,"reason":gap.get("reason") or fin.get("reason")},"criticality":req.get("criticality") or fin.get("criticality"),"decision_effect":req.get("decision_effect") or fin.get("decision_effect"),
    "root_cause_ids":sorted(str(x.get("group_id")) for x in root_map.get(rid,[]) if x.get("group_id")),"priority":self._priority(action_map.get(rid,[])),"next_action":self._next_action(action_map.get(rid,[])),"final_requirement_decision":final_state,"canonical_state":{"state":final_state,"reason_code":state.get("reason_code"),"state_authority":state.get("state_authority"),"requirement_version":state.get("requirement_version")},"traceability":{"effective_requirement_id":rid,"applicability_result":app.get("effective_requirement_id"),"evidence_match_id":match.get("match_id"),"technical_evaluation_ids":[x.get("evaluation_id") for x in tr if x.get("evaluation_id")],"final_decision_id":fin.get("decision_id"),"canonical_state_source_decision_ids":state.get("source_decision_ids") or [],"issue_ids":[x.get("issue_id") for x in issue_map.get(rid,[]) if x.get("issue_id")]}}
   records.append(record)
  records.sort(key=lambda x:(self._natural(x["clause_id"]),x["requirement_id"]))
  population=self._population(records,req_pairs,src["canonical_requirement_state"]);population["source_effective_requirement_objects"]=len(raw_req_pairs);population["duplicate_effective_requirement_ids"]=len(duplicate_requirement_ids);judgment=src["aggregated"].get("professional_judgment") or src["status"].get("professional_judgment") or {};metrics=copy.deepcopy(src["canonical_metrics"].get("client_metrics") or judgment.get("metrics") or {})
  disposition=self._disposition(src["status"],judgment);maturity=str(judgment.get("kb_maturity") or (kb.get("maturity") or {}).get("state") or "DRAFT")
  structure_findings=self._structure_findings(src["structure"]);parameter_findings=self._parameter_findings(src["parameters"]);evidence_findings=self._evidence_findings(records);na_findings=self._na_findings(records)
  unresolved=list(judgment.get("pre_llm_unresolved") or []);unresolved_counts=Counter(str(x.get("category")) for x in unresolved)
  source_paths=dict(source_paths or {});missing_sources=sorted(k for k,v in source_paths.items() if not v)
  diagnostics=[self._lineage_diagnostic(cid,req_pairs,apps,finals) for cid in lineage_audit_clause_ids]
  if duplicate_requirement_ids:diagnostics.append({"code":"DUPLICATE_EFFECTIVE_REQUIREMENT_ID","requirement_ids":duplicate_requirement_ids,"source_object_count":len(raw_req_pairs),"normalized_record_count":len(records)})
  context=FinalSummaryContext(SCHEMA_VERSION,self._run_context(src["manifest"],kb,src["final"],src["product_profile"],source_paths),self._standard_context(kb,src["standard_validation"],src["manifest"]),self._product_context(src["product_profile"]),population,
   [x["requirement_id"] for x in records if x["applicability"]["status"]=="APPLICABLE"],[x["requirement_id"] for x in records if x["applicability"]["status"]=="NOT_APPLICABLE"],[x["requirement_id"] for x in records if x["applicability"]["status"] in {"UNKNOWN","NEEDS_REVIEW"}],records,self._gap_summary(records),parameter_findings,evidence_findings,na_findings,structure_findings,self._root_views(roots),self._priority_views(src["actions"]),copy.deepcopy(src["actions"].get("actions") or []),metrics,
   {"maturity":maturity,"authoritative_pass_allowed":bool((src["response"].get("kb_authority") or {}).get("authoritative_pass_allowed") or disposition.get("value")=="PASS"),"authority_reason":"PASS authority follows the Step 40 disposition and recorded KB maturity.","review_scope":(kb.get("maturity") or {}).get("review_scope") or [],"coverage_limitations":(kb.get("maturity") or {}).get("limitations") or []},
   {"overall_compatibility":src["structure"].get("overall_compatibility") or (judgment.get("report_validity_summary") or {}).get("structure_compatibility"),"confidence":src["structure"].get("confidence"),"technical_product_failure_inferred":any(x.get("decision_effect")=="CONFIRMED_TECHNICAL_NONCOMPLIANCE" for x in roots)},disposition,{"total":len(unresolved),"counts":dict(sorted(unresolved_counts.items())),"cases":unresolved},
   {"requirement_ids_unique":len(records)==len({x["requirement_id"] for x in records}),"requirement_count_reconciles":population["total_effective_requirements"]==len(records),"canonical_state_count_reconciles":population["total_effective_requirements"]==sum(population["canonical_state_counts"].values()),"applicability_count_reconciles":population["total_effective_requirements"]==sum(population["applicability_state_counts"].values()),"canonical_requirement_state":{"schema_version":src["canonical_requirement_state"].get("schema_version"),"state_policy_version":src["canonical_requirement_state"].get("state_policy_version"),"projection_policy_version":src["canonical_requirement_state"].get("projection_policy_version"),"store_sha256":src["canonical_requirement_state"].get("store_sha256")},"gap_count_reconciles":sum(self._gap_summary(records)["by_type"].values())==self._gap_summary(records)["total"],"root_cause_child_references_valid":self._root_refs_valid(roots,src["issues"]),"source_artifact_paths":source_paths,"missing_source_artifacts":missing_sources,"benchmark_labels_used_as_ground_truth":False,"expert_labels_used_as_ground_truth":False,"assembly_policy_version":self.POLICY_VERSION},diagnostics)
  return context

 @staticmethod
 def _gap_class(app,final,tech,na,issues):
  if str(na.get("group_na_status")) in {"POTENTIAL_CONFLICT","INVALID"}:return "INVALID_NA"
  if app in {"UNKNOWN","NEEDS_REVIEW"}:return "MISSING_PRODUCT_FACT" if final=="UNKNOWN_APPLICABILITY" else "UNKNOWN_APPLICABILITY"
  if app=="NOT_APPLICABLE" or final in {"NOT_APPLICABLE","INACTIVE"}:return "NO_GAP"
  if final=="NON_COMPLIANT" or "VIOLATES" in tech:return "TECHNICAL_NON_COMPLIANCE"
  if any(x in {"UNSUPPORTED","UNSUPPORTED_RULE"} for x in tech):return "UNSUPPORTED_DETERMINISTIC_RULE"
  if any(x in {"REJECTED","REJECTED_EVIDENCE"} for x in tech):return "REJECTED_EVIDENCE"
  if final=="INSUFFICIENT_EVIDENCE" or "NO_MEASUREMENT" in tech:return "MISSING_EVIDENCE"
  if final=="NEEDS_REVIEW":return "HUMAN_REVIEW_REQUIRED"
  return "NO_GAP"
 @classmethod
 def _population(cls,records,pairs,canonical_store=None):
  app=Counter(x["applicability"]["status"] for x in records);dec=Counter(x["final_requirement_decision"] for x in records);gaps=Counter(x["gap"]["gap_type"] for x in records)
  canonical_counts=GenericCanonicalRequirementStateStore.state_counts(canonical_store or {"records":[]}) or dict(dec)
  return {"total_effective_requirements":len(records),"active_requirements":sum(str(r.get("effective_status"))!="INACTIVE" for _,r in pairs),"applicable":app["APPLICABLE"],"applicability_state_counts":dict(sorted(app.items())),"not_applicable":canonical_counts.get("NOT_APPLICABLE",0),"unknown_applicability":canonical_counts.get("UNKNOWN_APPLICABILITY",0),"needs_review":canonical_counts.get("NEEDS_REVIEW",0),"evaluated":canonical_counts.get("COMPLIANT",0)+canonical_counts.get("NON_COMPLIANT",0),"compliant":canonical_counts.get("COMPLIANT",0),"violated":canonical_counts.get("NON_COMPLIANT",0),"missing_evidence":canonical_counts.get("INSUFFICIENT_EVIDENCE",0),"rejected_evidence":gaps["REJECTED_EVIDENCE"],"unsupported_rules":gaps["UNSUPPORTED_DETERMINISTIC_RULE"],"incomparable":sum("INCOMPARABLE" in x["technical_evaluation"]["results"] for x in records),"other_unresolved":canonical_counts.get("NEEDS_REVIEW",0),"inactive":canonical_counts.get("INACTIVE",0),"canonical_state_counts":canonical_counts,"canonical_state_policy_version":(canonical_store or {}).get("state_policy_version"),"canonical_projection_policy_version":(canonical_store or {}).get("projection_policy_version")}
 @staticmethod
 def _gap_summary(records):
  c=Counter(x["gap"]["gap_type"] for x in records if x["gap"]["is_gap"]);return {"total":sum(c.values()),"by_type":dict(sorted(c.items())),"requirement_ids_by_type":{k:[x["requirement_id"] for x in records if x["gap"]["gap_type"]==k] for k in sorted(c)}}
 @staticmethod
 def _disposition(status,judgment):
  value=status.get("deterministic_disposition") or (judgment.get("final_disposition") or {}).get("value") or "HUMAN_REVIEW";return {"value":value,"policy_version":status.get("final_disposition_policy_version") or "STEP40_DISPOSITION_V1","reason":status.get("status_reason"),"blocking_conditions":status.get("reason_codes") or [],"critical_summary":judgment.get("critical_summary") or {},"authority_limited":value!="PASS"}
 @staticmethod
 def _product_context(profile):
  identity=profile.get("identity") or {};facts=profile.get("facts") or {};classifications=profile.get("classifications") or [];classification=classifications[0] if classifications else {}
  completeness=profile.get("required_fact_completeness") or {}
  missing=[{"fact_key":key,"status":item.get("status").value if isinstance(item.get("status"),Enum) else item.get("status"),"requirement_consumers":copy.deepcopy(item.get("requirement_consumers") or [])} for key,item in sorted(completeness.items()) if isinstance(item,dict) and str(item.get("status").value if isinstance(item.get("status"),Enum) else item.get("status")) in {"UNKNOWN","CONFLICT","CONFLICTING"}]
  source=profile.get("source") or {}
  observations=identity.get("product_identities") or []
  by_role=lambda role:[item.get("value") for item in observations if item.get("role")==role and item.get("value")]
  declared=by_role("DECLARED_MODEL") or identity.get("model_numbers") or []
  tested=by_role("TESTED_MODEL")
  representative=by_role("REPRESENTATIVE_MODEL")
  return {"reported_product_name":identity.get("product_name") or identity.get("name") or classification.get("reported_term"),"canonical_classification":classification.get("canonical_term") or identity.get("product_type") or identity.get("classification"),"classification_status":classification.get("status") or identity.get("classification_status"),"classification_confidence":classification.get("confidence") if classification.get("confidence") is not None else identity.get("classification_confidence"),"classification_basis":classification.get("classification_basis") or identity.get("classification_basis"),"classification_definition_reference":classification.get("definition_reference"),"classification_scope_reference":classification.get("scope_reference"),"model_numbers":identity.get("model_numbers") or [],"declared_models":declared,"tested_models":tested,"representative_models":representative,"type_references":identity.get("type_references") or [],"model_relationships":identity.get("relationships") or [],"brand":identity.get("brand") or identity.get("trademark"),"manufacturer":identity.get("manufacturer"),"tested_model":tested[0] if len(tested)==1 else None,"model_family":identity.get("model_family"),"identity_selection_provenance":identity.get("selection_provenance") or {},"source_report_identity":{"document_id":source.get("document_id"),"report_number":source.get("report_number"),"document_version":source.get("document_version"),"internal_identifier":source.get("internal_identifier"),"report_title":source.get("report_title"),"file_name":source.get("file_name"),"report_date":source.get("report_date"),"laboratory":source.get("laboratory"),"selection_provenance":source.get("selection_provenance") or {}},"confirmed_facts":facts,"inferred_facts":profile.get("inferred_facts") or [],"unknown_required_facts":profile.get("unknown_features") or [],"required_fact_completeness":completeness,"canonical_missing_required_facts":missing,"conflicting_facts":profile.get("conflicting_features") or []}
 @staticmethod
 def _standard_context(kb,validation,manifest):return {"base_standard":kb.get("base_standard"),"companion_standard":kb.get("delta_standard"),"effective_kb_id":kb.get("effective_kb_id"),"effective_kb_status":kb.get("build_status"),"effective_kb_maturity":(kb.get("maturity") or {}).get("state","DRAFT"),"standard_validation_status":validation.get("status"),"detected_report_standards":manifest.get("detected_standards") or [],"validation_diagnostics":validation.get("diagnostics") or []}
 @staticmethod
 def _run_context(manifest,kb,final,profile,paths):
  source=profile.get("source") or {}
  return {"run_id":manifest.get("run_id"),"generation_timestamp":manifest.get("completed_at") or manifest.get("started_at"),"summary_context_generated_at":manifest.get("completed_at") or manifest.get("started_at"),"pipeline_status":manifest.get("pipeline_status"),"report_identifier":final.get("report_document_id"),"source_report_number":source.get("report_number"),"source_report_document_id":source.get("document_id"),"effective_kb_id":kb.get("effective_kb_id"),"source_artifacts":dict(sorted(paths.items())),"policy_versions":{"assembly":"STEP43_ASSEMBLY_V1","root_cause":"STEP40_ROOT_CAUSE_V1","compliance":"STEP40_COMPLIANCE_V1","coverage":"STEP40_COVERAGE_V1","confidence":"STEP40_CONFIDENCE_V1","disposition":"STEP40_DISPOSITION_V1"}}
 @staticmethod
 def _parameter_findings(parameters):return [copy.deepcopy(x) for x in parameters.get("findings",[]) or [] if str(x.get("finding_type") or x.get("status")) not in {"","CONSISTENT","NO_CONFLICT"}]
 @staticmethod
 def _evidence_findings(records):return [{"requirement_id":x["requirement_id"],"status":x["evidence"]["status"],"gap_type":x["gap"]["gap_type"],"rejected_reasons":x["evidence"]["rejected_reasons"]} for x in records if x["gap"]["gap_type"] in {"MISSING_EVIDENCE","INVALID_EVIDENCE","REJECTED_EVIDENCE","REPORT_STRUCTURE_MISMATCH"}]
 @staticmethod
 def _na_findings(records):return [{"requirement_id":x["requirement_id"],**x["reported_na"],"engine_applicability":x["applicability"]["status"]} for x in records if x["reported_na"]["reported"] or x["reported_na"]["status"]]
 @staticmethod
 def _structure_findings(structure):return [{k:copy.deepcopy(structure.get(k)) for k in ("overall_compatibility","confidence","summary","findings","diagnostics") if structure.get(k) is not None}] if structure else []
 @staticmethod
 def _root_views(roots):return [{"root_cause_id":x.get("group_id"),"title":x.get("title"),"technical_basis":x.get("technical_basis") or {"root_reason":x.get("root_reason")},"affected_requirement_ids":x.get("requirement_ids") or [],"canonical_requirement_references":[{"requirement_id":rid,"state_source":"decisions/canonical_requirement_state_store.json"} for rid in (x.get("requirement_ids") or [])],"child_issue_ids":x.get("issue_ids") or [],"severity":(x.get("severity_summary") or {}).get("highest"),"decision_effect":x.get("decision_effect"),"hierarchy":x.get("hierarchy"),"parent_root_cause_id":x.get("parent_root_cause_id"),"upstream_cause_ids":x.get("upstream_cause_ids") or [],"decision_effect_policy_version":x.get("decision_effect_policy_version"),"dominant_blocker_policy_version":x.get("dominant_blocker_policy_version"),"corrective_action":x.get("primary_action"),"confidence":x.get("root_cause_confidence") or "DETERMINISTIC"} for x in roots]
 @staticmethod
 def _priority_views(actions):return [{"action_id":x.get("action_id"),"priority":x.get("priority_label") or x.get("priority_level"),"title":x.get("title"),"affected_root_cause_ids":x.get("affected_aggregate_group_ids") or []} for x in actions.get("actions",[]) or []]
 @staticmethod
 def _priority(actions):return next((x.get("priority_label") or x.get("priority_level") for x in actions),None)
 @staticmethod
 def _next_action(actions):return next((x.get("title") for x in actions if x.get("title")),None)
 @staticmethod
 def _root_refs_valid(roots,issues):
  known={str(x.get("issue_id")) for x in issues.get("issues",[]) or []};return all(set(map(str,x.get("issue_ids") or []))<=known for x in roots)
 @staticmethod
 def _source_standard(req,kb):return (kb.get("delta_standard") or {}).get("standard_number") if req.get("delta_sources") else (kb.get("base_standard") or {}).get("standard_number")
 @classmethod
 def _lineage_diagnostic(cls,clause_id,pairs,apps,finals):
  found=[r for c,r in pairs if str(r.get("clause_id") or c.get("clause_id"))==str(clause_id)]
  if not found:return {"code":"CLAUSE_LINEAGE_AUDIT","clause_id":clause_id,"result":"MISSING_FROM_EFFECTIVE_KB","requirement_ids":[]}
  ids=[str(x.get("effective_requirement_id") or x.get("requirement_id")) for x in found];states=[str(finals.get(x,{}).get("final_decision") or apps.get(x,{}).get("resolved_decision") or "NO_RESULT") for x in ids]
  return {"code":"CLAUSE_LINEAGE_AUDIT","clause_id":clause_id,"result":"PRESENT_WITH_ATOMIC_LINEAGE","requirement_ids":ids,"states":states}
 @classmethod
 def _requirements(cls,kb):
  def walk(items):
   for c in items or []:yield c;yield from walk(c.get("children") or [])
  for c in walk(kb.get("clauses") or []):
   for r in c.get("requirements") or []:yield c,r
  for a in kb.get("annexes") or []:
   for r in a.get("requirements") or []:yield {"clause_id":a.get("annex_id")},r
   for c in walk(a.get("clauses") or []):
    for r in c.get("requirements") or []:yield c,r
 @staticmethod
 def _index(items,key):return {str(x.get(key)):x for x in items or [] if x.get(key) is not None}
 @staticmethod
 def _read(path):return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
 @classmethod
 def _plain(cls,v):
  if isinstance(v,Enum):return v.value
  if is_dataclass(v):return cls._plain(asdict(v))
  if isinstance(v,Mapping):return {str(k):cls._plain(x) for k,x in v.items()}
  if isinstance(v,(list,tuple)):return [cls._plain(x) for x in v]
  return copy.deepcopy(v)
 @staticmethod
 def _natural(v):return tuple(int(x) if x.isdigit() else x for x in re.split(r"(\d+)",v or ""))
 @classmethod
 def to_dict(cls,v):return cls._plain(v)
 @classmethod
 def to_json(cls,v,indent=2):return json.dumps(cls.to_dict(v),ensure_ascii=False,sort_keys=True,indent=indent)
 @classmethod
 def save_json(cls,v,path):path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(cls.to_json(v)+"\n",encoding="utf-8");return path

__all__=["FinalSummaryContext","GenericFinalSummaryContextBuilder","SCHEMA_VERSION"]
