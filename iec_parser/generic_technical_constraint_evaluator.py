"""Evaluate matched report measurements against effective technical constraints."""
from __future__ import annotations
import copy,json,math,re
from collections import Counter
from dataclasses import asdict,dataclass,field,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Dict,Iterable,List,Mapping,Optional,Sequence,Set,Tuple,Union
from urllib.parse import quote

class TechnicalConstraintDecision(str,Enum):
 SATISFIES="SATISFIES"; VIOLATES="VIOLATES"; NO_MEASUREMENT="NO_MEASUREMENT"; INCOMPARABLE="INCOMPARABLE"; UNKNOWN="UNKNOWN"; NEEDS_REVIEW="NEEDS_REVIEW"; INACTIVE="INACTIVE"; NOT_APPLICABLE="NOT_APPLICABLE"

@dataclass
class MeasurementSnapshot:
 measurement_id:str; parameter:Optional[str]=None; parameter_text:Optional[str]=None; value:Any=None; value_secondary:Any=None; unit:Optional[str]=None; unit_normalized:Optional[str]=None; raw_text:Optional[str]=None; page:Optional[int]=None
@dataclass
class ConstraintSnapshot:
 constraint_id:str; parameter:Optional[str]=None; operator:Optional[str]=None; value:Any=None; value_secondary:Any=None; unit:Optional[str]=None; unit_normalized:Optional[str]=None; constraint_type:Optional[str]=None; status:Optional[str]=None; expression:Optional[Dict[str,Any]]=None; condition_text:Optional[str]=None; raw_text:Optional[str]=None
@dataclass
class TechnicalConstraintEvaluationResult:
 evaluation_id:str; effective_requirement_id:str; effective_clause_id:Optional[str]; clause_id:Optional[str]; constraint_id:str; decision:TechnicalConstraintDecision; reason_code:str; reason:str; applicability_decision:Optional[str]; constraint:ConstraintSnapshot; matched_measurements:List[MeasurementSnapshot]=field(default_factory=list); selected_measurement_id:Optional[str]=None; computed_limit:Any=None; comparison_details:Optional[Dict[str,Any]]=None; notes:Optional[str]=None
@dataclass
class TechnicalConstraintEvaluationReport:
 effective_kb_id:str; report_document_id:str; results:List[TechnicalConstraintEvaluationResult]=field(default_factory=list); summary:Dict[str,Any]=field(default_factory=dict); diagnostics:List[Dict[str,Any]]=field(default_factory=list);rule_results:List[Any]=field(default_factory=list)

class GenericTechnicalConstraintEvaluator:
 _OPERATOR_ALIASES={"GT":"greater_than",">":"greater_than","GTE":"greater_than_or_equal",">=":"greater_than_or_equal","≥":"greater_than_or_equal","LT":"less_than","<":"less_than","LTE":"less_than_or_equal","<=":"less_than_or_equal","≤":"less_than_or_equal","EQ":"equals","=":"equals","NEQ":"not_equals","!=":"not_equals","≠":"not_equals"}
 _ALIASES={"leakage current":"leakage_current","water flow":"water_flow_rate","flow of water":"water_flow_rate","drum speed":"drum_speed","temperature rise":"temperature_rise","opening distance":"opening_distance","lid opening":"opening_distance","door opening":"opening_distance","opening":"opening_distance","operation cycles":"operation_cycles","number of cycles":"operation_cycles","aperture diameter":"aperture_diameter","aperture area":"aperture_area","aperture width":"aperture_width","duration":"test_duration","elapsed time":"test_duration","test voltage":"test_voltage","voltage":"voltage","rated power input":"rated_power_input","power input":"power_input","force":"applied_force","distance":"distance","thickness":"thickness","charge":"charge","electric charge":"charge","energy":"energy","resistance":"resistance","humidity":"humidity","frequency":"frequency","temperature":"temperature","current":"current","torque":"torque"}
 _UNIT={"A":("current",1000.0,"mA"),"mA":("current",1.0,"mA"),"µA":("current",.001,"mA"),"V":("voltage",1.0,"V"),"mV":("voltage",.001,"V"),"kV":("voltage",1000.0,"V"),"W":("power",.001,"kW"),"kW":("power",1.0,"kW"),"m":("length",1000.0,"mm"),"cm":("length",10.0,"mm"),"mm":("length",1.0,"mm"),"L/min":("flow",1000.0,"mL/min"),"l/min":("flow",1000.0,"mL/min"),"mL/min":("flow",1.0,"mL/min"),"s":("time",1.0,"s"),"min":("time",60.0,"s"),"h":("time",3600.0,"s"),"%":("percent",1.0,"%"),"°C":("temperature",1.0,"°C"),"K":("rise",1.0,"K"),"r/min":("speed",1.0,"r/min"),"N":("force",1.0,"N"),"mJ":("energy",.001,"J"),"J":("energy",1.0,"J"),"µC":("charge",.000001,"C"),"C":("charge",1.0,"C"),"MΩ":("resistance",1000000.0,"Ω"),"kΩ":("resistance",1000.0,"Ω"),"Ω":("resistance",1.0,"Ω"),"cycles":("cycles",1.0,"cycles"),"mm²":("area",1.0,"mm²"),"N·m":("torque",1.0,"N·m"),"Nm":("torque",1.0,"N·m")}
 def __init__(self):self._diagnostics=[]
 def evaluate(self,effective_kb,applicability_report,evidence_match_report,report_evidence,product_profile=None,parameter_ledger=None,structure_compatibility=None):
  self._diagnostics=[];parameter_ledger=self._get(parameter_ledger,"parameter_ledger",parameter_ledger) or []; apps={self._get(x,"effective_requirement_id"):self._enum(self._get(x,"decision")) for x in self._get(applicability_report,"results",[]) or []}; matches={self._get(x,"effective_requirement_id"):x for x in self._get(evidence_match_report,"matches",[]) or []}; measurements=self._measurement_index(report_evidence); facts=self._get(product_profile,"facts",{}) or {}; results=[]
  for req,container in self._requirements(effective_kb):
   rid=self._get(req,"effective_requirement_id")
   for constraint in self._get(req,"technical_constraints",[]) or []:results.append(self.evaluate_constraint(req,constraint,apps.get(rid),matches.get(rid),measurements,facts,container))
  from .generic_technical_rule_families import GenericTechnicalRuleCompiler,GenericTechnicalRuleDispatcher
  compiler=GenericTechnicalRuleCompiler();dispatcher=GenericTechnicalRuleDispatcher();rule_results=[]
  rejected_clauses={str(self._get(x,"report_clause")) for x in self._get(structure_compatibility,"findings",[]) or [] if self._enum(self._get(x,"compatibility"))=="SEMANTIC_MISMATCH" and float(self._get(x,"confidence",0) or 0)>=.8}
  evidence_rows=[{"evidence_id":self._get(e,"evidence_id"),"raw_text":self._get(e,"raw_text")} for c in self._walk_clauses(self._get(report_evidence,"clauses",[]) or []) for e in self._get(c,"evidence_items",[]) or []]
  for req,container in self._requirements(effective_kb):
   rid=self._get(req,"effective_requirement_id");compiled=list(self._get(req,"executable_rules",[]) or []) or compiler.compile_requirement(req,self._get(req,"clause_id"));ledger_rules=compiler.compile_ledger_rules(req,self._get(req,"clause_id"),parameter_ledger);rules=([x for x in compiled if self._enum(self._get(x,"rule_family"))!="UNSUPPORTED"] if ledger_rules else compiled)+ledger_rules;match=matches.get(rid);rejected=self._get(match,"match_type")=="REJECTED_SEMANTIC_STRUCTURE_MISMATCH" or str(self._get(req,"clause_id")) in rejected_clauses
   for rule in rules:rule_results.append(dispatcher.evaluate(rule,product_facts=facts,ledger=parameter_ledger,evidence=evidence_rows,structure_rejected=rejected,applicability_decision=apps.get(rid)))
  report=TechnicalConstraintEvaluationReport(str(self._get(effective_kb,"effective_kb_id","")),str(self._get(report_evidence,"document_id","")),results,diagnostics=copy.deepcopy(self._diagnostics),rule_results=rule_results);report.summary=self.get_summary(report);return report
 def evaluate_constraint(self,requirement,constraint,applicability_decision,evidence_match,measurement_index,product_facts=None,effective_clause_id=None):
  rid=str(self._get(requirement,"effective_requirement_id"));cid=str(self._get(constraint,"constraint_id"));status=self._enum(self._get(requirement,"effective_status"));app=self._enum(applicability_decision);snap=self._constraint_snapshot(constraint);base=dict(evaluation_id=self._id(rid,cid),effective_requirement_id=rid,effective_clause_id=effective_clause_id,clause_id=self._get(requirement,"clause_id"),constraint_id=cid,applicability_decision=app,constraint=snap)
  if status=="INACTIVE":return self._result(base,TechnicalConstraintDecision.INACTIVE,"TECH_REQUIREMENT_INACTIVE","Effective requirement is inactive.")
  if app=="NOT_APPLICABLE":return self._result(base,TechnicalConstraintDecision.NOT_APPLICABLE,"TECH_REQUIREMENT_NOT_APPLICABLE","Active requirement is not applicable to this product.")
  if app=="UNKNOWN":return self._result(base,TechnicalConstraintDecision.UNKNOWN,"TECH_APPLICABILITY_UNKNOWN","Requirement applicability is unknown.")
  if app=="NEEDS_REVIEW":return self._result(base,TechnicalConstraintDecision.NEEDS_REVIEW,"TECH_APPLICABILITY_NEEDS_REVIEW","Requirement applicability needs review.")
  if app!="APPLICABLE":return self._result(base,TechnicalConstraintDecision.UNKNOWN,"TECH_APPLICABILITY_UNKNOWN","No usable applicability decision exists.")
  cstatus=self._enum(self._get(constraint,"status"));ctype=self._enum(self._get(constraint,"constraint_type"))
  if cstatus=="UNRESOLVED":return self._result(base,TechnicalConstraintDecision.UNKNOWN,"TECH_CONSTRAINT_UNRESOLVED","Technical constraint is unresolved.")
  if cstatus=="NEEDS_REVIEW":return self._result(base,TechnicalConstraintDecision.NEEDS_REVIEW,"TECH_CONSTRAINT_NEEDS_REVIEW","Technical constraint requires review.")
  mids=[mid for ref in self._get(evidence_match,"evidence_refs",[]) or [] for mid in self._get(ref,"measurement_ids",[]) or []]
  measures=[measurement_index[mid] for mid in mids if mid in measurement_index]
  # Exact clause ownership is stronger than numeric similarity and permits an
  # appended-table observation to reach the governing requirement even when
  # the report row matcher selected only the parent clause row. Parameter,
  # role and unit compatibility are still enforced below.
  owner=str(self._get(requirement,"clause_id") or "")
  constraint_parameter=self._parameter(self._get(constraint,"parameter") or self._get(constraint,"parameter_text"))
  constraint_unit=self._get(constraint,"unit_normalized") or self._get(constraint,"unit")
  def safely_owned(m):
   if str(self._get(m,"_owner_clause_id") or "")!=owner:return False
   if self._parameter(self._get(m,"parameter") or self._get(m,"parameter_text"))!=constraint_parameter:return False
   try:self._convert(1.0,self._get(m,"unit_normalized") or self._get(m,"unit"),constraint_unit)
   except (TypeError,ValueError):return False
   return True
  owned=[m for m in measurement_index.values() if safely_owned(m)]
  seen={self._get(m,"measurement_id") for m in measures}
  measures.extend(m for m in owned if self._get(m,"measurement_id") not in seen)
  if ctype=="FORMULA":
   limit,detail,code=self._formula_limit(self._get(constraint,"expression"),product_facts or {})
   if code:return self._result(base,TechnicalConstraintDecision.UNKNOWN,code,"A required formula input is unavailable.",matched=self._snaps(measures))
   return self._evaluate_simple(base,constraint,measures,limit,detail,accept_role="OBSERVED_VALUE")
  if ctype=="COMPOUND":return self._evaluate_compound(base,constraint,measures)
  role="TEST_PARAMETER" if ctype=="TEST_PARAMETER" else "OBSERVED_VALUE"
  return self._evaluate_simple(base,constraint,measures,self._get(constraint,"value"),None,accept_role=role)
 def _evaluate_simple(self,base,constraint,measures,limit,details,accept_role):
  parameter=self._parameter(self._get(constraint,"parameter") or self._get(constraint,"parameter_text")); compatible=[];unlabelled=[];wrong_parameter=False;wrong_role=False
  for m in measures:
   mp=self._parameter(self._get(m,"parameter") or self._get(m,"parameter_text"));role=self._role(m)
   if role!=accept_role:wrong_role=True;continue
   if not mp:
    try:self._convert(1.0,self._get(m,"unit_normalized") or self._get(m,"unit"),self._get(constraint,"unit_normalized") or self._get(constraint,"unit"));unlabelled.append(m)
    except (TypeError,ValueError):pass
    continue
   if mp!=parameter:wrong_parameter=True;continue
   compatible.append(m)
  # Exact evidence ownership plus one unit-compatible, unlabelled observation
  # is sufficient for comparison.  Multiple unlabelled values remain
  # conservative because parameter ownership would be ambiguous.
  if not compatible and len(unlabelled)==1 and not wrong_parameter:
   compatible=unlabelled
  snaps=self._snaps(measures)
  if not compatible:
   if measures and wrong_role:return self._result(base,TechnicalConstraintDecision.INCOMPARABLE,"TECH_MEASUREMENT_ROLE_INCOMPATIBLE","Matching parameter has an unsafe measurement role.",matched=snaps,limit=limit,details=details)
   if measures and wrong_parameter:return self._result(base,TechnicalConstraintDecision.INCOMPARABLE,"TECH_PARAMETER_MISMATCH","Matched evidence measurements concern another parameter.",matched=snaps,limit=limit,details=details)
   return self._result(base,TechnicalConstraintDecision.NO_MEASUREMENT,"TECH_NO_MEASUREMENT","No reliable matched measurement exists for this constraint.",matched=snaps,limit=limit,details=details)
  outcomes=[]
  for m in compatible:
   try:
    actual=self._convert(self._number(self._get(m,"value")),self._get(m,"unit_normalized") or self._get(m,"unit"),self._get(constraint,"unit_normalized") or self._get(constraint,"unit")); outcome=self._compare(actual,self._operator(self._get(constraint,"operator")),self._number(limit),self._number(self._get(constraint,"value_secondary")) if self._get(constraint,"value_secondary") is not None else None,self._get(constraint,"tolerance"));outcomes.append((outcome,m,actual))
   except (TypeError,ValueError):continue
  if not outcomes:return self._result(base,TechnicalConstraintDecision.INCOMPARABLE,"TECH_UNIT_INCOMPATIBLE","Values or units are not safely comparable.",matched=snaps)
  if len({o for o,_,_ in outcomes})>1 and len({self._get(m,"page") for _,m,_ in outcomes})>1:return self._result(base,TechnicalConstraintDecision.NEEDS_REVIEW,"TECH_MEASUREMENT_AMBIGUOUS","Compatible measurements from distinct contexts conflict.",matched=snaps)
  operator=self._operator(self._get(constraint,"operator")); chosen=min(outcomes,key=lambda x:x[2]) if operator in {"greater_than","greater_than_or_equal"} else max(outcomes,key=lambda x:x[2]);ok=all(o for o,_,_ in outcomes) if operator in {"between","equals","not_equals"} else chosen[0];dec=TechnicalConstraintDecision.SATISFIES if ok else TechnicalConstraintDecision.VIOLATES;prefix="TECH_TEST_PARAMETER" if accept_role=="TEST_PARAMETER" else ("TECH_RANGE" if operator in {"between","not_between"} else "TECH_SIMPLE");code=prefix+("_MATCH" if accept_role=="TEST_PARAMETER" and ok else "_MISMATCH" if accept_role=="TEST_PARAMETER" else "_SATISFIES" if ok else "_VIOLATES")
  detail={"observed_normalized":chosen[2],"operator":operator,"limit":limit};detail.update(details or {})
  return self._result(base,dec,code,"Matched measurement satisfies the constraint." if ok else "Matched measurement violates the constraint.",matched=snaps,selected=self._get(chosen[1],"measurement_id"),limit=limit,details=detail)
 def _evaluate_compound(self,base,constraint,measures):
  expression=self._get(constraint,"expression") or {}
  if "time_window" in expression or "trigger" in expression:
   nodes=[{"field":self._get(constraint,"parameter"),"operator":self._get(constraint,"operator"),"value":self._get(constraint,"value"),"unit":self._get(constraint,"unit_normalized") or self._get(constraint,"unit")}]
   if expression.get("time_window"):nodes.append({"field":"test_duration",**expression["time_window"]})
   if expression.get("trigger"):nodes.append({"field":expression["trigger"].get("parameter"),**expression["trigger"]})
   expression={"all":nodes}
  state,used=self._compound_node(expression,measures)
  mapping={"SAT":(TechnicalConstraintDecision.SATISFIES,"TECH_COMPOUND_SATISFIES"),"VIO":(TechnicalConstraintDecision.VIOLATES,"TECH_COMPOUND_VIOLATES"),"REV":(TechnicalConstraintDecision.NEEDS_REVIEW,"TECH_COMPOUND_INCOMPLETE"),"UNK":(TechnicalConstraintDecision.UNKNOWN,"TECH_COMPOUND_INCOMPLETE")};decision,code=mapping[state]
  return self._result(base,decision,code,"Compound constraint evaluated." if state in {"SAT","VIO"} else "Compound evidence is incomplete.",matched=self._snaps(measures),details={"measurement_ids_used":sorted(used)})
 def _compound_node(self,node,measures):
  if not isinstance(node,dict):return "REV",set()
  if "field" in node:
   p=self._parameter(node["field"]); candidates=[m for m in measures if self._parameter(self._get(m,"parameter") or self._get(m,"parameter_text"))==p and self._role(m)=="OBSERVED_VALUE"]
   if not candidates:return "UNK",set()
   states=[];used=set()
   for m in candidates:
    try:v=self._convert(self._number(self._get(m,"value")),self._get(m,"unit_normalized") or self._get(m,"unit"),node.get("unit"));states.append(self._compare(v,node.get("operator"),self._number(node.get("value")),self._number(node.get("value_secondary")) if node.get("value_secondary") is not None else None,None));used.add(self._get(m,"measurement_id"))
    except: return "REV",used
   return ("SAT" if all(states) else "VIO"),used
  key="all" if "all" in node else "any" if "any" in node else None
  if not key or not isinstance(node[key],list):return "REV",set()
  parts=[self._compound_node(x,measures) for x in node[key]];states=[x[0] for x in parts];used=set().union(*(x[1] for x in parts))
  if key=="all":return ("VIO" if "VIO" in states else "REV" if "REV" in states else "UNK" if "UNK" in states else "SAT"),used
  return ("SAT" if "SAT" in states else "REV" if "REV" in states else "UNK" if "UNK" in states else "VIO"),used
 def _formula_limit(self,expr,facts):
  if not isinstance(expr,dict) or expr.get("selection")!="MAX":return None,None,"TECH_FORMULA_INPUT_MISSING"
  values=[];detail={"formula":copy.deepcopy(expr)}
  for op in expr.get("operands",[]):
   if op.get("type")=="CONSTANT":values.append(float(op["value"]));continue
   variable=op.get("variable");fact=self._get(facts,variable)
   if not fact or self._enum(self._get(fact,"status")) not in {"CONFIRMED","INFERRED_STRONG"}:return None,detail,"TECH_FORMULA_INPUT_MISSING"
   raw=self._get(fact,"value");value=self._get(raw,"value") if isinstance(raw,Mapping) else raw;unit=self._get(raw,"unit") if isinstance(raw,Mapping) else None
   try:kw=self._convert(self._number(value),unit,"kW")
   except:return None,detail,"TECH_FORMULA_INPUT_MISSING"
   branch=float(op.get("coefficient",1))*kw;cap=op.get("cap");branch=min(branch,float(cap["value"])) if cap else branch;values.append(branch);detail[variable+"_kW"]=kw
  limit=max(values);detail["computed_limit"]=limit;return limit,detail,None
 @classmethod
 def _compare(cls,a,op,b,b2,tol):
  op=cls._operator(op)
  eps=1e-9
  if tol:
   if not isinstance(tol,Mapping) or "value" not in tol:return False
   delta=float(tol["value"]);delta=abs(b)*delta/100 if tol.get("unit")=="%" else delta;return abs(a-b)<=delta+eps
  if op=="equals":return abs(a-b)<=eps
  if op=="not_equals":return abs(a-b)>eps
  if op=="less_than":return a<b-eps
  if op=="less_than_or_equal":return a<=b+eps
  if op=="greater_than":return a>b+eps
  if op=="greater_than_or_equal":return a>=b-eps
  if op=="between":return b-eps<=a<=b2+eps
  if op=="not_between":return not(b-eps<=a<=b2+eps)
  raise ValueError("unsupported operator")
 @classmethod
 def _operator(cls,value):
  if value is None:return None
  raw=str(value.value if isinstance(value,Enum) else value).strip()
  return cls._OPERATOR_ALIASES.get(raw.upper(),cls._OPERATOR_ALIASES.get(raw,raw))
 @classmethod
 def _convert(cls,value,source,target):
  if not source or not target:
   if source==target:return value
   raise ValueError("missing unit")
  s=cls._UNIT.get(source);t=cls._UNIT.get(target)
  if not s or not t or s[0]!=t[0]:raise ValueError("incompatible unit")
  return value*s[1]/t[1]
 @classmethod
 def _parameter(cls,value):
  norm=re.sub(r"[^a-z0-9]+"," ",str(value or "").casefold()).strip();return cls._ALIASES.get(norm,norm.replace(" ","_"))
 @staticmethod
 def _role(m):
  notes=str(GenericTechnicalConstraintEvaluator._get(m,"notes","") or "").upper()
  if "TEST_PARAMETER" in notes:return "TEST_PARAMETER"
  if "REFERENCE_VALUE" in notes:return "REFERENCE_VALUE"
  if "OBSERVED_VALUE" in notes:return "OBSERVED_VALUE"
  return "UNKNOWN"
 @classmethod
 def _measurement_index(cls,report):
  out={}
  def owned(measurement,clause_id):
   item=copy.deepcopy(measurement)
   if isinstance(item,dict):item["_owner_clause_id"]=clause_id
   else:setattr(item,"_owner_clause_id",clause_id)
   return item
  def walk(items):
   for c in items:
    clause_id=cls._get(c,"clause_id")
    for m in cls._get(c,"measurements",[]) or []:out[cls._get(m,"measurement_id")]=owned(m,clause_id)
    for e in cls._get(c,"evidence_items",[]) or []:
     for m in cls._get(e,"measurements",[]) or []:out[cls._get(m,"measurement_id")]=owned(m,cls._get(e,"clause_id") or clause_id)
    walk(cls._get(c,"children",[]) or [])
  walk(cls._get(report,"clauses",[]) or []);return out
 @classmethod
 def _requirements(cls,kb):
  def walk(items):
   for c in items:
    for r in cls._get(c,"requirements",[]) or []:yield r,cls._get(c,"effective_clause_id")
    yield from walk(cls._get(c,"children",[]) or [])
  yield from walk(cls._get(kb,"clauses",[]) or [])
  for a in cls._get(kb,"annexes",[]) or []:
   for r in cls._get(a,"requirements",[]) or []:yield r,cls._get(a,"effective_annex_id")
   yield from walk(cls._get(a,"clauses",[]) or [])
 @classmethod
 def _walk_clauses(cls,nodes):
  for node in nodes:
   yield node;yield from cls._walk_clauses(cls._get(node,"children",[]) or [])
 @classmethod
 def _constraint_snapshot(cls,c):return ConstraintSnapshot(str(cls._get(c,"constraint_id")),cls._get(c,"parameter"),cls._get(c,"operator"),copy.deepcopy(cls._get(c,"value")),copy.deepcopy(cls._get(c,"value_secondary")),cls._get(c,"unit"),cls._get(c,"unit_normalized"),cls._enum(cls._get(c,"constraint_type")),cls._enum(cls._get(c,"status")),copy.deepcopy(cls._get(c,"expression")),cls._get(c,"condition_text"),cls._get(c,"raw_text"))
 @classmethod
 def _snaps(cls,ms):return [MeasurementSnapshot(str(cls._get(m,"measurement_id")),cls._get(m,"parameter"),cls._get(m,"parameter_text"),copy.deepcopy(cls._get(m,"value")),copy.deepcopy(cls._get(m,"value_secondary")),cls._get(m,"unit"),cls._get(m,"unit_normalized"),cls._get(m,"raw_text"),cls._get(m,"page")) for m in ms]
 @staticmethod
 def _result(base,decision,code,reason,matched=None,selected=None,limit=None,details=None):return TechnicalConstraintEvaluationResult(**base,decision=decision,reason_code=code,reason=reason,matched_measurements=matched or [],selected_measurement_id=selected,computed_limit=limit,comparison_details=details)
 @staticmethod
 def _number(v):
  if isinstance(v,bool) or not isinstance(v,(int,float,str)):raise TypeError
  if isinstance(v,str) and not re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?",v.strip()):raise ValueError
  return float(v.replace(",",".")) if isinstance(v,str) else float(v)
 @staticmethod
 def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d)
 @staticmethod
 def _enum(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
 @staticmethod
 def _id(r,c):return "TECH-EVAL-"+quote(r,safe="")+"-"+quote(c,safe="")
 @classmethod
 def to_dict(cls,v):return cls._safe(asdict(v)) if is_dataclass(v) else (_ for _ in ()).throw(TypeError("evaluation model required"))
 @classmethod
 def _safe(cls,v):
  if isinstance(v,Enum):return v.value
  if isinstance(v,dict):return {k:cls._safe(x) for k,x in v.items()}
  if isinstance(v,list):return [cls._safe(x) for x in v]
  return v
 @classmethod
 def to_json(cls,v,indent=2):return json.dumps(cls.to_dict(v),ensure_ascii=False,sort_keys=True,indent=indent)
 @classmethod
 def save_json(cls,r,p):
  p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(cls.to_json(r)+"\n",encoding="utf-8");return p
 @staticmethod
 def get_summary(r):
  c=Counter(x.decision.value for x in r.results);rc=Counter(x.decision.value for x in r.rule_results);return {"total_effective_technical_constraints_considered":len(r.results),**{d.value:c[d.value] for d in TechnicalConstraintDecision},"constraints_with_observed_measurement":sum(bool(x.matched_measurements) for x in r.results),"constraints_without_measurement":sum(not x.matched_measurements for x in r.results),"formula_evaluations_attempted":sum(x.constraint.constraint_type=="FORMULA" and x.applicability_decision=="APPLICABLE" for x in r.results),"formula_evaluations_completed":sum(x.reason_code=="TECH_FORMULA_EVALUATED" or (x.constraint.constraint_type=="FORMULA" and x.computed_limit is not None) for x in r.results),"compound_evaluations_attempted":sum(x.constraint.constraint_type=="COMPOUND" and x.applicability_decision=="APPLICABLE" for x in r.results),"compound_evaluations_completed":sum(x.reason_code in {"TECH_COMPOUND_SATISFIES","TECH_COMPOUND_VIOLATES"} for x in r.results),"unique_measurement_ids_used":sorted({x.selected_measurement_id for x in r.results if x.selected_measurement_id}),"executable_rules_total":len(r.rule_results),"rule_results_by_decision":dict(rc)}
 def get_diagnostics(self):return copy.deepcopy(self._diagnostics)

__all__=["ConstraintSnapshot","GenericTechnicalConstraintEvaluator","MeasurementSnapshot","TechnicalConstraintDecision","TechnicalConstraintEvaluationReport","TechnicalConstraintEvaluationResult"]
