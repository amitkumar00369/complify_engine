"""Validate report N/A using resolved evidence scope and group applicability."""
from __future__ import annotations
import copy,json
from collections import Counter,defaultdict
from dataclasses import asdict,dataclass,field,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Dict,List,Mapping,Optional,Sequence,Set

class ScopeAwareNAStatus(str,Enum):
 JUSTIFIED="JUSTIFIED";POTENTIAL_CONFLICT="POTENTIAL_CONFLICT";INSUFFICIENT_PRODUCT_DATA="INSUFFICIENT_PRODUCT_DATA";INSUFFICIENT_KB_RULE="INSUFFICIENT_KB_RULE";INSUFFICIENT_REPORT_EVIDENCE="INSUFFICIENT_REPORT_EVIDENCE";NEEDS_REVIEW="NEEDS_REVIEW";NOT_REPORTED_NA="NOT_REPORTED_NA";INACTIVE="INACTIVE"
@dataclass
class ScopeAwareNAMemberResult:
 effective_requirement_id:str;effective_clause_id:Optional[str];clause_id:Optional[str];group_id:Optional[str];effective_status:Optional[str];original_step15_decision:Optional[str];group_aware_applicability:Optional[str];reported_na:bool;scope_status:Optional[str];scope_evidence_ids:List[str]=field(default_factory=list);status:ScopeAwareNAStatus=ScopeAwareNAStatus.NOT_REPORTED_NA;reason_code:str="";reason:str="";missing_features:List[str]=field(default_factory=list);product_fact_ids:List[str]=field(default_factory=list);notes:Optional[str]=None
@dataclass
class ScopeAwareNAGroupResult:
 group_id:str;effective_clause_id:Optional[str];clause_id:Optional[str];primary_requirement_id:Optional[str];member_requirement_ids:List[str]=field(default_factory=list);group_applicability:Optional[str]=None;report_evidence_ids:List[str]=field(default_factory=list);report_clause_ids:List[str]=field(default_factory=list);scope_status:Optional[str]=None;status:ScopeAwareNAStatus=ScopeAwareNAStatus.NOT_REPORTED_NA;reason_code:str="";reason:str="";member_results:List[ScopeAwareNAMemberResult]=field(default_factory=list);diagnostics:List[Dict[str,Any]]=field(default_factory=list)
@dataclass
class ScopeAwareNAClauseSummary:
 clause_id:str;na_evidence_items:int;logical_groups_total:int;logical_groups_receiving_na:int;justified_groups:int=0;potential_conflict_groups:int=0;insufficient_product_data_groups:int=0;insufficient_kb_rule_groups:int=0;insufficient_report_evidence_groups:int=0;needs_review_groups:int=0;inactive_groups:int=0;overall_status:Optional[str]=None
@dataclass
class ScopeAwareNAValidationReport:
 effective_kb_id:str;profile_id:str;report_document_id:str;member_results:List[ScopeAwareNAMemberResult]=field(default_factory=list);group_results:List[ScopeAwareNAGroupResult]=field(default_factory=list);clause_summaries:List[ScopeAwareNAClauseSummary]=field(default_factory=list);summary:Dict[str,Any]=field(default_factory=dict);diagnostics:List[Dict[str,Any]]=field(default_factory=list)

class GenericScopeAwareNAValidator:
 SELECTING={"EXACT_GROUP","MULTIPLE_GROUPS","WHOLE_CLAUSE","PARENT_SCOPE","CHILD_SCOPE"};AMBIGUOUS={"AMBIGUOUS","UNRESOLVED"}
 def __init__(self):self._diagnostics=[]
 def validate(self,effective_kb,product_profile,group_aware_applicability,grouping_report,report_evidence,evidence_match_report,evidence_scope_report,original_na_report=None,conflict_audit_report=None,group_aware_na_report=None):
  self._diagnostics=[];apps={str(self._get(x,"effective_requirement_id")):x for x in self._get(group_aware_applicability,"results",[]) or []};groups={str(self._get(g,"group_id")):g for g in self._get(grouping_report,"groups",[]) or []};req_status=self._requirement_status(effective_kb);facts={str(self._get(f,"feature_id")):f for f in self._get(product_profile,"facts",[]) or []};evmap={str(self._get(e,"evidence_id")):e for e in self._evidence(report_evidence)}
  assignments=defaultdict(list);ambiguous=defaultdict(list);na_items=[]
  for scope in self._get(evidence_scope_report,"results",[]) or []:
   eid=str(self._get(scope,"report_evidence_id"));verdict=self._enum(self._get(scope,"reported_verdict"));status=self._enum(self._get(scope,"scope_status"))
   if verdict=="NA":na_items.append(scope)
   if status in self.SELECTING:
    for ref in self._get(scope,"selected_groups",[]) or []:assignments[str(self._get(ref,"group_id"))].append(scope)
   elif verdict=="NA" and status in self.AMBIGUOUS:
    for ref in self._get(scope,"candidate_groups",[]) or []:ambiguous[str(self._get(ref,"group_id"))].append(scope)
   elif verdict=="NA" and status=="NO_RELEVANT_GROUP":
    self._diagnostics.append({"code":"NA_EVIDENCE_NO_RELEVANT_GROUP","evidence_id":eid,"clause_id":self._get(scope,"report_clause_id")})
    self._diagnostics.append({"code":"NA_REPORT_EVIDENCE_WITHOUT_EFFECTIVE_GROUP","evidence_id":eid,"clause_id":self._get(scope,"report_clause_id")})
  results=[];global_members=[]
  target_gids=sorted({gid for gid,items in assignments.items() if any(self._enum(self._get(x,"reported_verdict"))=="NA" for x in items)}|set(ambiguous))
  for gid in target_gids:
   if gid not in groups:continue
   gr=self._group_result(groups[gid],apps,req_status,facts,assignments.get(gid,[]),ambiguous.get(gid,[]));results.append(gr);global_members.extend(gr.member_results)
  clause_summaries=self._clause_summaries(results,groups,na_items);report=ScopeAwareNAValidationReport(str(self._get(effective_kb,"effective_kb_id","")),str(self._get(product_profile,"profile_id","")),str(self._get(report_evidence,"document_id","")),global_members,results,clause_summaries,diagnostics=copy.deepcopy(self._diagnostics));report.summary=self.get_summary(report,na_items,original_na_report,group_aware_na_report,evidence_scope_report);return report
 def _group_result(self,g,apps,req_status,facts,scoped,ambiguous):
  gid=str(self._get(g,"group_id"));members=list(self._get(g,"members",[]) or []);rids=[str(self._get(m,"effective_requirement_id")) for m in members];primary=str(self._get(g,"primary_requirement_id") or "");app=apps.get(primary,{});decision=self._enum(self._get(app,"resolved_decision"));all_scope=list(scoped)+list(ambiguous);na_scopes=[x for x in all_scope if self._enum(self._get(x,"reported_verdict"))=="NA"];verdicts={self._enum(self._get(x,"reported_verdict")) for x in scoped if self._enum(self._get(x,"reported_verdict")) not in {None,"NOT_STATED"}};diagnostics=[]
  if ambiguous:status=ScopeAwareNAStatus.INSUFFICIENT_REPORT_EVIDENCE;code="NA_SCOPE_AMBIGUOUS";diagnostics.append({"code":"NA_SCOPE_AMBIGUOUS","evidence_ids":sorted({str(self._get(x,"report_evidence_id")) for x in ambiguous})})
  elif len(verdicts)>1 and "NA" in verdicts:status=ScopeAwareNAStatus.NEEDS_REVIEW;code="NA_CONFLICTING_REPORT_VERDICTS";diagnostics.append({"code":code,"verdicts":sorted(verdicts)})
  elif not na_scopes:status=ScopeAwareNAStatus.NOT_REPORTED_NA;code="NA_NOT_REPORTED"
  elif req_status.get(primary)=="INACTIVE" or decision=="INACTIVE":status=ScopeAwareNAStatus.INACTIVE;code="NA_GROUP_INACTIVE"
  elif self._circular(app,facts):status=ScopeAwareNAStatus.INSUFFICIENT_PRODUCT_DATA;code="NA_CIRCULAR_INFERRED_FROM_NA";diagnostics.append({"code":code})
  else:status,code=self._app_status(decision,app)
  scope_values=sorted({self._enum(self._get(x,"scope_status")) for x in all_scope});scope_status=scope_values[0] if len(scope_values)==1 else "MULTIPLE_SCOPE_RESULTS"
  eids=sorted({str(self._get(x,"report_evidence_id")) for x in na_scopes});clauses=sorted({str(self._get(x,"report_clause_id")) for x in na_scopes});member_results=[]
  for rid in rids:
   ma=apps.get(rid,{});member_results.append(ScopeAwareNAMemberResult(rid,self._get(ma,"effective_clause_id"),self._get(ma,"clause_id"),gid,req_status.get(rid),self._get(ma,"original_decision"),self._enum(self._get(ma,"resolved_decision")),bool(na_scopes),scope_status,eids,status,code,self._reason(status),[],sorted(self._get(ma,"product_fact_ids",[]) or []),"Group-level result projected for traceability."))
  for d in diagnostics:self._diagnostics.append(dict(d,group_id=gid))
  return ScopeAwareNAGroupResult(gid,self._get(g,"effective_clause_id"),self._get(g,"clause_id"),primary,rids,decision,eids,clauses,scope_status,status,code,self._reason(status),member_results,diagnostics)
 @classmethod
 def _app_status(cls,decision,app):
  if decision=="NOT_APPLICABLE":return ScopeAwareNAStatus.JUSTIFIED,"NA_JUSTIFIED_BY_GROUP_SCOPE"
  if decision=="APPLICABLE":return ScopeAwareNAStatus.POTENTIAL_CONFLICT,"NA_CONFLICT_WITH_GROUP_APPLICABILITY"
  if decision=="INACTIVE":return ScopeAwareNAStatus.INACTIVE,"NA_GROUP_INACTIVE"
  if decision=="UNKNOWN":
   kb=cls._enum(cls._get(app,"original_applicability_status"));return (ScopeAwareNAStatus.INSUFFICIENT_KB_RULE,"NA_KB_RULE_UNRESOLVED") if kb in {"UNRESOLVED","NEEDS_REVIEW"} else (ScopeAwareNAStatus.INSUFFICIENT_PRODUCT_DATA,"NA_PRODUCT_DATA_INSUFFICIENT")
  return ScopeAwareNAStatus.NEEDS_REVIEW,"NA_GROUP_APPLICABILITY_REVIEW"
 @classmethod
 def _circular(cls,app,facts):return any(cls._enum(cls._get(facts.get(str(fid)),"status"))=="INFERRED_FROM_NA" for fid in cls._get(app,"product_fact_ids",[]) or [])
 @staticmethod
 def _reason(status):return {ScopeAwareNAStatus.JUSTIFIED:"Resolved logical group is not applicable.",ScopeAwareNAStatus.POTENTIAL_CONFLICT:"Resolved logical group is applicable while scoped report evidence states N/A.",ScopeAwareNAStatus.INSUFFICIENT_PRODUCT_DATA:"Product facts are insufficient or circular.",ScopeAwareNAStatus.INSUFFICIENT_KB_RULE:"KB applicability semantics are insufficient.",ScopeAwareNAStatus.INSUFFICIENT_REPORT_EVIDENCE:"Report evidence scope remains ambiguous.",ScopeAwareNAStatus.NEEDS_REVIEW:"Conflicting verdicts or group applicability require review.",ScopeAwareNAStatus.NOT_REPORTED_NA:"No scoped N/A evidence applies to this group.",ScopeAwareNAStatus.INACTIVE:"The effective group is inactive."}[status]
 @classmethod
 def _clause_summaries(cls,results,groups,na_items):
  grouped=defaultdict(list)
  for x in results:grouped[str(x.clause_id)].append(x)
  totals=Counter(str(cls._get(g,"clause_id")) for g in groups.values());evc=Counter(str(cls._get(x,"report_clause_id")) for x in na_items);out=[];priority=["POTENTIAL_CONFLICT","NEEDS_REVIEW","INSUFFICIENT_REPORT_EVIDENCE","INSUFFICIENT_KB_RULE","INSUFFICIENT_PRODUCT_DATA","JUSTIFIED","INACTIVE"]
  for cid,items in sorted(grouped.items()):
   c=Counter(x.status.value for x in items);overall=next((x for x in priority if c[x]),None);out.append(ScopeAwareNAClauseSummary(cid,evc[cid],totals[cid],len(items),c["JUSTIFIED"],c["POTENTIAL_CONFLICT"],c["INSUFFICIENT_PRODUCT_DATA"],c["INSUFFICIENT_KB_RULE"],c["INSUFFICIENT_REPORT_EVIDENCE"],c["NEEDS_REVIEW"],c["INACTIVE"],overall))
  return out
 @classmethod
 def get_summary(cls,report,na_items,original_na=None,group_na=None,scope_report=None):
  gc=Counter(x.status.value for x in report.group_results);mc=Counter(x.status.value for x in report.member_results);sc=Counter(cls._enum(cls._get(x,"scope_status")) for x in na_items);cc=Counter(x.overall_status for x in report.clause_summaries);unique_clauses={str(cls._get(x,"report_clause_id")) for x in na_items};orig=sum(cls._enum(cls._get(x,"status"))=="POTENTIAL_CONFLICT" for x in cls._get(original_na,"results",[]) or []);oldgs=cls._get(group_na,"summary",{}) or {};receiving=len(report.group_results);members=len(report.member_results)
  return {"report_evidence_level":{"total_na_evidence_items":len(na_items),**{x:sc[x] for x in ["EXACT_GROUP","MULTIPLE_GROUPS","WHOLE_CLAUSE","PARENT_SCOPE","CHILD_SCOPE","AMBIGUOUS","UNRESOLVED","NO_RELEVANT_GROUP"]}},"logical_group_level":{"groups_receiving_na":receiving,**{x.value:gc[x.value] for x in ScopeAwareNAStatus}},"requirement_member_level":{"members_associated_with_na":members,**{x.value:mc[x.value] for x in ScopeAwareNAStatus}},"unique_clause_level":{"unique_report_na_clauses":len(unique_clauses),**{x.value:cc[x.value] for x in ScopeAwareNAStatus}},"reconciliation":{"step19_requirement_potential_conflicts":orig,"step19c_requirement_potential_conflicts":cls._get(cls._get(oldgs,"requirement_level",{}),"POTENTIAL_CONFLICT",0),"step19c_logical_group_potential_conflicts":cls._get(cls._get(oldgs,"logical_group_level",{}),"POTENTIAL_CONFLICT",0),"step19e_member_potential_conflicts":mc["POTENTIAL_CONFLICT"],"step19e_logical_group_potential_conflicts":gc["POTENTIAL_CONFLICT"],"step19e_unique_clause_potential_conflicts":cc["POTENTIAL_CONFLICT"]},"scope_inflation":{"total_na_evidence_items":len(na_items),"logical_groups_receiving_na":receiving,"member_requirements_receiving_na":members,"average_groups_per_na_evidence":round(receiving/len(na_items),6) if na_items else 0.0,"average_atomic_members_per_na_group":round(members/receiving,6) if receiving else 0.0}}
 @classmethod
 def _requirement_status(cls,kb):
  out={}
  def walk(items):
   for c in items:
    for r in cls._get(c,"requirements",[]) or []:out[str(cls._get(r,"effective_requirement_id"))]=cls._enum(cls._get(r,"effective_status"))
    walk(cls._get(c,"children",[]) or [])
  walk(cls._get(kb,"clauses",[]) or []);return out
 @classmethod
 def _evidence(cls,report):
  def walk(items):
   for c in items:
    yield from cls._get(c,"evidence_items",[]) or [];yield from walk(cls._get(c,"children",[]) or [])
  yield from walk(cls._get(report,"clauses",[]) or [])
 @staticmethod
 def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
 @staticmethod
 def _enum(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
 def get_diagnostics(self):return copy.deepcopy(self._diagnostics)
 @classmethod
 def to_dict(cls,v):return cls._safe(asdict(v)) if is_dataclass(v) else (_ for _ in ()).throw(TypeError("scope-aware N/A model required"))
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
__all__=["GenericScopeAwareNAValidator","ScopeAwareNAClauseSummary","ScopeAwareNAGroupResult","ScopeAwareNAMemberResult","ScopeAwareNAStatus","ScopeAwareNAValidationReport"]
