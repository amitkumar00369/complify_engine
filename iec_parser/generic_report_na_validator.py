"""Validate report N/A claims against independent requirement applicability."""
from __future__ import annotations
import copy,json,re
from collections import Counter,defaultdict
from dataclasses import asdict,dataclass,field,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Dict,Iterable,List,Mapping,Optional,Sequence,Set,Tuple
from urllib.parse import quote

class NAValidationStatus(str,Enum):
 JUSTIFIED="JUSTIFIED";POTENTIAL_CONFLICT="POTENTIAL_CONFLICT";INSUFFICIENT_PRODUCT_DATA="INSUFFICIENT_PRODUCT_DATA";INSUFFICIENT_KB_RULE="INSUFFICIENT_KB_RULE";INSUFFICIENT_REPORT_EVIDENCE="INSUFFICIENT_REPORT_EVIDENCE";NEEDS_REVIEW="NEEDS_REVIEW";NOT_REPORTED_NA="NOT_REPORTED_NA";INACTIVE="INACTIVE"
@dataclass
class NAEvidenceReference:
 evidence_id:Optional[str]=None;report_clause_id:Optional[str]=None;report_result_id:Optional[str]=None;reported_verdict:Optional[str]=None;page_start:Optional[int]=None;page_end:Optional[int]=None;match_status:Optional[str]=None;raw_text_excerpt:Optional[str]=None
@dataclass
class NAValidationResult:
 validation_id:str;effective_requirement_id:str;effective_clause_id:Optional[str];source_clause_id:Optional[str];effective_status:Optional[str];applicability_decision:Optional[str];reported_na:bool;status:NAValidationStatus;reason_code:str;reason:str;missing_features:List[str]=field(default_factory=list);conflicting_features:List[str]=field(default_factory=list);kb_rule_status:Optional[str]=None;evidence_match_status:Optional[str]=None;na_evidence:List[NAEvidenceReference]=field(default_factory=list);product_fact_refs:List[str]=field(default_factory=list);notes:Optional[str]=None
@dataclass
class ClauseNAValidationSummary:
 clause_id:str;requirements_total:int=0;reported_na_requirements:int=0;justified:int=0;potential_conflict:int=0;insufficient_product_data:int=0;insufficient_kb_rule:int=0;insufficient_report_evidence:int=0;needs_review:int=0;inactive:int=0;overall_na_status:Optional[str]=None
@dataclass
class NAValidationReport:
 effective_kb_id:str;profile_id:str;report_document_id:str;results:List[NAValidationResult]=field(default_factory=list);clause_summaries:List[ClauseNAValidationSummary]=field(default_factory=list);summary:Dict[str,Any]=field(default_factory=dict);diagnostics:List[Dict[str,Any]]=field(default_factory=list)

class GenericReportNAValidator:
 _RELIABLE={"EXACT_CLAUSE","EXACT_SUBCLAUSE","ANNEX_EXACT","PARENT_CLAUSE"}
 _UNSAFE={"MULTIPLE_CANDIDATES","NEEDS_REVIEW"}
 def __init__(self):self._diagnostics=[]
 def validate(self,effective_kb,product_profile,applicability_report,evidence_match_report,report_evidence,technical_constraint_report=None):
  self._diagnostics=[];apps={self._get(x,"effective_requirement_id"):x for x in self._get(applicability_report,"results",[]) or []};matches={self._get(x,"effective_requirement_id"):x for x in self._get(evidence_match_report,"matches",[]) or []};results=[];req_clause_ids=set()
  for req,container in self._requirements(effective_kb):
   rid=self._get(req,"effective_requirement_id");req_clause_ids.add(str(self._get(req,"clause_id")));results.append(self.validate_requirement(req,apps.get(rid),matches.get(rid),product_profile,container))
  clause_summaries=self._clause_summaries(results);used_na_ids={e.evidence_id for r in results for e in r.na_evidence if e.evidence_id};all_na=self._report_na_evidence(report_evidence)
  effective_clause_status=self._effective_clause_status(effective_kb)
  for item in all_na:
   eid=self._get(item,"evidence_id");cid=str(self._get(item,"clause_id"))
   if cid not in req_clause_ids:self._diagnostics.append({"code":"NA_REPORT_CLAUSE_WITHOUT_EFFECTIVE_REQUIREMENT","report_clause_id":cid,"evidence_id":eid,"effective_clause_status":effective_clause_status.get(cid),"reason":"Report N/A clause has no effective requirement object."})
   if eid not in used_na_ids:self._diagnostics.append({"code":"NA_REPORT_EVIDENCE_UNMATCHED","report_clause_id":cid,"evidence_id":eid,"page":self._get(item,"page_start"),"reason":"Report N/A evidence was not used by a reliable requirement match."})
  report=NAValidationReport(str(self._get(effective_kb,"effective_kb_id","")),str(self._get(product_profile,"profile_id","")),str(self._get(report_evidence,"document_id","")),results,clause_summaries,diagnostics=copy.deepcopy(self._diagnostics));report.summary=self.get_summary(report,all_na);return report
 def validate_requirement(self,requirement,app_result,match_result,product_profile=None,effective_clause_id=None):
  rid=str(self._get(requirement,"effective_requirement_id"));clause=self._get(requirement,"clause_id");estatus=self._enum(self._get(requirement,"effective_status"));app=self._enum(self._get(app_result,"decision"));mstatus=self._enum(self._get(match_result,"match_status"));refs=self._get(match_result,"evidence_refs",[]) or [];na_refs=[self._na_ref(x,mstatus) for x in refs if self._enum(self._get(x,"reported_verdict"))=="NA"];verdicts={self._enum(self._get(x,"reported_verdict")) for x in refs if self._enum(self._get(x,"reported_verdict")) not in {None,"NOT_STATED"}};missing=sorted(self._get(app_result,"missing_features",[]) or []);conflicting=sorted(self._get(app_result,"conflicting_features",[]) or []);facts=self._get(app_result,"facts_used",[]) or [];fact_refs=sorted({str(self._get(x,"feature_id")) for x in facts});kbstatus=self._get(app_result,"applicability_status_from_kb");base=dict(validation_id=self._id(rid),effective_requirement_id=rid,effective_clause_id=effective_clause_id,source_clause_id=clause,effective_status=estatus,applicability_decision=app,missing_features=missing,conflicting_features=conflicting,kb_rule_status=kbstatus,evidence_match_status=mstatus,na_evidence=na_refs,product_fact_refs=fact_refs)
  if estatus=="INACTIVE" or app=="INACTIVE":return self._result(base,bool(na_refs),NAValidationStatus.INACTIVE,"NA_EFFECTIVE_REQUIREMENT_INACTIVE","Effective requirement is inactive.")
  if not na_refs:return self._result(base,False,NAValidationStatus.NOT_REPORTED_NA,"NA_NOT_REPORTED","Matched report evidence does not state N/A.")
  if len(verdicts)>1:return self._result(base,True,NAValidationStatus.NEEDS_REVIEW,"NA_CONFLICTING_REPORT_VERDICTS","N/A conflicts with another report verdict occurrence.")
  if mstatus in self._UNSAFE:return self._result(base,True,NAValidationStatus.INSUFFICIENT_REPORT_EVIDENCE,"NA_EVIDENCE_MATCH_AMBIGUOUS","N/A evidence association is ambiguous.")
  if mstatus not in self._RELIABLE:return self._result(base,True,NAValidationStatus.INSUFFICIENT_REPORT_EVIDENCE,"NA_EVIDENCE_MATCH_AMBIGUOUS","N/A evidence is not reliably associated with this requirement.")
  circular=any(self._enum(self._get(x,"status"))=="INFERRED_FROM_NA" for x in facts)
  if conflicting:return self._result(base,True,NAValidationStatus.NEEDS_REVIEW,"NA_PRODUCT_FACT_CONFLICT","Applicability depends on conflicting product facts.")
  if app=="NOT_APPLICABLE":
   if circular:return self._result(base,True,NAValidationStatus.INSUFFICIENT_PRODUCT_DATA,"NA_CIRCULAR_INFERRED_FROM_NA","N/A-derived product data cannot justify the same report N/A.")
   return self._result(base,True,NAValidationStatus.JUSTIFIED,"NA_JUSTIFIED_BY_NOT_APPLICABLE","Independent applicability evaluation found the requirement not applicable.",notes="Report N/A is stated at parent-clause level." if mstatus=="PARENT_CLAUSE" else None)
  if app=="APPLICABLE":return self._result(base,True,NAValidationStatus.POTENTIAL_CONFLICT,"NA_CONFLICT_WITH_APPLICABLE","Requirement appears applicable while matched report evidence states N/A.",notes="Report N/A is stated at parent-clause level." if mstatus=="PARENT_CLAUSE" else None)
  reason_code=str(self._get(app_result,"reason_code","") or "");kb_issue=(kbstatus in {"UNRESOLVED","NEEDS_REVIEW"} or reason_code in {"INVALID_RULE","KB_APPLICABILITY_UNRESOLVED","KB_APPLICABILITY_NEEDS_REVIEW","INCOMPARABLE_VALUE"});product_issue=bool(missing or circular or any(self._enum(self._get(x,"status")) in {"UNKNOWN","INFERRED","INFERRED_FROM_NA"} for x in facts))
  if kb_issue and product_issue:return self._result(base,True,NAValidationStatus.NEEDS_REVIEW,"NA_MULTIPLE_UNCERTAINTIES","Both product data and KB applicability semantics are insufficient.")
  if product_issue:return self._result(base,True,NAValidationStatus.INSUFFICIENT_PRODUCT_DATA,"NA_CIRCULAR_INFERRED_FROM_NA" if circular else "NA_MISSING_PRODUCT_FACTS","Additional product facts are needed to validate N/A.")
  if kb_issue:return self._result(base,True,NAValidationStatus.INSUFFICIENT_KB_RULE,"NA_KB_RULE_UNRESOLVED","The normalized KB applicability rule is insufficient.")
  return self._result(base,True,NAValidationStatus.NEEDS_REVIEW,"NA_APPLICABILITY_REVIEW","Applicability cannot be safely explained from available diagnostics.")
 @staticmethod
 def _result(base,reported,status,code,reason,notes=None):return NAValidationResult(**base,reported_na=reported,status=status,reason_code=code,reason=reason,notes=notes)
 @classmethod
 def _na_ref(cls,x,mstatus):return NAEvidenceReference(cls._get(x,"evidence_id"),cls._get(x,"report_clause_id"),cls._get(x,"report_result_id"),cls._enum(cls._get(x,"reported_verdict")),cls._get(x,"page_start"),cls._get(x,"page_end"),mstatus,cls._get(x,"raw_text_excerpt"))
 @classmethod
 def _clause_summaries(cls,results):
  groups=defaultdict(list)
  for r in results:groups[str(r.source_clause_id)].append(r)
  output=[]
  for cid,items in sorted(groups.items()):
   na=[x for x in items if x.reported_na];c=Counter(x.status.value for x in na);overall=None
   for s in [NAValidationStatus.POTENTIAL_CONFLICT,NAValidationStatus.NEEDS_REVIEW,NAValidationStatus.INSUFFICIENT_REPORT_EVIDENCE,NAValidationStatus.INSUFFICIENT_KB_RULE,NAValidationStatus.INSUFFICIENT_PRODUCT_DATA]:
    if c[s.value]:overall=s.value;break
   if overall is None and na and all(x.status is NAValidationStatus.JUSTIFIED for x in na):overall="JUSTIFIED"
   if overall is None and na and all(x.status is NAValidationStatus.INACTIVE for x in na):overall="INACTIVE"
   output.append(ClauseNAValidationSummary(cid,len(items),len(na),c["JUSTIFIED"],c["POTENTIAL_CONFLICT"],c["INSUFFICIENT_PRODUCT_DATA"],c["INSUFFICIENT_KB_RULE"],c["INSUFFICIENT_REPORT_EVIDENCE"],c["NEEDS_REVIEW"],c["INACTIVE"],overall))
  return output
 @classmethod
 def _report_na_evidence(cls,report):
  out=[]
  def walk(items):
   for c in items:
    for e in cls._get(c,"evidence_items",[]) or []:
     if cls._enum(cls._get(e,"reported_verdict"))=="NA":out.append(e)
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
 @classmethod
 def _effective_clause_status(cls,kb):
  out={}
  def walk(items):
   for c in items:out[str(cls._get(c,"clause_id"))]=cls._enum(cls._get(c,"effective_status"));walk(cls._get(c,"children",[]) or [])
  walk(cls._get(kb,"clauses",[]) or []);return out
 @staticmethod
 def get_summary(report,all_na=None):
  c=Counter(x.status.value for x in report.results);na=[x for x in report.results if x.reported_na];unique_all={str(GenericReportNAValidator._get(x,"clause_id")) for x in all_na or []};matched={str(e.report_clause_id) for x in na for e in x.na_evidence};cs=report.clause_summaries
  return {"total_effective_requirements":len(report.results),"requirements_with_report_na":len(na),**{s.value:c[s.value] for s in NAValidationStatus},"na_evidence_references":sum(len(x.na_evidence) for x in na),"unique_report_na_clauses":len(unique_all),"matched_report_na_clauses":len(matched),"unmatched_report_na_clauses":len(unique_all-matched),"clauses_with_all_na_justified":sum(x.overall_na_status=="JUSTIFIED" for x in cs),"clauses_with_potential_conflicts":sum(x.overall_na_status=="POTENTIAL_CONFLICT" for x in cs),"clauses_needing_more_product_data":sum(x.overall_na_status=="INSUFFICIENT_PRODUCT_DATA" for x in cs),"clauses_needing_kb_review":sum(x.overall_na_status=="INSUFFICIENT_KB_RULE" for x in cs),"clauses_needing_report_evidence_review":sum(x.overall_na_status=="INSUFFICIENT_REPORT_EVIDENCE" for x in cs),"clauses_needing_review":sum(x.overall_na_status=="NEEDS_REVIEW" for x in cs)}
 @staticmethod
 def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
 @staticmethod
 def _enum(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
 @staticmethod
 def _id(rid):return "NA-VALIDATION-"+quote(rid,safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-")
 @classmethod
 def to_dict(cls,v):return cls._safe(asdict(v)) if is_dataclass(v) else (_ for _ in ()).throw(TypeError("validation model required"))
 @classmethod
 def _safe(cls,v):
  if isinstance(v,Enum):return v.value
  if isinstance(v,dict):return {k:cls._safe(x) for k,x in v.items()}
  if isinstance(v,list):return [cls._safe(x) for x in v]
  return v
 @classmethod
 def to_json(cls,v,indent=2):return json.dumps(cls.to_dict(v),ensure_ascii=False,sort_keys=True,indent=indent)
 @classmethod
 def save_json(cls,r,p):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(cls.to_json(r)+"\n",encoding="utf-8");return p
 def get_diagnostics(self):return copy.deepcopy(self._diagnostics)

__all__=["ClauseNAValidationSummary","GenericReportNAValidator","NAEvidenceReference","NAValidationReport","NAValidationResult","NAValidationStatus"]
