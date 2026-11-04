"""Extract source-owned test conditions from existing standard steps and report rows."""
from __future__ import annotations
import copy,hashlib,json,re
from collections import Counter,defaultdict
from dataclasses import asdict,dataclass,field,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Dict,List,Mapping,Optional,Sequence,Tuple
from .generic_evidence_enrichment_models import ActualTestCondition,EnrichmentStatus,EvidenceExpression,EvidenceParameterType,EvidenceProvenance,ExpressionType,NormalizedEvidenceValue,RequiredTestCondition

@dataclass
class SourceRequiredTestCondition(RequiredTestCondition):
 standard_structure_id:Optional[str]=None;standard_step_id:Optional[str]=None;confidence:float=0.0
@dataclass
class SourceActualTestCondition(ActualTestCondition):
 report_structure_id:Optional[str]=None;report_row_id:Optional[str]=None;confidence:float=0.0;calculation_refs:List[str]=field(default_factory=list)
@dataclass
class StandardStepConditionExtractionResult:
 standard_structure_id:str;standard_step_id:str;condition_ids:List[str];status:EnrichmentStatus;reason_code:str;reason:str
@dataclass
class ReportRowConditionExtractionResult:
 report_structure_id:str;report_row_id:str;condition_ids:List[str];status:EnrichmentStatus;reason_code:str;reason:str
@dataclass
class StructuralMatchConditionReconciliation:
 structure_link_id:str;clause_id:Optional[str];group_id:Optional[str];standard_step_id:str;standard_parameter:Optional[str];standard_role:Optional[str];required_condition_ids:List[str];report_row_id:str;report_parameter:Optional[str];report_role:Optional[str];actual_condition_ids:List[str];bridge_status:str
@dataclass
class SourceTestConditionExtractionReport:
 effective_kb_id:str;profile_id:str;report_document_id:str;required_conditions:List[SourceRequiredTestCondition]=field(default_factory=list);actual_conditions:List[SourceActualTestCondition]=field(default_factory=list);standard_step_extraction_results:List[StandardStepConditionExtractionResult]=field(default_factory=list);report_row_extraction_results:List[ReportRowConditionExtractionResult]=field(default_factory=list);structural_match_reconciliation:List[StructuralMatchConditionReconciliation]=field(default_factory=list);summary:Dict[str,Any]=field(default_factory=dict);diagnostics:List[Dict[str,Any]]=field(default_factory=list)

class GenericSourceTestConditionExtractor:
 _ELIGIBLE={"PRECONDITION","SETUP","APPLY_INPUT","OPERATE","WAIT","REPEAT"}
 _PARAM=[("temperature rise",EvidenceParameterType.TEMPERATURE_RISE,"OBSERVED_TEMPERATURE_RISE"),("leakage current",EvidenceParameterType.CURRENT,"OBSERVED_LEAKAGE_CURRENT"),("rated current",EvidenceParameterType.CURRENT,"PRODUCT_RATED_CURRENT"),("rated voltage",EvidenceParameterType.VOLTAGE,"PRODUCT_RATED_VOLTAGE"),("test voltage",EvidenceParameterType.VOLTAGE,"TEST_VOLTAGE"),("applied voltage",EvidenceParameterType.VOLTAGE,"TEST_VOLTAGE"),("supplied at",EvidenceParameterType.VOLTAGE,"TEST_VOLTAGE"),("test current",EvidenceParameterType.CURRENT,"TEST_CURRENT"),("duration",EvidenceParameterType.TIME,"TEST_DURATION"),("speed",EvidenceParameterType.SPEED,"TEST_SPEED"),("force",EvidenceParameterType.FORCE,"TEST_FORCE"),("load",EvidenceParameterType.GENERIC_NUMERIC,"TEST_LOAD"),("flow",EvidenceParameterType.FLOW_RATE,"TEST_FLOW"),("cycles",EvidenceParameterType.COUNT,"TEST_CYCLE_COUNT"),("temperature",EvidenceParameterType.TEMPERATURE,"TEST_TEMPERATURE"),("distance",EvidenceParameterType.DISTANCE,"TEST_DISTANCE"),("opening",EvidenceParameterType.DISTANCE,"TEST_DISTANCE"),("voltage",EvidenceParameterType.VOLTAGE,"TEST_VOLTAGE"),("current",EvidenceParameterType.CURRENT,"TEST_CURRENT"),("power",EvidenceParameterType.POWER,"TEST_POWER")]
 _UNITS=r"mA|A|mV|kV|V|kW|W|Hz|°C|K|s|min|h|mm|cm|m|r/min|N|kg|g|L/min|mL/min|cycles|times|%"
 _UNIT_DIM={"ma":"CURRENT","a":"CURRENT","mv":"VOLTAGE","kv":"VOLTAGE","v":"VOLTAGE","kw":"POWER","w":"POWER","hz":"FREQUENCY","\u00b0c":"TEMPERATURE","k":"TEMPERATURE_RISE","s":"TIME","min":"TIME","h":"TIME","mm":"DISTANCE","cm":"DISTANCE","m":"DISTANCE","r/min":"SPEED","n":"FORCE","kg":"LOAD","g":"LOAD","l/min":"FLOW_RATE","ml/min":"FLOW_RATE","cycles":"COUNT","times":"COUNT","%":"PERCENTAGE"}
 def extract(self,effective_kb,product_profile,report_evidence,grouping,evidence_scope,evidence_enrichment,test_structure,pair_result):
  diagnostics=[];required=[];actual=[];std_results=[];row_results=[];std={str(self._get(x,"structure_id")):x for x in self._get(test_structure,"standard_test_structures",[]) or []};rep={str(self._get(x,"structure_id")):x for x in self._get(test_structure,"report_clause_structures",[]) or []};row_scopes={str(self._get(x,"row_id")):x for x in self._get(test_structure,"row_scope_candidates",[]) or []};links=list(self._get(test_structure,"structure_links",[]) or []);matched=[x for x in links if self._enum(self._get(x,"candidate_status"))=="MATCHED"]
  priority_steps={str(v) for x in matched for v in self._get(x,"standard_step_ids",[]) or []};priority_rows={str(v) for x in matched for v in self._get(x,"report_row_ids",[]) or []};existing_actual={str(self._get(x,"condition_id")):x for x in self._get(evidence_enrichment,"actual_test_conditions",[]) or []};calculations={str(self._get(x,"calculation_id")):x for x in self._get(evidence_enrichment,"calculations",[]) or []}
  step_items=[]
  for sid,s in std.items():
   for step in self._get(s,"test_method_steps",[]) or []:step_items.append((str(self._get(step,"step_id")) not in priority_steps,sid,s,step))
  for _,sid,s,step in sorted(step_items,key=lambda x:(x[0],int(self._get(x[3],"step_order",0) or 0),str(self._get(x[3],"step_id")))):
   cond,code,reason=self._required(sid,s,step);step_id=str(self._get(step,"step_id"))
   if cond:required.append(cond);status=cond.status;ids=[cond.condition_id];diagnostics.append({"code":"SOURCE_CONDITION_REQUIRED_EXTRACTED","standard_step_id":step_id,"condition_id":cond.condition_id})
   else:status=EnrichmentStatus.UNRESOLVED;ids=[];diagnostics.append({"code":code,"standard_step_id":step_id})
   std_results.append(StandardStepConditionExtractionResult(sid,step_id,ids,status,code,reason))
  row_items=[]
  for sid,s in rep.items():
   for row in self._get(s,"rows",[]) or []:row_items.append((str(self._get(row,"row_id")) not in priority_rows,sid,s,row))
  for _,sid,s,row in sorted(row_items,key=lambda x:(x[0],int(self._get(x[3],"row_order",0) or 0),str(self._get(x[3],"row_id")))):
   conds,code,reason=self._actual(sid,s,row,row_scopes.get(str(self._get(row,"row_id"))),existing_actual,calculations);actual.extend(conds);row_id=str(self._get(row,"row_id"));status=EnrichmentStatus.RESOLVED if conds and all(x.status==EnrichmentStatus.RESOLVED for x in conds) else EnrichmentStatus.NEEDS_REVIEW if conds else EnrichmentStatus.UNRESOLVED;row_results.append(ReportRowConditionExtractionResult(sid,row_id,[x.condition_id for x in conds],status,code,reason));diagnostics.append({"code":code,"report_row_id":row_id,"condition_ids":[x.condition_id for x in conds]})
  required=self._dedup_conditions(required,"standard_step_id",diagnostics);actual=self._dedup_conditions(actual,"report_row_id",diagnostics);req_by_step=self._by(required,"standard_step_id");act_by_row=self._by(actual,"report_row_id");recon=[]
  step_lookup={str(self._get(x,"step_id")):x for s in std.values() for x in self._get(s,"test_method_steps",[]) or []};row_lookup={str(self._get(x,"row_id")):x for s in rep.values() for x in self._get(s,"rows",[]) or []}
  for link in matched:
   for step_id in [str(x) for x in self._get(link,"standard_step_ids",[]) or []]:
    for row_id in [str(x) for x in self._get(link,"report_row_ids",[]) or []]:
     rc=req_by_step.get(step_id,[]);ac=act_by_row.get(row_id,[]);bridge="FULL_CONDITION_BRIDGE" if rc and ac else "REQUIRED_ONLY" if rc else "ACTUAL_ONLY" if ac else "NEITHER";step=step_lookup.get(step_id,{});row=row_lookup.get(row_id,{});rp,rr=self._semantics(str(self._get(row,"raw_text","") or ""));recon.append(StructuralMatchConditionReconciliation(str(self._get(link,"link_id")),self._get(link,"clause_id"),self._get(link,"group_id"),step_id,self._get(step,"parameter_type"),self._get(step,"condition_role"),[x.condition_id for x in rc],row_id,rp.value if rp else None,rr,[x.condition_id for x in ac],bridge))
  old_req=len(self._get(evidence_enrichment,"required_test_conditions",[]) or []);old_actual=len(self._get(evidence_enrichment,"actual_test_conditions",[]) or []);rs=Counter(x.status.value for x in required);ac=Counter(x.status.value for x in actual);rr=Counter(x.condition_role for x in required);ar=Counter(x.condition_role for x in actual);bridges=Counter(x.bridge_status for x in recon)
  summary={"standard":{"steps_examined":len(step_items),"conditions_detected":sum(bool(x.condition_ids) for x in std_results),"required_conditions_extracted":len(required),"status":{x.value:rs[x.value] for x in EnrichmentStatus},"by_role":dict(rr)},"report":{"rows_examined":len(row_items),"actual_conditions_extracted":len(actual),"status":{x.value:ac[x.value] for x in EnrichmentStatus},"by_role":dict(ar)},"comparison":{"old_required_condition_count":old_req,"new_source_extracted_required_count":len(required),"new_unique_required_conditions":len(required),"old_actual_condition_count":old_actual,"new_source_extracted_actual_count":len(actual),"new_unique_actual_conditions":len(actual)},"structural_bridge":{"matched_structure_links_examined":len(recon),**{x:bridges[x] for x in ("FULL_CONDITION_BRIDGE","REQUIRED_ONLY","ACTUAL_ONLY","NEITHER")}}}
  return SourceTestConditionExtractionReport(str(self._get(effective_kb,"effective_kb_id","") or ""),str(self._get(product_profile,"profile_id","") or ""),str(self._get(report_evidence,"document_id","") or ""),sorted(required,key=lambda x:x.condition_id),sorted(actual,key=lambda x:x.condition_id),sorted(std_results,key=lambda x:x.standard_step_id),sorted(row_results,key=lambda x:x.report_row_id),sorted(recon,key=lambda x:x.structure_link_id+x.standard_step_id),summary,sorted(self._dedup_diag(diagnostics),key=lambda x:json.dumps(x,sort_keys=True)))
 def _required(self,sid,structure,step):
  stype=self._enum(self._get(step,"step_type"));text=str(self._get(step,"text","") or "");step_id=str(self._get(step,"step_id"));ptype=self._ptype(self._get(step,"parameter_type"));role=self._get(step,"condition_role");
  if stype in {"ACCEPTANCE_CHECK","POST_TEST_CHECK"} or self._acceptance(text):return None,"SOURCE_CONDITION_ACCEPTANCE_NOT_SETUP","Acceptance or post-test semantics are not test setup."
  if stype=="MEASURE" and not re.search(r"\b(at|with|under|for)\b.{0,50}\d",text,re.I):return None,"SOURCE_CONDITION_MEASUREMENT_NOT_SETUP","Measurement expectation has no setup parameter."
  if stype not in self._ELIGIBLE and stype not in {"MEASURE","OTHER"}:return None,"SOURCE_CONDITION_REQUIRED_UNRESOLVED","Step type is not eligible."
  inferred_type,inferred_role=self._semantics(text);ptype=ptype or inferred_type;role=role or inferred_role
  if role in {"PRODUCT_RATED_VOLTAGE","PRODUCT_RATED_CURRENT","OBSERVED_LEAKAGE_CURRENT","OBSERVED_TEMPERATURE_RISE"}:return None,"SOURCE_CONDITION_REQUIRED_UNRESOLVED","Product-rating or observed-result semantics are not test conditions."
  expression=self._expression(text,"STANDARD",step_id);value,unit=self._value(text);value=self._get(step,"value",value);unit=self._get(step,"unit",unit);unit=self._normalize_unit(unit)
  if not ptype:return None,"SOURCE_CONDITION_PARAMETER_UNKNOWN","No safe semantic parameter exists."
  if not role or not role.startswith("TEST_"):return None,"SOURCE_CONDITION_ROLE_UNKNOWN","No safe condition role exists."
  if expression is not None and not self._expression_compatible(ptype,expression):expression=None
  if value is not None and not self._unit_compatible(ptype,unit,role):
   value=unit=None
  if value is None and expression is None:return None,"SOURCE_CONDITION_VALUE_MISSING","Condition language has no safe value or expression."
  provs=[EvidenceProvenance("STANDARD_REQUIREMENT","test_structure",step_id,self._get(structure,"clause_id"),self._first_req(step),self._get(structure,"group_id"),None,None,text[:500])];status=EnrichmentStatus.RESOLVED;nv=NormalizedEvidenceValue(value,None,"number" if isinstance(value,(int,float)) else "string",unit,unit,None,text,.95,status) if value is not None else None;cid=self._id("SOURCE-REQ",sid,step_id,role,str(value),str(unit),str(self._get(expression,"raw_expression")));return SourceRequiredTestCondition(cid,self._first_req(step) or str(self._get(structure,"primary_requirement_id","") or ""),self._get(structure,"group_id"),self._get(structure,"clause_id"),ptype,role,None,nv,expression,None,True,status,provs,"Extracted from exact StandardTestStep ownership.",standard_structure_id=sid,standard_step_id=step_id,confidence=.95),"SOURCE_CONDITION_REQUIRED_EXTRACTED","Required condition extracted from structured standard step."
 def _actual(self,sid,structure,row,row_scope,existing,calculations):
  row_id=str(self._get(row,"row_id"));raw=str(self._get(row,"raw_text","") or "");ptype,role=self._semantics(raw);scope_status=self._enum(self._get(row_scope,"outer_scope_status"));groups=[str(x) for x in self._get(row_scope,"narrowed_group_ids",[]) or []];ambiguous=scope_status=="AMBIGUOUS" or not groups;conds=[]
  if role in {"PRODUCT_RATED_VOLTAGE","PRODUCT_RATED_CURRENT","OBSERVED_LEAKAGE_CURRENT","OBSERVED_TEMPERATURE_RISE"}:return [],"SOURCE_CONDITION_MEASUREMENT_NOT_SETUP","Row concerns a rating or observed result, not test setup."
  owned=[existing[str(x)] for x in self._get(row,"actual_conditions",[]) or [] if str(x) in existing]
  for old in owned:
   op=self._ptype(self._get(old,"parameter_type"));orole=self._get(old,"condition_role");
   if orole and str(orole).startswith("TEST_"):ptype=op or ptype;role=orole
  expression=self._expression(raw,"REPORT",row_id);value,unit=self._value(raw)
  for old in owned:
   ov=self._get(old,"observed_value");value=self._get(ov,"value",value);unit=self._get(ov,"unit_normalized",self._get(ov,"unit",unit));expression=self._get(old,"observed_expression") or expression
  unit=self._normalize_unit(unit)
  if not ptype:return [],"SOURCE_CONDITION_PARAMETER_UNKNOWN","No safe report-row parameter semantics."
  if not role or not str(role).startswith("TEST_"):return [],"SOURCE_CONDITION_ROLE_UNKNOWN","Report row does not establish test-condition role."
  if expression is not None and not self._expression_compatible(ptype,expression):expression=None
  if value is not None and not self._unit_compatible(ptype,unit,str(role)):
   value=unit=None
  if value is None and expression is None:return [],"SOURCE_CONDITION_VALUE_MISSING","Report row has no safe condition value or expression."
  status=EnrichmentStatus.NEEDS_REVIEW if ambiguous else EnrichmentStatus.RESOLVED;eid=self._first_source(row);prov=[EvidenceProvenance("REPORT_TEST_PARAMETER","test_structure",eid,self._get(structure,"report_clause_id"),None,groups[0] if len(groups)==1 else None,self._first_page(row),self._first_page(row),raw[:500])];nv=NormalizedEvidenceValue(value,None,"number" if isinstance(value,(int,float)) else "string",unit,unit,None,raw,.95,status) if value is not None else None;calc_refs=[str(x) for x in self._get(row,"calculation_refs",[]) or [] if str(x) in calculations];cid=self._id("SOURCE-ACT",sid,row_id,str(role),str(value),str(unit),str(self._get(expression,"raw_expression")));conds.append(SourceActualTestCondition(cid,eid or row_id,self._get(structure,"report_clause_id"),groups,ptype,str(role),nv,expression,status,prov,"Extracted from exact ReportResultRow ownership.",report_structure_id=sid,report_row_id=row_id,confidence=.9 if status==EnrichmentStatus.RESOLVED else .65,calculation_refs=calc_refs));return conds,"SOURCE_CONDITION_ACTUAL_EXTRACTED","Actual condition extracted from structured report row."
 @classmethod
 def _semantics(cls,text):
  s=str(text or "").casefold()
  for cue,p,r in cls._PARAM:
   if cue in s:return p,r
  if re.search(r"\bfor\s+\d+(?:[.,]\d+)?\s*(?:s|sec|seconds?|min|minutes?|h|hours?)\b",s):return EvidenceParameterType.TIME,"TEST_DURATION"
  return None,None
 @classmethod
 def _expression(cls,text,source,owner):
  m=re.search(r"(\d+(?:[.,]\d+)?)\s*(?:times|[×xX*])\s*(rated[_ ](?:voltage|current|power|frequency))",text,re.I)
  if m:return EvidenceExpression(cls._id("SOURCE-EXPR",source,owner,m.group(0)),ExpressionType.MULTIPLIER,"MULTIPLY",None,None,float(m.group(1).replace(",",".")),m.group(2).casefold().replace(" ","_"),[m.group(2).casefold().replace(" ","_")],None,None,m.group(0),EnrichmentStatus.RESOLVED,[])
  m=re.search(r"(\d+(?:[.,]\d+)?)\s*%\s+of\s+(rated[_ ](?:voltage|current|power|frequency))",text,re.I)
  if m:return EvidenceExpression(cls._id("SOURCE-EXPR",source,owner,m.group(0)),ExpressionType.PERCENTAGE,"PERCENTAGE_OF",None,None,float(m.group(1).replace(",",".")),m.group(2).casefold().replace(" ","_"),[m.group(2).casefold().replace(" ","_")],None,"%",m.group(0),EnrichmentStatus.RESOLVED,[])
  return None
 @classmethod
 def _value(cls,text):
  m=re.search(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*("+cls._UNITS+r")(?![\w/])",str(text or ""),re.I);return ((float(m.group(1).replace(",",".")) if re.search(r"[.,]",m.group(1)) else int(m.group(1))),cls._normalize_unit(m.group(2))) if m else (None,None)
 @staticmethod
 def _normalize_unit(unit):
  if unit is None:return None
  canonical={"ma":"mA","a":"A","mv":"mV","kv":"kV","v":"V","kw":"kW","w":"W","hz":"Hz","°c":"°C","k":"K","n":"N","l/min":"L/min","ml/min":"mL/min"}
  raw=str(unit).strip();return canonical.get(raw.casefold(),raw.casefold() if raw.casefold() in {"min","mm","cm","m","s","h","kg","g","r/min","cycles","times"} else raw)
 @classmethod
 def _unit_compatible(cls,ptype,unit,role):
  if unit is None:return False
  dim=cls._UNIT_DIM.get(str(unit).casefold());expected=cls._enum(ptype)
  if role=="TEST_LOAD":return dim=="LOAD"
  if expected=="TEMPERATURE":return dim in {"TEMPERATURE","TEMPERATURE_RISE"}
  if expected=="TEMPERATURE_RISE":return dim in {"TEMPERATURE_RISE","TEMPERATURE"}
  if expected=="GENERIC_NUMERIC":return dim is None
  return dim==expected
 @classmethod
 def _expression_compatible(cls,ptype,expression):
  variable=str(cls._get(expression,"variable","") or "").casefold();expected=cls._enum(ptype).casefold()
  if not variable:return False
  aliases={"current":"current","voltage":"voltage","power":"power","frequency":"frequency"}
  return any(name in variable and expected==kind for name,kind in aliases.items())
 @staticmethod
 def _acceptance(text):return bool(re.search(r"\bshall\s+not\s+(?:exceed|be greater)|\bshall withstand\b|\bthere shall be no\b",text,re.I))
 @staticmethod
 def _ptype(v):
  if not v:return None
  try:return EvidenceParameterType(str(v.value if isinstance(v,Enum) else v))
  except ValueError:return None
 @classmethod
 def _first_req(cls,step):return next((str(cls._get(x,"requirement_id")) for x in cls._get(step,"provenance",[]) or [] if cls._get(x,"requirement_id")),None)
 @classmethod
 def _first_source(cls,row):return next((str(cls._get(x,"source_id")) for x in cls._get(row,"provenance",[]) or [] if cls._get(x,"source_id")),None)
 @classmethod
 def _first_page(cls,row):return next((cls._get(x,"page_start") for x in cls._get(row,"provenance",[]) or [] if cls._get(x,"page_start") is not None),None)
 @classmethod
 def _dedup_conditions(cls,items,owner,diagnostics):
  out={}
  for x in items:
   v=cls._get(x,"expected_value",cls._get(x,"observed_value"));e=cls._get(x,"expected_expression",cls._get(x,"observed_expression"));key=(cls._get(x,owner),cls._enum(cls._get(x,"parameter_type")),cls._get(x,"condition_role"),json.dumps(cls._plain(v),sort_keys=True),json.dumps(cls._plain(e),sort_keys=True))
   if key in out:diagnostics.append({"code":"SOURCE_CONDITION_DUPLICATE_SUPPRESSED","condition_id":x.condition_id})
   else:out[key]=x
  return list(out.values())
 @classmethod
 def _by(cls,items,key):
  out=defaultdict(list)
  for x in items:out[str(cls._get(x,key))].append(x)
  return out
 @staticmethod
 def _dedup_diag(items):return list({json.dumps(x,sort_keys=True):x for x in items}.values())
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
 def to_dict(cls,v):return cls._plain(asdict(v)) if is_dataclass(v) else (_ for _ in ()).throw(TypeError("source condition report required"))
 @classmethod
 def to_json(cls,v,indent=2):return json.dumps(cls.to_dict(v),ensure_ascii=False,sort_keys=True,indent=indent)
 @classmethod
 def save_json(cls,v,p):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(cls.to_json(v)+"\n",encoding="utf-8");return p
__all__=["GenericSourceTestConditionExtractor","ReportRowConditionExtractionResult","SourceActualTestCondition","SourceRequiredTestCondition","SourceTestConditionExtractionReport","StandardStepConditionExtractionResult","StructuralMatchConditionReconciliation"]
