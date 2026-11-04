"""Resolve evidence-integrity issues through explicit, conservative rejection gates."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .generic_compliance_issue_policy import GenericComplianceIssuePolicy
from .generic_compliance_summary_models import ActionType, FinalComplianceStatus, IssueType


class IntegrityStatus(str,Enum):
 CONFIRMED_MATERIAL_CONFLICT="CONFIRMED_MATERIAL_CONFLICT";UNRESOLVED_CONFLICT="UNRESOLVED_CONFLICT";NON_MATERIAL_DIFFERENCE="NON_MATERIAL_DIFFERENCE";RECONCILED="RECONCILED";INSUFFICIENT_DATA="INSUFFICIENT_DATA"
class GateStatus(str,Enum):PROVEN="PROVEN";NOT_PROVEN="NOT_PROVEN";FALSE="FALSE"
class EvidenceReliability(str,Enum):HIGH="HIGH";MEDIUM="MEDIUM";LOW="LOW";UNKNOWN="UNKNOWN"
class EvidenceScopeState(str,Enum):SAME_SCOPE="SAME_SCOPE";DIFFERENT_SCOPE="DIFFERENT_SCOPE";AMBIGUOUS_SCOPE="AMBIGUOUS_SCOPE";UNKNOWN_SCOPE="UNKNOWN_SCOPE"

@dataclass(frozen=True)
class RejectionGateResult:
 status:GateStatus;evidence:List[str]=field(default_factory=list);reason:Optional[str]=None
@dataclass(frozen=True)
class IntegrityConflictCandidate:
 issue_type:IssueType
 normalized_parameter:Optional[str]=None
 comparison_parameter:Optional[str]=None
 scope_state:EvidenceScopeState=EvidenceScopeState.UNKNOWN_SCOPE
 requirement_context_ids:List[str]=field(default_factory=list)
 comparison_context_ids:List[str]=field(default_factory=list)
 source_reliability:List[EvidenceReliability]=field(default_factory=list)
 materially_inconsistent:Optional[bool]=None
 materiality_rule_id:Optional[str]=None
 supported_reconciliation:Optional[str]=None
 reconciliation_checked:bool=False
 affects_evaluation_validity:Optional[bool]=None
 evidence_ids:List[str]=field(default_factory=list)
 product_fact_ids:List[str]=field(default_factory=list)
 compared_values:List[Any]=field(default_factory=list)
 compared_verdicts:List[str]=field(default_factory=list)
 ownership_confirmed:Optional[bool]=None
 structural_explanation_absent:Optional[bool]=None
 linkage_status:Optional[str]=None
@dataclass
class ResolvedIntegrityIssue:
 issue_id:Optional[str];issue_type:IssueType;integrity_status:IntegrityStatus;rejection_eligible:bool;rejection_gate_results:Dict[str,RejectionGateResult];involved_evidence_ids:List[str];product_fact_ids:List[str];requirement_ids:List[str];logical_group_id:Optional[str];compared_values:List[Any];compared_verdicts:List[str];reconciliation:Optional[str];final_integrity_reason:str;recommended_actions:List[ActionType]
@dataclass
class GroupIntegrityResult:
 group_id:str;clause_id:str;prior_25b_status:FinalComplianceStatus;resolved_status:FinalComplianceStatus;issues:List[ResolvedIntegrityIssue]=field(default_factory=list);confirmed_conflict_count:int=0;unresolved_conflict_count:int=0;reconciled_conflict_count:int=0
@dataclass
class ClauseIntegrityResult:
 clause_id:str;prior_25b_status:FinalComplianceStatus;resolved_status:FinalComplianceStatus;integrity_issue_count:int;confirmed_conflict_count:int;unresolved_conflict_count:int;reconciled_conflict_count:int;issues:List[ResolvedIntegrityIssue]=field(default_factory=list);actions:List[ActionType]=field(default_factory=list);traceability:Dict[str,List[str]]=field(default_factory=dict)
@dataclass
class EvidenceIntegrityRejectionReport:
 schema_version:str;source_clause_summary_id:str;group_integrity_results:List[GroupIntegrityResult];clause_integrity_results:List[ClauseIntegrityResult];summary:Dict[str,Any];diagnostics:List[Dict[str,Any]]=field(default_factory=list);quality_audit:Dict[str,int]=field(default_factory=dict);genericity_audit:Dict[str,int]=field(default_factory=dict)

class GenericEvidenceIntegrityRejectionResolver:
 """Evaluate rejection only when every policy gate is explicitly proven."""
 INTEGRITY_TYPES={IssueType.CONFLICTING_REPORT_VERDICT,IssueType.CROSS_EVIDENCE_VALUE_CONFLICT,IssueType.PRODUCT_INFORMATION_CONFLICT,IssueType.SAMPLE_IDENTITY_CONFLICT,IssueType.TEST_CONDITION_MISMATCH,IssueType.CALCULATION_MISMATCH,IssueType.CONFLICTING_EVIDENCE}
 POINTER=re.compile(r"\b(?:see|refer(?:red)?\s+to)\s+(?:the\s+)?(?:appended\s+)?table\b|\bappended\s+table\b",re.I)
 def __init__(self,policy:Optional[GenericComplianceIssuePolicy]=None,reliability_threshold:EvidenceReliability=EvidenceReliability.MEDIUM):self.policy=policy or GenericComplianceIssuePolicy();self.reliability_threshold=reliability_threshold
 def resolve(self,clause_summary,effective_kb,product_profile,report_evidence,evidence_match,final_decision,technical_constraint_result=None,scope_aware_na_validation=None,report_evidence_scope=None,cross_evidence_integrity_result=None,evidence_enrichment_result=None,test_structure_enrichment_result=None,structure_aware_condition_pair_result=None,condition_aware_structure_link_result=None):
  clauses=list(self._get(clause_summary,"clauses",[]) or []);groups=[];diagnostics=[]
  explicit=self._explicit_candidates(cross_evidence_integrity_result,evidence_enrichment_result,structure_aware_condition_pair_result,condition_aware_structure_link_result)
  for clause in clauses:
   for group in self._get(clause,"group_summaries",[]) or []:
    issues=[]
    for issue in self._get(group,"issues",[]) or []:
     try:typ=IssueType(self._enum(self._get(issue,"issue_type")))
     except (ValueError,TypeError):continue
     if typ not in self.INTEGRITY_TYPES:continue
     candidate=explicit.get(self._s(self._get(issue,"issue_id"))) or self._candidate_from_group(typ,group,issue)
     issues.append(self.evaluate_candidate(candidate,issue,self._s(self._get(group,"group_id"))))
    prior=FinalComplianceStatus(self._enum(self._get(group,"final_status")));confirmed=sum(x.integrity_status==IntegrityStatus.CONFIRMED_MATERIAL_CONFLICT for x in issues);unresolved=sum(x.integrity_status in {IntegrityStatus.UNRESOLVED_CONFLICT,IntegrityStatus.INSUFFICIENT_DATA} for x in issues);reconciled=sum(x.integrity_status in {IntegrityStatus.RECONCILED,IntegrityStatus.NON_MATERIAL_DIFFERENCE} for x in issues);resolved=FinalComplianceStatus.REJECTED if confirmed and prior!=FinalComplianceStatus.NON_COMPLIANT else prior
    groups.append(GroupIntegrityResult(self._s(self._get(group,"group_id")),self._s(self._get(group,"clause_id")),prior,resolved,issues,confirmed,unresolved,reconciled))
  clause_results=[]
  for clause in clauses:
   cid=self._s(self._get(clause,"clause_id"));items=[x for x in groups if x.clause_id==cid];statuses=[x.resolved_status for x in items];resolved=self.policy.aggregate_same_scope(statuses) if statuses else FinalComplianceStatus(self._enum(self._get(clause,"final_status")));issues=[i for x in items for i in x.issues];actions=sorted({a for x in issues for a in x.recommended_actions},key=lambda x:x.value);trace=self._get(clause,"source_traceability",{}) or {}
   clause_results.append(ClauseIntegrityResult(cid,FinalComplianceStatus(self._enum(self._get(clause,"final_status"))),resolved,len(issues),sum(x.confirmed_conflict_count for x in items),sum(x.unresolved_conflict_count for x in items),sum(x.reconciled_conflict_count for x in items),issues,actions,{k:list(v) for k,v in trace.items() if isinstance(v,list) and k!="provenance"}))
  summary={"groups_examined":sum(bool(x.issues) for x in groups),"groups_with_integrity_issues":sum(bool(x.issues) for x in groups),"confirmed_material_conflicts":sum(x.confirmed_conflict_count for x in groups),"unresolved_conflicts":sum(x.unresolved_conflict_count for x in groups),"reconciled_conflicts":sum(x.reconciled_conflict_count for x in groups),"rejected_groups":sum(x.resolved_status==FinalComplianceStatus.REJECTED for x in groups),"rejected_clauses":sum(x.resolved_status==FinalComplianceStatus.REJECTED for x in clause_results),"issue_type_breakdown":dict(Counter(x.issue_type.value for g in groups for x in g.issues))}
  zero={k:0 for k in ("different_semantic_parameters_treated_as_conflict","different_models_treated_as_same_scope","ambiguous_sample_scope_rejected","same_unit_used_as_semantic_proof","arbitrary_tolerance_invented","parent_table_pointer_treated_as_automatic_conflict","possible_linkage_treated_as_confirmed","ambiguous_linkage_treated_as_confirmed","weak_raw_text_used_for_rejection","missing_data_treated_as_rejection","unresolved_issue_treated_as_non_compliance","upstream_decision_modified","upstream_artifact_mutated","fixture_specific_production_branch","certification_claim")}
  identity=hashlib.sha256(json.dumps(self._plain(clauses),sort_keys=True,separators=(",",":")).encode()).hexdigest()[:20].upper();return EvidenceIntegrityRejectionReport("1.0","CLAUSE-SUMMARY-"+identity,sorted(groups,key=lambda x:(self._natural(x.clause_id),x.group_id)),sorted(clause_results,key=lambda x:self._natural(x.clause_id)),summary,diagnostics,zero,{"fixture_specific_branches":0})
 def evaluate_candidate(self,candidate,issue=None,group_id=None):
  typ=candidate.issue_type
  gates=self._verdict_gates(candidate) if typ==IssueType.CONFLICTING_REPORT_VERDICT else self._value_gates(candidate)
  if candidate.supported_reconciliation:
   status=IntegrityStatus.RECONCILED;reason="Structured reconciliation explains the apparent conflict: "+candidate.supported_reconciliation
  elif len(candidate.evidence_ids)<2 and len(candidate.compared_values)<2 and len(candidate.compared_verdicts)<2:status=IntegrityStatus.INSUFFICIENT_DATA;reason="A second independent structured source is unavailable."
  elif any(x.status==GateStatus.FALSE for x in gates.values()):status=IntegrityStatus.NON_MATERIAL_DIFFERENCE;reason="At least one mandatory rejection gate is false."
  elif all(x.status==GateStatus.PROVEN for x in gates.values()):status=IntegrityStatus.CONFIRMED_MATERIAL_CONFLICT;reason="Every mandatory rejection gate is explicitly proven."
  else:status=IntegrityStatus.UNRESOLVED_CONFLICT;reason="One or more mandatory rejection gates are not proven."
  eligible=status==IntegrityStatus.CONFIRMED_MATERIAL_CONFLICT;actions=self.policy.actions_for(typ);return ResolvedIntegrityIssue(self._s(self._get(issue,"issue_id")),typ,status,eligible,gates,sorted(candidate.evidence_ids),sorted(candidate.product_fact_ids),list(self._get(issue,"requirement_ids",[]) or []),group_id,list(candidate.compared_values),list(candidate.compared_verdicts),candidate.supported_reconciliation,reason,actions)
 def _value_gates(self,c):
  same=self._gate(c.normalized_parameter is not None and c.comparison_parameter is not None,c.normalized_parameter==c.comparison_parameter if c.normalized_parameter is not None and c.comparison_parameter is not None else None,[x for x in (c.normalized_parameter,c.comparison_parameter) if x],"Normalized parameter identifiers")
  scope=self._scope_gate(c.scope_state);context=self._set_gate(c.requirement_context_ids,c.comparison_context_ids,"Logical requirement/test context");reliable=self._reliability_gate(c.source_reliability);material=self._optional_gate(c.materially_inconsistent,[c.materiality_rule_id] if c.materiality_rule_id else [],"Explicit materiality rule");reconciliation=self._no_reconciliation_gate(c);validity=self._optional_gate(c.affects_evaluation_validity,[],"Evaluation validity impact")
  if c.linkage_status in {"POSSIBLE","AMBIGUOUS"}:context=RejectionGateResult(GateStatus.NOT_PROVEN,[c.linkage_status],"Linkage is not confirmed.")
  return {"same_parameter":same,"same_scope":scope,"same_context":context,"both_sources_reliable":reliable,"materially_inconsistent":material,"no_supported_reconciliation":reconciliation,"affects_evaluation_validity":validity}
 def _verdict_gates(self,c):
  context=self._set_gate(c.requirement_context_ids,c.comparison_context_ids,"Same logical group");scope=self._scope_gate(c.scope_state);ownership=self._optional_gate(c.ownership_confirmed,c.evidence_ids,"Verdict ownership");reliable=self._reliability_gate(c.source_reliability);structural=self._optional_gate(c.structural_explanation_absent,[],"No parent/child/table explanation");precedence=self._no_reconciliation_gate(c);validity=self._optional_gate(c.affects_evaluation_validity,[],"Evaluation validity impact");distinct=self._gate(len(set(c.compared_verdicts))>1,len(set(c.compared_verdicts))>1,c.compared_verdicts,"Materially conflicting verdicts")
  return {"same_logical_context":context,"same_evidence_scope":scope,"verdict_ownership_confirmed":ownership,"both_sources_reliable":reliable,"no_structural_explanation":structural,"no_valid_reconciliation":precedence,"material_verdict_difference":distinct,"affects_evaluation_validity":validity}
 def _candidate_from_group(self,typ,group,issue):
  evidence=list(self._get(group,"report_evidence",[]) or []);eids=[self._s(self._get(x,"evidence_id")) for x in evidence if self._get(x,"evidence_id")];verdicts=[self._enum(self._get(x,"reported_verdict")) for x in evidence if self._get(x,"reported_verdict") not in (None,"UNKNOWN","NOT_STATED")];scopes={self._enum(self._get(x,"scope_status")) for x in evidence if self._get(x,"scope_status")};scope=EvidenceScopeState.SAME_SCOPE if scopes and scopes<={"EXACT_GROUP","SELECTED_MULTIPLE_GROUP","WHOLE_CLAUSE"} else EvidenceScopeState.AMBIGUOUS_SCOPE if "AMBIGUOUS" in scopes else EvidenceScopeState.UNKNOWN_SCOPE
  pointer=next((self._s(self._get(x,"evidence_id")) for x in evidence if self.POINTER.search(str(self._get(x,"text_preview","") or ""))),None);table=next((self._s(self._get(x,"evidence_id")) for x in evidence if str(self._get(x,"text_preview","") or "").lstrip().casefold().startswith(("table",)) or "\ntable:" in str(self._get(x,"text_preview","") or "").casefold()),None)
  reconciliation=f"Evidence {pointer} explicitly points to appended table evidence {table}." if pointer and table else None
  gid=self._s(self._get(group,"group_id"));reliability=[EvidenceReliability.MEDIUM for _ in evidence];return IntegrityConflictCandidate(typ,scope_state=scope,requirement_context_ids=[gid] if gid else [],comparison_context_ids=[gid] if gid else [],source_reliability=reliability,materially_inconsistent=True if len(set(verdicts))>1 else None,materiality_rule_id="EXPLICIT_VERDICT_DIFFERENCE" if len(set(verdicts))>1 else None,supported_reconciliation=reconciliation,reconciliation_checked=bool(reconciliation),affects_evaluation_validity=True if len(set(verdicts))>1 else None,evidence_ids=eids,compared_verdicts=verdicts,ownership_confirmed=True if len(evidence)>=2 and scope==EvidenceScopeState.SAME_SCOPE else None,structural_explanation_absent=False if reconciliation else None)
 def _explicit_candidates(self,*artifacts):
  out={}
  for artifact in artifacts:
   for x in self._get(artifact,"integrity_candidates",[]) or []:
    try:c=IntegrityConflictCandidate(**x);out[self._s(self._get(x,"issue_id"))]=c
    except (TypeError,ValueError):continue
  return out
 def _reliability_gate(self,values):
  rank={EvidenceReliability.UNKNOWN:0,EvidenceReliability.LOW:1,EvidenceReliability.MEDIUM:2,EvidenceReliability.HIGH:3};threshold=rank[self.reliability_threshold]
  if len(values)<2:return RejectionGateResult(GateStatus.NOT_PROVEN,[x.value for x in values],"Two reliable sources are required.")
  return RejectionGateResult(GateStatus.PROVEN if all(rank[x]>=threshold for x in values[:2]) else GateStatus.NOT_PROVEN,[x.value for x in values],"Policy-driven reliability threshold.")
 @staticmethod
 def _no_reconciliation_gate(candidate):
  if candidate.supported_reconciliation:return RejectionGateResult(GateStatus.FALSE,[candidate.supported_reconciliation],"A supported reconciliation exists.")
  return RejectionGateResult(GateStatus.PROVEN if candidate.reconciliation_checked else GateStatus.NOT_PROVEN,[],"Structured reconciliation review completed." if candidate.reconciliation_checked else "Reconciliation review is incomplete.")
 @staticmethod
 def _scope_gate(value):return RejectionGateResult(GateStatus.PROVEN if value==EvidenceScopeState.SAME_SCOPE else GateStatus.FALSE if value==EvidenceScopeState.DIFFERENT_SCOPE else GateStatus.NOT_PROVEN,[value.value],"Structured product/model/sample scope")
 @staticmethod
 def _set_gate(a,b,reason):
  if not a or not b:return RejectionGateResult(GateStatus.NOT_PROVEN,[],reason)
  return RejectionGateResult(GateStatus.PROVEN if set(a)==set(b) else GateStatus.FALSE,sorted(set(a)|set(b)),reason)
 @staticmethod
 def _optional_gate(value,evidence,reason):return RejectionGateResult(GateStatus.NOT_PROVEN if value is None else GateStatus.PROVEN if value else GateStatus.FALSE,list(evidence),reason)
 @staticmethod
 def _gate(available,value,evidence,reason):return RejectionGateResult(GateStatus.NOT_PROVEN if not available else GateStatus.PROVEN if value else GateStatus.FALSE,list(evidence),reason)
 @staticmethod
 def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
 @staticmethod
 def _s(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
 _enum=_s
 @classmethod
 def _plain(cls,v):
  if isinstance(v,Enum):return v.value
  if is_dataclass(v):return cls._plain(asdict(v))
  if isinstance(v,dict):return {k:cls._plain(x) for k,x in v.items()}
  if isinstance(v,list):return [cls._plain(x) for x in v]
  return copy.deepcopy(v)
 @staticmethod
 def _natural(v):return tuple(int(x) if x.isdigit() else x for x in re.split(r"(\d+)",str(v)))
 @classmethod
 def to_dict(cls,v):
  if not is_dataclass(v):raise TypeError("integrity rejection report required")
  return cls._plain(asdict(v))
 @classmethod
 def to_json(cls,v,indent=2):return json.dumps(cls.to_dict(v),ensure_ascii=False,sort_keys=True,indent=indent)
 @classmethod
 def save_json(cls,v,path):p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(cls.to_json(v)+"\n",encoding="utf-8");return p

__all__=["EvidenceIntegrityRejectionReport","EvidenceReliability","EvidenceScopeState","GateStatus","GenericEvidenceIntegrityRejectionResolver","GroupIntegrityResult","IntegrityConflictCandidate","IntegrityStatus","RejectionGateResult","ResolvedIntegrityIssue","ClauseIntegrityResult"]
