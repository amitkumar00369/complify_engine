"""Resolve report evidence scope across logical requirement groups."""
from __future__ import annotations
import copy,json,re
from collections import Counter,defaultdict
from dataclasses import asdict,dataclass,field,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Dict,Iterable,List,Mapping,Optional,Sequence,Set,Tuple
from urllib.parse import quote

class ReportEvidenceScopeStatus(str,Enum):
 EXACT_GROUP="EXACT_GROUP";MULTIPLE_GROUPS="MULTIPLE_GROUPS";WHOLE_CLAUSE="WHOLE_CLAUSE";PARENT_SCOPE="PARENT_SCOPE";CHILD_SCOPE="CHILD_SCOPE";AMBIGUOUS="AMBIGUOUS";UNRESOLVED="UNRESOLVED";NO_RELEVANT_GROUP="NO_RELEVANT_GROUP"
@dataclass
class ScopedGroupReference:
 group_id:str;clause_id:str;scope_confidence:Optional[float];scope_reason:str;matched_requirement_ids:List[str]=field(default_factory=list);semantic_overlap_score:Optional[float]=None;structural_score:Optional[float]=None;source_order_score:Optional[float]=None
@dataclass
class ReportEvidenceScopeResult:
 scope_id:str;report_evidence_id:str;report_result_id:Optional[str];report_clause_id:Optional[str];reported_verdict:Optional[str];page_start:Optional[int];page_end:Optional[int];scope_status:ReportEvidenceScopeStatus;selected_groups:List[ScopedGroupReference]=field(default_factory=list);candidate_groups:List[ScopedGroupReference]=field(default_factory=list);excluded_groups:List[str]=field(default_factory=list);reason:str="";diagnostics:List[Dict[str,Any]]=field(default_factory=list);raw_text_excerpt:Optional[str]=None
@dataclass
class ReportEvidenceScopeReport:
 effective_kb_id:str;report_document_id:str;results:List[ReportEvidenceScopeResult]=field(default_factory=list);summary:Dict[str,Any]=field(default_factory=dict);diagnostics:List[Dict[str,Any]]=field(default_factory=list)

class GenericReportEvidenceScopeResolver:
 """Assign evidence to groups using structure and distinctive text only."""
 BOILERPLATE={"shall","appliance","appliances","compliance","checked","check","test","tests","testing","requirement","requirements","inspection","general","clause","part","result","applicable","not","the","and","with","that","this","from","into","only","accordance","carried","out"}
 STRONG={"EXACT_CLAUSE","EXACT_SUBCLAUSE","ANNEX_EXACT"};PARENT={"PARENT_CLAUSE"};CHILD={"CHILD_CLAUSE"}
 def __init__(self):self._diagnostics=[]
 def resolve(self,effective_kb,grouping_report,report_evidence,evidence_match_report,group_aware_applicability_report=None,group_aware_na_report=None,conflict_audit_report=None):
  self._diagnostics=[];req_text=self._requirement_texts(effective_kb);groups=list(self._get(grouping_report,"groups",[]) or []);group_by_id={str(self._get(g,"group_id")):g for g in groups};member_group={str(self._get(m,"effective_requirement_id")):str(self._get(g,"group_id")) for g in groups for m in self._get(g,"members",[]) or []};clause_groups=defaultdict(list)
  for g in groups:clause_groups[str(self._get(g,"clause_id"))].append(str(self._get(g,"group_id")))
  evidence_links=defaultdict(lambda:{"groups":defaultdict(set),"statuses":set()})
  for m in self._get(evidence_match_report,"matches",[]) or []:
   rid=str(self._get(m,"effective_requirement_id"));gid=member_group.get(rid)
   for ref in self._get(m,"evidence_refs",[]) or []:
    eid=str(self._get(ref,"evidence_id"));evidence_links[eid]["statuses"].add(self._enum(self._get(m,"match_status")))
    if gid:evidence_links[eid]["groups"][gid].add(rid)
  results=[]
  for ev in self._evidence(report_evidence):results.append(self.resolve_evidence(ev,group_by_id,clause_groups,evidence_links.get(str(self._get(ev,"evidence_id")),{}),req_text))
  report=ReportEvidenceScopeReport(str(self._get(effective_kb,"effective_kb_id","")),str(self._get(report_evidence,"document_id","")),results,diagnostics=copy.deepcopy(self._diagnostics));report.summary=self.get_summary(report,grouping_report);return report
 def resolve_evidence(self,ev,group_by_id,clause_groups,links,req_text):
  eid=str(self._get(ev,"evidence_id"));cid=str(self._get(ev,"clause_id") or "");linked=set(self._get(links,"groups",{}));same=set(clause_groups.get(cid,[]));evidence_type=self._enum(self._get(ev,"evidence_type"));verdict=self._enum(self._get(ev,"reported_verdict"));independent_row=evidence_type=="CLAUSE_ROW" and verdict not in {None,"NOT_STATED"} and not (self._get(ev,"child_evidence_ids",[]) or []);candidate_ids=(linked if evidence_type=="SUBROW" or independent_row else linked|same);statuses=set(self._get(links,"statuses",set()) or set());raw=self._evidence_text(ev);refs=[]
  for gid in sorted(candidate_ids):
   g=group_by_id[gid];gtext=" ".join(req_text.get(str(self._get(m,"effective_requirement_id")),"") for m in self._get(g,"members",[]) or []);semantic=self._overlap(raw,gtext);structural=.55 if str(self._get(g,"clause_id"))==cid else .35 if gid in linked else 0;matched=sorted(self._get(self._get(links,"groups",{}),gid,set()));order_score=self._order_score(ev,g);score=round(structural+semantic*.4+order_score*.05,6);refs.append((score,ScopedGroupReference(gid,str(self._get(g,"clause_id")),score,"Structural and distinctive-text scope score.",matched,round(semantic,6),structural,order_score)))
  refs.sort(key=lambda x:(-x[0],x[1].group_id));candidates=[x[1] for x in refs];selected=[];diagnostics=[]
  if evidence_type=="CLAUSE_ROW" and self._get(ev,"child_evidence_ids",[]) and candidates:
   selected=candidates;status=ReportEvidenceScopeStatus.WHOLE_CLAUSE;reason="Structural clause-row container establishes evidence presence only; child subrows retain independent verdict scope."
  elif not candidates:status=ReportEvidenceScopeStatus.NO_RELEVANT_GROUP;reason="No structurally relevant effective requirement group exists."
  elif len(candidates)==1:
   selected=[candidates[0]]
   if not self._tokens(raw):status=ReportEvidenceScopeStatus.WHOLE_CLAUSE;reason="A textless clause result has exactly one logical group."
   elif statuses & self.PARENT:status=ReportEvidenceScopeStatus.PARENT_SCOPE;reason="Existing structural matching identifies parent-clause scope for the only relevant group."
   elif statuses & self.CHILD:status=ReportEvidenceScopeStatus.CHILD_SCOPE;reason="Existing structural matching identifies child-clause scope for the only relevant group."
   else:status=ReportEvidenceScopeStatus.EXACT_GROUP;reason="Exactly one logical group is structurally relevant."
  else:
   best,second=refs[0],refs[1];strong=[r for score,r in refs if r.semantic_overlap_score is not None and r.semantic_overlap_score>=.32]
   if best[1].semantic_overlap_score>=.28 and best[0]-second[0]>=.12:selected=[best[1]];status=ReportEvidenceScopeStatus.EXACT_GROUP;reason="One group has strong distinctive-text separation from other candidates."
   elif 1<len(strong)<len(candidates):selected=strong;status=ReportEvidenceScopeStatus.MULTIPLE_GROUPS;reason="Distinctive evidence text supports a known subset of candidate groups."
   elif len(strong)==len(candidates) and all(x.semantic_overlap_score>=.45 for x in candidates):selected=candidates;status=ReportEvidenceScopeStatus.WHOLE_CLAUSE;reason="Evidence strongly covers every logical group under the clause."
   else:status=ReportEvidenceScopeStatus.AMBIGUOUS;reason="Multiple logical groups remain plausible without safe textual separation.";diagnostics.append({"code":"REPORT_SCOPE_MULTIPLE_PLAUSIBLE_GROUPS","candidate_count":len(candidates)})
  excluded=sorted(set(candidate_ids)-{x.group_id for x in selected});result=ReportEvidenceScopeResult("SCOPE-"+quote(eid,safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"),eid,self._get(ev,"result_id"),cid or None,self._enum(self._get(ev,"reported_verdict")),self._get(ev,"page_start"),self._get(ev,"page_end"),status,selected,candidates,excluded,reason,diagnostics,str(self._get(ev,"raw_text",raw))[:1000] or None);self._diagnostics.extend(dict(x,report_evidence_id=eid) for x in diagnostics);return result
 @classmethod
 def get_summary(cls,report,grouping_report=None):
  c=Counter(x.scope_status.value for x in report.results);by_clause=defaultdict(set)
  for g in cls._get(grouping_report,"groups",[]) or []:by_clause[str(cls._get(g,"clause_id"))].add(str(cls._get(g,"group_id")))
  multi={cid for cid,v in by_clause.items() if len(v)>1};single={cid for cid,v in by_clause.items() if len(v)==1};multi_results=[x for x in report.results if str(x.report_clause_id) in multi]
  verdicts={}
  for label,pred in {"NA":lambda v:v=="NA","PASS":lambda v:v=="PASS","OTHER":lambda v:v not in {"NA","PASS"}}.items():
   items=[x for x in report.results if pred(x.reported_verdict)];vc=Counter(x.scope_status.value for x in items);verdicts[label]={"total":len(items),"exactly_scoped":vc["EXACT_GROUP"],"multi_group_scoped":vc["MULTIPLE_GROUPS"],"whole_clause_scoped":vc["WHOLE_CLAUSE"],"ambiguous":vc["AMBIGUOUS"]}
  mc=Counter(x.scope_status.value for x in multi_results)
  return {"total_report_evidence_items_considered":len(report.results),**{x.value:c[x.value] for x in ReportEvidenceScopeStatus},"report_clauses_with_single_logical_group":len(single),"report_clauses_with_multiple_logical_groups":len(multi),"multi_group_clause_results":{"one_exact_group":mc["EXACT_GROUP"],"known_subset":mc["MULTIPLE_GROUPS"],"whole_clause":mc["WHOLE_CLAUSE"],"ambiguous":mc["AMBIGUOUS"]},"verdict_scope_summary":verdicts}
 @classmethod
 def _evidence(cls,report):
  def walk(items):
   for c in items:
    for e in cls._get(c,"evidence_items",[]) or []:yield e
    yield from walk(cls._get(c,"children",[]) or [])
  yield from walk(cls._get(report,"clauses",[]) or [])
 @classmethod
 def _requirement_texts(cls,kb):
  out={}
  def walk(items):
   for c in items:
    for r in cls._get(c,"requirements",[]) or []:out[str(cls._get(r,"effective_requirement_id"))]=str(cls._get(r,"text", ""))
    walk(cls._get(c,"children",[]) or [])
  walk(cls._get(kb,"clauses",[]) or [])
  for a in cls._get(kb,"annexes",[]) or []:
   for r in cls._get(a,"requirements",[]) or []:out[str(cls._get(r,"effective_requirement_id"))]=str(cls._get(r,"text",""))
  return out
 @classmethod
 def _evidence_text(cls,ev):
  parts=[cls._get(ev,"raw_text",""),cls._get(ev,"remarks","")]
  for m in cls._get(ev,"measurements",[]) or []:parts.extend([cls._get(m,"parameter",""),cls._get(m,"raw_text","")])
  return " ".join(str(x) for x in parts if x)
 @classmethod
 def _tokens(cls,text):return {x for x in re.findall(r"[a-z0-9]+",str(text).lower()) if len(x)>2 and x not in cls.BOILERPLATE}
 @classmethod
 def _overlap(cls,a,b):
  x,y=cls._tokens(a),cls._tokens(b);return len(x&y)/len(y) if y else 0.0
 @classmethod
 def _order_score(cls,ev,g):
  eo=cls._get(ev,"source_order");members=cls._get(g,"members",[]) or [];go=min([cls._get(x,"source_order",0) for x in members] or [0]);return 1.0 if eo is not None and go and abs(int(eo)-int(go))<=1 else 0.0
 @staticmethod
 def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
 @staticmethod
 def _enum(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
 def get_diagnostics(self):return copy.deepcopy(self._diagnostics)
 @classmethod
 def to_dict(cls,v):return cls._safe(asdict(v)) if is_dataclass(v) else (_ for _ in ()).throw(TypeError("scope model required"))
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
__all__=["GenericReportEvidenceScopeResolver","ReportEvidenceScopeReport","ReportEvidenceScopeResult","ReportEvidenceScopeStatus","ScopedGroupReference"]
