"""Build deterministic clause and logical-group views from established artifacts."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .generic_compliance_issue_policy import GenericComplianceIssuePolicy
from .generic_compliance_summary_models import (ActionType, ClauseEvaluationSummary,
 ComplianceIssue, ComplianceSummarySerializer, EvaluationConfidenceStatus,
 FinalComplianceStatus, IssueSeverity, IssueType, LogicalGroupEvaluationSummary,
 NextAction, SourceTraceability)


class GenericClauseEvaluationSummaryBuilder:
    """Project upstream decisions into compact UI summaries without reevaluation."""
    GAP_ISSUES={"NON_COMPLIANCE_GAP":IssueType.TECHNICAL_VIOLATION,
      "EVIDENCE_GAP":IssueType.MISSING_REPORT_EVIDENCE,
      "TECHNICAL_MEASUREMENT_GAP":IssueType.MISSING_MEASUREMENT,
      "PRODUCT_DATA_GAP":IssueType.MISSING_PRODUCT_INFORMATION,
      "APPLICABILITY_GAP":IssueType.UNKNOWN_APPLICABILITY,
      "REPORT_SCOPE_GAP":IssueType.AMBIGUOUS_REPORT_SCOPE,
      "KB_REVIEW_GAP":IssueType.KB_SEMANTIC_UNRESOLVED,
      "NA_CONFLICT_GAP":IssueType.NA_APPLICABILITY_CONFLICT,
      "CONFLICTING_EVIDENCE_GAP":IssueType.CONFLICTING_REPORT_VERDICT,
      "TEST_METHOD_EVIDENCE_GAP":IssueType.TEST_METHOD_INCOMPLETE}
    def __init__(self,policy:Optional[GenericComplianceIssuePolicy]=None):self.policy=policy or GenericComplianceIssuePolicy()
    def build(self,effective_kb,product_profile,report_evidence,applicability,evidence_match,
              requirement_grouping,final_decision,coverage_gap,technical_constraint_result=None,
              scope_aware_na_validation=None,group_aware_applicability=None,
              report_evidence_scope=None,overall_readiness=None,
              cross_evidence_consistency_result=None):
        groups=list(self._get(requirement_grouping,"groups",[]) or []);reqs,clause_titles=self._requirements(effective_kb)
        facts=self._facts(product_profile);evidence=self._evidence(report_evidence)
        apps=self._index(self._get(applicability,"results",[]) or [],"effective_requirement_id")
        group_apps=self._index(self._get(group_aware_applicability,"results",[]) or [],"effective_requirement_id")
        matches=self._index(self._get(evidence_match,"matches",[]) or [],"effective_requirement_id")
        finals=self._index(self._get(final_decision,"results",[]) or [],"effective_requirement_id")
        final_groups=self._index(self._get(final_decision,"group_decisions",[]) or [],"group_id")
        gaps=self._index(self._get(coverage_gap,"requirement_gaps",[]) or [],"effective_requirement_id")
        group_gaps=self._index(self._get(coverage_gap,"group_gaps",[]) or [],"group_id")
        tech=defaultdict(list)
        for x in self._get(technical_constraint_result,"results",[]) or []:tech[self._s(self._get(x,"effective_requirement_id"))].append(x)
        for x in self._get(technical_constraint_result,"rule_results",[]) or []:tech[self._s(self._get(x,"source_requirement_id"))].append(x)
        na=self._index(self._get(scope_aware_na_validation,"member_results",[]) or [],"effective_requirement_id")
        scopes_by_group=defaultdict(list)
        for x in self._get(report_evidence_scope,"results",[]) or []:
            for selected in self._get(x,"selected_groups",[]) or []:scopes_by_group[self._s(self._get(selected,"group_id"))].append(x)
        consistency_by_group=defaultdict(list)
        consistency_by_clause=defaultdict(list)
        global_consistency=[]
        for finding in self._get(cross_evidence_consistency_result,"findings",[]) or []:
            group_ids=list(self._get(finding,"requirement_group_ids",[]) or [])
            clause_ids=list(self._get(finding,"clause_ids",[]) or [])
            subject=self._get(finding,"subject",{}) or {}
            if self._get(subject,"requirement_group_id"):group_ids.append(self._get(subject,"requirement_group_id"))
            if self._get(subject,"clause_id"):clause_ids.append(self._get(subject,"clause_id"))
            for key in set(self._s(x) for x in group_ids if x):consistency_by_group[key].append(finding)
            for key in set(self._s(x) for x in clause_ids if x):consistency_by_clause[key].append(finding)
            if not group_ids and not clause_ids:global_consistency.append(finding)
        summaries=[]
        clauses_with_assigned_consistency=set()
        for group_index,group in enumerate(groups):
            gid=self._s(self._get(group,"group_id"));clause=self._s(self._get(group,"clause_id"));members=[self._s(self._get(x,"effective_requirement_id")) for x in self._get(group,"members",[]) or []]
            consistency=list(consistency_by_group.get(gid,[]))
            if not consistency and clause in consistency_by_clause and clause not in clauses_with_assigned_consistency:
                consistency=list(consistency_by_clause[clause]);clauses_with_assigned_consistency.add(clause)
            if group_index==0:consistency.extend(global_consistency)
            summaries.append(self._group_summary(gid,clause,members,group,reqs,clause_titles,facts,evidence,apps,group_apps,matches,finals,final_groups.get(gid),gaps,group_gaps.get(gid),tech,na,scopes_by_group.get(gid,[]),consistency))
        clauses=[]
        by_clause=defaultdict(list)
        for x in summaries:by_clause[x.clause_id].append(x)
        for clause,items in by_clause.items():
            issues=self._dedup_issues([x for g in items for x in g.issues]);actions=self._dedup_actions([x for g in items for x in g.next_actions]);status=self.policy.aggregate_same_scope([x.final_status for x in items]);severity=self._highest([x.severity for x in items if x.severity]);trace=self._merge_trace([x.source_traceability for x in items])
            clauses.append(ClauseEvaluationSummary(clause,status,clause_titles.get(clause),severity,sorted(x.group_id for x in items),sorted({r for x in items for r in x.effective_requirement_ids}),[],[],[],issues,actions,"Conservative aggregation of logical-group statuses.",trace,sorted(items,key=lambda x:x.group_id),len(issues)))
        return sorted(clauses,key=lambda x:self._natural(x.clause_id))
    def _group_summary(self,gid,clause,members,group,reqs,titles,facts,evidence,apps,group_apps,matches,finals,group_final,gaps,group_gap,tech,na,scopes,consistency_findings=None):
        member_reqs=[reqs[x] for x in members if x in reqs];member_apps=[apps[x] for x in members if x in apps];member_group_apps=[group_apps[x] for x in members if x in group_apps];member_matches=[matches[x] for x in members if x in matches];member_finals=[finals[x] for x in members if x in finals];member_gaps=[gaps[x] for x in members if x in gaps];member_na=[na[x] for x in members if x in na];member_tech=[x for rid in members for x in tech.get(rid,[])]
        feature_keys=sorted({self._feature_key(v) for x in member_apps for key in ("facts_used","required_features","missing_features","review_features","conflicting_features") for v in self._get(x,key,[]) or [] if self._feature_key(v)})
        condition_text=" ".join(str(self._get(x,"condition_text","") or "").casefold() for x in member_apps)
        feature_keys=sorted(set(feature_keys)|{key for key in facts if key and key.casefold().replace("_"," ") in condition_text})
        product_view=[]
        for key in feature_keys:
            fact=facts.get(key);product_view.append({"feature_key":key,"fact_id":self._get(fact,"fact_id",self._get(fact,"feature_id")),"value":copy.deepcopy(self._get(fact,"value")),"status":self._enum(self._get(fact,"status")) if fact else "MISSING","provenance":copy.deepcopy(self._get(fact,"evidence",[]) or []) if fact else []})
        evidence_ids=set()
        for x in member_finals:evidence_ids.update(self._get(x,"supporting_evidence_ids",[]) or [])
        for x in member_gaps:evidence_ids.update(self._get(x,"supporting_evidence_ids",[]) or [])
        for x in member_matches:
            for ref in self._get(x,"evidence_refs",[]) or []:
                eid=self._get(ref,"evidence_id");evidence_ids.add(eid) if eid else None
        for x in scopes:
            eid=self._get(x,"report_evidence_id");evidence_ids.add(eid) if eid else None
        evidence_view=[self._evidence_view(evidence[x],self._scope_status(x,scopes)) for x in sorted(evidence_ids) if x in evidence]
        issues=[]
        gap_types=[]
        for gap in member_gaps:
            gap_types.extend([self._enum(self._get(gap,"primary_gap_type"))]+[self._enum(x) for x in self._get(gap,"secondary_gap_types",[]) or []])
        if group_gap:gap_types.extend([self._enum(self._get(group_gap,"primary_gap_type"))]+[self._enum(x) for x in self._get(group_gap,"secondary_gap_types",[]) or []])
        for gap_type in sorted(set(x for x in gap_types if x in self.GAP_ISSUES)):
            if gap_type=="CONFLICTING_EVIDENCE_GAP" and len(members)>1 and not (
                any(self._enum(self._get(x,"match_status"))=="CONFLICTING_VERDICTS" for x in member_matches)
                or any(len(set(self._get(x,"report_verdicts",[]) or []))>1 for x in member_finals)
            ):
                continue
            issues.append(self._issue(self.GAP_ISSUES[gap_type],gid,clause,members,evidence_ids,member_gaps,gap_type))
        if any(self._enum(self._get(x,"match_status"))=="CONFLICTING_VERDICTS" for x in member_matches) or any(len(set(self._get(x,"report_verdicts",[]) or []))>1 for x in member_finals):issues.append(self._issue(IssueType.CONFLICTING_REPORT_VERDICT,gid,clause,members,evidence_ids,member_matches,"Conflicting upstream verdict records require reconciliation."))
        if any(self._enum(self._get(x,"decision"))=="NO_MEASUREMENT" for x in member_tech):issues.append(self._issue(IssueType.MISSING_MEASUREMENT,gid,clause,members,evidence_ids,member_tech,"A technical result explicitly reports no measurement."))
        for finding in consistency_findings or []:
            finding_type=self._enum(self._get(finding,"finding_type"));finding_status=self._enum(self._get(finding,"status"))
            if finding_status not in {"MATERIAL_CONFLICT","UNRESOLVED"}:continue
            mapping={"IDENTITY_CONFLICT":IssueType.SAMPLE_IDENTITY_CONFLICT,
                     "IDENTITY_RELATIONSHIP_UNRESOLVED":IssueType.OTHER_REVIEW_REQUIRED,
                     "RATING_CONFLICT":IssueType.CROSS_EVIDENCE_VALUE_CONFLICT,
                     "VALUE_CONFLICT":IssueType.CROSS_EVIDENCE_VALUE_CONFLICT,
                     "TEST_CONDITION_MISMATCH":IssueType.TEST_CONDITION_MISMATCH,
                     "CALCULATION_MISMATCH":IssueType.CALCULATION_MISMATCH,
                     "APPLICABILITY_EXECUTION_CONFLICT":IssueType.CONFLICTING_EVIDENCE}
            issue_type=mapping.get(finding_type,IssueType.OTHER_REVIEW_REQUIRED)
            if finding_status=="UNRESOLVED":issue_type=IssueType.OTHER_REVIEW_REQUIRED
            finding_evidence=set(self._get(finding,"evidence_ids",[]) or []);evidence_ids.update(finding_evidence)
            reason=self._get(self._get(finding,"reconciliation",{}) or {},"reason") or "Cross-evidence consistency review is required."
            issues.append(self._issue(issue_type,gid,clause,members,finding_evidence,[finding],reason,self._consistency_diagnostic(finding)))
        issues=self._dedup_issues(issues);actions=self._actions(issues)
        internal=self._enum(self._get(group_final,"group_decision")) or self._aggregate_internal([self._enum(self._get(x,"final_decision")) for x in member_finals])
        proven_violation=internal=="NON_COMPLIANT" and any(self._enum(self._get(x,"decision"))=="VIOLATES" for x in member_tech)
        status=self._status(internal,issues,proven_violation)
        standard_view=[self._standard_view(x) for x in member_reqs];technical_view=[self._technical_view(x) for x in member_tech]
        app_view={"group_decisions":[self._plain(x) for x in member_group_apps],"member_decisions":[self._plain(x) for x in member_apps],**{key:sorted({self._feature_key(v) for x in member_apps for v in self._get(x,key,[]) or [] if self._feature_key(v)}) for key in ("facts_used","required_features","missing_features","review_features","conflicting_features")}}
        match_view={"member_matches":[self._plain(x) for x in member_matches],"matched_evidence_ids":sorted(evidence_ids),"statuses":sorted({self._enum(self._get(x,"match_status")) for x in member_matches})}
        na_view={"available":bool(member_na),"member_results":[self._plain(x) for x in member_na]}
        trace=SourceTraceability(members,[gid],sorted(evidence_ids),[self._s(self._get(facts[k],"fact_id",self._get(facts[k],"feature_id"))) for k in feature_keys if k in facts and self._get(facts[k],"fact_id",self._get(facts[k],"feature_id"))],feature_keys,[self._s(self._get(x,"evaluation_id")) for x in member_apps if self._get(x,"evaluation_id")],[self._s(self._get(x,"match_id")) for x in member_matches if self._get(x,"match_id")],[self._s(self._get(x,"validation_id")) for x in member_na if self._get(x,"validation_id")],[self._s(self._get(x,"evaluation_id")) for x in member_tech if self._get(x,"evaluation_id")],[self._s(self._get(x,"decision_id")) for x in member_finals if self._get(x,"decision_id")],[self._s(self._get(x,"gap_id")) for x in member_gaps if self._get(x,"gap_id")],[])
        reason=self._get(group_final,"reason") or "; ".join(dict.fromkeys(self._s(self._get(x,"reason")) for x in member_finals if self._get(x,"reason")))
        return LogicalGroupEvaluationSummary(clause,gid,status,titles.get(clause),self._highest([x.severity for x in issues]),members,standard_view,product_view,evidence_view,app_view,match_view,na_view,technical_view,issues,actions,reason,trace)
    def _status(self,internal,issues,proven_violation):
        if internal=="NOT_APPLICABLE":return FinalComplianceStatus.NOT_APPLICABLE
        if internal=="INACTIVE":return FinalComplianceStatus.INACTIVE
        if internal=="COMPLIANT" and not issues:return FinalComplianceStatus.COMPLIANT
        return self.policy.resolve(issues=issues,proven_technical_violation=proven_violation,evidence_sufficient=internal not in {"INSUFFICIENT_EVIDENCE"})
    def _issue(self,typ,gid,clause,members,evidence_ids,sources,reason,diagnostic=None):
        severity=self.policy.severity_for(typ);blocking=typ!=IssueType.OTHER_REVIEW_REQUIRED;identity=json.dumps([typ.value,gid,sorted(members),sorted(evidence_ids)],separators=(",",":"));iid="ISSUE-"+hashlib.sha256(identity.encode()).hexdigest()[:20].upper()
        return ComplianceIssue(typ,severity,blocking,typ.value.replace("_"," ").title(),str(reason),iid,clause,gid,sorted(members),sorted(evidence_ids),[],[],sorted({"derived_summary"}),.95 if typ==IssueType.TECHNICAL_VIOLATION else .8,EvaluationConfidenceStatus.RESOLVED if typ not in {IssueType.CONFLICTING_REPORT_VERDICT,IssueType.CONFLICTING_EVIDENCE} else EvaluationConfidenceStatus.NEEDS_REVIEW,None,SourceTraceability(sorted(members),[gid],sorted(evidence_ids)),diagnostic)
    @classmethod
    def _consistency_diagnostic(cls,finding):
        finding_type=cls._enum(cls._get(finding,"finding_type"))
        titles={"IDENTITY_RELATIONSHIP_UNRESOLVED":"Declared and tested product identities require reconciliation","APPLICABILITY_EXECUTION_CONFLICT":"Report test execution conflicts with resolved applicability","RATING_CONFLICT":"Product rating information is inconsistent","TEST_CONDITION_MISMATCH":"Reported test condition does not match the required test basis","CALCULATION_MISMATCH":"Reported calculation is inconsistent with the available inputs","LIMIT_EXCEEDED":"Measured result exceeds the applicable limit","UNIT_OR_PARAMETER_AMBIGUITY":"Reported values cannot be compared reliably"}
        labels={"DECLARED_MODEL":"Declared model","TESTED_MODEL":"Tested model","STANDARD_APPLICABILITY":"Standard applicability","REPORT_EXECUTION":"Report execution"}
        observations=[]
        for observation in cls._get(finding,"observations",[]) or []:
            role=cls._enum(cls._get(observation,"role"));observations.append({"label":labels.get(role,role.replace("_"," ").title() if role else "Observation"),"value":copy.deepcopy(cls._get(observation,"value")),"normalized_value":copy.deepcopy(cls._get(observation,"normalized_value")),"unit":cls._get(observation,"unit"),"role":role,"source_context":cls._get(observation,"source_context"),"page_refs":copy.deepcopy(cls._get(observation,"page_refs",[]) or []),"evidence_refs":copy.deepcopy(cls._get(observation,"source_evidence_ids",[]) or [])})
        comparison=copy.deepcopy(cls._get(finding,"comparison",{}) or {})
        if "comparison_basis" in comparison:comparison["basis"]=comparison.pop("comparison_basis")
        return {"finding_id":cls._get(finding,"finding_id"),"finding_type":finding_type,"finding_status":cls._enum(cls._get(finding,"status")),"title":titles.get(finding_type,"Cross-evidence consistency requires review"),"observations":observations,"comparison":comparison,"reconciliation":copy.deepcopy(cls._get(finding,"reconciliation",{}) or {}),"effect":copy.deepcopy(cls._get(finding,"effect",{}) or {}),"product_fact_ids":copy.deepcopy(cls._get(finding,"product_fact_ids",[]) or []),"product_identity_ids":copy.deepcopy(cls._get(finding,"product_identity_ids",[]) or []),"evidence_refs":copy.deepcopy(cls._get(finding,"evidence_ids",[]) or [])}
    def _actions(self,issues):
        items=[]
        for issue in issues:
            for action in self.policy.actions_for(issue.issue_type):items.append(NextAction(action,action.value.replace("_"," ").title(),f"Required by {issue.issue_type.value}.",issue.severity,[issue.issue_id] if issue.issue_id else []))
        return self._dedup_actions(items)
    @classmethod
    def _requirements(cls,kb):
        out={};titles={}
        def walk(items):
            for c in items or []:
                cid=cls._s(cls._get(c,"clause_id",cls._get(c,"annex_id")));titles[cid]=cls._get(c,"title")
                for r in cls._get(c,"requirements",[]) or []:out[cls._s(cls._get(r,"effective_requirement_id",cls._get(r,"requirement_id")))]=r
                walk(cls._get(c,"children",[]) or [])
        walk(cls._get(kb,"clauses",[]) or []);walk(cls._get(kb,"annexes",[]) or []);return out,titles
    @classmethod
    def _facts(cls,profile):
        raw=cls._get(profile,"facts",{}) or {};return {cls._s(k):v for k,v in raw.items()} if isinstance(raw,Mapping) else {cls._s(cls._get(x,"feature_key")):x for x in raw}
    @classmethod
    def _evidence(cls,report):
        out={}
        def walk(clauses):
            for c in clauses or []:
                for x in cls._get(c,"evidence_items",[]) or []:out[cls._s(cls._get(x,"evidence_id"))]=x
                walk(cls._get(c,"children",[]) or [])
        walk(cls._get(report,"clauses",[]) or [])
        for x in cls._get(report,"unmapped_sections",[]) or []:out[cls._s(cls._get(x,"evidence_id"))]=x
        return out
    @classmethod
    def _standard_view(cls,r):
        app=cls._get(r,"applicability",{}) or {};constraints=cls._get(r,"technical_constraints",[]) or [];sources=list(cls._get(r,"base_sources",[]) or [])+list(cls._get(r,"delta_sources",[]) or [])
        return {"effective_requirement_id":cls._get(r,"effective_requirement_id"),"requirement_text":cls._get(r,"text"),"requirement_type":cls._enum(cls._get(r,"requirement_type")),"effective_source_type":cls._enum(cls._get(r,"effective_source_type")),"effective_status":cls._enum(cls._get(r,"effective_status")),"applicability_condition_text":cls._get(r,"condition_text",cls._get(app,"condition_text")),"applicability_rule":copy.deepcopy(cls._get(app,"logic")),"technical_constraint_ids":[cls._s(cls._get(x,"constraint_id")) for x in constraints],"sources":copy.deepcopy(sources)}
    @classmethod
    def _evidence_view(cls,e,scope):return {"evidence_id":cls._get(e,"evidence_id"),"evidence_type":cls._enum(cls._get(e,"evidence_type")),"reported_verdict":cls._enum(cls._get(e,"reported_verdict")),"page_start":cls._get(e,"page_start"),"page_end":cls._get(e,"page_end"),"table_reference":cls._get(e,"table_reference"),"measurements":copy.deepcopy(cls._get(e,"measurements",[]) or []),"remarks":cls._get(e,"remarks"),"text_preview":str(cls._get(e,"raw_text","") or "")[:500],"scope_status":scope}
    @classmethod
    def _technical_view(cls,x):return {"evaluation_id":cls._get(x,"evaluation_id"),"constraint_id":cls._get(x,"constraint_id"),"parameter":cls._get(cls._get(x,"constraint",{}),"parameter"),"expected":copy.deepcopy(cls._get(x,"computed_limit",cls._get(x,"constraint"))),"observed_measurement_id":cls._get(x,"selected_measurement_id"),"comparison_status":cls._get(x,"comparison_details"),"decision":cls._enum(cls._get(x,"decision")),"reason":cls._get(x,"reason")}
    @classmethod
    def _scope_status(cls,eid,scopes):return next((cls._enum(cls._get(x,"scope_status")) for x in scopes if cls._get(x,"report_evidence_id")==eid),None)
    @staticmethod
    def _index(items,key):return {str(GenericClauseEvaluationSummaryBuilder._get(x,key)):x for x in items if GenericClauseEvaluationSummaryBuilder._get(x,key) is not None}
    @classmethod
    def _feature_key(cls,value):
        if isinstance(value,Mapping):return cls._s(cls._get(value,"feature_key",cls._get(value,"key",cls._get(value,"canonical_key"))))
        return cls._s(value)
    @staticmethod
    def _aggregate_internal(items):
        order=("NON_COMPLIANT","INSUFFICIENT_EVIDENCE","NEEDS_REVIEW","UNKNOWN_APPLICABILITY","NOT_APPLICABLE","COMPLIANT","INACTIVE");s=set(items);return next((x for x in order if x in s),"NEEDS_REVIEW")
    @staticmethod
    def _highest(values):
        rank={IssueSeverity.CRITICAL:5,IssueSeverity.HIGH:4,IssueSeverity.MEDIUM:3,IssueSeverity.LOW:2,IssueSeverity.INFORMATIONAL:1};return max(values,key=lambda x:rank[x]) if values else None
    @staticmethod
    def _dedup_issues(items):return sorted({(x.issue_type.value,x.logical_group_id,tuple(x.requirement_ids),tuple(x.evidence_ids)):x for x in items}.values(),key=lambda x:(x.issue_type.value,x.issue_id or ""))
    @staticmethod
    def _dedup_actions(items):return sorted({x.action_type.value:x for x in items}.values(),key=lambda x:x.action_type.value)
    @classmethod
    def _merge_trace(cls,items):
        field_names=("effective_requirement_ids","logical_group_ids","report_evidence_ids","product_fact_ids","feature_keys","applicability_evaluation_ids","evidence_match_ids","na_validation_ids","technical_constraint_result_ids","final_requirement_decision_ids","coverage_gap_ids")
        vals={n:sorted({x for t in items for x in getattr(t,n)}) for n in field_names};return SourceTraceability(**vals,provenance=[])
    @staticmethod
    def _natural(v):return tuple(int(x) if x.isdigit() else x for x in __import__("re").split(r"(\d+)",str(v)))
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
    def to_dict(cls,clauses):return {"schema_version":"1.0","clauses":[ComplianceSummarySerializer.to_dict(x) for x in clauses],"summary":cls.get_summary(clauses)}
    @classmethod
    def to_json(cls,clauses,indent=2):return json.dumps(cls.to_dict(clauses),ensure_ascii=False,sort_keys=True,indent=indent)
    @classmethod
    def save_json(cls,clauses,path):p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(cls.to_json(clauses)+"\n",encoding="utf-8");return p
    @staticmethod
    def get_summary(clauses):
        groups=[g for c in clauses for g in c.group_summaries];return {"clauses_summarized":len(clauses),"logical_groups_summarized":len(groups),"status_summary":dict(Counter(g.final_status.value for g in groups)),"issue_summary":dict(Counter(i.issue_type.value for g in groups for i in g.issues)),"next_action_summary":dict(Counter(a.action_type.value for g in groups for a in g.next_actions)),"evidence_references_recovered":sum(len(g.report_evidence) for g in groups),"groups_with_missing_traceability":sum(not g.source_traceability.effective_requirement_ids for g in groups)}

__all__=["GenericClauseEvaluationSummaryBuilder"]
