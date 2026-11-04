"""Compile and execute non-product-specific deterministic technical rule families."""
from __future__ import annotations
import hashlib,re
from dataclasses import dataclass,field
from decimal import Decimal,InvalidOperation
from enum import Enum
from typing import Any,Dict,List,Mapping,Optional,Sequence
from .generic_iec_kb_models import ExecutableTechnicalRule,TechnicalRuleFamily
from .generic_iec_feature_registry import CanonicalProductFeatureRegistry

class TechnicalRuleDecision(str,Enum):
 SATISFIES="SATISFIES";VIOLATES="VIOLATES";MISSING_OPERAND="MISSING_OPERAND"
 MISSING_EVIDENCE="MISSING_EVIDENCE";INCOMPARABLE="INCOMPARABLE";UNKNOWN="UNKNOWN"
 UNSUPPORTED_RULE="UNSUPPORTED_RULE";NOT_APPLICABLE="NOT_APPLICABLE";REJECTED_EVIDENCE="REJECTED_EVIDENCE"
@dataclass
class TechnicalRuleEvaluation:
 evaluation_id:str;rule_id:str;source_requirement_id:str;rule_family:TechnicalRuleFamily
 decision:TechnicalRuleDecision;reason_code:str;reason:str
 evidence_ids:List[str]=field(default_factory=list);operand_values:Dict[str,Any]=field(default_factory=dict)
 provenance:List[Dict[str,Any]]=field(default_factory=list);logic_group:str="ALL_OF"
 source_clause:Optional[str]=None;operator:Optional[str]=None;unit:Optional[str]=None
 test_family:Optional[str]=None;test_phase:Optional[str]=None;conditioning_state:Optional[str]=None
 component_scope:Optional[str]=None;derivation:Optional[Dict[str,Any]]=None

class GenericTechnicalRuleCompiler:
 """Compile bounded rule metadata once from an atomic requirement."""
 def __init__(self):self.registry=CanonicalProductFeatureRegistry()
 def compile_requirement(self,requirement,source_clause=None):
  rid=str(self._get(requirement,"effective_requirement_id",self._get(requirement,"requirement_id","")) or "");text=str(self._get(requirement,"text","") or "");rules=[]
  for constraint in self._get(requirement,"technical_constraints",[]) or []:rules.append(self._constraint_rule(rid,source_clause,constraint))
  rules.extend(self._presence_rules(rid,source_clause,text));rules.extend(self._classification_rules(rid,source_clause,text));rules.extend(self._sequence_rules(rid,source_clause,text));rules.extend(self._qualitative_rules(rid,source_clause,text));rules.extend(self._dependency_rules(rid,source_clause,text,self._get(requirement,"references",[]) or []))
  condition=self._get(self._get(requirement,"applicability",{}),"logic") or self._get(requirement,"condition_text")
  if condition:
   rule=self._rule(rid,source_clause,TechnicalRuleFamily.CONDITIONAL,text);rule.applicability_condition=condition if isinstance(condition,dict) else {"raw_text":str(condition)};rules.append(rule)
  unique={x.rule_id:x for x in rules}
  if not unique and bool(self._get(requirement,"normative",True)):
   rule=self._rule(rid,source_clause,TechnicalRuleFamily.UNSUPPORTED,text);rule.supported=False;rule.unsupported_reason="Normative semantics do not map safely to a supported deterministic family.";unique[rule.rule_id]=rule
  return sorted(unique.values(),key=lambda x:x.rule_id)
 def compile_kb(self,kb):
  for req,clause in self._requirements(kb):
   rules=self.compile_requirement(req,clause);self._set(req,"executable_rules",rules)
  return kb
 def compile_ledger_rules(self,requirement,source_clause,ledger):
  """Compile only source-backed operand relationships already resolved by Step 45-C."""
  rid=str(self._get(requirement,"effective_requirement_id",self._get(requirement,"requirement_id","")) or "");text=str(self._get(requirement,"text","") or "")
  operator=self._text_operator(text);out=[]
  for entry in ledger or []:
   parameter=str(self._get(entry,"canonical_parameter","") or "");observations=[x for x in self._get(entry,"observations",[]) or [] if str(self._get(x,"source_clause","") or "")==str(source_clause or "")]
   measured=[x for x in observations if self._enum(self._get(x,"semantic_role")) in {"MEASURED","CALCULATED"}];limits=[x for x in observations if self._enum(self._get(x,"semantic_role"))=="LIMIT"]
   for limit in limits:
    context=[x for x in measured if self._semantic_context_equal(x,limit)]
    if not context or not operator:continue
    rule=self._rule(rid,source_clause,TechnicalRuleFamily.NUMERIC_LIMIT,text,parameter);rule.rule_id=self._id(rid,"LEDGER_LIMIT",parameter,self._get(limit,"component_scope"),self._get(limit,"observation_id"));rule.operator=operator;rule.expected_value=self._get(limit,"normalized_value");rule.unit=self._get(limit,"normalized_unit") or self._get(limit,"unit");rule.test_family=self._get(limit,"test_family");rule.test_phase=self._get(limit,"test_phase");rule.conditioning_state=self._get(limit,"conditioning_state");rule.component_dependency={"component_scope":self._get(limit,"component_scope"),"model_scope":self._get(limit,"model_scope",[]),"product_scope":self._get(limit,"product_scope")};rule.required_operands=[parameter];rule.required_evidence_type="LEDGER_MEASUREMENT_LIMIT";rule.provenance+=[{"limit_observation_id":self._get(limit,"observation_id"),"evidence_id":self._get(limit,"evidence_id")}];out.append(rule)
   links=[(o,link) for o in observations for link in self._get(o,"formula_operand_links",[]) or [] if rid in (self._get(o,"requirement_ids",[]) or [])]
   for owner,link in links:
    if self._get(link,"operation") not in {"MULTIPLY","ADD","SUBTRACT","DIVIDE","PERCENT_OF","MIN","MAX"}:continue
    target="test_voltage" if self._get(link,"operand_reference")=="rated_voltage" else parameter
    dependency={"model_scope":self._get(owner,"model_scope",[]),"product_scope":self._get(owner,"product_scope")}
    rule=self._rule(rid,source_clause,TechnicalRuleFamily.NUMERIC_LIMIT,text,target);rule.rule_id=self._id(rid,"LEDGER_FORMULA",target,self._get(link,"operation"),self._get(link,"operand_reference"),self._get(link,"multiplier"),self._get(link,"constant"),self._get(link,"range_basis"));rule.operator="equals";rule.formula=dict(link);rule.required_operands=[str(self._get(link,"operand_reference"))];rule.required_evidence_type="APPLIED_TEST_CONDITION";rule.test_family=self._get(owner,"test_family");rule.test_phase=self._get(owner,"test_phase");rule.conditioning_state=self._get(owner,"conditioning_state");rule.component_dependency=dependency;out.append(rule)
    duration=self._get(link,"duration")
    if isinstance(duration,Mapping) and self._get(duration,"value") is not None:
     duration_rule=self._rule(rid,source_clause,TechnicalRuleFamily.NUMERIC_LIMIT,text,"test_duration");duration_rule.rule_id=self._id(rid,"LEDGER_DURATION",self._get(duration,"value"),self._get(duration,"unit"));duration_rule.operator="equals";duration_rule.expected_value=self._get(duration,"value");duration_rule.unit=self._get(duration,"unit");duration_rule.required_operands=["test_duration"];duration_rule.required_evidence_type="APPLIED_TEST_DURATION";duration_rule.test_family=self._get(owner,"test_family");duration_rule.test_phase=self._get(owner,"test_phase");duration_rule.conditioning_state=self._get(owner,"conditioning_state");duration_rule.component_dependency=dependency;duration_rule.provenance+=[{"duration_observation_id":self._get(owner,"observation_id"),"evidence_id":self._get(owner,"evidence_id")}];out.append(duration_rule)
  unique={x.rule_id:x for x in out};return sorted(unique.values(),key=lambda x:x.rule_id)
 @staticmethod
 def _text_operator(text):
  value=str(text or "").casefold()
  for pattern,operator in ((r"shall\s+not\s+exceed|at\s+most|no\s+more\s+than","less_than_or_equal"),(r"at\s+least|not\s+less\s+than","greater_than_or_equal"),(r"shall\s+be\s+less\s+than","less_than"),(r"shall\s+be\s+greater\s+than","greater_than")):
   if re.search(pattern,value):return operator
  return None
 @classmethod
 def _semantic_context_equal(cls,left,right):
  keys=("test_family","test_phase","conditioning_state","component_scope")
  return all(not cls._get(left,k) or not cls._get(right,k) or cls._get(left,k)==cls._get(right,k) for k in keys)
 def _constraint_rule(self,rid,clause,c):
  ctype=self._enum(self._get(c,"constraint_type"));parameter=self._get(c,"parameter") or self._get(c,"parameter_text");family=(TechnicalRuleFamily.RANGE_TOLERANCE if ctype in {"RANGE","TOLERANCE"} else TechnicalRuleFamily.DIMENSION if ctype=="DISTANCE_LIMIT" or any(x in str(parameter or "").casefold() for x in ("distance","clearance","creepage","diameter","width","length","thickness","spacing","area")) else TechnicalRuleFamily.SEQUENCE_ENDURANCE if ctype in {"COUNT_LIMIT","TIME_LIMIT"} else TechnicalRuleFamily.NUMERIC_LIMIT)
  operator=self._get(c,"operator");rule=ExecutableTechnicalRule(self._id(rid,ctype,str(self._get(c,"constraint_id"))),family,rid,clause,parameter,operator,self._get(c,"value"),self._get(c,"value"),self._get(c,"value_secondary"),self._get(c,"tolerance"),self._get(c,"unit_normalized") or self._get(c,"unit"),self._get(c,"expression"),[str(parameter)] if parameter else [],required_evidence_type="MEASUREMENT",provenance=[{"constraint_id":self._get(c,"constraint_id"),"raw_text":self._get(c,"raw_text")}])
  if family in {TechnicalRuleFamily.NUMERIC_LIMIT,TechnicalRuleFamily.RANGE_TOLERANCE,TechnicalRuleFamily.DIMENSION} and (not parameter or not operator):rule.rule_family=TechnicalRuleFamily.UNSUPPORTED;rule.supported=False;rule.unsupported_reason="Numeric wording lacks a safe deterministic parameter/operator interpretation."
  return rule
 def _presence_rules(self,rid,clause,text):
  patterns=[re.compile(r"\b(?:shall|must)\s+(?P<neg>not\s+)?(?:be\s+)?(?:provided|incorporated|fitted|included|present|have)\s*(?:with\s+)?(?P<subject>[^.;,]{2,80})",re.I),re.compile(r"(?P<subject>\b[a-z][^.;,]{1,60}?)\s+(?:shall|must)\s+(?P<neg>not\s+)?(?:be\s+)?(?:provided|incorporated|fitted|included|present)\b",re.I)];out=[]
  for pattern in patterns:
   for m in pattern.finditer(text):
    subject=self._fact_key(m.group("subject"));rule=self._rule(rid,clause,TechnicalRuleFamily.PRESENCE_ABSENCE,m.group(0),subject);rule.expected_value=not bool(m.group("neg"));rule.required_product_facts=[subject];out.append(rule)
  return out
 def _classification_rules(self,rid,clause,text):
  out=[]
  for m in re.finditer(r"\b(?P<parameter>class(?:ification)?|ip\s*(?:rating|classification)?)\s*(?:shall\s+be|of|at\s+least)?\s*(?P<value>[A-Z0-9-]{1,12})\b",text,re.I):
   rule=self._rule(rid,clause,TechnicalRuleFamily.CLASSIFICATION,m.group(0),self._fact_key(m.group("parameter")));rule.operator="equals";rule.expected_value=m.group("value").upper();rule.required_product_facts=[rule.parameter];out.append(rule)
  return out
 def _sequence_rules(self,rid,clause,text):
  if not re.search(r"\b(?:cycles?|repetition|repeated|sequence|endurance|operations?|rest\s+period|duration)\b",text,re.I):return []
  rule=self._rule(rid,clause,TechnicalRuleFamily.SEQUENCE_ENDURANCE,text,"operation_sequence");rule.required_evidence_type="SEQUENCE";count=re.search(r"(\d+(?:[.,]\d+)?)\s*(cycles?|operations?|repetitions?)",text,re.I);duration=re.search(r"(\d+(?:[.,]\d+)?)\s*(s|min|h|seconds?|minutes?|hours?)",text,re.I);rule.result_semantics={"ordered":bool(re.search(r"\b(?:order|sequence|followed\s+by)\b",text,re.I)),"completion_required":True,"minimum_count":float(count.group(1).replace(",",".")) if count else None,"duration":{"value":float(duration.group(1).replace(",",".")),"unit":duration.group(2)} if duration else None};return [rule]
 def _qualitative_rules(self,rid,clause,text):
  m=re.search(r"\b(?:no|without)\s+(breakdown|dangerous\s+deformation|accessible\s+live\s+parts?|water\s+trace|damage[^.;,]{0,50})",text,re.I)
  if not m:return []
  rule=self._rule(rid,clause,TechnicalRuleFamily.QUALITATIVE_OBSERVATION,m.group(0),self._fact_key(m.group(1)));rule.expected_value=False;rule.required_evidence_type="EXPLICIT_QUALITATIVE_OBSERVATION";return [rule]
 def _dependency_rules(self,rid,clause,text,references):
  out=[];refs=[str(self._get(x,"target",x)) for x in references]
  for target in refs:
   rule=self._rule(rid,clause,TechnicalRuleFamily.CROSS_CLAUSE,text);rule.cross_clause_dependencies=[target];out.append(rule)
  if re.search(r"\b(?:component|switch|transformer)\b.{0,100}\b(?:comply|complies|compliant)\b",text,re.I):
   rule=self._rule(rid,clause,TechnicalRuleFamily.COMPONENT_COMPLIANCE,text,"component_compliance");rule.component_dependency={"references":refs};rule.required_evidence_type="COMPONENT_COMPLIANCE";out.append(rule)
  return out
 def _rule(self,rid,clause,family,raw,parameter=None):return ExecutableTechnicalRule(self._id(rid,family.value,raw),family,rid,clause,parameter,provenance=[{"requirement_id":rid,"clause_id":clause,"raw_text":raw}])
 def _fact_key(self,value):
  normalized=re.sub(r"[^a-z0-9]+","_",str(value or "").casefold()).strip("_");normalized=re.sub(r"^(?:a|an|the)_","",normalized)
  registry=self.registry;matches=registry.search_alias(normalized.replace("_"," "))
  if len(matches)==1:return matches[0].key
  candidate="has_"+normalized
  return candidate if registry.exists(candidate) else normalized
 @staticmethod
 def _id(*values):return "TECH-RULE-"+hashlib.sha256("\x1f".join(map(str,values)).encode()).hexdigest()[:20].upper()
 @classmethod
 def _requirements(cls,kb):
  def walk(nodes):
   for c in nodes:
    cid=cls._get(c,"clause_id")
    for r in cls._get(c,"requirements",[]) or []:yield r,cid
    yield from walk(cls._get(c,"children",[]) or [])
  yield from walk(cls._get(kb,"clauses",[]) or [])
  for annex in cls._get(kb,"annexes",[]) or []:
   for requirement in cls._get(annex,"requirements",[]) or []:yield requirement,cls._get(annex,"annex_id")
   yield from walk(cls._get(annex,"clauses",[]) or [])
 @staticmethod
 def _set(v,n,x):
  if isinstance(v,dict):v[n]=x
  else:setattr(v,n,x)
 @staticmethod
 def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
 @staticmethod
 def _enum(v):return str(v.value if isinstance(v,Enum) else v)

class GenericTechnicalRuleDispatcher:
 """Execute non-numeric families; numeric families delegate to the existing evaluator."""
 NUMERIC={TechnicalRuleFamily.NUMERIC_LIMIT,TechnicalRuleFamily.RANGE_TOLERANCE,TechnicalRuleFamily.DIMENSION}
 def evaluate(self,rule,*,product_facts=None,ledger=None,evidence=None,dependency_results=None,structure_rejected=False,applicable=True,applicability_decision=None):
  base=dict(evaluation_id="RULE-EVAL-"+str(self._get(rule,"rule_id")),rule_id=str(self._get(rule,"rule_id")),source_requirement_id=str(self._get(rule,"source_requirement_id")),rule_family=TechnicalRuleFamily(self._enum(self._get(rule,"rule_family"))),provenance=list(self._get(rule,"provenance",[]) or []),logic_group=str(self._get(rule,"logic_group","ALL_OF")),source_clause=self._get(rule,"source_clause"),operator=self._get(rule,"operator"),unit=self._get(rule,"unit"),test_family=self._get(rule,"test_family"),test_phase=self._get(rule,"test_phase"),conditioning_state=self._get(rule,"conditioning_state"),component_scope=self._get(self._get(rule,"component_dependency",{}),"component_scope"))
  app=self._enum(applicability_decision) if applicability_decision is not None else ("APPLICABLE" if applicable else "NOT_APPLICABLE")
  if app=="NOT_APPLICABLE":return self._result(base,TechnicalRuleDecision.NOT_APPLICABLE,"RULE_NOT_APPLICABLE","Applicability excludes this rule.")
  if app not in {"APPLICABLE",None}:return self._result(base,TechnicalRuleDecision.MISSING_OPERAND,"RULE_APPLICABILITY_UNRESOLVED","Applicability does not authorize technical execution.")
  if structure_rejected:return self._result(base,TechnicalRuleDecision.REJECTED_EVIDENCE,"RULE_STRUCTURE_REJECTED","Semantically incompatible report evidence cannot resolve the rule.")
  if not self._get(rule,"supported",True) or base["rule_family"] is TechnicalRuleFamily.UNSUPPORTED:return self._result(base,TechnicalRuleDecision.UNSUPPORTED_RULE,"RULE_UNSUPPORTED",self._get(rule,"unsupported_reason") or "Rule semantics are unsupported.")
  family=base["rule_family"]
  if family in self.NUMERIC:return self._ledger_numeric(base,rule,ledger)
  if family is TechnicalRuleFamily.CONDITIONAL:return self._result(base,TechnicalRuleDecision.SATISFIES,"RULE_CONDITION_APPLICABLE","The upstream applicability decision satisfied the bounded condition.")
  if family in {TechnicalRuleFamily.PRESENCE_ABSENCE,TechnicalRuleFamily.CLASSIFICATION}:return self._fact(base,rule,product_facts or {})
  if family is TechnicalRuleFamily.SEQUENCE_ENDURANCE:return self._sequence(base,rule,evidence or [])
  if family is TechnicalRuleFamily.QUALITATIVE_OBSERVATION:return self._qualitative(base,rule,evidence or [])
  if family is TechnicalRuleFamily.CROSS_CLAUSE:return self._dependency(base,rule,dependency_results or {})
  if family is TechnicalRuleFamily.COMPONENT_COMPLIANCE:return self._component(base,rule,evidence or [])
  return self._result(base,TechnicalRuleDecision.UNKNOWN,"RULE_SEMANTICS_UNKNOWN","No deterministic dispatcher is available.")
 def _fact(self,base,rule,facts):
  key=str(self._get(rule,"parameter") or "");fact=self._get(facts,key)
  if not fact:return self._result(base,TechnicalRuleDecision.MISSING_OPERAND,"RULE_FACT_MISSING","Required Product Fact is unavailable.")
  status=self._enum(self._get(fact,"status"));value=self._get(fact,"value")
  if status in {"UNKNOWN","CONFLICT"} or value is None:return self._result(base,TechnicalRuleDecision.UNKNOWN,"RULE_FACT_UNRESOLVED","Product Fact is unknown or conflicting.")
  expected=self._get(rule,"expected_value");ok=str(value).casefold()==str(expected).casefold()
  return self._result(base,TechnicalRuleDecision.SATISFIES if ok else TechnicalRuleDecision.VIOLATES,"RULE_FACT_SATISFIES" if ok else "RULE_FACT_VIOLATES","Source-backed Product Fact evaluated.",operands={key:value})
 def _ledger_numeric(self,base,rule,ledger):
  parameter=str(self._get(rule,"parameter") or "");entry=next((e for e in ledger or [] if str(self._get(e,"canonical_parameter"))==parameter),None);observations=list(self._get(entry,"observations",[]) or [])
  observations=[o for o in observations if self._authorized(o,rule)]
  if not self._get(rule,"required_evidence_type") and self._get(rule,"expected_value") is None:
   return self._result(base,TechnicalRuleDecision.MISSING_EVIDENCE,"RULE_NUMERIC_DELEGATED","Numeric execution requires a compiled constraint or source-backed ledger relationship.",evidence=sorted({str(self._get(x,"evidence_id")) for x in observations if self._get(x,"evidence_id")}))
  if any(str(self._get(o,"evidence_status","")).startswith(("REJECTED","WRONG_TEST_FAMILY")) for o in self._get(entry,"observations",[]) or []):
   if not observations:return self._result(base,TechnicalRuleDecision.REJECTED_EVIDENCE,"RULE_EVIDENCE_REJECTED","Rejected semantic evidence cannot supply an operand.")
  formula=self._get(rule,"formula")
  if formula:return self._formula(base,rule,ledger,observations,formula)
  measured=[o for o in observations if self._enum(self._get(o,"semantic_role")) in {"MEASURED","CALCULATED","APPLIED"}]
  if not measured:return self._result(base,TechnicalRuleDecision.MISSING_OPERAND,"RULE_MEASUREMENT_MISSING","No authorized ledger observation supplies the measured operand.")
  limit=self._get(rule,"expected_value")
  if limit is None:return self._result(base,TechnicalRuleDecision.MISSING_OPERAND,"RULE_LIMIT_MISSING","The rule limit operand is unavailable.")
  outcomes=[]
  for item in measured:
   try:
    actual=self._convert_decimal(self._get(item,"normalized_value"),self._get(item,"normalized_unit") or self._get(item,"unit"),self._get(rule,"unit"));ok=self._compare_decimal(actual,self._get(rule,"operator"),self._decimal(limit));outcomes.append((ok,item,actual))
   except (InvalidOperation,TypeError,ValueError):continue
  if not outcomes:return self._result(base,TechnicalRuleDecision.INCOMPARABLE,"RULE_NUMERIC_INCOMPARABLE","Authorized operands are not safely comparable.")
  ok=all(x[0] for x in outcomes);selected=max(outcomes,key=lambda x:x[2]);eids=sorted({str(self._get(x[1],"evidence_id")) for x in outcomes if self._get(x[1],"evidence_id")});operands={"measured":str(selected[2]),"limit":str(self._decimal(limit)),"operator":self._get(rule,"operator"),"parameter":parameter,"unit":self._get(rule,"unit")}
  return self._result(base,TechnicalRuleDecision.SATISFIES if ok else TechnicalRuleDecision.VIOLATES,"RULE_NUMERIC_SATISFIES" if ok else "RULE_NUMERIC_VIOLATES","Authorized semantic operands satisfy the numeric rule." if ok else "Authorized semantic operands violate the numeric rule.",evidence=eids,operands=operands)
 def _formula(self,base,rule,ledger,applied,formula):
  operand=str(self._get(formula,"operand_reference") or "");source=next((e for e in ledger or [] if str(self._get(e,"canonical_parameter"))==operand),None);candidates=[o for o in self._get(source,"observations",[]) or [] if self._enum(self._get(o,"semantic_role")) in {"DECLARED","TEST_BASIS"} and self._authorized(o,rule,allow_component_missing=True)]
  if not candidates:return self._result(base,TechnicalRuleDecision.MISSING_OPERAND,"RULE_FORMULA_OPERAND_MISSING","A required formula operand is unavailable.")
  values={self._decimal(self._get(x,"normalized_value")).normalize() for x in candidates if not isinstance(self._get(x,"normalized_value"),Mapping)}
  if any(isinstance(self._get(x,"normalized_value"),Mapping) for x in candidates):values|={str(self._get(x,"normalized_value")) for x in candidates if isinstance(self._get(x,"normalized_value"),Mapping)}
  if len(values)>1:return self._result(base,TechnicalRuleDecision.MISSING_OPERAND,"RULE_FORMULA_AUTHORITY_CONFLICT","Formula operand authority is conflicting.")
  raw=self._get(candidates[0],"normalized_value");basis=self._get(formula,"range_basis")
  if isinstance(raw,Mapping):
   if basis not in {"MIN","MAX"}:return self._result(base,TechnicalRuleDecision.UNKNOWN,"RULE_RANGE_BASIS_UNRESOLVED","A range operand requires an explicit basis.")
   raw=self._get(raw,basis.casefold())
  operation=str(self._get(formula,"operation") or "");constant=self._get(formula,"multiplier",self._get(formula,"constant"))
  if constant is None:return self._result(base,TechnicalRuleDecision.MISSING_OPERAND,"RULE_FORMULA_CONSTANT_MISSING","Formula constant is unavailable.")
  left=self._decimal(raw);right=self._decimal(constant)
  operations={"MULTIPLY":lambda:left*right,"ADD":lambda:left+right,"SUBTRACT":lambda:left-right,"DIVIDE":lambda:left/right,"PERCENT_OF":lambda:left*right/Decimal("100"),"MIN":lambda:min(left,right),"MAX":lambda:max(left,right)}
  if operation not in operations:return self._result(base,TechnicalRuleDecision.UNSUPPORTED_RULE,"RULE_FORMULA_UNSUPPORTED","Formula operation is not allow-listed.")
  derived=operations[operation]();observed=[x for x in applied if self._enum(self._get(x,"semantic_role"))=="APPLIED"]
  derivation={"operation":operation,"operands":[{"parameter":operand,"value":str(left),"unit":self._get(candidates[0],"normalized_unit") or self._get(candidates[0],"unit")}],"constant":str(right),"result":str(derived),"unit":self._get(rule,"unit") or self._get(candidates[0],"normalized_unit") or self._get(candidates[0],"unit")}
  if not observed:return self._result(base,TechnicalRuleDecision.MISSING_OPERAND,"RULE_APPLIED_CONDITION_MISSING","Applied test-condition evidence is unavailable.",derivation=derivation)
  actual=self._convert_decimal(self._get(observed[0],"normalized_value"),self._get(observed[0],"normalized_unit") or self._get(observed[0],"unit"),derivation["unit"]);ok=self._compare_decimal(actual,self._get(rule,"operator") or "equals",derived);return self._result(base,TechnicalRuleDecision.SATISFIES if ok else TechnicalRuleDecision.VIOLATES,"RULE_FORMULA_SATISFIES" if ok else "RULE_FORMULA_VIOLATES","Structured formula and applied condition were evaluated.",evidence=sorted({str(self._get(x,"evidence_id")) for x in [candidates[0],observed[0]] if self._get(x,"evidence_id")}),operands={"required":str(derived),"applied":str(actual)},derivation=derivation)
 def _authorized(self,o,rule,allow_component_missing=False):
  if str(self._get(o,"evidence_status","")).startswith(("REJECTED","WRONG_TEST_FAMILY")):return False
  if self._get(rule,"source_clause") and self._get(o,"source_clause") and str(self._get(rule,"source_clause"))!=str(self._get(o,"source_clause")):return False
  for key in ("test_family","test_phase","conditioning_state"):
   if self._get(rule,key) and self._get(o,key) and self._get(rule,key)!=self._get(o,key):return False
  component=self._get(self._get(rule,"component_dependency",{}),"component_scope")
  if component and self._get(o,"component_scope") and component!=self._get(o,"component_scope"):return False
  expected_models=set(self._get(self._get(rule,"component_dependency",{}),"model_scope",[]) or []);observed_models=set(self._get(o,"model_scope",[]) or [])
  if expected_models and observed_models and expected_models.isdisjoint(observed_models):return False
  expected_product=self._get(self._get(rule,"component_dependency",{}),"product_scope")
  if expected_product and self._get(o,"product_scope") and expected_product!=self._get(o,"product_scope"):return False
  return True
 @staticmethod
 def _decimal(value):return Decimal(str(value))
 @classmethod
 def _convert_decimal(cls,value,source,target):
  from .generic_technical_constraint_evaluator import GenericTechnicalConstraintEvaluator as E
  if source==target:return cls._decimal(value)
  s=E._UNIT.get(source);t=E._UNIT.get(target)
  if not s or not t or s[0]!=t[0]:raise ValueError("incompatible unit")
  return cls._decimal(value)*cls._decimal(s[1])/cls._decimal(t[1])
 @classmethod
 def _compare_decimal(cls,a,op,b):
  op=str(op or "");return {"equals":a==b,"=":a==b,"==":a==b,"not_equals":a!=b,"!=":a!=b,"less_than":a<b,"<":a<b,"less_than_or_equal":a<=b,"<=":a<=b,"greater_than":a>b,">":a>b,"greater_than_or_equal":a>=b,">=":a>=b}.get(op,False)
 def _sequence(self,base,rule,evidence):
  explicit=[x for x in evidence if self._get(x,"sequence_complete") is not None]
  if not explicit:return self._result(base,TechnicalRuleDecision.MISSING_EVIDENCE,"RULE_SEQUENCE_EVIDENCE_MISSING","Explicit sequence/endurance evidence is unavailable.")
  semantics=self._get(rule,"result_semantics",{}) or {};minimum=self._get(semantics,"minimum_count");duration=self._get(semantics,"duration");ok=all(bool(self._get(x,"sequence_complete")) for x in explicit)
  if minimum is not None:ok=ok and all(float(self._get(x,"count",-1))>=float(minimum) for x in explicit)
  if duration:ok=ok and all(float(self._get(x,"duration",-1))>=float(self._get(duration,"value")) for x in explicit)
  return self._result(base,TechnicalRuleDecision.SATISFIES if ok else TechnicalRuleDecision.VIOLATES,"RULE_SEQUENCE_SATISFIES" if ok else "RULE_SEQUENCE_VIOLATES","Explicit sequence completion, count, and duration evaluated.")
 def _qualitative(self,base,rule,evidence):
  explicit=[x for x in evidence if self._get(x,"explicit_state") is not None]
  if not explicit:return self._result(base,TechnicalRuleDecision.MISSING_EVIDENCE,"RULE_QUALITATIVE_AMBIGUOUS","No explicit qualitative state is available.")
  actual=self._get(explicit[-1],"explicit_state");ok=actual==self._get(rule,"expected_value");return self._result(base,TechnicalRuleDecision.SATISFIES if ok else TechnicalRuleDecision.VIOLATES,"RULE_QUALITATIVE_SATISFIES" if ok else "RULE_QUALITATIVE_VIOLATES","Explicit qualitative observation evaluated.")
 def _dependency(self,base,rule,results):
  deps=list(self._get(rule,"cross_clause_dependencies",[]) or []);missing=[x for x in deps if x not in results]
  if missing:return self._result(base,TechnicalRuleDecision.MISSING_OPERAND,"RULE_DEPENDENCY_MISSING","Required dependency outcome is unavailable.")
  rejected=[x for x in deps if self._enum(results[x]) not in {"SATISFIES","PASS"}]
  return self._result(base,TechnicalRuleDecision.SATISFIES if not rejected else TechnicalRuleDecision.VIOLATES,"RULE_DEPENDENCY_SATISFIES" if not rejected else "RULE_DEPENDENCY_VIOLATES","Authorized dependency outcomes evaluated.")
 def _component(self,base,rule,evidence):
  values=[x for x in evidence if self._get(x,"component_compliance") is not None]
  if not values:return self._result(base,TechnicalRuleDecision.MISSING_EVIDENCE,"RULE_COMPONENT_EVIDENCE_MISSING","Component compliance evidence is unavailable.")
  ok=all(bool(self._get(x,"component_compliance")) for x in values);return self._result(base,TechnicalRuleDecision.SATISFIES if ok else TechnicalRuleDecision.VIOLATES,"RULE_COMPONENT_SATISFIES" if ok else "RULE_COMPONENT_VIOLATES","Supplied component evidence evaluated.")
 @staticmethod
 def aggregate(results,logic="ALL_OF"):
  decisions=[x.decision for x in results]
  if not decisions:return TechnicalRuleDecision.MISSING_OPERAND
  if logic=="ANY_OF":return TechnicalRuleDecision.SATISFIES if TechnicalRuleDecision.SATISFIES in decisions else TechnicalRuleDecision.VIOLATES if all(x is TechnicalRuleDecision.VIOLATES for x in decisions) else TechnicalRuleDecision.UNKNOWN
  return TechnicalRuleDecision.VIOLATES if TechnicalRuleDecision.VIOLATES in decisions else TechnicalRuleDecision.SATISFIES if all(x is TechnicalRuleDecision.SATISFIES for x in decisions) else TechnicalRuleDecision.UNKNOWN
 @staticmethod
 def _result(base,decision,code,reason,evidence=None,operands=None,derivation=None):return TechnicalRuleEvaluation(**base,decision=decision,reason_code=code,reason=reason,evidence_ids=evidence or [],operand_values=operands or {},derivation=derivation)
 @staticmethod
 def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
 @staticmethod
 def _enum(v):return str(v.value if isinstance(v,Enum) else v)

__all__=["GenericTechnicalRuleCompiler","GenericTechnicalRuleDispatcher","TechnicalRuleDecision","TechnicalRuleEvaluation"]
