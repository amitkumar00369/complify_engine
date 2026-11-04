"""Revalidate report N/A at logical requirement-group scope."""
from __future__ import annotations
import copy,json
from collections import Counter,defaultdict
from dataclasses import asdict,dataclass,field,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Dict,List,Mapping,Optional,Sequence,Set

class GroupAwareNAStatus(str,Enum):
 JUSTIFIED="JUSTIFIED";POTENTIAL_CONFLICT="POTENTIAL_CONFLICT";INSUFFICIENT_PRODUCT_DATA="INSUFFICIENT_PRODUCT_DATA";INSUFFICIENT_KB_RULE="INSUFFICIENT_KB_RULE";INSUFFICIENT_REPORT_EVIDENCE="INSUFFICIENT_REPORT_EVIDENCE";NEEDS_REVIEW="NEEDS_REVIEW";NOT_REPORTED_NA="NOT_REPORTED_NA";INACTIVE="INACTIVE"
@dataclass
class GroupAwareNAMemberResult:
 effective_requirement_id:str;original_step15_decision:Optional[str];group_aware_decision:Optional[str];scope_source:Optional[str];reported_na:bool;group_na_status:GroupAwareNAStatus;reason:str
@dataclass
class GroupAwareNAGroupResult:
 group_id:str;effective_clause_id:Optional[str];clause_id:Optional[str];primary_requirement_id:Optional[str];member_requirement_ids:List[str]=field(default_factory=list);report_evidence_ids:List[str]=field(default_factory=list);report_clause_ids:List[str]=field(default_factory=list);resolved_group_applicability:Optional[str]=None;status:GroupAwareNAStatus=GroupAwareNAStatus.NOT_REPORTED_NA;reason:str="";product_fact_ids:List[str]=field(default_factory=list);member_results:List[GroupAwareNAMemberResult]=field(default_factory=list);diagnostics:List[Dict[str,Any]]=field(default_factory=list)
@dataclass
class GroupAwareNAValidationReport:
 effective_kb_id:str;profile_id:str;report_document_id:str;group_results:List[GroupAwareNAGroupResult]=field(default_factory=list);member_results:List[GroupAwareNAMemberResult]=field(default_factory=list);summary:Dict[str,Any]=field(default_factory=dict);diagnostics:List[Dict[str,Any]]=field(default_factory=list)

class GenericGroupAwareNAValidator:
 STRONG={"EXACT_CLAUSE","EXACT_SUBCLAUSE","ANNEX_EXACT"};WEAK={"PARENT_CLAUSE","CHILD_CLAUSE","MULTIPLE_CANDIDATES","NEEDS_REVIEW"}
 def __init__(self):self._diagnostics=[]
 def validate(self,effective_kb,product_profile,group_aware_applicability,evidence_match_report,report_evidence,grouping_report,original_na_report=None):
  self._diagnostics=[];apps={str(self._get(x,"effective_requirement_id")):x for x in self._get(group_aware_applicability,"results",[]) or []};matches={str(self._get(x,"effective_requirement_id")):x for x in self._get(evidence_match_report,"matches",[]) or []};groups=self._get(grouping_report,"groups",[]) or []
  evidence_groups=defaultdict(set)
  for g in groups:
   gid=str(self._get(g,"group_id"))
   for m in self._get(g,"members",[]) or []:
    rid=str(self._get(m,"effective_requirement_id"))
    for ref in self._na_refs(matches.get(rid,{})):evidence_groups[str(self._get(ref,"evidence_id"))].add(gid)
  group_results=[];global_members=[];covered=set()
  for g in groups:
   gr=self.validate_group(g,apps,matches,evidence_groups);group_results.append(gr);global_members.extend(gr.member_results);covered.update(gr.member_requirement_ids)
  for rid,app in apps.items():
   if rid in covered:continue
   match=matches.get(rid,{});refs=self._na_refs(match);decision=self._enum(self._get(app,"resolved_decision"));status=self._status(decision,app,match,bool(refs),False);global_members.append(GroupAwareNAMemberResult(rid,self._get(app,"original_decision"),decision,self._enum(self._get(app,"resolution_source")),bool(refs),status,self._reason(status)))
  report=GroupAwareNAValidationReport(str(self._get(effective_kb,"effective_kb_id","")),str(self._get(product_profile,"profile_id","")),str(self._get(report_evidence,"document_id","")),group_results,global_members,diagnostics=copy.deepcopy(self._diagnostics));report.summary=self.get_summary(report,original_na_report);return report
 def validate_group(self,g,apps,matches,evidence_groups):
  gid=str(self._get(g,"group_id"));members=self._get(g,"members",[]) or [];rids=[str(self._get(m,"effective_requirement_id")) for m in members];refs=[];statuses=set();verdicts=set()
  for rid in rids:
   match=matches.get(rid,{});statuses.add(self._enum(self._get(match,"match_status")))
   for ref in self._get(match,"evidence_refs",[]) or []:
    verdicts.add(self._enum(self._get(ref,"reported_verdict")))
    if self._enum(self._get(ref,"reported_verdict"))=="NA":refs.append(ref)
  unique_refs={str(self._get(x,"evidence_id")):x for x in refs};ambiguous=any(len(evidence_groups[eid])>1 for eid in unique_refs);diagnostics=[]
  primary=str(self._get(g,"primary_requirement_id") or "");primary_app=apps.get(primary);decision=self._enum(self._get(primary_app,"resolved_decision")) if primary_app else None
  if not refs:status=GroupAwareNAStatus.NOT_REPORTED_NA
  elif len({x for x in verdicts if x not in {None,"NOT_STATED"}})>1:status=GroupAwareNAStatus.NEEDS_REVIEW;diagnostics.append({"code":"GROUP_NA_CONFLICTING_VERDICTS"})
  elif ambiguous:status=GroupAwareNAStatus.INSUFFICIENT_REPORT_EVIDENCE;diagnostics.append({"code":"GROUP_NA_REPORT_SCOPE_AMBIGUOUS"})
  elif any(x in self.WEAK for x in statuses) or not any(x in self.STRONG for x in statuses):status=GroupAwareNAStatus.INSUFFICIENT_REPORT_EVIDENCE;diagnostics.append({"code":"GROUP_NA_REPORT_SCOPE_AMBIGUOUS"})
  else:status=self._status(decision,primary_app,{},True,False)
  member_results=[]
  for m in members:
   rid=str(self._get(m,"effective_requirement_id"));app=apps.get(rid,{});reported=bool(self._na_refs(matches.get(rid,{})));member_status=status if reported else GroupAwareNAStatus.NOT_REPORTED_NA
   member_results.append(GroupAwareNAMemberResult(rid,self._get(app,"original_decision"),self._enum(self._get(app,"resolved_decision")),self._enum(self._get(app,"resolution_source")),reported,member_status,self._reason(member_status)))
  for d in diagnostics:self._diagnostics.append(dict(d,group_id=gid))
  return GroupAwareNAGroupResult(gid,self._get(g,"effective_clause_id"),self._get(g,"clause_id"),primary,rids,sorted(unique_refs),sorted({str(self._get(x,"report_clause_id")) for x in refs}),decision,status,self._reason(status),sorted({f for rid in rids for f in self._get(apps.get(rid,{}),"product_fact_ids",[]) or []}),member_results,diagnostics)
 @classmethod
 def _status(cls,decision,app,match,reported,ambiguous):
  if not reported:return GroupAwareNAStatus.NOT_REPORTED_NA
  if ambiguous:return GroupAwareNAStatus.INSUFFICIENT_REPORT_EVIDENCE
  if decision=="INACTIVE":return GroupAwareNAStatus.INACTIVE
  if decision=="NOT_APPLICABLE":return GroupAwareNAStatus.JUSTIFIED
  if decision=="APPLICABLE":return GroupAwareNAStatus.POTENTIAL_CONFLICT
  if decision=="NEEDS_REVIEW":return GroupAwareNAStatus.NEEDS_REVIEW
  status=cls._enum(cls._get(app,"original_applicability_status"));return GroupAwareNAStatus.INSUFFICIENT_KB_RULE if status in {"UNRESOLVED","NEEDS_REVIEW"} else GroupAwareNAStatus.INSUFFICIENT_PRODUCT_DATA
 @staticmethod
 def _reason(status):return {GroupAwareNAStatus.JUSTIFIED:"Logical group applicability is NOT_APPLICABLE.",GroupAwareNAStatus.POTENTIAL_CONFLICT:"Logical group applicability is APPLICABLE while report states N/A.",GroupAwareNAStatus.INSUFFICIENT_REPORT_EVIDENCE:"Report N/A scope does not distinguish independent logical groups.",GroupAwareNAStatus.NOT_REPORTED_NA:"No matched report N/A evidence.",GroupAwareNAStatus.INACTIVE:"Requirement is inactive.",GroupAwareNAStatus.INSUFFICIENT_PRODUCT_DATA:"Applicability remains unknown from product data.",GroupAwareNAStatus.INSUFFICIENT_KB_RULE:"KB applicability rule remains insufficient.",GroupAwareNAStatus.NEEDS_REVIEW:"Group-aware applicability or evidence needs review."}[status]
 @classmethod
 def get_summary(cls,report,original_na=None):
  mc=Counter(x.group_na_status.value for x in report.member_results);with_na=[g for g in report.group_results if g.report_evidence_ids];gc=Counter(g.status.value for g in with_na);orig=sum(cls._enum(cls._get(x,"status"))=="POTENTIAL_CONFLICT" for x in cls._get(original_na,"results",[]) or [])
  original_items=[x for x in cls._get(original_na,"results",[]) or [] if cls._enum(cls._get(x,"status"))=="POTENTIAL_CONFLICT"];original_conflicts={str(cls._get(x,"effective_requirement_id")) for x in original_items};new_conflicts={x.effective_requirement_id for x in report.member_results if x.group_na_status is GroupAwareNAStatus.POTENTIAL_CONFLICT};member_map={x.effective_requirement_id:x for x in report.member_results};justified_from_conflict=sum(member_map[r].group_na_status is GroupAwareNAStatus.JUSTIFIED for r in original_conflicts if r in member_map);scope_from_conflict=sum(member_map[r].group_na_status is GroupAwareNAStatus.INSUFFICIENT_REPORT_EVIDENCE for r in original_conflicts if r in member_map)
  return {"requirement_level":{x.value:mc[x.value] for x in GroupAwareNAStatus},"logical_group_level":{"groups_with_report_na":len(with_na),**{x.value:gc[x.value] for x in GroupAwareNAStatus if x is not GroupAwareNAStatus.NOT_REPORTED_NA and x is not GroupAwareNAStatus.INACTIVE}},"original_requirement_potential_conflicts":orig,"original_unique_conflicting_clauses":len({str(cls._get(x,"source_clause_id")) for x in original_items}),"new_requirement_potential_conflicts":mc["POTENTIAL_CONFLICT"],"new_logical_group_potential_conflicts":gc["POTENTIAL_CONFLICT"],"new_justified_requirements":mc["JUSTIFIED"],"new_justified_logical_groups":gc["JUSTIFIED"],"conflicts_removed_due_to_group_awareness":len(original_conflicts-new_conflicts),"conflicts_removed_by_inherited_not_applicable":justified_from_conflict,"conflicts_reclassified_as_report_scope_ambiguous":scope_from_conflict,"conflicts_reduced_by_logical_group_deduplication":max(0,mc["POTENTIAL_CONFLICT"]-gc["POTENTIAL_CONFLICT"]),"remaining_independent_conflicts":gc["POTENTIAL_CONFLICT"],"remaining_evidence_scope_ambiguities":gc["INSUFFICIENT_REPORT_EVIDENCE"]}
 @classmethod
 def _na_refs(cls,m):return [x for x in cls._get(m,"evidence_refs",[]) or [] if cls._enum(cls._get(x,"reported_verdict"))=="NA"]
 @staticmethod
 def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
 @staticmethod
 def _enum(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
 def get_diagnostics(self):return copy.deepcopy(self._diagnostics)
 @classmethod
 def to_dict(cls,v):return cls._safe(asdict(v)) if is_dataclass(v) else (_ for _ in ()).throw(TypeError("group-aware N/A model required"))
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
__all__=["GenericGroupAwareNAValidator","GroupAwareNAMemberResult","GroupAwareNAGroupResult","GroupAwareNAStatus","GroupAwareNAValidationReport"]
