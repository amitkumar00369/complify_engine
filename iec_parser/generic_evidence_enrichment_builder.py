"""Build normalized evidence candidates from existing structured artifacts."""
from __future__ import annotations
import copy,hashlib,json,math,re
from collections import Counter,defaultdict
from dataclasses import asdict,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Dict,Iterable,List,Mapping,Optional,Sequence,Tuple
from .generic_evidence_enrichment_models import *

class GenericEvidenceEnrichmentBuilder:
 _TYPE_PATTERNS=[("temperature rise",EvidenceParameterType.TEMPERATURE_RISE),("leakage current",EvidenceParameterType.CURRENT),("rated current",EvidenceParameterType.CURRENT),("test voltage",EvidenceParameterType.VOLTAGE),("applied voltage",EvidenceParameterType.VOLTAGE),("rated voltage",EvidenceParameterType.VOLTAGE),("voltage",EvidenceParameterType.VOLTAGE),("power",EvidenceParameterType.POWER),("frequency",EvidenceParameterType.FREQUENCY),("temperature",EvidenceParameterType.TEMPERATURE),("duration",EvidenceParameterType.TIME),("time",EvidenceParameterType.TIME),("speed",EvidenceParameterType.SPEED),("distance",EvidenceParameterType.DISTANCE),("opening",EvidenceParameterType.DISTANCE),("flow",EvidenceParameterType.FLOW_RATE),("cycle",EvidenceParameterType.COUNT),("force",EvidenceParameterType.FORCE),("area",EvidenceParameterType.AREA),("width",EvidenceParameterType.WIDTH),("diameter",EvidenceParameterType.DIAMETER),("model",EvidenceParameterType.MODEL_NUMBER),("type reference",EvidenceParameterType.TYPE_REFERENCE),("serial",EvidenceParameterType.SERIAL_NUMBER),("sample identifier",EvidenceParameterType.SAMPLE_IDENTIFIER),("product name",EvidenceParameterType.PRODUCT_NAME),("brand",EvidenceParameterType.BRAND),("protection class",EvidenceParameterType.PROTECTION_CLASS),("ip rating",EvidenceParameterType.IP_RATING)]
 _UNIT_TYPE={"V":EvidenceParameterType.VOLTAGE,"mV":EvidenceParameterType.VOLTAGE,"kV":EvidenceParameterType.VOLTAGE,"A":EvidenceParameterType.CURRENT,"mA":EvidenceParameterType.CURRENT,"W":EvidenceParameterType.POWER,"kW":EvidenceParameterType.POWER,"Hz":EvidenceParameterType.FREQUENCY,"s":EvidenceParameterType.TIME,"min":EvidenceParameterType.TIME,"h":EvidenceParameterType.TIME,"r/min":EvidenceParameterType.SPEED,"N":EvidenceParameterType.FORCE,"°C":EvidenceParameterType.TEMPERATURE,"K":EvidenceParameterType.TEMPERATURE_RISE,"cycles":EvidenceParameterType.COUNT,"%":EvidenceParameterType.PERCENTAGE}
 _UNIT_DIM={"V":"voltage","mV":"voltage","kV":"voltage","A":"current","mA":"current","W":"power","kW":"power","Hz":"frequency","s":"time","min":"time","h":"time","mm":"length","cm":"length","m":"length","K":"rise","°C":"temperature","r/min":"speed","N":"force","%":"percentage","cycles":"count"}
 def build(self,effective_kb,product_profile,report_evidence,evidence_match,technical_result,grouping,evidence_scope,final_decision,step23_result):
  facts=[];identities=[];required=[];actual=[];calculations=[];diagnostics=[]
  groups=self._groups(grouping,final_decision);scope=self._scope(evidence_scope)
  facts.extend(self._profile_facts(product_profile));identities.extend(self._identities(product_profile))
  report_facts,actual,calculations=self._report_enrichment(report_evidence,scope,diagnostics);facts.extend(report_facts)
  required=self._required(effective_kb,groups,diagnostics)
  pairs=self._pairs(required,actual);sets=self._comparison_sets(facts);diagnostics.extend(self._linkage_diagnostics(required,actual,pairs))
  before=Counter(self._get(x,"code") for x in self._get(step23_result,"diagnostics",[]) or [])
  usable={"INTEGRITY_MISSING_EXPECTED_TEST_CONDITION":sum(x.status==EnrichmentStatus.RESOLVED for x in required),"INTEGRITY_MISSING_MEASUREMENT":sum(x.status==EnrichmentStatus.RESOLVED for x in actual),"INTEGRITY_MISSING_PARAMETER_SEMANTICS":sum(x.parameter_type!=EvidenceParameterType.UNKNOWN for x in facts),"INTEGRITY_MISSING_SAMPLE_IDENTIFIER":sum(x.identifier_type in {EvidenceParameterType.SERIAL_NUMBER,EvidenceParameterType.SAMPLE_IDENTIFIER} for x in identities)}
  if not usable["INTEGRITY_MISSING_SAMPLE_IDENTIFIER"]:diagnostics.append({"code":"SCHEMA_EXTENSION_REQUIRED","missing_field":"identity.sample_identifiers or identity.serial_numbers","upstream_model":"ProductProfile.identity / ReportEvidence metadata","reason":"No distinct tested-sample identifier is preserved in structured artifacts or recoverable from their stored evidence.","minimum_backward_compatible_extension":"Add optional independent lists for sample_identifiers and serial_numbers with EvidenceProvenance."})
  reconciliation={k:{"before":before[k],"usable_candidates_after_enrichment":min(before[k],usable[k]),"remaining":max(0,before[k]-usable[k])} for k in usable}
  summary={"normalized_facts":len(facts),"facts_by_parameter_role":dict(Counter(x.parameter_role.value for x in facts)),"sample_identity_records":len(identities),"report_measurements_enriched":sum(any(p.source_type=="REPORT_MEASUREMENT" for p in x.provenance) for x in facts),"actual_test_conditions":len(actual),"required_test_conditions":len(required),"safe_expressions":sum(x.observed_expression is not None and x.observed_expression.status==EnrichmentStatus.RESOLVED for x in actual)+sum(x.expected_expression is not None and x.expected_expression.status==EnrichmentStatus.RESOLVED for x in required),"recomputable_calculations":sum(x.recomputable for x in calculations),"condition_pairs":{s.value:sum(x.link_status==s for x in pairs) for s in ConditionLinkStatus},"comparison_sets":len(sets),"unresolved_parameter_semantics":sum(x.parameter_type==EvidenceParameterType.UNKNOWN for x in facts),"unresolved_expected_test_conditions":sum(x.status!=EnrichmentStatus.RESOLVED for x in required),"unresolved_sample_identity":int(not any(x.identifier_type in {EvidenceParameterType.SERIAL_NUMBER,EvidenceParameterType.SAMPLE_IDENTIFIER} for x in identities)),"step23_diagnostic_reconciliation":reconciliation}
  return EvidenceEnrichmentReport(str(self._get(final_decision,"effective_kb_id",self._get(effective_kb,"effective_kb_id","")) or ""),str(self._get(product_profile,"profile_id","") or ""),str(self._get(report_evidence,"document_id","") or ""),sorted(facts,key=lambda x:x.fact_id),sorted(required,key=lambda x:x.condition_id),sorted(actual,key=lambda x:x.condition_id),sorted(calculations,key=lambda x:x.calculation_id),sorted(identities,key=lambda x:x.identity_id),sorted(pairs,key=lambda x:x.pair_id),sorted(sets,key=lambda x:x.comparison_id),summary,sorted(diagnostics,key=lambda x:json.dumps(x,sort_keys=True)))
 def _profile_facts(self,profile):
  out=[]
  for key,f in (self._get(profile,"facts",{}) or {}).items():
   value=self._get(f,"value");v,u=self._value_unit(value);ptype=self.parameter_type(key);role=EvidenceParameterRole.PRODUCT_RATING if any(x in key.casefold() for x in ("rated_","rating")) else EvidenceParameterRole.OTHER;status=self._status(self._get(f,"status"));provs=[]
   for e in self._get(f,"evidence",[]) or []:provs.append(EvidenceProvenance("PRODUCT_PROFILE","product_profile",self._get(e,"evidence_id"),self._get(e,"clause_id"),self._get(e,"requirement_id"),None,self._get(e,"page"),self._get(e,"page"),self._get(e,"raw_text")))
   nv=NormalizedEvidenceValue(v,None,self._value_type(v),u,u,None,None,float(self._get(f,"confidence",0) or 0),status);out.append(NormalizedEvidenceFact(self._id("FACT-PROFILE",key),ptype,role,key,nv,provs,float(self._get(f,"confidence",0) or 0),status,f"{role.value}:{key}","Preserved Product Profile fact."))
  return out
 def _identities(self,profile):
  ident=self._get(profile,"identity",{}) or {};mapping=(("model_numbers",EvidenceParameterType.MODEL_NUMBER),("type_references",EvidenceParameterType.TYPE_REFERENCE),("serial_numbers",EvidenceParameterType.SERIAL_NUMBER),("sample_identifiers",EvidenceParameterType.SAMPLE_IDENTIFIER),("product_name",EvidenceParameterType.PRODUCT_NAME),("brand",EvidenceParameterType.BRAND));out=[]
  for key,ptype in mapping:
   raw=self._get(ident,key);vals=raw if isinstance(raw,list) else [raw] if raw else []
   for i,item in enumerate(vals):
    v=self._get(item,"value",item);status=self._status(self._get(item,"status","CONFIRMED"));prov=EvidenceProvenance("PRODUCT_PROFILE","product_profile",self._get(item,"evidence_id",key),None,None,None,self._get(item,"page_start"),self._get(item,"page_end"),None);out.append(SampleIdentityEvidence(self._id("IDENTITY",ptype.value,str(i),str(v)),ptype,v,"PRODUCT_PROFILE",status,[prov]))
  return out
 def _report_enrichment(self,report,scope,diagnostics):
  facts=[];actual=[];calculations=[]
  for clause,e,m in self._walk_report(report):
   eid=str(self._get(e,"evidence_id","") or "");raw=str(self._get(m,"raw_text",self._get(e,"raw_text","")) or "");name=self._get(m,"parameter") or self._get(m,"parameter_text");ptype=self.parameter_type(name);role=self.parameter_role(name,self._get(m,"notes"),raw);value=self._get(m,"value");unit=self._get(m,"unit_normalized") or self._get(m,"unit");status=EnrichmentStatus.RESOLVED if ptype!=EvidenceParameterType.UNKNOWN and value is not None else EnrichmentStatus.NEEDS_REVIEW
   if ptype==EvidenceParameterType.UNKNOWN:diagnostics.append({"code":"ENRICHMENT_PARAMETER_SEMANTICS_UNRESOLVED","source_id":self._get(m,"measurement_id")})
   prov=EvidenceProvenance("REPORT_MEASUREMENT","report_evidence",self._get(m,"measurement_id"),clause,None,None,self._get(m,"page"),self._get(m,"page"),raw[:500] or None);canonical=self._canonical(name);nv=NormalizedEvidenceValue(value,self._get(m,"value_secondary"),self._value_type(value),self._get(m,"unit"),unit,self._get(m,"operator"),raw,.95,status);fid=self._id("FACT-REPORT",str(self._get(m,"measurement_id")));facts.append(NormalizedEvidenceFact(fid,ptype,role,canonical,nv,[prov],.95,status,f"{role.value}:{canonical}","Preserved report measurement."))
   if role in {EvidenceParameterRole.TEST_INPUT,EvidenceParameterRole.TEST_PARAMETER,EvidenceParameterRole.TEST_CONDITION}:
    expr,calc=self._expression(raw,eid,clause,scope.get(eid,{}),prov,ptype)
    gids=self._selected_group_ids(scope.get(eid,{}));astatus=EnrichmentStatus.NEEDS_REVIEW if self._enum(self._get(scope.get(eid,{}),"scope_status"))=="AMBIGUOUS" else status;actual.append(ActualTestCondition(self._id("ACTUAL",str(self._get(m,"measurement_id"))),eid,clause,gids,ptype,self._condition_role(canonical,ptype),nv,expr,astatus,[prov],"Derived from existing report measurement."));
    if calc:calculations.append(calc)
  # Expressions without measurement ownership are retained only when safely structured.
  for clause,e,_ in self._walk_report(report,include_empty=True):
   raw=str(self._get(e,"raw_text","") or "");eid=str(self._get(e,"evidence_id","") or "")
   if not raw:continue
   prov=EvidenceProvenance("REPORT_CLAUSE","report_evidence",eid,clause,None,None,self._get(e,"page_start"),self._get(e,"page_end"),raw[:500]);expr,calc=self._expression(raw,eid,clause,scope.get(eid,{}),prov,EvidenceParameterType.UNKNOWN)
   if calc and not any(x.calculation_id==calc.calculation_id for x in calculations):calculations.append(calc)
  return facts,self._unique(actual,"condition_id"),self._unique(calculations,"calculation_id")
 def _required(self,kb,groups,diagnostics):
  out=[]
  for req,clause in self._requirements(kb):
   rid=str(self._get(req,"effective_requirement_id",self._get(req,"requirement_id","")) or "");text=str(self._get(req,"text","") or "")
   for c in self._get(req,"technical_constraints",[]) or []:
    cid=str(self._get(c,"constraint_id","") or "");name=self._get(c,"parameter") or self._get(c,"parameter_text");ptype=self.parameter_type(name or self._get(c,"raw_text"));ctype=self._enum(self._get(c,"constraint_type"));raw=str(self._get(c,"raw_text","") or "");classification=self._classify_required(text,raw,ctype)
    if classification in {TestConditionClassification.ACCEPTANCE_CONSTRAINT,TestConditionClassification.POST_TEST_ACCEPTANCE}:continue
    if classification==TestConditionClassification.UNRESOLVED and ctype!="TEST_PARAMETER":continue
    status=self._status(self._get(c,"status"));unit=self._get(c,"unit_normalized") or self._get(c,"unit");reason=self._unresolved_reason(ptype,self._condition_role(self._canonical(name),ptype),unit,raw)
    if reason:status=EnrichmentStatus.NEEDS_REVIEW
    prov=EvidenceProvenance("STANDARD_TECHNICAL_CONSTRAINT","effective_kb",cid,clause,rid,groups.get(rid,[None])[0] if groups.get(rid) else None,None,None,raw[:500]);expr=self._constraint_expression(c,prov);nv=NormalizedEvidenceValue(self._get(c,"value"),self._get(c,"value_secondary"),self._value_type(self._get(c,"value")),self._get(c,"unit"),unit,self._get(c,"operator"),raw,.95,status)
    if status!=EnrichmentStatus.RESOLVED:diagnostics.append({"code":"ENRICHMENT_EXPECTED_CONDITION_UNRESOLVED","requirement_id":rid,"constraint_id":cid})
    out.append(RequiredTestCondition(self._id("REQUIRED",rid,cid),rid,groups.get(rid,[None])[0] if groups.get(rid) else None,clause,ptype,self._condition_role(self._canonical(name),ptype),self._get(c,"operator"),nv,expr,cid,True,status,[prov],"Separate enrichment interpretation; original constraint unchanged.",classification,reason,self._get(req,"source_order")))
  return out
 def _expression(self,raw,eid,clause,scope,prov,ptype):
  # Safe numeric multiplier with explicit input and reported result.
  m=re.search(r"(?P<f>\d+(?:[.,]\d+)?)\s*[×xX*]\s*(?P<i>\d+(?:[.,]\d+)?)\s*(?P<u>[A-Za-z°/%]+)\s*=\s*(?P<r>\d+(?:[.,]\d+)?)\s*(?P=u)\b",raw)
  if m:
   f=float(m.group("f").replace(",","."));iv=float(m.group("i").replace(",","."));rv=float(m.group("r").replace(",","."));expr=EvidenceExpression(self._id("EXPR",eid,m.group(0)),ExpressionType.MULTIPLIER,"MULTIPLY",iv,rv,f,None,[],None,m.group("u"),m.group(0),EnrichmentStatus.RESOLVED,[prov]);gids=self._selected_group_ids(scope);result=NormalizedEvidenceValue(rv,None,"number",m.group("u"),m.group("u"),"equals",m.group(0),.99,EnrichmentStatus.RESOLVED);calc=CalculationEvidence(self._id("CALC",eid,m.group(0)),clause,gids,eid,ptype,[{"value":f},{"value":iv,"unit":m.group("u")}],expr,result,True,f*iv,rv-f*iv,0,EnrichmentStatus.RESOLVED,[prov],"Structured only; correctness is not decided here.");return expr,calc
  m=re.search(r"(?P<f>\d+(?:[.,]\d+)?)\s*(?:times|[×xX*])\s*(?P<v>[a-z][a-z0-9 _-]+)",raw,re.I)
  if m:return EvidenceExpression(self._id("EXPR",eid,m.group(0)),ExpressionType.MULTIPLIER,"MULTIPLY",None,None,float(m.group("f").replace(",",".")),self._canonical(m.group("v")),[self._canonical(m.group("v"))],None,None,m.group(0),EnrichmentStatus.RESOLVED,[prov]),None
  return None,None
 def _constraint_expression(self,c,prov):
  e=self._get(c,"expression")
  if isinstance(e,Mapping):return EvidenceExpression(self._id("EXPR-CONSTRAINT",str(self._get(c,"constraint_id"))),ExpressionType.FORMULA,self._get(e,"operator") or self._get(e,"selection"),copy.deepcopy(self._get(e,"left")),copy.deepcopy(self._get(e,"right")),self._get(e,"factor"),self._get(e,"variable"),list(self._get(e,"variables",[]) or []),self._get(e,"constant"),self._get(c,"unit_normalized") or self._get(c,"unit"),json.dumps(e,sort_keys=True),EnrichmentStatus.RESOLVED,[prov])
  raw=str(self._get(c,"raw_text","") or "");expr,_=self._expression(raw,str(self._get(c,"constraint_id")),self._get(prov,"clause_id"),{},prov,self.parameter_type(self._get(c,"parameter")));return expr
 def _pairs(self,required,actual):
  out=[];candidate_counts=Counter()
  for r in required:
   for a in actual:
    if a.parameter_type==r.parameter_type and a.condition_role==r.condition_role and r.group_id in a.group_ids and self._compatible(self._unit(r),self._unit(a)):candidate_counts[("r",r.condition_id)]+=1;candidate_counts[("a",a.condition_id)]+=1
  for r in required:
   candidates=[a for a in actual if a.parameter_type==r.parameter_type]
   if not candidates:out.append(TestConditionPair(self._id("PAIR",r.condition_id,"NONE"),r.condition_id,None,False,False,False,False,ConditionLinkStatus.NO_MATCH,"No actual condition with compatible parameter semantics."));continue
   for a in candidates:
    role=a.condition_role==r.condition_role;scope=bool(r.group_id and r.group_id in a.group_ids);amb=a.status==EnrichmentStatus.NEEDS_REVIEW;unit=self._compatible(self._unit(r),self._unit(a));unique=candidate_counts[("r",r.condition_id)]==1 and candidate_counts[("a",a.condition_id)]==1
    status=ConditionLinkStatus.NO_MATCH if not role or not unit else ConditionLinkStatus.AMBIGUOUS if amb or (scope and not unique) else ConditionLinkStatus.MATCHED if scope and unique else ConditionLinkStatus.POSSIBLE
    reason="Unique semantic, role, unit, and resolved-scope linkage." if status==ConditionLinkStatus.MATCHED else "Multiple or unresolved candidates prevent an exact linkage." if status==ConditionLinkStatus.AMBIGUOUS else "Some semantic linkage signals exist but exact linkage is incomplete." if status==ConditionLinkStatus.POSSIBLE else "Parameter counterpart exists but role or scope excludes linkage."
    out.append(TestConditionPair(self._id("PAIR",r.condition_id,a.condition_id),r.condition_id,a.condition_id,True,role,unit,scope,status,reason))
  return out
 def _linkage_diagnostics(self,required,actual,pairs):
  out=[];rmap={x.condition_id:x for x in required};amap={x.condition_id:x for x in actual}
  for r in required:
   if r.status!=EnrichmentStatus.RESOLVED:out.append({"code":"LINKAGE_REQUIRED_CONDITION_UNRESOLVED","condition_id":r.condition_id,"reason":r.unresolved_reason or "SOURCE_SEMANTICS_INCOMPLETE"})
  for a in actual:
   if a.status!=EnrichmentStatus.RESOLVED:out.append({"code":"LINKAGE_ACTUAL_CONDITION_UNRESOLVED","condition_id":a.condition_id})
  for p in pairs:
   code={ConditionLinkStatus.MATCHED:"LINKAGE_MATCHED",ConditionLinkStatus.POSSIBLE:"LINKAGE_POSSIBLE",ConditionLinkStatus.AMBIGUOUS:"LINKAGE_AMBIGUOUS",ConditionLinkStatus.NO_MATCH:"LINKAGE_PARAMETER_ROLE_MISMATCH"}[p.link_status]
   if not p.scope_compatible and p.actual_condition_id:code="LINKAGE_SCOPE_MISMATCH" if p.link_status==ConditionLinkStatus.NO_MATCH else code
   if not p.unit_compatible and p.actual_condition_id:code="LINKAGE_UNIT_MISMATCH"
   out.append({"code":code,"pair_id":p.pair_id})
  return out
 @classmethod
 def _classify_required(cls,text,raw,ctype):
  s=(text+" "+raw).casefold()
  if re.search(r"\b(after|following)\s+the\s+test\b",s):return TestConditionClassification.POST_TEST_ACCEPTANCE
  if re.search(r"\bshall\s+not\s+(?:exceed|be greater)|\bshall\s+be\s+at\s+(?:least|most)|\bmaximum\b",s):return TestConditionClassification.ACCEPTANCE_CONSTRAINT
  if ctype=="TEST_PARAMETER":return TestConditionClassification.TEST_PARAMETER
  if re.search(r"\b(test|operated|supplied|performed|carried out|made)\b.{0,80}\b(at|for|with|under|to)\b",s):return TestConditionClassification.REQUIRED_TEST_CONDITION
  if re.search(r"\b(for a period of|for\s+\d|at a speed|with a force|with a load|cycles?|flow rate)\b",s):return TestConditionClassification.REQUIRED_TEST_CONDITION
  return TestConditionClassification.UNRESOLVED
 @classmethod
 def _unresolved_reason(cls,ptype,role,unit,raw):
  if ptype==EvidenceParameterType.UNKNOWN:return "PARAMETER_UNKNOWN"
  if role=="OTHER":return "CONDITION_ROLE_UNKNOWN"
  expected={EvidenceParameterType.VOLTAGE:"voltage",EvidenceParameterType.CURRENT:"current",EvidenceParameterType.POWER:"power",EvidenceParameterType.TIME:"time",EvidenceParameterType.DISTANCE:"length",EvidenceParameterType.FORCE:"force",EvidenceParameterType.TEMPERATURE:"temperature",EvidenceParameterType.TEMPERATURE_RISE:"rise",EvidenceParameterType.SPEED:"speed",EvidenceParameterType.COUNT:"count"}.get(ptype)
  if unit and expected and cls._UNIT_DIM.get(unit)!=expected:return "SOURCE_SEMANTICS_INCOMPLETE"
  if not unit and re.search(r"\d",raw):return "MISSING_UNIT"
  return None
 def _comparison_sets(self,facts):
  by=defaultdict(list)
  for f in facts:by[f.semantic_key].append(f)
  return [EvidenceComparisonSet(self._id("COMPARE",k),k,sorted(x.fact_id for x in v),len(v)>1,"Facts share parameter semantics and role; no conflict decision is made.") for k,v in by.items() if len(v)>1]
 @classmethod
 def parameter_type(cls,name):
  s=cls._canonical(name)
  for pattern,t in cls._TYPE_PATTERNS:
   if pattern.replace(" ","_") in s:return t
  return EvidenceParameterType.UNKNOWN
 @classmethod
 def parameter_role(cls,name,notes=None,raw=None):
  s=" ".join(map(str,(name or "",notes or "",raw or ""))).casefold()
  if "measurement role: test_parameter" in s or "test voltage" in s or "applied voltage" in s:return EvidenceParameterRole.TEST_PARAMETER
  if "measurement role: observed_value" in s or any(x in s for x in ("measured","temperature rise","leakage current")):return EvidenceParameterRole.OBSERVED_MEASUREMENT
  if "rated" in s or "marking" in s:return EvidenceParameterRole.PRODUCT_RATING
  return EvidenceParameterRole.OTHER
 @classmethod
 def _condition_role(cls,name,ptype):
  return {EvidenceParameterType.VOLTAGE:"TEST_VOLTAGE",EvidenceParameterType.TIME:"TEST_DURATION",EvidenceParameterType.SPEED:"TEST_SPEED",EvidenceParameterType.TEMPERATURE:"TEST_TEMPERATURE",EvidenceParameterType.TEMPERATURE_RISE:"TEST_TEMPERATURE",EvidenceParameterType.DISTANCE:"TEST_DISTANCE",EvidenceParameterType.CURRENT:"TEST_CURRENT",EvidenceParameterType.POWER:"TEST_POWER",EvidenceParameterType.COUNT:"TEST_CYCLE_COUNT",EvidenceParameterType.FLOW_RATE:"TEST_FLOW"}.get(ptype,"OTHER")
 @classmethod
 def _compatible(cls,a,b):return bool(a and b and cls._UNIT_DIM.get(a)==cls._UNIT_DIM.get(b)) or a==b
 @staticmethod
 def _unit(x):
  v=x.expected_value if isinstance(x,RequiredTestCondition) else x.observed_value;return v.unit_normalized if v else None
 @classmethod
 def _groups(cls,grouping,final):
  out=defaultdict(list)
  for g in cls._get(grouping,"groups",[]) or []:
   for m in cls._get(g,"members",[]) or []:out[str(cls._get(m,"effective_requirement_id"))].append(str(cls._get(g,"group_id")))
  for g in cls._get(final,"group_decisions",[]) or []:
   for r in cls._get(g,"member_requirement_ids",[]) or []:
    if str(cls._get(g,"group_id")) not in out[str(r)]:out[str(r)].append(str(cls._get(g,"group_id")))
  return out
 @classmethod
 def _scope(cls,s):return {str(cls._get(x,"report_evidence_id")):x for x in cls._get(s,"results",[]) or []}
 @classmethod
 def _selected_group_ids(cls,scope):return [str(cls._get(x,"group_id",x)) for x in cls._get(scope,"selected_groups",[]) or []]
 @classmethod
 def _walk_report(cls,report,include_empty=False):
  def walk(nodes):
   for c in nodes:
    cid=cls._get(c,"clause_id")
    for e in cls._get(c,"evidence_items",[]) or []:
     ms=cls._get(e,"measurements",[]) or []
     if ms:
      for m in ms:yield cid,e,m
     elif include_empty:yield cid,e,{}
    yield from walk(cls._get(c,"children",[]) or [])
  yield from walk(cls._get(report,"clauses",[]) or [])
 @classmethod
 def _requirements(cls,kb):
  def walk(nodes):
   for c in nodes:
    for r in cls._get(c,"requirements",[]) or []:yield r,cls._get(c,"clause_id")
    yield from walk(cls._get(c,"children",[]) or [])
  yield from walk(cls._get(kb,"clauses",[]) or [])
  for a in cls._get(kb,"annexes",[]) or []:
   for r in cls._get(a,"requirements",[]) or []:yield r,cls._get(a,"annex_id")
 @staticmethod
 def _value_unit(v):return (v.get("value"),v.get("unit")) if isinstance(v,Mapping) else (v,None)
 @staticmethod
 def _value_type(v):return "boolean" if isinstance(v,bool) else "number" if isinstance(v,(int,float)) else "string" if isinstance(v,str) else "unknown"
 @staticmethod
 def _status(s):return EnrichmentStatus.RESOLVED if str(getattr(s,"value",s)) in {"CONFIRMED","INFERRED_STRONG","RESOLVED"} else EnrichmentStatus.NEEDS_REVIEW if str(getattr(s,"value",s))=="NEEDS_REVIEW" else EnrichmentStatus.UNRESOLVED
 @staticmethod
 def _canonical(v):return re.sub(r"[^a-z0-9]+","_",str(v or "").casefold()).strip("_")
 @staticmethod
 def _id(*parts):return parts[0]+"-"+hashlib.sha256("\x1f".join(parts[1:]).encode()).hexdigest()[:18].upper()
 @staticmethod
 def _unique(items,key):return list({getattr(x,key):x for x in items}.values())
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
 def to_dict(cls,v):return cls._plain(asdict(v)) if is_dataclass(v) else (_ for _ in ()).throw(TypeError("enrichment report required"))
 @classmethod
 def to_json(cls,v,indent=2):return json.dumps(cls.to_dict(v),ensure_ascii=False,sort_keys=True,indent=indent)
 @classmethod
 def save_json(cls,v,p):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(cls.to_json(v)+"\n",encoding="utf-8");return p
__all__=["GenericEvidenceEnrichmentBuilder"]
