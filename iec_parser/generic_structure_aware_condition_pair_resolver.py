"""Resolve condition-pair candidates through explicit standard/report structure bridges."""
from __future__ import annotations
import copy,hashlib,json
from collections import Counter,defaultdict
from dataclasses import asdict,dataclass,field,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Dict,List,Mapping,Optional,Sequence,Tuple

class StructureAwarePairStatus(str,Enum):MATCHED="MATCHED";POSSIBLE="POSSIBLE";AMBIGUOUS="AMBIGUOUS";NO_MATCH="NO_MATCH"
@dataclass
class PairProvenance:
 source_artifact:str;source_id:str;bridge_role:str
@dataclass
class StructureAwareTestConditionPair:
 pair_id:str;required_condition_id:str;actual_condition_id:Optional[str];standard_structure_id:Optional[str];standard_step_id:Optional[str];report_structure_id:Optional[str];report_row_id:Optional[str];structure_link_id:Optional[str];group_id:Optional[str];clause_id:Optional[str];parameter_type:Optional[str];condition_role:Optional[str];required_expression:Any=None;actual_expression:Any=None;required_value:Any=None;actual_value:Any=None;unit_compatible:bool=False;parameter_compatible:bool=False;role_compatible:bool=False;scope_compatible:bool=False;expression_compatible:bool=False;variable_compatible:bool=False;pair_status:StructureAwarePairStatus=StructureAwarePairStatus.NO_MATCH;confidence:float=0.0;reason_code:str="";reason:str="";provenance:List[PairProvenance]=field(default_factory=list)
@dataclass
class StructureLinkReconciliation:
 structure_link_id:str;standard_structure_id:str;standard_step_id:Optional[str];standard_parameter:Optional[str];standard_role:Optional[str];report_structure_id:str;report_row_id:Optional[str];report_parameter:Optional[str];report_role:Optional[str];required_condition_found:bool;actual_condition_found:bool;result:str;reason:str
@dataclass
class PreviousPairReconciliation:
 old_pair_id:str;old_status:str;structure_link_ids:List[str];new_status:str;reason:str
@dataclass
class StructureAwareConditionPairResult:
 effective_kb_id:str;profile_id:str;report_document_id:str;pairs:List[StructureAwareTestConditionPair]=field(default_factory=list);structure_link_reconciliation:List[StructureLinkReconciliation]=field(default_factory=list);previous_pair_reconciliation:List[PreviousPairReconciliation]=field(default_factory=list);summary:Dict[str,Any]=field(default_factory=dict);diagnostics:List[Dict[str,Any]]=field(default_factory=list)

class GenericStructureAwareConditionPairResolver:
 _UNIT_DIM={"V":"voltage","mV":"voltage","kV":"voltage","A":"current","mA":"current","W":"power","kW":"power","Hz":"frequency","s":"time","min":"time","h":"time","mm":"length","cm":"length","m":"length","K":"rise","°C":"temperature","r/min":"speed","N":"force","cycles":"count","%":"percentage"}
 def resolve(self,effective_kb,product_profile,report_evidence,grouping,evidence_scope,evidence_enrichment,test_structure):
  required={str(self._get(x,"condition_id")):x for x in self._get(evidence_enrichment,"required_test_conditions",[]) or []};actual={str(self._get(x,"condition_id")):x for x in self._get(evidence_enrichment,"actual_test_conditions",[]) or []};std={str(self._get(x,"structure_id")):x for x in self._get(test_structure,"standard_test_structures",[]) or []};rep={str(self._get(x,"structure_id")):x for x in self._get(test_structure,"report_clause_structures",[]) or []};links=list(self._get(test_structure,"structure_links",[]) or []);rowscope={str(self._get(x,"row_id")):x for x in self._get(test_structure,"row_scope_candidates",[]) or []};facts=self._reliable_facts(product_profile,evidence_enrichment)
  steps={};step_owner={};rows={};row_owner={}
  for sid,s in std.items():
   for x in self._get(s,"test_method_steps",[]) or []:steps[str(self._get(x,"step_id"))]=x;step_owner[str(self._get(x,"step_id"))]=sid
  for sid,s in rep.items():
   for x in self._get(s,"rows",[]) or []:rows[str(self._get(x,"row_id"))]=x;row_owner[str(self._get(x,"row_id"))]=sid
  req_steps=self._required_steps(required,std,steps);actual_rows=self._actual_rows(actual,rows);pairs=[];diagnostics=[];reconciliations=[];bridge_candidates=[]
  for link in links:
   lid=str(self._get(link,"link_id"));lstatus=self._enum(self._get(link,"candidate_status"));ssid=str(self._get(link,"standard_structure_id"));rsid=str(self._get(link,"report_structure_id"));step_ids=[str(x) for x in self._get(link,"standard_step_ids",[]) or []];row_ids=[str(x) for x in self._get(link,"report_row_ids",[]) or []]
   for step_id in step_ids:
    for row_id in row_ids:
     step=steps.get(step_id,{});row=rows.get(row_id,{});rids=[rid for rid,sids in req_steps.items() if step_id in sids];aids=[aid for aid,rids2 in actual_rows.items() if row_id in rids2];sp=self._get(step,"parameter_type");sr=self._get(step,"condition_role");rp,rr=self._row_semantics(row,actual,aids)
     result="NO_PAIR_DATA";reason="The structural bridge lacks a required or actual condition object."
     if not rids:diagnostics.append({"code":"STRUCTURE_MATCH_HAS_NO_REQUIRED_CONDITION","structure_link_id":lid,"standard_structure_id":ssid,"standard_step_id":step_id,"report_row_id":row_id,"parameter":sp,"role":sr})
     if not aids:diagnostics.append({"code":"STRUCTURE_MATCH_HAS_NO_ACTUAL_CONDITION","structure_link_id":lid,"standard_step_id":step_id,"report_structure_id":rsid,"report_row_id":row_id,"parameter":rp,"role":rr})
     if rids and aids:
      result="PAIR_CANDIDATE";reason="Required and actual condition objects complete the structure bridge."
      for rid in rids:
       for aid in aids:bridge_candidates.append((required[rid],actual[aid],link,step,row,rowscope.get(row_id),ssid,rsid))
     reconciliations.append(StructureLinkReconciliation(lid,ssid,step_id,sp,sr,rsid,row_id,rp,rr,bool(rids),bool(aids),result,reason))
  # Resolve candidates first, then conservatively downgrade equal competitors.
  for candidate in bridge_candidates:pairs.append(self._pair(*candidate,facts=facts))
  competing_required=Counter(x.required_condition_id for x in pairs if x.pair_status==StructureAwarePairStatus.MATCHED);competing_actual=Counter(x.actual_condition_id for x in pairs if x.pair_status==StructureAwarePairStatus.MATCHED)
  for x in pairs:
   if x.pair_status==StructureAwarePairStatus.MATCHED and (competing_required[x.required_condition_id]>1 or competing_actual[x.actual_condition_id]>1):x.pair_status=StructureAwarePairStatus.AMBIGUOUS;x.reason_code="STRUCTURE_PAIR_MULTIPLE_CANDIDATES";x.reason="Multiple otherwise compatible condition bridges remain equally plausible.";diagnostics.append({"code":"STRUCTURE_PAIR_MULTIPLE_CANDIDATES","pair_id":x.pair_id})
  bridged_req={x.required_condition_id for x in pairs}
  for rid,r in required.items():
   if rid not in bridged_req:
    pairs.append(self._missing_pair(r,req_steps.get(rid,[])));diagnostics.append({"code":"STRUCTURE_PAIR_ACTUAL_CONDITION_MISSING","required_condition_id":rid})
  bridged_actual={x.actual_condition_id for x in pairs if x.actual_condition_id}
  for aid in actual:
   if aid not in bridged_actual:diagnostics.append({"code":"STRUCTURE_PAIR_REQUIRED_CONDITION_MISSING","actual_condition_id":aid})
  old_recon=self._old_reconciliation(evidence_enrichment,pairs,links,req_steps,actual_rows)
  counts=Counter(x.pair_status.value for x in pairs);matched=[x for x in pairs if x.pair_status==StructureAwarePairStatus.MATCHED];matched_links=[x for x in reconciliations if self._link_status(links,x.structure_link_id)=="MATCHED"]
  summary={"required_conditions_considered":len(required),"actual_conditions_considered":len(actual),"structure_links_considered":len(links),"condition_pairs":{x.value:counts[x.value] for x in StructureAwarePairStatus},"matched_structure_links_with_full_condition_data":sum(x.required_condition_found and x.actual_condition_found for x in matched_links),"matched_structure_links_missing_required_condition":sum(not x.required_condition_found for x in matched_links),"matched_structure_links_missing_actual_condition":sum(not x.actual_condition_found for x in matched_links),"matched_structure_links_with_semantic_mismatch":sum(x.pair_status!=StructureAwarePairStatus.MATCHED for x in pairs if x.structure_link_id and self._link_status(links,x.structure_link_id)=="MATCHED"),"comparison_eligibility":{"comparable_matched_pairs":len(matched),"expression_comparable_matched_pairs":sum(x.expression_compatible for x in matched),"value_comparable_matched_pairs":sum(x.required_value is not None and x.actual_value is not None and x.unit_compatible for x in matched),"formula_comparable_matched_pairs":sum(x.required_expression is not None and x.actual_expression is not None and x.expression_compatible for x in matched)}}
  for x in pairs:diagnostics.append({"code":{"MATCHED":"STRUCTURE_PAIR_MATCHED","POSSIBLE":"STRUCTURE_PAIR_POSSIBLE","AMBIGUOUS":"STRUCTURE_PAIR_AMBIGUOUS","NO_MATCH":x.reason_code or "STRUCTURE_PAIR_NO_MATCH"}[x.pair_status.value],"pair_id":x.pair_id})
  return StructureAwareConditionPairResult(str(self._get(effective_kb,"effective_kb_id","") or ""),str(self._get(product_profile,"profile_id","") or ""),str(self._get(report_evidence,"document_id","") or ""),sorted(pairs,key=lambda x:x.pair_id),sorted(reconciliations,key=lambda x:x.structure_link_id+x.standard_step_id),old_recon,summary,sorted(self._dedup(diagnostics),key=lambda x:json.dumps(x,sort_keys=True)))
 def _pair(self,r,a,link,step,row,row_scope,ssid,rsid,facts):
  rid=str(self._get(r,"condition_id"));aid=str(self._get(a,"condition_id"));lid=str(self._get(link,"link_id"));step_id=str(self._get(step,"step_id"));row_id=str(self._get(row,"row_id"));param=self._enum(self._get(r,"parameter_type"));role=str(self._get(r,"condition_role","") or "");pcompat=param==self._enum(self._get(a,"parameter_type"));rcompat=role==str(self._get(a,"condition_role","") or "") and role!="OTHER";groups=[str(x) for x in self._get(a,"group_ids",[]) or []];gid=str(self._get(r,"group_id","") or "");scope=gid in groups and gid in [str(x) for x in self._get(row_scope,"narrowed_group_ids",[]) or []];rv=self._get(r,"expected_value");av=self._get(a,"observed_value");unit=self._units(self._get(rv,"unit_normalized") or self._get(rv,"unit"),self._get(av,"unit_normalized") or self._get(av,"unit"));rexp=self._get(r,"expected_expression");aexp=self._get(a,"observed_expression");expr,var=self._expressions(rexp,aexp,facts);lstatus=self._enum(self._get(link,"candidate_status"));semantic=pcompat and rcompat and scope and unit
  status=StructureAwarePairStatus.MATCHED if lstatus=="MATCHED" and semantic and expr and var else StructureAwarePairStatus.AMBIGUOUS if lstatus=="AMBIGUOUS" and pcompat and rcompat else StructureAwarePairStatus.POSSIBLE if lstatus in {"MATCHED","POSSIBLE"} and (pcompat or scope) else StructureAwarePairStatus.NO_MATCH
  code="STRUCTURE_PAIR_MATCHED" if status==StructureAwarePairStatus.MATCHED else "STRUCTURE_PAIR_PARAMETER_MISMATCH" if not pcompat else "STRUCTURE_PAIR_ROLE_MISMATCH" if not rcompat else "STRUCTURE_PAIR_SCOPE_MISMATCH" if not scope else "STRUCTURE_PAIR_UNIT_MISMATCH" if not unit else "STRUCTURE_PAIR_EXPRESSION_UNRESOLVED" if not expr else "STRUCTURE_PAIR_POSSIBLE"
  confidence=min(1.0,float(self._get(link,"confidence",0) or 0)*(.5+.1*sum((pcompat,rcompat,scope,unit,expr))))
  prov=[PairProvenance("evidence_enrichment",rid,"REQUIRED_CONDITION"),PairProvenance("test_structure",step_id,"STANDARD_STEP"),PairProvenance("test_structure",lid,"STRUCTURE_LINK"),PairProvenance("test_structure",row_id,"REPORT_ROW"),PairProvenance("evidence_enrichment",aid,"ACTUAL_CONDITION")]
  return StructureAwareTestConditionPair(self._id("STRUCT-PAIR",rid,aid,lid),rid,aid,ssid,step_id,rsid,row_id,lid,gid,self._get(r,"clause_id"),param,role,copy.deepcopy(rexp),copy.deepcopy(aexp),copy.deepcopy(rv),copy.deepcopy(av),unit,pcompat,rcompat,scope,expr,var,status,round(confidence,6),code,"Structure and semantic compatibility only; values are not compared.",prov)
 def _missing_pair(self,r,step_ids):
  rid=str(self._get(r,"condition_id"));step=step_ids[0] if len(step_ids)==1 else None;return StructureAwareTestConditionPair(self._id("STRUCT-PAIR",rid,"NONE"),rid,None,None,step,None,None,None,self._get(r,"group_id"),self._get(r,"clause_id"),self._enum(self._get(r,"parameter_type")),self._get(r,"condition_role"),copy.deepcopy(self._get(r,"expected_expression")),None,copy.deepcopy(self._get(r,"expected_value")),None,False,False,False,False,False,False,StructureAwarePairStatus.NO_MATCH,0.0,"STRUCTURE_PAIR_ACTUAL_CONDITION_MISSING","No structurally bridged actual condition exists.",[PairProvenance("evidence_enrichment",rid,"REQUIRED_CONDITION")])
 def _required_steps(self,required,std,steps):
  out=defaultdict(list)
  for rid,r in required.items():
   reqid=str(self._get(r,"effective_requirement_id"));ptype=self._enum(self._get(r,"parameter_type"));role=self._get(r,"condition_role")
   for s in std.values():
    if rid not in [str(x) for x in self._get(s,"required_conditions",[]) or []]:continue
    candidates=[]
    for step in self._get(s,"test_method_steps",[]) or []:
     prov_req={str(self._get(p,"requirement_id")) for p in self._get(step,"provenance",[]) or []};score=3*(reqid in prov_req)+2*(ptype==self._get(step,"parameter_type"))+2*(role==self._get(step,"condition_role"));
     if score:candidates.append((score,int(self._get(step,"step_order",0) or 0),str(self._get(step,"step_id"))))
    if candidates:
     best=max(x[0] for x in candidates);out[rid].extend(x[2] for x in candidates if x[0]==best)
  return out
 @classmethod
 def _actual_rows(cls,actual,rows):
  out=defaultdict(list)
  for row_id,row in rows.items():
   for aid in cls._get(row,"actual_conditions",[]) or []:
    if str(aid) in actual:out[str(aid)].append(row_id)
  return out
 @classmethod
 def _row_semantics(cls,row,actual,aids):
  if len(aids)==1:return cls._enum(cls._get(actual[aids[0]],"parameter_type")),cls._get(actual[aids[0]],"condition_role")
  return None,None
 @classmethod
 def _expressions(cls,rexp,aexp,facts):
  if not rexp and not aexp:return True,True
  if not rexp or not aexp:return True,True  # constants remain value-comparable without equal expression forms
  rt=cls._enum(cls._get(rexp,"expression_type"));at=cls._enum(cls._get(aexp,"expression_type"));variables=[str(x) for x in self._get(rexp,"variables",[]) or []];variable=self._get(rexp,"variable");variables+=([str(variable)] if variable else []);resolved=all(x in facts for x in variables);return rt==at or {rt,at}<={"CONSTANT","MULTIPLIER"},resolved
 @classmethod
 def _reliable_facts(cls,profile,enrichment):
  out={}
  for key,x in (cls._get(profile,"facts",{}) or {}).items():
   if cls._enum(cls._get(x,"status")) in {"CONFIRMED","INFERRED_STRONG"}:out[str(key)]=x
  for x in cls._get(enrichment,"facts",[]) or []:
   if cls._enum(cls._get(x,"status"))=="RESOLVED":out[str(cls._get(x,"canonical_name"))]=x
  return out
 @classmethod
 def _units(cls,a,b):return a==b or bool(a and b and cls._UNIT_DIM.get(str(a))==cls._UNIT_DIM.get(str(b)))
 def _old_reconciliation(self,enrichment,pairs,links,req_steps,actual_rows):
  new={(x.required_condition_id,x.actual_condition_id):x for x in pairs};out=[]
  for old in self._get(enrichment,"condition_pairs",[]) or []:
   rid=str(self._get(old,"required_condition_id"));aid=str(self._get(old,"actual_condition_id","") or "");x=new.get((rid,aid));support=[str(self._get(l,"link_id")) for l in links if set(str(v) for v in self._get(l,"standard_step_ids",[]) or [])&set(req_steps.get(rid,[])) and set(str(v) for v in self._get(l,"report_row_ids",[]) or [])&set(actual_rows.get(aid,[]))];status=x.pair_status.value if x else "NO_MATCH";reason=x.reason if x else "No complete structural bridge supports the previous flat pair.";out.append(PreviousPairReconciliation(str(self._get(old,"pair_id")),self._enum(self._get(old,"link_status")) or "NO_MATCH",sorted(support),status,reason))
  return sorted(out,key=lambda x:x.old_pair_id)
 @classmethod
 def _link_status(cls,links,lid):return next((cls._enum(cls._get(x,"candidate_status")) for x in links if str(cls._get(x,"link_id"))==lid),None)
 @staticmethod
 def _dedup(items):return list({json.dumps(x,sort_keys=True):x for x in items}.values())
 @staticmethod
 def _id(*parts):return parts[0]+"-"+hashlib.sha256("\x1f".join(parts[1:]).encode()).hexdigest()[:18].upper()
 @staticmethod
 def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
 @staticmethod
 def _enum(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
 @classmethod
 def _plain(cls,v):
  if isinstance(v,Enum):return v.value
  if is_dataclass(v):return cls._plain(asdict(v))
  if isinstance(v,dict):return {k:cls._plain(x) for k,x in v.items()}
  if isinstance(v,list):return [cls._plain(x) for x in v]
  return v
 @classmethod
 def to_dict(cls,v):return cls._plain(asdict(v)) if is_dataclass(v) else (_ for _ in ()).throw(TypeError("structure-aware pair result required"))
 @classmethod
 def to_json(cls,v,indent=2):return json.dumps(cls.to_dict(v),ensure_ascii=False,sort_keys=True,indent=indent)
 @classmethod
 def save_json(cls,v,p):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(cls.to_json(v)+"\n",encoding="utf-8");return p
__all__=["GenericStructureAwareConditionPairResolver","PairProvenance","PreviousPairReconciliation","StructureAwareConditionPairResult","StructureAwarePairStatus","StructureAwareTestConditionPair","StructureLinkReconciliation"]
