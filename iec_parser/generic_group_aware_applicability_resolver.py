"""Derive applicability decisions from explicit requirement-group scope metadata."""
from __future__ import annotations
import copy,json
from collections import Counter
from dataclasses import asdict,dataclass,field,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Dict,List,Mapping,Optional

class GroupAwareApplicabilityDecision(str,Enum):
 APPLICABLE="APPLICABLE";NOT_APPLICABLE="NOT_APPLICABLE";UNKNOWN="UNKNOWN";NEEDS_REVIEW="NEEDS_REVIEW";INACTIVE="INACTIVE"
class ApplicabilityResolutionSource(str,Enum):
 ORIGINAL="ORIGINAL";INHERITED_PRIMARY="INHERITED_PRIMARY";INHERITED_PREVIOUS="INHERITED_PREVIOUS";SHARED_GROUP="SHARED_GROUP";INDEPENDENT="INDEPENDENT";UNRESOLVED="UNRESOLVED"
@dataclass
class GroupAwareApplicabilityResult:
 effective_requirement_id:str;effective_clause_id:Optional[str];clause_id:Optional[str];original_decision:Optional[str];resolved_decision:GroupAwareApplicabilityDecision;resolution_source:ApplicabilityResolutionSource;requirement_group_id:Optional[str];primary_requirement_id:Optional[str];inherited_from_requirement_id:Optional[str];original_applicability_status:Optional[str];product_fact_ids:List[str]=field(default_factory=list);reason:str="";diagnostics:List[Dict[str,Any]]=field(default_factory=list);scope_evaluation:Optional[Dict[str,Any]]=None
@dataclass
class GroupAwareApplicabilityReport:
 effective_kb_id:str;profile_id:str;results:List[GroupAwareApplicabilityResult]=field(default_factory=list);summary:Dict[str,Any]=field(default_factory=dict);diagnostics:List[Dict[str,Any]]=field(default_factory=list)

class GenericGroupAwareApplicabilityResolver:
 def __init__(self):self._diagnostics=[]
 def resolve(self,effective_kb,applicability_report,grouping_report):
  self._diagnostics=[];apps={str(self._get(x,"effective_requirement_id")):x for x in self._get(applicability_report,"results",[]) or []};members={};groups={}
  for g in self._get(grouping_report,"groups",[]) or []:
   gid=str(self._get(g,"group_id"));groups[gid]=g
   for i,m in enumerate(self._get(g,"members",[]) or []):members[str(self._get(m,"effective_requirement_id"))]=(g,m,i)
  results=[];resolved={}
  for app in self._get(applicability_report,"results",[]) or []:
   rid=str(self._get(app,"effective_requirement_id"));triple=members.get(rid);diagnostics=[];original=self._decision(self._get(app,"decision"));decision=original;source=ApplicabilityResolutionSource.ORIGINAL;gid=primary=inherited=None
   if triple:
    g,m,index=triple;gid=self._get(g,"group_id");primary=self._get(g,"primary_requirement_id");scope=self._enum(self._get(m,"applicability_scope"))
    if scope=="INDEPENDENT":source=ApplicabilityResolutionSource.INDEPENDENT
    elif scope=="OWN":source=ApplicabilityResolutionSource.ORIGINAL
    elif scope=="UNRESOLVED":decision=GroupAwareApplicabilityDecision.NEEDS_REVIEW;source=ApplicabilityResolutionSource.UNRESOLVED;diagnostics.append({"code":"GROUP_SCOPE_UNRESOLVED"})
    elif scope in {"INHERIT_PRIMARY","INHERIT_PREVIOUS"}:
     source=ApplicabilityResolutionSource.INHERITED_PRIMARY if scope=="INHERIT_PRIMARY" else ApplicabilityResolutionSource.INHERITED_PREVIOUS
     target=str(primary) if scope=="INHERIT_PRIMARY" else (str(self._get(self._get(g,"members",[])[index-1],"effective_requirement_id")) if index>0 else "")
     inherited=target or None;target_result=resolved.get(target);target_app=apps.get(target)
     if not target or (target_result is None and target_app is None):decision=GroupAwareApplicabilityDecision.NEEDS_REVIEW;diagnostics.append({"code":"GROUP_SCOPE_SOURCE_MISSING"})
     else:
      target_decision=target_result.resolved_decision if target_result else self._decision(self._get(target_app,"decision"))
      if target_decision is GroupAwareApplicabilityDecision.INACTIVE and original is not GroupAwareApplicabilityDecision.INACTIVE:decision=GroupAwareApplicabilityDecision.NEEDS_REVIEW;diagnostics.append({"code":"GROUP_SCOPE_INACTIVE_PRIMARY"})
      elif self._has_own_rule(app):decision=GroupAwareApplicabilityDecision.NEEDS_REVIEW;diagnostics.append({"code":"GROUP_SCOPE_CONFLICTING_MEMBER_RULE"})
      else:decision=target_decision;diagnostics.append({"code":"GROUP_SCOPE_INHERITED","from_requirement_id":target})
    elif scope=="SHARED_GROUP":
     source=ApplicabilityResolutionSource.SHARED_GROUP
     target=str(primary or "");inherited=target or None;target_result=resolved.get(target);target_app=apps.get(target)
     if self._get(g,"shared_applicability_rule") and (target_result or target_app):decision=target_result.resolved_decision if target_result else self._decision(self._get(target_app,"decision"))
     else:decision=GroupAwareApplicabilityDecision.NEEDS_REVIEW;diagnostics.append({"code":"GROUP_SCOPE_SHARED_RULE_MISSING"})
   result=GroupAwareApplicabilityResult(rid,self._get(app,"effective_clause_id"),self._get(app,"clause_id"),self._enum(self._get(app,"decision")),decision,source,gid,primary,inherited,self._enum(self._get(app,"applicability_status_from_kb")),sorted({str(self._get(x,"feature_id")) for x in self._get(app,"facts_used",[]) or []}),self._reason(original,decision,source),diagnostics,copy.deepcopy(self._get(app,"scope_evaluation")))
   results.append(result);resolved[rid]=result;self._diagnostics.extend(dict(x,effective_requirement_id=rid) for x in diagnostics)
  report=GroupAwareApplicabilityReport(str(self._get(applicability_report,"effective_kb_id",self._get(effective_kb,"effective_kb_id",""))),str(self._get(applicability_report,"profile_id","")),results,diagnostics=copy.deepcopy(self._diagnostics));report.summary=self.get_summary(report);return report
 @staticmethod
 def _reason(original,resolved,source):return "Original applicability retained." if original is resolved else f"Applicability changed from {original.value} to {resolved.value} using {source.value}."
 @classmethod
 def _has_own_rule(cls,app):return cls._enum(cls._get(app,"applicability_status_from_kb")) not in {None,"ALWAYS"} or bool(cls._get(app,"condition_text") or cls._get(app,"rule"))
 @staticmethod
 def _decision(v):
  try:return GroupAwareApplicabilityDecision(str(v.value if isinstance(v,Enum) else v))
  except:return GroupAwareApplicabilityDecision.NEEDS_REVIEW
 @staticmethod
 def get_summary(report):
  o=Counter(x.original_decision for x in report.results);r=Counter(x.resolved_decision.value for x in report.results);s=Counter(x.resolution_source.value for x in report.results);changes=Counter(f"{x.original_decision} -> {x.resolved_decision.value}" for x in report.results if x.original_decision!=x.resolved_decision.value)
  return {"total_requirements":len(report.results),"original_decisions":{x.value:o[x.value] for x in GroupAwareApplicabilityDecision},"resolved_decisions":{x.value:r[x.value] for x in GroupAwareApplicabilityDecision},"decisions_changed_by_grouping":sum(changes.values()),"decision_changes":dict(sorted(changes.items())),"resolution_sources":{x.value:s[x.value] for x in ApplicabilityResolutionSource}}
 @staticmethod
 def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
 @staticmethod
 def _enum(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
 def get_diagnostics(self):return copy.deepcopy(self._diagnostics)
 @classmethod
 def to_dict(cls,v):return cls._safe(asdict(v)) if is_dataclass(v) else (_ for _ in ()).throw(TypeError("group-aware applicability model required"))
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
__all__=["ApplicabilityResolutionSource","GenericGroupAwareApplicabilityResolver","GroupAwareApplicabilityDecision","GroupAwareApplicabilityReport","GroupAwareApplicabilityResult"]
