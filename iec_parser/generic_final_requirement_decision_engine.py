"""Combine independently derived artifacts into strict final requirement decisions."""
from __future__ import annotations
import copy,json,re
from collections import Counter,defaultdict
from dataclasses import asdict,dataclass,field,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Dict,Iterable,List,Mapping,Optional,Sequence,Tuple
from urllib.parse import quote

STRICT_EVIDENCE_POLICY=True
class FinalRequirementDecision(str,Enum):
 COMPLIANT="COMPLIANT";NON_COMPLIANT="NON_COMPLIANT";NOT_APPLICABLE="NOT_APPLICABLE";INSUFFICIENT_EVIDENCE="INSUFFICIENT_EVIDENCE";UNKNOWN_APPLICABILITY="UNKNOWN_APPLICABILITY";NEEDS_REVIEW="NEEDS_REVIEW";INACTIVE="INACTIVE"
class EvidenceSufficiency(str,Enum):
 SUFFICIENT="SUFFICIENT";PARTIAL="PARTIAL";INSUFFICIENT="INSUFFICIENT";NOT_REQUIRED="NOT_REQUIRED";UNKNOWN="UNKNOWN"
class DecisionBasis(str,Enum):
 EFFECTIVE_INACTIVE="EFFECTIVE_INACTIVE";APPLICABILITY_NOT_APPLICABLE="APPLICABILITY_NOT_APPLICABLE";APPLICABILITY_UNKNOWN="APPLICABILITY_UNKNOWN";APPLICABILITY_REVIEW="APPLICABILITY_REVIEW";TECHNICAL_SATISFIES="TECHNICAL_SATISFIES";TECHNICAL_VIOLATES="TECHNICAL_VIOLATES";TECHNICAL_NO_MEASUREMENT="TECHNICAL_NO_MEASUREMENT";TECHNICAL_REVIEW="TECHNICAL_REVIEW";REPORT_PASS="REPORT_PASS";REPORT_FAIL="REPORT_FAIL";REPORT_NA="REPORT_NA";REPORT_NOT_STATED="REPORT_NOT_STATED";EVIDENCE_EXACT_GROUP="EVIDENCE_EXACT_GROUP";EVIDENCE_WHOLE_CLAUSE="EVIDENCE_WHOLE_CLAUSE";EVIDENCE_MULTIPLE_GROUPS="EVIDENCE_MULTIPLE_GROUPS";EVIDENCE_AMBIGUOUS="EVIDENCE_AMBIGUOUS";NA_JUSTIFIED="NA_JUSTIFIED";NA_POTENTIAL_CONFLICT="NA_POTENTIAL_CONFLICT";NA_INSUFFICIENT_PRODUCT_DATA="NA_INSUFFICIENT_PRODUCT_DATA";NA_INSUFFICIENT_REPORT_EVIDENCE="NA_INSUFFICIENT_REPORT_EVIDENCE";NON_NUMERIC_REPORT_EVIDENCE="NON_NUMERIC_REPORT_EVIDENCE";NO_REPORT_EVIDENCE="NO_REPORT_EVIDENCE"
@dataclass
class FinalRequirementDecisionResult:
 decision_id:str;effective_requirement_id:str;effective_clause_id:Optional[str];clause_id:Optional[str];group_id:Optional[str];effective_status:Optional[str];final_decision:FinalRequirementDecision;evidence_sufficiency:EvidenceSufficiency;reason_code:str;reason:str;applicability_decision:Optional[str];report_verdicts:List[str]=field(default_factory=list);evidence_match_statuses:List[str]=field(default_factory=list);report_scope_statuses:List[str]=field(default_factory=list);scope_aware_na_status:Optional[str]=None;technical_constraint_decisions:List[str]=field(default_factory=list);decision_bases:List[DecisionBasis]=field(default_factory=list);supporting_evidence_ids:List[str]=field(default_factory=list);supporting_measurement_ids:List[str]=field(default_factory=list);missing_features:List[str]=field(default_factory=list);review_reasons:List[str]=field(default_factory=list);base_sources:List[Dict[str,Any]]=field(default_factory=list);delta_sources:List[Dict[str,Any]]=field(default_factory=list);notes:Optional[str]=None;criticality:Optional[Dict[str,Any]]=None;decision_effect:Optional[str]=None;evidence_match_status:Optional[str]=None;evidence_sufficiency_status:Optional[str]=None;evaluation_basis:Optional[str]=None;evaluation_authority:Optional[str]=None;authority_reason:Optional[str]=None;technical_execution_ids:List[str]=field(default_factory=list)
@dataclass
class FinalRequirementGroupDecision:
 group_id:str;clause_id:Optional[str];member_requirement_ids:List[str];group_applicability:Optional[str];group_decision:FinalRequirementDecision;member_decisions:Dict[str,str];report_evidence_ids:List[str];technical_constraint_summary:Dict[str,int];reason:str;review_reasons:List[str]=field(default_factory=list)
@dataclass
class FinalClauseDecision:
 clause_id:str;group_ids:List[str];requirement_ids:List[str];decision:FinalRequirementDecision;counts:Dict[str,int];reason:str
@dataclass
class FinalRequirementDecisionReport:
 effective_kb_id:str;profile_id:str;report_document_id:str;results:List[FinalRequirementDecisionResult]=field(default_factory=list);group_decisions:List[FinalRequirementGroupDecision]=field(default_factory=list);clause_decisions:List[FinalClauseDecision]=field(default_factory=list);summary:Dict[str,Any]=field(default_factory=dict);diagnostics:List[Dict[str,Any]]=field(default_factory=list)

class GenericFinalRequirementDecisionEngine:
 """Apply strict evidence policy without recomputing any upstream responsibility."""
 PRECEDENCE=[FinalRequirementDecision.NON_COMPLIANT,FinalRequirementDecision.NEEDS_REVIEW,FinalRequirementDecision.UNKNOWN_APPLICABILITY,FinalRequirementDecision.INSUFFICIENT_EVIDENCE,FinalRequirementDecision.COMPLIANT,FinalRequirementDecision.NOT_APPLICABLE,FinalRequirementDecision.INACTIVE]
 RELIABLE_SCOPES={"EXACT_GROUP","WHOLE_CLAUSE","MULTIPLE_GROUPS","PARENT_SCOPE","CHILD_SCOPE"}
 ACCEPTANCE_TYPES={"SIMPLE_LIMIT","RANGE","MINIMUM","MAXIMUM","EXACT","TOLERANCE","COMPOUND","FORMULA","TIME_LIMIT","DISTANCE_LIMIT","TEMPERATURE_LIMIT","CURRENT_LIMIT","VOLTAGE_LIMIT","POWER_LIMIT","SPEED_LIMIT","FLOW_LIMIT","FORCE_LIMIT","COUNT_LIMIT","PERCENTAGE_LIMIT","OTHER"}
 def __init__(self):self._diagnostics=[]
 def evaluate(self,effective_kb,product_profile,group_aware_applicability,report_evidence,evidence_match,technical_constraint_result,requirement_grouping,report_evidence_scope,scope_aware_na_validation,canonical_evidence_sufficiency=None):
  self._diagnostics=[];reqs={str(self._get(r,"effective_requirement_id")):r for r in self._requirements(effective_kb)};apps={str(self._get(x,"effective_requirement_id")):x for x in self._get(group_aware_applicability,"results",[]) or []};tech=defaultdict(list)
  for x in self._get(technical_constraint_result,"results",[]) or []:tech[str(self._get(x,"effective_requirement_id"))].append(x)
  for x in self._get(technical_constraint_result,"rule_results",[]) or []:tech[str(self._get(x,"source_requirement_id"))].append(x)
  groups={str(self._get(g,"group_id")):g for g in self._get(requirement_grouping,"groups",[]) or []};member_group={str(self._get(m,"effective_requirement_id")):str(self._get(g,"group_id")) for g in groups.values() for m in self._get(g,"members",[]) or []};matches={str(self._get(x,"effective_requirement_id")):x for x in self._get(evidence_match,"matches",[]) or []};na_members={str(self._get(x,"effective_requirement_id")):x for x in self._get(scope_aware_na_validation,"member_results",[]) or []};scoped=self._scoped_by_group(report_evidence_scope);evmap={str(self._get(x,"evidence_id")):x for x in self._evidence(report_evidence)}
  canonical_evidence={str(self._get(x,"effective_requirement_id") or self._get(x,"requirement_id")):x for x in self._get(canonical_evidence_sufficiency,"results",[]) or []}
  results=[]
  for rid,req in reqs.items():
   gid=member_group.get(rid);result=self.evaluate_requirement(req,apps.get(rid,{}),matches.get(rid,{}),tech.get(rid,[]),na_members.get(rid),gid,scoped.get(gid,[]),evmap);results.append(self._apply_canonical_evidence_gate(result,canonical_evidence.get(rid)))
  group_decisions=[self.evaluate_group(g,[x for x in results if x.group_id==gid]) for gid,g in sorted(groups.items())];grouped_ids={x.effective_requirement_id for x in results if x.group_id};group_decisions.extend(self._standalone_group(x) for x in results if x.effective_requirement_id not in grouped_ids)
  clauses=defaultdict(list)
  for g in group_decisions:clauses[str(g.clause_id)].append(g)
  clause_decisions=[self.aggregate_clause(cid,items) for cid,items in sorted(clauses.items(),key=lambda x:self._natural(x[0]))];report=FinalRequirementDecisionReport(str(self._get(effective_kb,"effective_kb_id","")),str(self._get(product_profile,"profile_id","")),str(self._get(report_evidence,"document_id","")),results,group_decisions,clause_decisions,diagnostics=copy.deepcopy(self._diagnostics));report.summary=self.get_summary(report,tech,scoped);return report
 def _apply_canonical_evidence_gate(self,result,canonical):
  """Canonical evidence may remove an unsupported pass, never create one."""
  if canonical is None:
   if result.final_decision==FinalRequirementDecision.COMPLIANT:
    result.final_decision=FinalRequirementDecision.INSUFFICIENT_EVIDENCE;result.evidence_sufficiency=EvidenceSufficiency.INSUFFICIENT;result.reason_code="FINAL_CANONICAL_EVIDENCE_MISSING";result.reason=self._reason(result.reason_code);result.review_reasons=list(dict.fromkeys(result.review_reasons+[result.reason_code]));result.notes="Step 50-B pass authority blocked compliance because no canonical evidence-authority record exists."
   return result
  status=self._enum(self._get(self._get(canonical,"sufficiency",{}),"status"));usable=self._enum(self._get(self._get(canonical,"identity_usability",{}),"status"))
  basis=self._enum(self._get(canonical,"evaluation_basis"));authority=self._enum(self._get(canonical,"evaluation_authority"))
  result.evidence_match_status=self._enum(self._get(self._get(canonical,"evidence_match",{}),"match_status"));result.evidence_sufficiency_status=status;result.evaluation_basis=basis;result.evaluation_authority=authority;result.authority_reason=self._get(canonical,"authority_reason");result.supporting_evidence_ids=sorted(set((self._get(result,"supporting_evidence_ids",[]) or [])+(self._get(canonical,"supporting_evidence_ids",[]) or [])));result.technical_execution_ids=sorted(set(self._get(canonical,"technical_execution_ids",[]) or []))
  if result.final_decision!=FinalRequirementDecision.COMPLIANT:return result
  if status=="SUFFICIENT" and usable=="USABLE" and basis in {"DETERMINISTIC_RULE","REPORTED_VERDICT","INSPECTION","DOCUMENT_REVIEW"} and authority=="AUTHORITATIVE":return result
  if status=="INSUFFICIENT":result.final_decision=FinalRequirementDecision.INSUFFICIENT_EVIDENCE;result.evidence_sufficiency=EvidenceSufficiency.INSUFFICIENT;result.reason_code="FINAL_CANONICAL_EVIDENCE_INSUFFICIENT"
  else:result.final_decision=FinalRequirementDecision.NEEDS_REVIEW;result.evidence_sufficiency=EvidenceSufficiency.UNKNOWN;result.reason_code="FINAL_CANONICAL_EVIDENCE_NOT_COMPARABLE" if status=="NOT_COMPARABLE" or usable=="NOT_USABLE" else "FINAL_CANONICAL_EVIDENCE_BASIS_MISSING" if not basis else "FINAL_CANONICAL_EVIDENCE_REVIEW"
  result.reason=self._reason(result.reason_code);result.review_reasons=list(dict.fromkeys(result.review_reasons+[result.reason_code]));result.notes="Step 48-E canonical evidence authority blocked an unsupported compliance pass.";return result
 def evaluate_requirement(self,req,app,match,technical,na_member,group_id,scopes,evmap):
  rid=str(self._get(req,"effective_requirement_id"));estatus=self._enum(self._get(req,"effective_status"));decision=self._enum(self._get(app,"resolved_decision"));owned={str(self._get(x,"evidence_id")) for x in self._get(match,"evidence_refs",[]) or [] if self._get(x,"evidence_id")};match_type=self._get(match,"match_type");scopes=[] if not owned and match_type=="CLAUSE_PRESENCE_ONLY" else [x for x in scopes if not owned or str(self._get(x,"report_evidence_id")) in owned];verdicts=sorted({self._enum(self._get(x,"reported_verdict")) for x in scopes if self._get(x,"reported_verdict") and self._enum(self._get(x,"reported_verdict"))!="NOT_STATED"});scope_statuses=sorted({self._enum(self._get(x,"scope_status")) for x in scopes});eids=sorted({str(value) for x in technical for value in (self._get(x,"evidence_ids",[]) or []) if value}|{str(self._get(x,"report_evidence_id")) for x in scopes});match_statuses=sorted({self._enum(self._get(match,"match_status"))} - {None});tdec=sorted(self._enum(self._get(x,"decision")) for x in technical);measurements=sorted({str(mid) for x in technical for mid in ([self._get(x,"selected_measurement_id")] if self._get(x,"selected_measurement_id") else [])});na_status=self._enum(self._get(na_member,"status"));bases=[];reviews=[];grouped_verdict=self._get(match,"evidence_scope")=="GROUP_VERDICT"
  if estatus=="INACTIVE" or decision=="INACTIVE":final,suff,code=FinalRequirementDecision.INACTIVE,EvidenceSufficiency.NOT_REQUIRED,"FINAL_EFFECTIVE_INACTIVE";bases=[DecisionBasis.EFFECTIVE_INACTIVE]
  elif decision=="NOT_APPLICABLE":final,suff,code=FinalRequirementDecision.NOT_APPLICABLE,EvidenceSufficiency.NOT_REQUIRED,"FINAL_NOT_APPLICABLE";bases=[DecisionBasis.APPLICABILITY_NOT_APPLICABLE]+([DecisionBasis.NA_JUSTIFIED] if na_status=="JUSTIFIED" else [])
  elif decision=="UNKNOWN":final,suff,code=FinalRequirementDecision.UNKNOWN_APPLICABILITY,EvidenceSufficiency.UNKNOWN,"FINAL_APPLICABILITY_UNKNOWN";bases=[DecisionBasis.APPLICABILITY_UNKNOWN]
  elif decision=="NEEDS_REVIEW":final,suff,code=FinalRequirementDecision.NEEDS_REVIEW,EvidenceSufficiency.UNKNOWN,"FINAL_APPLICABILITY_NEEDS_REVIEW";bases=[DecisionBasis.APPLICABILITY_REVIEW];reviews.append(code)
  elif "VIOLATES" in tdec:final,suff,code,bases,reviews=self._evidence_decision(req,verdicts,scope_statuses,technical,tdec)
  elif na_status=="POTENTIAL_CONFLICT":final,suff,code=FinalRequirementDecision.NEEDS_REVIEW,EvidenceSufficiency.PARTIAL,"FINAL_NA_POTENTIAL_CONFLICT";bases=[DecisionBasis.REPORT_NA,DecisionBasis.NA_POTENTIAL_CONFLICT];reviews.append("REPORT_NA_CONFLICT_WITH_APPLICABLE_REQUIREMENT")
  elif na_status in {"INSUFFICIENT_REPORT_EVIDENCE"}:final,suff,code=FinalRequirementDecision.NEEDS_REVIEW,EvidenceSufficiency.UNKNOWN,"FINAL_NA_SCOPE_AMBIGUOUS";bases=[DecisionBasis.NA_INSUFFICIENT_REPORT_EVIDENCE,DecisionBasis.EVIDENCE_AMBIGUOUS];reviews.append(code)
  elif na_status=="NEEDS_REVIEW":final,suff,code=FinalRequirementDecision.NEEDS_REVIEW,EvidenceSufficiency.UNKNOWN,"FINAL_CONFLICTING_REPORT_EVIDENCE";bases=[DecisionBasis.REPORT_NA];reviews.append(code)
  elif grouped_verdict:
   final,suff,code=FinalRequirementDecision.NEEDS_REVIEW,EvidenceSufficiency.PARTIAL,"FINAL_GROUPED_EVIDENCE_INSUFFICIENT_GRANULARITY";bases=[DecisionBasis.EVIDENCE_MULTIPLE_GROUPS];reviews.append(code)
  else:
   final,suff,code,bases,reviews=self._evidence_decision(req,verdicts,scope_statuses,technical,tdec)
  bases+=self._scope_bases(scope_statuses);reason=self._reason(code);result=FinalRequirementDecisionResult("FINAL-REQ-"+quote(rid,safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"),rid,self._get(app,"effective_clause_id"),self._get(req,"clause_id"),group_id,estatus,final,suff,code,reason,decision,verdicts,match_statuses,scope_statuses,na_status,tdec,list(dict.fromkeys(bases)),eids,measurements,[],reviews,copy.deepcopy(self._get(req,"base_sources",[]) or []),copy.deepcopy(self._get(req,"delta_sources",[]) or []),"Strict evidence policy." );criticality=self._get(req,"criticality");result.criticality=copy.deepcopy(criticality.to_dict() if hasattr(criticality,"to_dict") else criticality);result.decision_effect=self._enum(self._get(req,"decision_effect"));return result
 def _evidence_decision(self,req,verdicts,scopes,technical,tdec):
  bases=[];reviews=[];has_pass="PASS" in verdicts;has_fail="FAIL" in verdicts;has_na="NA" in verdicts;reliable=bool(set(scopes)&self.RELIABLE_SCOPES);acceptance=[x for x in technical if self._enum(self._get(self._get(x,"constraint",{}),"constraint_type")) in self.ACCEPTANCE_TYPES];testparams=[x for x in technical if self._enum(self._get(self._get(x,"constraint",{}),"constraint_type"))=="TEST_PARAMETER"]
  if verdicts and set(scopes)&{"AMBIGUOUS","UNRESOLVED"}:return FinalRequirementDecision.NEEDS_REVIEW,EvidenceSufficiency.UNKNOWN,"FINAL_REPORT_EVIDENCE_SCOPE_AMBIGUOUS",[DecisionBasis.EVIDENCE_AMBIGUOUS],["REPORT_EVIDENCE_SCOPE_AMBIGUOUS"]
  if "VIOLATES" in tdec:
   if has_fail and "SATISFIES" in tdec:return FinalRequirementDecision.NEEDS_REVIEW,EvidenceSufficiency.PARTIAL,"FINAL_CONFLICTING_REPORT_EVIDENCE",[DecisionBasis.REPORT_FAIL,DecisionBasis.TECHNICAL_SATISFIES], ["REPORT_FAIL_CONFLICTS_WITH_TECHNICAL_EVIDENCE"]
   return FinalRequirementDecision.NON_COMPLIANT,EvidenceSufficiency.SUFFICIENT,"FINAL_TECHNICAL_VIOLATION",[DecisionBasis.TECHNICAL_VIOLATES]+([DecisionBasis.REPORT_PASS] if has_pass else []),[]
  if has_na:return FinalRequirementDecision.NEEDS_REVIEW,EvidenceSufficiency.PARTIAL,"FINAL_NA_POTENTIAL_CONFLICT",[DecisionBasis.REPORT_NA,DecisionBasis.NA_POTENTIAL_CONFLICT],["REPORT_NA_CONFLICT_WITH_APPLICABLE_REQUIREMENT"]
  if "NOT_EXECUTABLE" in tdec:return FinalRequirementDecision.INSUFFICIENT_EVIDENCE,EvidenceSufficiency.INSUFFICIENT,"FINAL_TECHNICAL_EVIDENCE_MISSING",[DecisionBasis.TECHNICAL_NO_MEASUREMENT],[]
  if any(x in {"NEEDS_REVIEW","INCOMPARABLE","UNKNOWN"} for x in tdec):return FinalRequirementDecision.NEEDS_REVIEW,EvidenceSufficiency.UNKNOWN,"FINAL_TECHNICAL_NEEDS_REVIEW",[DecisionBasis.TECHNICAL_REVIEW],["UNRESOLVED_TECHNICAL_CONSTRAINT"]
  if has_pass and has_fail:return FinalRequirementDecision.NEEDS_REVIEW,EvidenceSufficiency.PARTIAL,"FINAL_CONFLICTING_REPORT_EVIDENCE",[DecisionBasis.REPORT_PASS,DecisionBasis.REPORT_FAIL],["CONFLICTING_REPORT_VERDICTS"]
  if has_fail:
   if not reliable:return FinalRequirementDecision.NEEDS_REVIEW,EvidenceSufficiency.UNKNOWN,"FINAL_REPORT_FAIL_SCOPE_AMBIGUOUS",[DecisionBasis.REPORT_FAIL,DecisionBasis.EVIDENCE_AMBIGUOUS],["REPORT_FAIL_SCOPE_AMBIGUOUS"]
   if "SATISFIES" in tdec:return FinalRequirementDecision.NEEDS_REVIEW,EvidenceSufficiency.PARTIAL,"FINAL_CONFLICTING_REPORT_EVIDENCE",[DecisionBasis.REPORT_FAIL,DecisionBasis.TECHNICAL_SATISFIES],["REPORT_FAIL_CONFLICTS_WITH_TECHNICAL_EVIDENCE"]
   return FinalRequirementDecision.NON_COMPLIANT,EvidenceSufficiency.SUFFICIENT,"FINAL_REPORTED_FAIL",[DecisionBasis.REPORT_FAIL],[]
  if testparams and "NO_MEASUREMENT" in tdec:return FinalRequirementDecision.NEEDS_REVIEW,EvidenceSufficiency.INSUFFICIENT,"FINAL_TEST_METHOD_EVIDENCE_INCOMPLETE",[DecisionBasis.TECHNICAL_NO_MEASUREMENT],["TEST_METHOD_NOT_DEMONSTRATED"]
  if acceptance and "NO_MEASUREMENT" in tdec:return FinalRequirementDecision.INSUFFICIENT_EVIDENCE,EvidenceSufficiency.INSUFFICIENT,"FINAL_REPORT_PASS_WITHOUT_MEASUREMENT" if has_pass else "FINAL_TECHNICAL_EVIDENCE_MISSING",([DecisionBasis.REPORT_PASS] if has_pass else [])+[DecisionBasis.TECHNICAL_NO_MEASUREMENT],[]
  if has_pass and reliable:return FinalRequirementDecision.COMPLIANT,EvidenceSufficiency.SUFFICIENT,"FINAL_TECHNICAL_EVIDENCE_COMPLETE" if acceptance and tdec and all(x=="SATISFIES" for x in tdec) else "FINAL_REPORTED_PASS_NON_NUMERIC",[DecisionBasis.REPORT_PASS]+([DecisionBasis.TECHNICAL_SATISFIES] if "SATISFIES" in tdec else [DecisionBasis.NON_NUMERIC_REPORT_EVIDENCE]),[]
  if verdicts:return FinalRequirementDecision.INSUFFICIENT_EVIDENCE,EvidenceSufficiency.INSUFFICIENT,"FINAL_REPORT_VERDICT_UNKNOWN",[DecisionBasis.REPORT_NOT_STATED],[]
  return FinalRequirementDecision.INSUFFICIENT_EVIDENCE,EvidenceSufficiency.INSUFFICIENT,"FINAL_NO_REPORT_EVIDENCE",[DecisionBasis.NO_REPORT_EVIDENCE],[]
 def evaluate_group(self,g,members):
  gid=str(self._get(g,"group_id"));primary=str(self._get(g,"primary_requirement_id") or "");p=next((x for x in members if x.effective_requirement_id==primary),members[0] if members else None);app=p.applicability_decision if p else None
  if app=="NOT_APPLICABLE":decision=FinalRequirementDecision.NOT_APPLICABLE
  else:decision=self._aggregate([x.final_decision for x in members])
  tc=Counter(y for x in members for y in x.technical_constraint_decisions);return FinalRequirementGroupDecision(gid,self._get(g,"clause_id"),[x.effective_requirement_id for x in members],app,decision,{x.effective_requirement_id:x.final_decision.value for x in members},sorted({e for x in members for e in x.supporting_evidence_ids}),dict(sorted(tc.items())),f"Conservative aggregation of {len(members)} member decisions.",sorted({r for x in members for r in x.review_reasons}))
 def _standalone_group(self,x):return FinalRequirementGroupDecision("UNGROUPED-"+x.effective_requirement_id,x.clause_id,[x.effective_requirement_id],x.applicability_decision,x.final_decision,{x.effective_requirement_id:x.final_decision.value},x.supporting_evidence_ids,dict(Counter(x.technical_constraint_decisions)),"Ungrouped effective requirement retains its own decision.",x.review_reasons)
 def aggregate_clause(self,cid,groups):
  decision=self._aggregate([x.group_decision for x in groups]);counts=Counter(x.group_decision.value for x in groups);return FinalClauseDecision(cid,[x.group_id for x in groups],[r for x in groups for r in x.member_requirement_ids],decision,{x.value:counts[x.value] for x in FinalRequirementDecision},f"Conservative aggregation of {len(groups)} logical groups.")
 def _aggregate(self,decisions):
  return next((x for x in self.PRECEDENCE if x in decisions),FinalRequirementDecision.NEEDS_REVIEW)
 @classmethod
 def _scoped_by_group(cls,scope):
  out=defaultdict(list)
  for x in cls._get(scope,"results",[]) or []:
   status=cls._enum(cls._get(x,"scope_status"))
   refs=cls._get(x,"selected_groups",[]) if status in cls.RELIABLE_SCOPES else cls._get(x,"candidate_groups",[]) if status in {"AMBIGUOUS","UNRESOLVED"} else []
   for g in refs:out[str(cls._get(g,"group_id"))].append(x)
  return out
 @staticmethod
 def _scope_bases(scopes):
  m={"EXACT_GROUP":DecisionBasis.EVIDENCE_EXACT_GROUP,"WHOLE_CLAUSE":DecisionBasis.EVIDENCE_WHOLE_CLAUSE,"MULTIPLE_GROUPS":DecisionBasis.EVIDENCE_MULTIPLE_GROUPS,"AMBIGUOUS":DecisionBasis.EVIDENCE_AMBIGUOUS,"UNRESOLVED":DecisionBasis.EVIDENCE_AMBIGUOUS};return [m[x] for x in scopes if x in m]
 @staticmethod
 def _reason(code):return {"FINAL_EFFECTIVE_INACTIVE":"Effective requirement is inactive.","FINAL_NOT_APPLICABLE":"Group-aware applicability establishes that the requirement does not apply.","FINAL_APPLICABILITY_UNKNOWN":"Applicability cannot be determined from available product facts.","FINAL_APPLICABILITY_NEEDS_REVIEW":"Applicability semantics require review.","FINAL_NA_POTENTIAL_CONFLICT":"Scoped report N/A conflicts with an applicable logical group.","FINAL_NA_SCOPE_AMBIGUOUS":"Report N/A scope remains ambiguous.","FINAL_REPORT_EVIDENCE_SCOPE_AMBIGUOUS":"Report evidence scope remains ambiguous.","FINAL_GROUPED_EVIDENCE_INSUFFICIENT_GRANULARITY":"The report provides a grouped verdict, but does not independently prove this atomic requirement.","FINAL_TECHNICAL_VIOLATION":"Reliable technical evidence violates an acceptance constraint.","FINAL_TECHNICAL_EVIDENCE_COMPLETE":"Technical and report evidence are sufficient.","FINAL_TECHNICAL_EVIDENCE_MISSING":"A material technical constraint lacks comparable evidence.","FINAL_TECHNICAL_NEEDS_REVIEW":"Technical constraint evaluation remains unresolved.","FINAL_REPORTED_FAIL":"Reliably scoped report evidence states FAIL.","FINAL_REPORT_FAIL_SCOPE_AMBIGUOUS":"FAIL evidence scope is ambiguous.","FINAL_REPORTED_PASS_NON_NUMERIC":"Reliably scoped PASS covers a non-numeric obligation.","FINAL_REPORT_PASS_WITHOUT_MEASUREMENT":"PASS does not replace missing numeric measurement evidence.","FINAL_NO_REPORT_EVIDENCE":"No reliably scoped report evidence supports the applicable requirement.","FINAL_REPORT_VERDICT_UNKNOWN":"Scoped evidence has no decisive verdict.","FINAL_CONFLICTING_REPORT_EVIDENCE":"Upstream evidence decisions conflict.","FINAL_TEST_METHOD_EVIDENCE_INCOMPLETE":"Mandatory test setup evidence is incomplete.","FINAL_CANONICAL_EVIDENCE_MISSING":"No canonical evidence-authority record exists for this requirement.","FINAL_CANONICAL_EVIDENCE_INSUFFICIENT":"Canonical evidence is not materially sufficient for compliance.","FINAL_CANONICAL_EVIDENCE_NOT_COMPARABLE":"Canonical evidence is not comparable or usable for this requirement identity.","FINAL_CANONICAL_EVIDENCE_BASIS_MISSING":"Canonical evidence lacks an authoritative positive evaluation basis.","FINAL_CANONICAL_EVIDENCE_REVIEW":"Canonical evidence or identity usability requires review."}.get(code,code)
 @classmethod
 def get_summary(cls,report,tech,scoped):
  rc=Counter(x.final_decision.value for x in report.results);gc=Counter(x.group_decision.value for x in report.group_decisions);cc=Counter(x.decision.value for x in report.clause_decisions);applicable=[x for x in report.results if x.applicability_decision=="APPLICABLE"];tc=Counter(cls._enum(cls._get(x,"decision")) for xs in tech.values() for x in xs)
  return {"requirement_level":{"total":len(report.results),**{x.value:rc[x.value] for x in FinalRequirementDecision}},"group_level":{"total":len(report.group_decisions),**{x.value:gc[x.value] for x in FinalRequirementDecision}},"clause_level":{"total":len(report.clause_decisions),**{x.value:cc[x.value] for x in FinalRequirementDecision}},"applicable_report_evidence":{"PASS":sum("PASS" in x.report_verdicts for x in applicable),"FAIL":sum("FAIL" in x.report_verdicts for x in applicable),"NA":sum("NA" in x.report_verdicts for x in applicable),"NO_EVIDENCE":sum(not x.report_verdicts for x in applicable)},"requirements_with_technical_constraints":sum(bool(x.technical_constraint_decisions) for x in report.results),"technical_constraint_decisions":dict(sorted(tc.items())),"zero_inflation":{"atomic_NON_COMPLIANT":rc["NON_COMPLIANT"],"logical_group_NON_COMPLIANT":gc["NON_COMPLIANT"],"unique_clause_NON_COMPLIANT":cc["NON_COMPLIANT"],"atomic_NEEDS_REVIEW":rc["NEEDS_REVIEW"],"logical_group_NEEDS_REVIEW":gc["NEEDS_REVIEW"],"unique_clause_NEEDS_REVIEW":cc["NEEDS_REVIEW"]}}
 @classmethod
 def _requirements(cls,kb):
  def walk(items):
   for c in items:
    yield from cls._get(c,"requirements",[]) or [];yield from walk(cls._get(c,"children",[]) or [])
  yield from walk(cls._get(kb,"clauses",[]) or [])
  for a in cls._get(kb,"annexes",[]) or []:yield from cls._get(a,"requirements",[]) or []
 @classmethod
 def _evidence(cls,report):
  def walk(items):
   for c in items:yield from cls._get(c,"evidence_items",[]) or [];yield from walk(cls._get(c,"children",[]) or [])
  yield from walk(cls._get(report,"clauses",[]) or [])
 @staticmethod
 def _natural(v):return tuple(int(x) if x.isdigit() else x for x in re.split(r"(\d+)",v or ""))
 @staticmethod
 def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
 @staticmethod
 def _enum(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
 def get_diagnostics(self):return copy.deepcopy(self._diagnostics)
 @classmethod
 def to_dict(cls,v):return cls._safe(asdict(v)) if is_dataclass(v) else (_ for _ in ()).throw(TypeError("final decision model required"))
 @classmethod
 def _safe(cls,v):
  if isinstance(v,Enum):return v.value
  if isinstance(v,dict):return {k:cls._safe(x) for k,x in v.items()}
  if isinstance(v,list):return [cls._safe(x) for x in v]
  return v
 @classmethod
 def to_json(cls,v,indent=2):return json.dumps(cls.to_dict(v),ensure_ascii=False,sort_keys=True,indent=indent)
 @classmethod
 def save_json(cls,v,p):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(cls.to_json(v)+"\n",encoding="utf-8");return p
__all__=["DecisionBasis","EvidenceSufficiency","FinalClauseDecision","FinalRequirementDecision","FinalRequirementDecisionReport","FinalRequirementDecisionResult","FinalRequirementGroupDecision","GenericFinalRequirementDecisionEngine","STRICT_EVIDENCE_POLICY"]
