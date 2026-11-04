"""Classify unresolved coverage gaps from final, independently derived decisions."""
from __future__ import annotations
import copy,json,re
from collections import Counter,defaultdict
from dataclasses import asdict,dataclass,field,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Dict,List,Mapping,Optional,Sequence
from urllib.parse import quote

class GapType(str,Enum):
 NO_GAP="NO_GAP";NON_COMPLIANCE_GAP="NON_COMPLIANCE_GAP";EVIDENCE_GAP="EVIDENCE_GAP";TECHNICAL_MEASUREMENT_GAP="TECHNICAL_MEASUREMENT_GAP";PRODUCT_DATA_GAP="PRODUCT_DATA_GAP";APPLICABILITY_GAP="APPLICABILITY_GAP";REPORT_SCOPE_GAP="REPORT_SCOPE_GAP";KB_REVIEW_GAP="KB_REVIEW_GAP";NA_CONFLICT_GAP="NA_CONFLICT_GAP";CONFLICTING_EVIDENCE_GAP="CONFLICTING_EVIDENCE_GAP";TEST_METHOD_EVIDENCE_GAP="TEST_METHOD_EVIDENCE_GAP";NOT_APPLICABLE="NOT_APPLICABLE";INACTIVE="INACTIVE";MULTIPLE_GAPS="MULTIPLE_GAPS"
class GapSeverity(str,Enum):
 CRITICAL="CRITICAL";HIGH="HIGH";MEDIUM="MEDIUM";LOW="LOW";INFORMATIONAL="INFORMATIONAL";NONE="NONE"
class GapResolutionAction(str,Enum):
 NONE="NONE";PROVIDE_REPORT_EVIDENCE="PROVIDE_REPORT_EVIDENCE";PROVIDE_MEASUREMENT="PROVIDE_MEASUREMENT";PROVIDE_PRODUCT_INFORMATION="PROVIDE_PRODUCT_INFORMATION";REVIEW_APPLICABILITY="REVIEW_APPLICABILITY";REVIEW_KB_REQUIREMENT="REVIEW_KB_REQUIREMENT";REVIEW_REPORT_SCOPE="REVIEW_REPORT_SCOPE";REVIEW_REPORTED_NA="REVIEW_REPORTED_NA";REVIEW_CONFLICTING_EVIDENCE="REVIEW_CONFLICTING_EVIDENCE";REPEAT_OR_VERIFY_TEST="REPEAT_OR_VERIFY_TEST";MANUAL_TECHNICAL_REVIEW="MANUAL_TECHNICAL_REVIEW";MULTIPLE_ACTIONS="MULTIPLE_ACTIONS"
@dataclass
class RequirementGapResult:
 gap_id:str;effective_requirement_id:str;effective_clause_id:Optional[str];clause_id:Optional[str];group_id:Optional[str];final_decision:Optional[str];primary_gap_type:GapType;secondary_gap_types:List[GapType]=field(default_factory=list);severity:GapSeverity=GapSeverity.NONE;resolution_actions:List[GapResolutionAction]=field(default_factory=list);reason_code:str="";reason:str="";missing_features:List[str]=field(default_factory=list);missing_measurements:List[str]=field(default_factory=list);missing_evidence_types:List[str]=field(default_factory=list);report_scope_status:List[str]=field(default_factory=list);scope_aware_na_status:Optional[str]=None;technical_constraint_decisions:List[str]=field(default_factory=list);supporting_evidence_ids:List[str]=field(default_factory=list);review_reasons:List[str]=field(default_factory=list);source_standard_refs:List[Dict[str,Any]]=field(default_factory=list);notes:Optional[str]=None
@dataclass
class GroupGapResult:
 group_id:str;clause_id:Optional[str];final_group_decision:Optional[str];primary_gap_type:GapType;secondary_gap_types:List[GapType];severity:GapSeverity;member_gap_ids:List[str];resolution_actions:List[GapResolutionAction];reason:str;review_reasons:List[str]=field(default_factory=list)
@dataclass
class ClauseGapResult:
 clause_id:str;final_clause_decision:Optional[str];primary_gap_type:GapType;secondary_gap_types:List[GapType];severity:GapSeverity;group_ids:List[str];requirement_ids:List[str];resolution_actions:List[GapResolutionAction];reason:str
@dataclass
class CoverageGapAnalysisReport:
 effective_kb_id:str;profile_id:str;report_document_id:str;requirement_gaps:List[RequirementGapResult]=field(default_factory=list);group_gaps:List[GroupGapResult]=field(default_factory=list);clause_gaps:List[ClauseGapResult]=field(default_factory=list);summary:Dict[str,Any]=field(default_factory=dict);diagnostics:List[Dict[str,Any]]=field(default_factory=list)

class GenericCoverageGapAnalyzer:
 PRIORITY=[GapType.NON_COMPLIANCE_GAP,GapType.NA_CONFLICT_GAP,GapType.CONFLICTING_EVIDENCE_GAP,GapType.KB_REVIEW_GAP,GapType.APPLICABILITY_GAP,GapType.REPORT_SCOPE_GAP,GapType.TECHNICAL_MEASUREMENT_GAP,GapType.TEST_METHOD_EVIDENCE_GAP,GapType.PRODUCT_DATA_GAP,GapType.EVIDENCE_GAP,GapType.NO_GAP,GapType.NOT_APPLICABLE,GapType.INACTIVE]
 SEVERITY={GapType.NON_COMPLIANCE_GAP:GapSeverity.CRITICAL,GapType.NA_CONFLICT_GAP:GapSeverity.HIGH,GapType.CONFLICTING_EVIDENCE_GAP:GapSeverity.HIGH,GapType.KB_REVIEW_GAP:GapSeverity.HIGH,GapType.APPLICABILITY_GAP:GapSeverity.MEDIUM,GapType.REPORT_SCOPE_GAP:GapSeverity.MEDIUM,GapType.TECHNICAL_MEASUREMENT_GAP:GapSeverity.MEDIUM,GapType.TEST_METHOD_EVIDENCE_GAP:GapSeverity.MEDIUM,GapType.PRODUCT_DATA_GAP:GapSeverity.MEDIUM,GapType.EVIDENCE_GAP:GapSeverity.MEDIUM,GapType.NO_GAP:GapSeverity.NONE,GapType.NOT_APPLICABLE:GapSeverity.NONE,GapType.INACTIVE:GapSeverity.NONE,GapType.MULTIPLE_GAPS:GapSeverity.HIGH}
 ACTION={GapType.NON_COMPLIANCE_GAP:GapResolutionAction.MANUAL_TECHNICAL_REVIEW,GapType.EVIDENCE_GAP:GapResolutionAction.PROVIDE_REPORT_EVIDENCE,GapType.TECHNICAL_MEASUREMENT_GAP:GapResolutionAction.PROVIDE_MEASUREMENT,GapType.PRODUCT_DATA_GAP:GapResolutionAction.PROVIDE_PRODUCT_INFORMATION,GapType.APPLICABILITY_GAP:GapResolutionAction.REVIEW_APPLICABILITY,GapType.REPORT_SCOPE_GAP:GapResolutionAction.REVIEW_REPORT_SCOPE,GapType.KB_REVIEW_GAP:GapResolutionAction.REVIEW_KB_REQUIREMENT,GapType.NA_CONFLICT_GAP:GapResolutionAction.REVIEW_REPORTED_NA,GapType.CONFLICTING_EVIDENCE_GAP:GapResolutionAction.REVIEW_CONFLICTING_EVIDENCE,GapType.TEST_METHOD_EVIDENCE_GAP:GapResolutionAction.REPEAT_OR_VERIFY_TEST,GapType.NO_GAP:GapResolutionAction.NONE,GapType.NOT_APPLICABLE:GapResolutionAction.NONE,GapType.INACTIVE:GapResolutionAction.NONE}
 def __init__(self):self._diagnostics=[]
 def analyze(self,final_decision_report,effective_kb,product_profile,group_aware_applicability,report_evidence,evidence_match,technical_constraint_result,requirement_grouping,report_evidence_scope,scope_aware_na_validation):
  self._diagnostics=[];apps={str(self._get(x,"effective_requirement_id")):x for x in self._get(group_aware_applicability,"results",[]) or []};tech=defaultdict(list)
  for x in self._get(technical_constraint_result,"results",[]) or []:tech[str(self._get(x,"effective_requirement_id"))].append(x)
  for x in self._get(technical_constraint_result,"rule_results",[]) or []:tech[str(self._get(x,"source_requirement_id"))].append(x)
  req_gaps=[self.analyze_requirement(x,apps.get(str(self._get(x,"effective_requirement_id")),{}),tech.get(str(self._get(x,"effective_requirement_id")),[])) for x in self._get(final_decision_report,"results",[]) or []];reqmap={x.effective_requirement_id:x for x in req_gaps};group_gaps=[]
  for g in self._get(final_decision_report,"group_decisions",[]) or []:group_gaps.append(self.analyze_group(g,[reqmap[x] for x in self._get(g,"member_requirement_ids",[]) if x in reqmap]))
  groupmap={x.group_id:x for x in group_gaps};clause_gaps=[]
  for c in self._get(final_decision_report,"clause_decisions",[]) or []:clause_gaps.append(self.analyze_clause(c,[groupmap[x] for x in self._get(c,"group_ids",[]) if x in groupmap]))
  report=CoverageGapAnalysisReport(str(self._get(final_decision_report,"effective_kb_id","")),str(self._get(final_decision_report,"profile_id","")),str(self._get(final_decision_report,"report_document_id","")),req_gaps,group_gaps,clause_gaps,diagnostics=copy.deepcopy(self._diagnostics));report.summary=self.get_summary(report,technical_constraint_result,scope_aware_na_validation);return report
 def analyze_requirement(self,final,app,technical):
  decision=self._enum(self._get(final,"final_decision"));types=[];code=str(self._get(final,"reason_code","") or "");na=self._enum(self._get(final,"scope_aware_na_status"));scopes=set(self._get(final,"report_scope_statuses",[]) or []);tdec=set(self._get(final,"technical_constraint_decisions",[]) or []);reviews=self._get(final,"review_reasons",[]) or []
  if decision=="COMPLIANT":types=[GapType.NO_GAP]
  elif decision=="NON_COMPLIANT":types=[GapType.NON_COMPLIANCE_GAP]
  elif decision=="NOT_APPLICABLE":types=[GapType.NOT_APPLICABLE]
  elif decision=="INACTIVE":types=[GapType.INACTIVE]
  else:
   if na=="POTENTIAL_CONFLICT" or code=="FINAL_NA_POTENTIAL_CONFLICT":types.append(GapType.NA_CONFLICT_GAP)
   if scopes&{"AMBIGUOUS","UNRESOLVED"} or "SCOPE_AMBIGUOUS" in code:types.append(GapType.REPORT_SCOPE_GAP)
   if "CONFLICTING" in code or any("CONFLICT" in str(x) and "NA_CONFLICT" not in str(x) for x in reviews):types.append(GapType.CONFLICTING_EVIDENCE_GAP)
   if "VIOLATES" in tdec:types.append(GapType.NON_COMPLIANCE_GAP)
   if "NO_MEASUREMENT" in tdec:types.append(GapType.TECHNICAL_MEASUREMENT_GAP)
   if "INCOMPARABLE" in tdec:types.extend([GapType.TECHNICAL_MEASUREMENT_GAP,GapType.TEST_METHOD_EVIDENCE_GAP])
   if tdec&{"UNKNOWN","NEEDS_REVIEW"}:types.append(GapType.KB_REVIEW_GAP)
   if "TEST_METHOD" in code:types.append(GapType.TEST_METHOD_EVIDENCE_GAP)
   if decision=="UNKNOWN_APPLICABILITY":
    kb=self._enum(self._get(app,"original_applicability_status"));types.append(GapType.KB_REVIEW_GAP if kb in {"UNRESOLVED","NEEDS_REVIEW"} else GapType.PRODUCT_DATA_GAP)
   if decision=="NEEDS_REVIEW" and "APPLICABILITY" in code:types.append(GapType.APPLICABILITY_GAP)
   if decision=="INSUFFICIENT_EVIDENCE" and not types:types.append(GapType.EVIDENCE_GAP)
   if decision=="NEEDS_REVIEW" and not types:types.append(GapType.KB_REVIEW_GAP)
  types=list(dict.fromkeys(types));primary=self._primary(types);secondary=[x for x in types if x is not primary];actions=sorted({self.ACTION[x] for x in types if x in self.ACTION},key=lambda x:x.value);missing_measurements=sorted({str(self._get(x,"constraint_id")) for x in technical if self._enum(self._get(x,"decision")) in {"NO_MEASUREMENT","INCOMPARABLE"}});missing_features=list(self._get(final,"missing_features",[]) or []);missing_evidence=[]
  if GapType.EVIDENCE_GAP in types:missing_evidence.append("REPORT_EVIDENCE")
  if GapType.TEST_METHOD_EVIDENCE_GAP in types:missing_evidence.append("TEST_METHOD_EVIDENCE")
  rid=str(self._get(final,"effective_requirement_id"));sources=list(self._get(final,"base_sources",[]) or [])+list(self._get(final,"delta_sources",[]) or []);return RequirementGapResult("GAP-R-"+quote(rid,safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"),rid,self._get(final,"effective_clause_id"),self._get(final,"clause_id"),self._get(final,"group_id"),decision,primary,secondary,self.SEVERITY[primary],actions,"GAP_"+primary.value,f"Final decision {decision} maps to {primary.value} from preserved upstream causes.",missing_features,missing_measurements,missing_evidence,list(scopes),na,sorted(tdec),list(self._get(final,"supporting_evidence_ids",[]) or []),list(reviews),copy.deepcopy(sources),"Coverage classification only.")
 def analyze_group(self,g,members):
  types=[]
  for x in members:types.extend([x.primary_gap_type]+x.secondary_gap_types)
  types=list(dict.fromkeys(types));decision=self._enum(self._get(g,"group_decision"));types=self._normalize_rollup(types,decision);primary=self._primary(types);secondary=[x for x in types if x is not primary];actions=sorted({self.ACTION[x] for x in types if x in self.ACTION},key=lambda x:x.value);gid=str(self._get(g,"group_id"));return GroupGapResult(gid,self._get(g,"clause_id"),decision,primary,secondary,self.SEVERITY[primary],[x.gap_id for x in members],actions,f"Deduplicated {len(members)} member gap records into logical group causes.",list(self._get(g,"review_reasons",[]) or []))
 def analyze_clause(self,c,groups):
  types=[]
  for x in groups:types.extend([x.primary_gap_type]+x.secondary_gap_types)
  decision=self._enum(self._get(c,"decision"));types=self._normalize_rollup(list(dict.fromkeys(types)),decision);primary=self._primary(types);secondary=[x for x in types if x is not primary];actions=sorted({self.ACTION[x] for x in types if x in self.ACTION},key=lambda x:x.value);cid=str(self._get(c,"clause_id"));return ClauseGapResult(cid,decision,primary,secondary,self.SEVERITY[primary],list(self._get(c,"group_ids",[]) or []),list(self._get(c,"requirement_ids",[]) or []),actions,f"Deduplicated logical group causes across clause {cid}.")
 @classmethod
 def _normalize_rollup(cls,types,decision):
  material=[x for x in types if x not in {GapType.NO_GAP,GapType.NOT_APPLICABLE,GapType.INACTIVE}]
  if material:return material
  return [GapType.NOT_APPLICABLE] if decision=="NOT_APPLICABLE" else [GapType.INACTIVE] if decision=="INACTIVE" else [GapType.NO_GAP]
 @classmethod
 def _primary(cls,types):return next((x for x in cls.PRIORITY if x in types),GapType.NO_GAP)
 @classmethod
 def get_summary(cls,report,technical,na_report):
  def layer(items,field):
   c=Counter(getattr(x,field).value for x in items);return {"total":len(items),**{x.value:c[x.value] for x in GapType}}
  severity=Counter(x.severity.value for x in report.group_gaps);actions=Counter(a.value for x in report.group_gaps for a in x.resolution_actions);req_final=Counter(x.final_decision for x in report.requirement_gaps);grp_final=Counter(x.final_group_decision for x in report.group_gaps);cl_final=Counter(x.final_clause_decision for x in report.clause_gaps);tc=Counter(cls._enum(cls._get(x,"decision")) for x in cls._get(technical,"results",[]) or []);na=Counter(cls._enum(cls._get(x,"status")) for x in cls._get(na_report,"group_results",[]) or [])
  return {"requirement_layer":layer(report.requirement_gaps,"primary_gap_type"),"group_layer":layer(report.group_gaps,"primary_gap_type"),"clause_layer":layer(report.clause_gaps,"primary_gap_type"),"severity":{x.value:severity[x.value] for x in GapSeverity},"resolution_actions":{x.value:actions[x.value] for x in GapResolutionAction},"coverage":{"requirements":{"applicable_requirement_count":sum(req_final[x] for x in ["COMPLIANT","NON_COMPLIANT","INSUFFICIENT_EVIDENCE","NEEDS_REVIEW"]),"requirements_with_sufficient_evidence":req_final["COMPLIANT"]+req_final["NON_COMPLIANT"],"requirements_with_partial_or_insufficient_evidence":req_final["INSUFFICIENT_EVIDENCE"]+req_final["NEEDS_REVIEW"],"requirements_with_unknown_applicability":req_final["UNKNOWN_APPLICABILITY"],"not_applicable_requirements":req_final["NOT_APPLICABLE"],"inactive_requirements":req_final["INACTIVE"]},"groups":{"applicable_group_count":sum(grp_final[x] for x in ["COMPLIANT","NON_COMPLIANT","INSUFFICIENT_EVIDENCE","NEEDS_REVIEW"]),"groups_with_sufficient_evidence":grp_final["COMPLIANT"]+grp_final["NON_COMPLIANT"],"groups_with_partial_or_insufficient_evidence":grp_final["INSUFFICIENT_EVIDENCE"]+grp_final["NEEDS_REVIEW"],"groups_with_unknown_applicability":grp_final["UNKNOWN_APPLICABILITY"],"not_applicable_groups":grp_final["NOT_APPLICABLE"],"inactive_groups":grp_final["INACTIVE"]},"clauses":{"evidence_sufficient":cl_final["COMPLIANT"]+cl_final["NON_COMPLIANT"],"partial_or_insufficient":cl_final["INSUFFICIENT_EVIDENCE"]+cl_final["NEEDS_REVIEW"],"unknown_applicability":cl_final["UNKNOWN_APPLICABILITY"],"not_applicable":cl_final["NOT_APPLICABLE"],"inactive":cl_final["INACTIVE"]}},"technical_evidence_coverage":{"constraints_with_observed_comparable_evidence":tc["SATISFIES"]+tc["VIOLATES"],"constraints_without_measurement":tc["NO_MEASUREMENT"],"constraints_needing_review":tc["NEEDS_REVIEW"]+tc["UNKNOWN"]+tc["INCOMPARABLE"]},"na_validation_coverage":{"validated_justified":na["JUSTIFIED"],"established_potential_conflict":na["POTENTIAL_CONFLICT"],"insufficient_product_data":na["INSUFFICIENT_PRODUCT_DATA"],"insufficient_report_scope":na["INSUFFICIENT_REPORT_EVIDENCE"],"review":na["NEEDS_REVIEW"]}}
 @staticmethod
 def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
 @staticmethod
 def _enum(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
 def get_diagnostics(self):return copy.deepcopy(self._diagnostics)
 @classmethod
 def to_dict(cls,v):return cls._safe(asdict(v)) if is_dataclass(v) else (_ for _ in ()).throw(TypeError("gap analysis model required"))
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
__all__=["ClauseGapResult","CoverageGapAnalysisReport","GapResolutionAction","GapSeverity","GapType","GenericCoverageGapAnalyzer","GroupGapResult","RequirementGapResult"]
