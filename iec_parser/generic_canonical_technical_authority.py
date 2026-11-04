"""Canonical deterministic technical authority (Step 48-F)."""
from __future__ import annotations
import copy,hashlib,json
from collections import Counter
from dataclasses import asdict,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Mapping

SCHEMA_VERSION="CANONICAL_TECHNICAL_AUTHORITY_V1"
POLICY_VERSION="STEP48F_TECHNICAL_AUTHORITY_POLICY_V1"
EXECUTION_POLICY_VERSION="STEP48F_TECHNICAL_EXECUTION_POLICY_V1"
INTEGRITY_VERSION="CANONICAL_TECHNICAL_AUTHORITY_INTEGRITY_V1"
STATUSES={"SATISFIES","VIOLATES","NOT_EXECUTABLE","NEEDS_REVIEW","NOT_REQUIRED"}
PRODUCT_SPECIFIC_BRANCHES_ADDED=MODEL_SPECIFIC_BRANCHES_ADDED=REPORT_SPECIFIC_BRANCHES_ADDED=0
STANDARD_SPECIFIC_BRANCHES_ADDED=CLAUSE_SPECIFIC_BRANCHES_ADDED=GOLDEN_SPECIFIC_BRANCHES_ADDED=0

class GenericCanonicalTechnicalAuthority:
 def build(self,applicability,evidence,legacy,facts=None):
  apps={str(self._get(x,'requirement_id') or self._get(x,'effective_requirement_id')):self._enum(self._get(x,'status')) for x in self._get(applicability,'results',[]) or []};aliases={}
  for item in self._get(applicability,'results',[]) or []:
   effective=str(self._get(item,'requirement_id') or self._get(item,'effective_requirement_id') or '')
   if effective:aliases[effective]=effective
   for source in list(self._get(item,'base_sources',[]) or [])+list(self._get(item,'delta_sources',[]) or []):
    source_id=str(self._get(source,'requirement_id') or '')
    if source_id and effective:aliases[source_id]=effective
  ev={str(self._get(x,'requirement_id') or self._get(x,'effective_requirement_id')):self._plain(x) for x in self._get(evidence,'results',[]) or []};rows=[]
  for source_kind,key in [('CONSTRAINT','results'),('RULE','rule_results')]:
   for old in self._get(legacy,key,[]) or []:
    x=self._plain(old);raw_rid=str(x.get('effective_requirement_id') or x.get('source_requirement_id') or '');rid=aliases.get(raw_rid,raw_rid);rows.append(self._record(rid,x,source_kind,apps.get(rid,'UNKNOWN'),ev.get(rid,{})))
  counts=Counter(x['execution_result'] for x in rows);kinds=Counter(x['rule_family'] for x in rows)
  out={'schema_version':SCHEMA_VERSION,'policy_version':POLICY_VERSION,'execution_policy_version':EXECUTION_POLICY_VERSION,'effective_kb_id':self._get(legacy,'effective_kb_id'),'report_document_id':self._get(legacy,'report_document_id'),'authoritative':True,'legacy_artifact_role':'NORMALIZED_EXECUTION_INPUT_ONLY','results':rows,'summary':{'technical_rules_identified':len(rows),'technical_rules_executable':counts['SATISFIES']+counts['VIOLATES'],'status_counts':{x:counts[x] for x in sorted(STATUSES)},'rule_family_counts':dict(sorted(kinds.items()))}}
  out['technical_authority_sha256']=self._hash(out);return out
 def _record(self,rid,x,kind,app,ev):
  suff=self._get(self._get(ev,'sufficiency',{}),'status') or 'INSUFFICIENT';usable=self._get(self._get(ev,'identity_usability',{}),'status') or 'NEEDS_REVIEW';legacy=self._enum(x.get('decision')) or 'UNKNOWN';op=x.get('operator') or self._get(x.get('constraint',{}),'operator');parameter=self._get(x.get('operand_values',{}),'parameter') or self._get(x.get('constraint',{}),'parameter');unit=x.get('unit') or self._get(x.get('operand_values',{}),'unit') or self._get(x.get('constraint',{}),'unit_normalized')
  inputs=[];limits=[]
  operands=x.get('operand_values') or {};measured=operands.get('measured');limit=operands.get('limit')
  matches=x.get('matched_measurements') or []
  if measured is None and matches:measured=matches[0].get('value')
  if limit is None:limit=self._get(x.get('comparison_details',{}),'limit') or self._get(x.get('constraint',{}),'value')
  if measured is not None:inputs.append({'value':self._number(measured),'unit':unit or (matches[0].get('unit_normalized') if matches else None),'semantic_role':'MEASURED','source_fact_id':None,'source_evidence_id':(x.get('evidence_ids') or [x.get('selected_measurement_id')])[0]})
  if limit is not None:limits.append({'value':self._number(limit),'unit':unit,'semantic_role':'LIMIT','source_requirement_id':rid})
  basis=bool(inputs and (limits or x.get('derivation') or x.get('formula')) and op);reason=[]
  if app=='NOT_APPLICABLE':result='NOT_REQUIRED';reason=['APPLICABILITY_NOT_APPLICABLE']
  elif app!='APPLICABLE':result='NEEDS_REVIEW';reason=['APPLICABILITY_NOT_AUTHORITATIVE']
  elif suff in {'INSUFFICIENT','NOT_COMPARABLE'}:result='NOT_EXECUTABLE';reason=['EVIDENCE_GATE_BLOCKED']
  elif suff=='NEEDS_REVIEW' or usable in {'RESTRICTED','NEEDS_REVIEW'}:result='NEEDS_REVIEW';reason=['EVIDENCE_OR_IDENTITY_REVIEW']
  elif usable=='NOT_USABLE':result='NOT_EXECUTABLE';reason=['IDENTITY_NOT_USABLE']
  elif legacy in {'SATISFIES','VIOLATES'} and basis:result=legacy;reason=['DETERMINISTIC_EXECUTION_PRESERVED']
  elif legacy in {'SATISFIES','VIOLATES'}:result='NOT_EXECUTABLE';reason=['EXECUTION_BASIS_INCOMPLETE']
  elif legacy in {'NEEDS_REVIEW','UNKNOWN','INCOMPARABLE'}:result='NEEDS_REVIEW';reason=['LEGACY_EXECUTION_UNRESOLVED']
  else:result='NOT_EXECUTABLE';reason=['MANDATORY_OPERAND_OR_RULE_MISSING']
  mechanism=self._mechanism(result,op);eids=sorted({str(v) for v in (x.get('evidence_ids') or []) if v}|{str(v) for v in [x.get('selected_measurement_id')] if v});rule_id=str(x.get('rule_id') or x.get('constraint_id') or x.get('evaluation_id') or '')
  return {'technical_evaluation_id':'CANONICAL-TECH-'+self._hash((rid,rule_id))[:20].upper(),'requirement_id':rid,'technical_rule_id':rule_id,'applicability_status':app,'evidence_sufficiency':suff,'identity_usability':usable,'test_family':x.get('test_family'),'technical_subject':x.get('component_scope'),'canonical_parameter':parameter,'input_values':inputs,'limits':limits,'conditions':[v for v in [x.get('conditioning_state'),x.get('test_phase'),self._get(x.get('constraint',{}),'condition_text')] if v and v not in {'UNSPECIFIED_CONDITIONING','UNSPECIFIED_PHASE'}],'formula':x.get('formula') or x.get('derivation'),'operator':op,'normalized_inputs':{'parameter':parameter,'unit':unit,'inputs':inputs,'limits':limits},'execution_result':result,'execution_basis':{'legacy_execution_id':x.get('evaluation_id'),'source_kind':kind,'operator':op,'operand_count':len(inputs)+len(limits)} if basis else None,'failure_mechanism':mechanism if result=='VIOLATES' else None,'satisfaction_basis':mechanism if result=='SATISFIES' else None,'reason_codes':reason,'conflicts':[],'dependency_ids':sorted(set([rid,rule_id]+eids)),'source_trace':{'requirement_id':rid,'technical_rule_id':rule_id,'evidence_ids':eids,'legacy_evaluation_id':x.get('evaluation_id'),'identity_relationship_ids':self._get(self._get(ev,'identity_usability',{}),'relationship_ids',[])},'rule_family':x.get('rule_family') or self._get(x.get('constraint',{}),'constraint_type') or 'UNCLASSIFIED','legacy_technical_result':legacy,'policy_version':POLICY_VERSION}
 @staticmethod
 def _mechanism(result,op):
  maximum={'less_than','less_than_or_equal','maximum','<','<='};minimum={'greater_than','greater_than_or_equal','minimum','>','>='}
  if result=='VIOLATES':return 'MEASURED_VALUE_EXCEEDS_MAXIMUM' if op in maximum else 'MEASURED_VALUE_BELOW_MINIMUM' if op in minimum else 'DETERMINISTIC_RULE_VIOLATED'
  if result=='SATISFIES':return 'MEASURED_VALUE_WITHIN_MAXIMUM' if op in maximum else 'MEASURED_VALUE_MEETS_MINIMUM' if op in minimum else 'DETERMINISTIC_RULE_SATISFIED'
 def compatibility_report(self,canonical,legacy):
  out=copy.deepcopy(self._plain(legacy));index={x['technical_evaluation_id']:x for x in canonical['results']};by_old={x['source_trace']['legacy_evaluation_id']:x for x in canonical['results']}
  for key in ('results','rule_results'):
   for x in out.get(key,[]):
    c=by_old.get(x.get('evaluation_id'));x['legacy_decision']=x.get('decision');x['decision']=c['execution_result'] if c else 'NOT_EXECUTABLE';x['canonical_technical_evaluation_id']=c['technical_evaluation_id'] if c else None
  return out
 def validate(self,artifact):
  diagnostics=[]
  for x in self._get(artifact,'results',[]) or []:
   r=x.get('execution_result');basis=x.get('execution_basis');trace=x.get('source_trace') or {}
   def add(c):diagnostics.append({'code':c,'requirement_id':x.get('requirement_id'),'technical_rule_id':x.get('technical_rule_id')})
   if r not in STATUSES:add('INVALID_TECHNICAL_STATUS')
   if r=='SATISFIES' and not basis:add('SATISFIES_WITHOUT_EXECUTION_BASIS')
   if r=='VIOLATES' and not basis:add('VIOLATES_WITHOUT_EXECUTION_BASIS')
   if r=='VIOLATES' and not x.get('failure_mechanism'):add('VIOLATES_WITHOUT_FAILURE_MECHANISM')
   if r in {'SATISFIES','VIOLATES'} and x.get('evidence_sufficiency')!='SUFFICIENT':add('INSUFFICIENT_EVIDENCE_EXECUTED')
   if r in {'SATISFIES','VIOLATES'} and x.get('identity_usability')!='USABLE':add('RESTRICTED_IDENTITY_EXECUTED_AS_AUTHORITATIVE')
   if r in {'SATISFIES','VIOLATES'} and x.get('applicability_status')!='APPLICABLE':add('UNKNOWN_APPLICABILITY_EXECUTED')
   if r in {'SATISFIES','VIOLATES'} and not all(trace.get(k) for k in ('requirement_id','technical_rule_id','legacy_evaluation_id')):add('TECHNICAL_SOURCE_TRACE_MISSING')
   if x.get('policy_version')!=POLICY_VERSION:add('STALE_TECHNICAL_VERSION')
  names=['SATISFIES_WITHOUT_EXECUTION_BASIS','VIOLATES_WITHOUT_EXECUTION_BASIS','VIOLATES_WITHOUT_FAILURE_MECHANISM','INCOMPATIBLE_UNIT_COMPARISON','PARAMETER_ROLE_SUBSTITUTION','WRONG_TEST_FAMILY_USED','WRONG_TEST_CONDITION_USED','DECLARED_USED_AS_MEASURED','MEASURED_USED_AS_RATED_WITHOUT_POLICY','MISSING_FORMULA_OPERAND_EXECUTED','CONFLICTING_VALUES_SILENTLY_RESOLVED','REPORT_VERDICT_USED_AS_TECHNICAL_AUTHORITY','INSUFFICIENT_EVIDENCE_EXECUTED','NOT_COMPARABLE_EVIDENCE_EXECUTED','RESTRICTED_IDENTITY_EXECUTED_AS_AUTHORITATIVE','UNKNOWN_APPLICABILITY_EXECUTED','INACTIVE_REQUIREMENT_EXECUTED','TECHNICAL_SOURCE_TRACE_MISSING','INVALID_TECHNICAL_STATUS','LEGACY_TECHNICAL_OVERRIDE','STALE_TECHNICAL_VERSION'];c=Counter(x['code'] for x in diagnostics);return {'schema_version':INTEGRITY_VERSION,'policy_version':POLICY_VERSION,'valid':not diagnostics,'total_errors':len(diagnostics),'diagnostic_counts':{x:c[x] for x in names},'diagnostics':diagnostics}
 @staticmethod
 def _number(v):
  try:return float(v)
  except:return v
 @classmethod
 def _plain(cls,v):
  if is_dataclass(v):return cls._plain(asdict(v))
  if isinstance(v,Enum):return v.value
  if isinstance(v,Mapping):return {str(k):cls._plain(x) for k,x in v.items()}
  if isinstance(v,(list,tuple)):return [cls._plain(x) for x in v]
  return v
 @staticmethod
 def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
 @staticmethod
 def _enum(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
 @classmethod
 def _hash(cls,v):return hashlib.sha256(json.dumps(cls._plain(v),sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
 @classmethod
 def save_json(cls,v,p):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(cls._plain(v),sort_keys=True,indent=2)+'\n');return p
