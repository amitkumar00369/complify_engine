"""Translate validated group findings into deterministic end-user issues and actions."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .generic_compliance_summary_models import IssueSeverity, IssueType


class ComplianceConclusion(str, Enum):
    COMPLIANT="COMPLIANT";NONCOMPLIANT="NONCOMPLIANT";UNRESOLVED="UNRESOLVED";NOT_EVALUATED="NOT_EVALUATED"
class FinalIssueType(str, Enum):
    CONFIRMED_NONCOMPLIANCE="CONFIRMED_NONCOMPLIANCE";MISSING_EVIDENCE="MISSING_EVIDENCE";INSUFFICIENT_EVIDENCE="INSUFFICIENT_EVIDENCE";INVALID_TEST_EVIDENCE="INVALID_TEST_EVIDENCE";UNRESOLVED_EVIDENCE_CONFLICT="UNRESOLVED_EVIDENCE_CONFLICT";TRACEABILITY_ISSUE="TRACEABILITY_ISSUE";STANDARD_SOURCE_GAP="STANDARD_SOURCE_GAP";CALCULATION_ISSUE="CALCULATION_ISSUE";TEST_CONDITION_ISSUE="TEST_CONDITION_ISSUE";APPLICABILITY_JUSTIFICATION_REQUIRED="APPLICABILITY_JUSTIFICATION_REQUIRED";REPORT_DATA_INCONSISTENCY="REPORT_DATA_INCONSISTENCY"
class FinalActionType(str, Enum):
    NO_ACTION="NO_ACTION";PROVIDE_EVIDENCE="PROVIDE_EVIDENCE";PROVIDE_PRODUCT_INFORMATION="PROVIDE_PRODUCT_INFORMATION";PROVIDE_NA_JUSTIFICATION="PROVIDE_NA_JUSTIFICATION";STANDARD_SOURCE_REQUEST="STANDARD_SOURCE_REQUEST";LAB_CLARIFICATION="LAB_CLARIFICATION";CORRECT_REPORT="CORRECT_REPORT";CORRECT_CALCULATION="CORRECT_CALCULATION";RETEST="RETEST";TECHNICAL_REVIEW="TECHNICAL_REVIEW"
class Actionability(str, Enum):ACTIONABLE="ACTIONABLE";SUPPRESSED="SUPPRESSED";INFORMATIONAL="INFORMATIONAL"
class FinalSeverity(str, Enum):CRITICAL="CRITICAL";HIGH="HIGH";MEDIUM="MEDIUM";LOW="LOW";INFO="INFO";UNKNOWN="UNKNOWN"

@dataclass(frozen=True)
class FinalNextAction:
    type:FinalActionType;description:str
@dataclass(frozen=True)
class FinalIssueProvenance:
    step_25b_status:Optional[str]=None;step_25c_status:Optional[str]=None;integrity_disposition:Optional[str]=None;originating_issue_type:Optional[str]=None;originating_issue_id:Optional[str]=None;upstream_reason:Optional[str]=None;upstream_metadata:Dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class FinalComplianceIssue:
    issue_id:str;clause_id:Optional[str];requirement_group_id:Optional[str];issue_type:FinalIssueType;compliance_conclusion:ComplianceConclusion;severity:FinalSeverity;actionability:Actionability;blocking:Optional[bool];user_explanation:str;impact:str;next_action:FinalNextAction;secondary_actions:List[FinalNextAction]=field(default_factory=list);evidence_refs:List[str]=field(default_factory=list);requirement_ids:List[str]=field(default_factory=list);product_fact_ids:List[str]=field(default_factory=list);provenance:FinalIssueProvenance=field(default_factory=FinalIssueProvenance);product_identity_ids:List[str]=field(default_factory=list);diagnostic:Optional[Dict[str,Any]]=None
@dataclass
class FinalComplianceIssueReport:
    schema_version:str;source_clause_summary_id:Optional[str];source_integrity_result_id:Optional[str];issues:List[FinalComplianceIssue];suppressed_findings:List[FinalComplianceIssue];summary:Dict[str,Any];quality_audit:Dict[str,int];genericity_audit:Dict[str,int];diagnostics:List[Dict[str,Any]]=field(default_factory=list)

class GenericFinalIssueResolver:
    """Translate upstream classifications; never perform a new compliance evaluation."""
    MAP={
      "TECHNICAL_VIOLATION":(FinalIssueType.CONFIRMED_NONCOMPLIANCE,FinalActionType.TECHNICAL_REVIEW),
      "MISSING_REPORT_EVIDENCE":(FinalIssueType.MISSING_EVIDENCE,FinalActionType.PROVIDE_EVIDENCE),
      "EVIDENCE_NOT_LINKED":(FinalIssueType.TRACEABILITY_ISSUE,FinalActionType.PROVIDE_EVIDENCE),
      "TEST_METHOD_INCOMPLETE":(FinalIssueType.INSUFFICIENT_EVIDENCE,FinalActionType.PROVIDE_EVIDENCE),
      "MISSING_MEASUREMENT":(FinalIssueType.INSUFFICIENT_EVIDENCE,FinalActionType.PROVIDE_EVIDENCE),
      "MISSING_PRODUCT_INFORMATION":(FinalIssueType.TRACEABILITY_ISSUE,FinalActionType.PROVIDE_PRODUCT_INFORMATION),
      "UNKNOWN_APPLICABILITY":(FinalIssueType.APPLICABILITY_JUSTIFICATION_REQUIRED,FinalActionType.PROVIDE_PRODUCT_INFORMATION),
      "AMBIGUOUS_REPORT_SCOPE":(FinalIssueType.TRACEABILITY_ISSUE,FinalActionType.LAB_CLARIFICATION),
      "KB_SEMANTIC_UNRESOLVED":(FinalIssueType.TRACEABILITY_ISSUE,FinalActionType.TECHNICAL_REVIEW),
      "INVALID_NA":(FinalIssueType.APPLICABILITY_JUSTIFICATION_REQUIRED,FinalActionType.PROVIDE_NA_JUSTIFICATION),
      "NA_APPLICABILITY_CONFLICT":(FinalIssueType.APPLICABILITY_JUSTIFICATION_REQUIRED,FinalActionType.PROVIDE_NA_JUSTIFICATION),
      "TEST_CONDITION_MISMATCH":(FinalIssueType.TEST_CONDITION_ISSUE,FinalActionType.RETEST),
      "CALCULATION_MISMATCH":(FinalIssueType.CALCULATION_ISSUE,FinalActionType.CORRECT_CALCULATION),
      "PRODUCT_INFORMATION_CONFLICT":(FinalIssueType.REPORT_DATA_INCONSISTENCY,FinalActionType.CORRECT_REPORT),
      "SAMPLE_IDENTITY_CONFLICT":(FinalIssueType.TRACEABILITY_ISSUE,FinalActionType.LAB_CLARIFICATION),
      "CROSS_EVIDENCE_VALUE_CONFLICT":(FinalIssueType.REPORT_DATA_INCONSISTENCY,FinalActionType.LAB_CLARIFICATION),
      "CONFLICTING_REPORT_VERDICT":(FinalIssueType.REPORT_DATA_INCONSISTENCY,FinalActionType.LAB_CLARIFICATION),
      "CONFLICTING_EVIDENCE":(FinalIssueType.UNRESOLVED_EVIDENCE_CONFLICT,FinalActionType.LAB_CLARIFICATION),
      "OTHER_REVIEW_REQUIRED":(FinalIssueType.TRACEABILITY_ISSUE,FinalActionType.TECHNICAL_REVIEW)}
    TEXT={
      FinalIssueType.CONFIRMED_NONCOMPLIANCE:("Upstream evaluation confirms that an applicable requirement is not satisfied.","Corrective technical review is required."),
      FinalIssueType.MISSING_EVIDENCE:("Required report evidence is not available for this requirement.","A reliable compliance conclusion cannot currently be established."),
      FinalIssueType.INSUFFICIENT_EVIDENCE:("The available evidence is insufficient to establish the requirement result.","The requirement remains unevaluated or unresolved."),
      FinalIssueType.INVALID_TEST_EVIDENCE:("Upstream validation identifies invalid test evidence.","The submitted test evidence cannot support a reliable conclusion."),
      FinalIssueType.UNRESOLVED_EVIDENCE_CONFLICT:("The available report evidence could not be reliably reconciled for this requirement.","A reliable compliance conclusion cannot currently be established."),
      FinalIssueType.TRACEABILITY_ISSUE:("Required scope, ownership, or product traceability is incomplete.","Evidence cannot yet be assigned reliably to the evaluated requirement."),
      FinalIssueType.STANDARD_SOURCE_GAP:("The governing standard amendment or revision used by the report is not available in the supplied source set.","The reported row cannot be evaluated against authoritative requirement content until the source set is aligned."),
      FinalIssueType.CALCULATION_ISSUE:("Upstream validation identifies a calculation inconsistency.","The affected calculated evidence requires correction."),
      FinalIssueType.TEST_CONDITION_ISSUE:("Upstream validation identifies an invalid or inconsistent test condition.","The existing test result may not support the evaluated requirement."),
      FinalIssueType.APPLICABILITY_JUSTIFICATION_REQUIRED:("The available information does not justify the reported applicability outcome.","Applicability cannot currently be resolved safely."),
      FinalIssueType.REPORT_DATA_INCONSISTENCY:("The report contains structured information that requires reconciliation or correction.","A reliable conclusion cannot be established until the inconsistency is resolved.")}
    ACTION_TEXT={FinalActionType.NO_ACTION:"No user action is required for this finding.",FinalActionType.PROVIDE_EVIDENCE:"Provide the authoritative supporting report evidence.",FinalActionType.PROVIDE_PRODUCT_INFORMATION:"Provide the missing or authoritative product information.",FinalActionType.PROVIDE_NA_JUSTIFICATION:"Provide documented justification for the reported not-applicable result.",FinalActionType.STANDARD_SOURCE_REQUEST:"Provide the governing amendment or revision used by the report so its requirements can be evaluated against authoritative source content.",FinalActionType.LAB_CLARIFICATION:"Request clarification from the test laboratory and obtain the authoritative supporting evidence.",FinalActionType.CORRECT_REPORT:"Obtain a corrected report that resolves the established inconsistency.",FinalActionType.CORRECT_CALCULATION:"Correct and independently verify the structured calculation.",FinalActionType.RETEST:"Repeat or verify the affected test under the required conditions.",FinalActionType.TECHNICAL_REVIEW:"Perform a documented technical review of the upstream finding."}
    DIAGNOSTIC_TEXT={
      "IDENTITY_RELATIONSHIP_UNRESOLVED":("The report identifies one model as the declared product and another as the tested model, but the available evidence does not establish the relationship between them.","Test evidence cannot yet be assigned reliably to the declared product.",FinalActionType.LAB_CLARIFICATION,"Provide the authoritative relationship between the declared model and the tested model, such as model-family, representative-model, equivalence, or corrected test documentation."),
      "APPLICABILITY_EXECUTION_CONFLICT":("The applicable requirement is resolved as not applicable for the evaluated product, but the report contains evidence showing the excluded test as performed. The report and applicability record therefore require reconciliation.","The report's applicability and test execution records are inconsistent, so the evaluated requirement cannot be accepted without clarification.",FinalActionType.LAB_CLARIFICATION,"Request laboratory clarification explaining why the test was performed despite the resolved not-applicable condition, and provide corrected applicability/result documentation."),
      "RATING_CONFLICT":("Structured product-rating observations are inconsistent and require reconciliation.","The report does not provide one authoritative rating basis for the evaluation.",FinalActionType.LAB_CLARIFICATION,"Request laboratory clarification identifying the authoritative product rating and corrected supporting documentation."),
      "CALCULATION_MISMATCH":("The structured reported calculation is inconsistent with its available inputs.","The reported calculation cannot currently be relied on as valid supporting evidence.",FinalActionType.TECHNICAL_REVIEW,"Perform a technical review of the calculation and provide corrected, verifiable inputs and result."),
      "LIMIT_EXCEEDED":("The structured measured result exceeds its identified applicable limit.","The measured result does not satisfy the stated limit.",FinalActionType.TECHNICAL_REVIEW,"Review the established limit evaluation and provide the authoritative technical disposition.")}
    def resolve(self,clause_summary,integrity_result):
        groups={(self._s(self._get(g,"clause_id")),self._s(self._get(g,"group_id"))):g for c in self._get(clause_summary,"clauses",[]) or [] for g in self._get(c,"group_summaries",[]) or []};integrity={(self._s(self._get(g,"clause_id")),self._s(self._get(g,"group_id"))):g for g in self._get(integrity_result,"group_integrity_results",[]) or []};emitted=[];suppressed=[]
        for key,group in sorted(groups.items()):
            integ=integrity.get(key);integrity_by_origin={self._s(self._get(x,"issue_id")):x for x in self._get(integ,"issues",[]) or []}
            for issue in self._get(group,"issues",[]) or []:
                origin_id=self._s(self._get(issue,"issue_id"));resolved=integrity_by_origin.get(origin_id);disposition=self._enum(self._get(resolved,"integrity_status"));
                if disposition in {"RECONCILED","NON_MATERIAL_DIFFERENCE"}:
                    suppressed.append(self._suppressed(group,issue,integ,resolved));continue
                emitted.append(self._translate(group,issue,integ,resolved))
        emitted=self._dedup(emitted);suppressed=self._dedup(suppressed);summary=self._summary(groups,emitted,suppressed)
        zero={k:0 for k in ("unresolved_converted_to_noncompliance_without_proof","reconciled_exposed_as_actionable_conflict","missing_evidence_treated_as_failure","missing_data_treated_as_rejection","severity_invented_from_clause_identity","standard_specific_production_branch","product_specific_production_branch","clause_specific_production_branch","page_specific_production_branch","model_specific_production_branch","report_specific_production_branch","fixture_specific_production_branch","upstream_decision_modified","upstream_artifact_mutated","overall_saas_aggregation_created","certification_claim_created")}
        source25b=self._get(clause_summary,"summary_id") or "CLAUSE-SUMMARY-"+hashlib.sha256(json.dumps(self._plain(clause_summary),sort_keys=True,separators=(",",":")).encode()).hexdigest()[:20].upper();source25c=self._get(integrity_result,"source_clause_summary_id")
        return FinalComplianceIssueReport("1.0",source25b,source25c,emitted,suppressed,summary,zero,{"fixture_specific_branches":0})
    def _translate(self,group,issue,integ,resolved):
        origin=self._enum(self._get(issue,"issue_type"));kind,action=self.MAP.get(origin,(FinalIssueType.TRACEABILITY_ISSUE,FinalActionType.TECHNICAL_REVIEW));disposition=self._enum(self._get(resolved,"integrity_status"));prior=self._enum(self._get(group,"final_status"));resolved_status=self._enum(self._get(integ,"resolved_status")) or prior
        if disposition in {"UNRESOLVED_CONFLICT","INSUFFICIENT_DATA"}:kind=FinalIssueType.UNRESOLVED_EVIDENCE_CONFLICT;action=FinalActionType.LAB_CLARIFICATION
        if disposition=="CONFIRMED_MATERIAL_CONFLICT":kind=FinalIssueType.REPORT_DATA_INCONSISTENCY;action=FinalActionType.CORRECT_REPORT
        proven_noncompliance=prior=="NON_COMPLIANT" and origin=="TECHNICAL_VIOLATION"
        conclusion=ComplianceConclusion.NONCOMPLIANT if proven_noncompliance else ComplianceConclusion.NOT_EVALUATED if prior in {"INSUFFICIENT_EVIDENCE","NOT_APPLICABLE","INACTIVE"} else ComplianceConclusion.UNRESOLVED
        severity=self._severity(self._get(issue,"severity"));blocking=self._get(issue,"blocking");explanation,impact=self.TEXT[kind];iid=self._id(self._s(self._get(group,"group_id")),origin,self._s(self._get(issue,"issue_id")),disposition or "NONE")
        diagnostic=copy.deepcopy(self._get(issue,"diagnostic"));diagnostic_type=self._s(self._get(diagnostic,"finding_type"))
        action_description=self.ACTION_TEXT[action]
        if diagnostic_type in self.DIAGNOSTIC_TEXT:
            explanation,impact,action,action_description=self.DIAGNOSTIC_TEXT[diagnostic_type]
        provenance=FinalIssueProvenance(prior,resolved_status,disposition,origin,self._s(self._get(issue,"issue_id")),self._s(self._get(issue,"reason")),{"integrity_reason":self._get(resolved,"final_integrity_reason"),"reconciliation":self._get(resolved,"reconciliation")})
        return FinalComplianceIssue(iid,self._s(self._get(group,"clause_id")),self._s(self._get(group,"group_id")),kind,conclusion,severity,Actionability.ACTIONABLE,blocking,explanation,impact,FinalNextAction(action,action_description),[],sorted(self._get(issue,"evidence_ids",[]) or []),sorted(self._get(issue,"requirement_ids",[]) or []),sorted(self._get(issue,"product_fact_ids",[]) or []),provenance,sorted(self._get(diagnostic,"product_identity_ids",[]) or []),diagnostic)
    def _suppressed(self,group,issue,integ,resolved):
        origin=self._enum(self._get(issue,"issue_type"));iid=self._id(self._s(self._get(group,"group_id")),origin,self._s(self._get(issue,"issue_id")),"SUPPRESSED");reason=self._get(resolved,"final_integrity_reason") or "The upstream integrity layer reconciled this finding."
        return FinalComplianceIssue(iid,self._s(self._get(group,"clause_id")),self._s(self._get(group,"group_id")),FinalIssueType.REPORT_DATA_INCONSISTENCY,ComplianceConclusion.NOT_EVALUATED,self._severity(self._get(issue,"severity")),Actionability.SUPPRESSED,False,"The apparent evidence difference was reconciled by structured upstream provenance.","No action is required solely for the reconciled difference.",FinalNextAction(FinalActionType.NO_ACTION,self.ACTION_TEXT[FinalActionType.NO_ACTION]),[],sorted(self._get(issue,"evidence_ids",[]) or []),sorted(self._get(issue,"requirement_ids",[]) or []),sorted(self._get(issue,"product_fact_ids",[]) or []),FinalIssueProvenance(self._enum(self._get(group,"final_status")),self._enum(self._get(integ,"resolved_status")),self._enum(self._get(resolved,"integrity_status")),origin,self._s(self._get(issue,"issue_id")),reason,{"reconciliation":self._get(resolved,"reconciliation")}))
    @staticmethod
    def _severity(value):
        raw=GenericFinalIssueResolver._enum(value);return FinalSeverity.INFO if raw=="INFORMATIONAL" else FinalSeverity(raw) if raw in FinalSeverity._value2member_map_ else FinalSeverity.UNKNOWN
    @staticmethod
    def _id(*parts):return "FINAL-ISSUE-"+hashlib.sha256("\x1f".join(str(x or "") for x in parts).encode()).hexdigest()[:20].upper()
    @staticmethod
    def _dedup(items):return sorted({x.issue_id:x for x in items}.values(),key=lambda x:x.issue_id)
    @staticmethod
    def _summary(groups,issues,suppressed):
        return {"total_input_groups":len(groups),"total_input_issues":sum(len(GenericFinalIssueResolver._get(x,"issues",[]) or []) for x in groups.values()),"total_emitted_issues":len(issues),"actionable_issues":sum(x.actionability==Actionability.ACTIONABLE for x in issues),"suppressed_reconciled_issues":len(suppressed),"informational_issues":sum(x.actionability==Actionability.INFORMATIONAL for x in issues),"counts_by_issue_type":dict(Counter(x.issue_type.value for x in issues)),"counts_by_compliance_conclusion":dict(Counter(x.compliance_conclusion.value for x in issues)),"counts_by_action_type":dict(Counter(x.next_action.type.value for x in issues)),"counts_by_severity":dict(Counter(x.severity.value for x in issues)),"counts_by_actionability":dict(Counter(x.actionability.value for x in issues+suppressed)),"unresolved_issue_count":sum(x.compliance_conclusion==ComplianceConclusion.UNRESOLVED for x in issues),"confirmed_noncompliance_count":sum(x.compliance_conclusion==ComplianceConclusion.NONCOMPLIANT for x in issues),"reconciled_suppressed_count":len(suppressed)}
    @staticmethod
    def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
    @staticmethod
    def _s(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
    _enum=_s
    @classmethod
    def _plain(cls,v):
        if isinstance(v,Enum):return v.value
        if is_dataclass(v):return cls._plain(asdict(v))
        if isinstance(v,dict):return {k:cls._plain(x) for k,x in v.items()}
        if isinstance(v,list):return [cls._plain(x) for x in v]
        return copy.deepcopy(v)
    @classmethod
    def to_dict(cls,v):
        if not is_dataclass(v):raise TypeError("final issue report required")
        return cls._plain(asdict(v))
    @classmethod
    def to_json(cls,v,indent=2):return json.dumps(cls.to_dict(v),ensure_ascii=False,sort_keys=True,indent=indent)
    @classmethod
    def save_json(cls,v,path):p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(cls.to_json(v)+"\n",encoding="utf-8");return p

__all__=["Actionability","ComplianceConclusion","FinalActionType","FinalComplianceIssue","FinalComplianceIssueReport","FinalIssueProvenance","FinalIssueType","FinalNextAction","FinalSeverity","GenericFinalIssueResolver"]
