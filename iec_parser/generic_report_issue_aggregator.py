"""Deterministically organize final compliance issues into report-level groups."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


class RootCauseDecisionEffect(str, Enum):
    """Deterministic decision impact, independent of issue severity."""

    NO_DIRECT_EFFECT = "NO_DIRECT_EFFECT"
    BLOCK_AUTHORITATIVE_PASS = "BLOCK_AUTHORITATIVE_PASS"
    BLOCK_FINAL_EVALUATION = "BLOCK_FINAL_EVALUATION"
    REQUIRE_ADDITIONAL_EVIDENCE = "REQUIRE_ADDITIONAL_EVIDENCE"
    REQUIRE_PRODUCT_INFORMATION = "REQUIRE_PRODUCT_INFORMATION"
    REQUIRE_LAB_CLARIFICATION = "REQUIRE_LAB_CLARIFICATION"
    REQUIRE_TECHNICAL_REVIEW = "REQUIRE_TECHNICAL_REVIEW"
    CONFIRMED_TECHNICAL_NONCOMPLIANCE = "CONFIRMED_TECHNICAL_NONCOMPLIANCE"
    REPORT_REPLACEMENT_REQUIRED = "REPORT_REPLACEMENT_REQUIRED"


class RootCauseHierarchy(str, Enum):
    PRIMARY = "PRIMARY_ROOT_CAUSE"
    SECONDARY = "SECONDARY_ROOT_CAUSE"
    SUPPORTING = "SUPPORTING_FINDING"


@dataclass(frozen=True)
class AggregateAction:
    """An unchanged user action shared by the contributing issues."""

    type: str
    description: str


@dataclass(frozen=True)
class AggregateSeveritySummary:
    """Counts of upstream severities and their highest observed value."""

    highest: str
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0
    unknown: int = 0


@dataclass(frozen=True)
class AggregateBlockingSummary:
    """Counts of existing upstream blocking states without reinterpretation."""

    blocking_count: int = 0
    non_blocking_count: int = 0
    unknown_count: int = 0


@dataclass(frozen=True)
class AggregatedIssueGroup:
    """A deterministic collection of semantically compatible final issues."""

    group_id: str
    issue_type: str
    root_reason: str
    title: str
    summary: str
    compliance_conclusion: Optional[str]
    conclusion_summary: Dict[str, int]
    primary_action: AggregateAction
    issue_count: int
    affected_requirement_count: int
    affected_requirement_group_count: int
    affected_clause_count: int
    affected_clauses: List[str]
    severity_summary: AggregateSeveritySummary
    blocking_summary: AggregateBlockingSummary
    issue_ids: List[str]
    requirement_group_ids: List[str]
    requirement_ids: List[str]
    evidence_refs: List[str]
    individual_issues: List[Dict[str, Any]]
    diagnostic_finding_types: List[str] = field(default_factory=list)
    diagnostic_finding_ids: List[str] = field(default_factory=list)
    technical_basis: Dict[str, Any] = field(default_factory=dict)
    decision_effect: Optional[str] = None
    root_cause_confidence: str = "DETERMINISTIC"
    grouping_signals: List[str] = field(default_factory=list)
    hierarchy: str = RootCauseHierarchy.PRIMARY.value
    parent_root_cause_id: Optional[str] = None
    upstream_cause_ids: List[str] = field(default_factory=list)
    decision_effect_policy_version: str = "STEP45E_DECISION_EFFECT_V1"
    dominant_blocker_policy_version: str = "STEP45E_DOMINANT_BLOCKER_V1"


@dataclass
class AggregatedComplianceIssueReport:
    """Report-level organization of actionable and informational issues."""

    schema_version: str
    source_final_issue_report_id: str
    actionable_groups: List[AggregatedIssueGroup]
    informational_groups: List[AggregatedIssueGroup]
    suppressed_issue_ids: List[str]
    summary: Dict[str, Any]
    quality_audit: Dict[str, int]
    genericity_audit: Dict[str, int]
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    root_cause_policy_version: str = "STEP40_ROOT_CAUSE_V1"
    professional_judgment: Dict[str, Any] = field(default_factory=dict)


class GenericReportIssueAggregator:
    """Aggregate Step 25D records without changing any upstream decision."""

    SEVERITY_RANK = {"UNKNOWN": 0, "INFO": 1, "LOW": 2, "MEDIUM": 3, "HIGH": 4, "CRITICAL": 5}
    TEXT = {
        "MISSING_EVIDENCE": ("Required test evidence is missing", "Evidence required to evaluate one or more requirements was not found in the available report."),
        "INSUFFICIENT_EVIDENCE": ("Available evidence is incomplete", "Evidence is present, but it is not sufficient to establish a reliable conclusion for the affected requirements."),
        "TRACEABILITY_ISSUE": ("Product or evidence traceability requires clarification", "Structured traceability information is incomplete for one or more affected requirements."),
        "APPLICABILITY_JUSTIFICATION_REQUIRED": ("Requirement applicability requires justification", "The reported applicability outcome requires additional structured justification."),
        "UNRESOLVED_EVIDENCE_CONFLICT": ("Conflicting evidence requires laboratory clarification", "Available evidence contains an unresolved conflict for one or more affected requirements."),
        "CONFIRMED_NONCOMPLIANCE": ("Confirmed non-compliance requires attention", "Upstream evaluation identified one or more confirmed non-compliant requirements."),
        "INVALID_TEST_EVIDENCE": ("Test evidence is invalid", "Upstream validation identified invalid evidence for one or more affected requirements."),
        "CALCULATION_ISSUE": ("A report calculation requires correction", "Upstream validation identified a calculation issue for one or more affected requirements."),
        "TEST_CONDITION_ISSUE": ("Test conditions require review", "Upstream validation identified a test-condition issue for one or more affected requirements."),
        "REPORT_DATA_INCONSISTENCY": ("Report data requires reconciliation", "Structured report data contains an inconsistency requiring reconciliation."),
    }
    QUALITY_KEYS = (
        "individual_issue_conclusion_modified", "individual_issue_severity_modified", "individual_issue_action_modified",
        "suppressed_issue_promoted_to_actionable", "distinct_requirements_incorrectly_deduplicated",
        "mixed_conclusions_promoted_to_noncompliance", "new_noncompliance_created", "new_blocking_decision_created",
        "action_priority_invented", "overall_report_status_created", "readiness_score_created",
        "standard_specific_production_branch", "product_specific_production_branch", "clause_specific_production_branch",
        "page_specific_production_branch", "model_specific_production_branch", "report_specific_production_branch",
        "fixture_specific_production_branch", "upstream_artifact_mutated", "certification_claim_created",
    )

    def aggregate(self, final_report: Any, *, final_decision: Any=None, canonical_requirement_state: Any=None,
                  coverage_gap_analysis: Any=None, effective_kb: Any=None,
                  structure_compatibility: Any=None, product_profile: Any=None,
                  technical_constraint_result: Any=None) -> AggregatedComplianceIssueReport:
        """Return stable groups while leaving ``final_report`` untouched."""
        source = self._plain(final_report)
        issues = list(source.get("issues", []) or [])
        suppressed = list(source.get("suppressed_findings", []) or [])
        actionable = [x for x in issues if self._value(x.get("actionability")) == "ACTIONABLE"]
        informational = [x for x in issues if self._value(x.get("actionability")) == "INFORMATIONAL"]
        actionable_groups, actionable_duplicates = self._groups(actionable)
        informational_groups, informational_duplicates = self._groups(informational)
        actionable_groups = self._decision_effects(actionable_groups, final_decision, technical_constraint_result)
        structure_group = self._structure_group(structure_compatibility, actionable_groups)
        if structure_group is not None:
            actionable_groups.append(structure_group)
            actionable_groups = self._link_structure_consequences(actionable_groups, structure_group.group_id)
        actionable_groups = sorted(actionable_groups, key=self._sort_key)
        suppressed_ids = sorted({str(x.get("issue_id")) for x in suppressed if x.get("issue_id") is not None})
        source_id = "FINAL-ISSUES-" + hashlib.sha256(self._canonical(source).encode()).hexdigest()[:20].upper()
        accounted_ids = sorted({x for g in actionable_groups for x in g.issue_ids})
        expected_ids = sorted({str(x.get("issue_id")) for x in actionable if x.get("issue_id") is not None})
        summary = {
            "source_issue_count": len(issues) + len(suppressed),
            "actionable_source_issue_count": len(actionable),
            "suppressed_issue_count": len(suppressed),
            "informational_issue_count": len(informational),
            "aggregate_group_count": len(actionable_groups),
            "informational_group_count": len(informational_groups),
            "duplicate_issue_count_removed": actionable_duplicates + informational_duplicates,
            "counts_by_aggregate_issue_type": dict(sorted(Counter(g.issue_type for g in actionable_groups).items())),
            "counts_by_primary_action": dict(sorted(Counter(g.primary_action.type for g in actionable_groups).items())),
            "highest_severity_distribution": dict(sorted(Counter(g.severity_summary.highest for g in actionable_groups).items())),
            "total_unique_clauses_represented": len({c for g in actionable_groups for c in g.affected_clauses}),
            "total_unique_requirement_groups_represented": len({r for g in actionable_groups for r in g.requirement_group_ids}),
            "accounted_actionable_issue_count": len(accounted_ids),
            "all_actionable_issue_ids_accounted_for": accounted_ids == expected_ids,
        }
        diagnostics = [] if accounted_ids == expected_ids else [{"code": "ACTIONABLE_ISSUE_ACCOUNTING_MISMATCH", "expected": expected_ids, "actual": accounted_ids}]
        zeros = {key: 0 for key in self.QUALITY_KEYS}
        genericity = {key: zeros[key] for key in zeros if key.endswith("_production_branch")}
        judgment=self._professional_judgment(canonical_requirement_state or final_decision,coverage_gap_analysis,effective_kb,
                                              structure_compatibility,product_profile,actionable_groups)
        summary["root_cause_count"]=len(actionable_groups)
        summary["root_cause_policy_version"]="STEP40_ROOT_CAUSE_V1"
        summary["decision_effect_policy_version"]="STEP45E_DECISION_EFFECT_V1"
        summary["dominant_blocker_policy_version"]="STEP45E_DOMINANT_BLOCKER_V1"
        summary["decision_effect_null_count"]=sum(g.decision_effect is None for g in actionable_groups)
        summary["root_cause_hierarchy_counts"]=dict(sorted(Counter(g.hierarchy for g in actionable_groups).items()))
        summary["blocking_condition_traceability"]={
            "ACTIONABLE_APPLICABILITY_GAPS":sorted(g.group_id for g in actionable_groups if g.decision_effect==RootCauseDecisionEffect.REQUIRE_PRODUCT_INFORMATION.value),
            "ACTIONABLE_EVIDENCE_GAPS":sorted(g.group_id for g in actionable_groups if g.decision_effect in {RootCauseDecisionEffect.REQUIRE_ADDITIONAL_EVIDENCE.value,RootCauseDecisionEffect.REPORT_REPLACEMENT_REQUIRED.value}),
            "ACTIONABLE_TRACEABILITY_GAPS":sorted(g.group_id for g in actionable_groups if g.decision_effect in {RootCauseDecisionEffect.REQUIRE_LAB_CLARIFICATION.value,RootCauseDecisionEffect.REQUIRE_TECHNICAL_REVIEW.value}),
            "CONFIRMED_TECHNICAL_NONCOMPLIANCE":sorted(g.group_id for g in actionable_groups if g.decision_effect==RootCauseDecisionEffect.CONFIRMED_TECHNICAL_NONCOMPLIANCE.value),
        }
        judgment["root_cause_policy_version"]="STEP40_ROOT_CAUSE_V1"
        judgment["decision_effect_policy_version"]="STEP45E_DECISION_EFFECT_V1"
        judgment["dominant_blocker_policy_version"]="STEP45E_DOMINANT_BLOCKER_V1"
        return AggregatedComplianceIssueReport("1.2", source_id, actionable_groups, informational_groups, suppressed_ids, summary, zeros, genericity, diagnostics,"STEP40_ROOT_CAUSE_V1",judgment)

    def _groups(self, issues: Sequence[Mapping[str, Any]]) -> Tuple[List[AggregatedIssueGroup], int]:
        unique: Dict[str, Mapping[str, Any]] = {}
        duplicates = 0
        for issue in sorted((self._plain(x) for x in issues), key=self._canonical):
            issue_id = str(issue.get("issue_id") or "")
            identity = issue_id or "ANON-" + hashlib.sha256(self._canonical(issue).encode()).hexdigest()
            if identity in unique:
                duplicates += 1
                continue
            unique[identity] = issue
        buckets: Dict[Tuple[str, str, str, str], List[Mapping[str, Any]]] = {}
        for issue in unique.values():
            action = issue.get("next_action") or {}
            provenance = issue.get("provenance") or {}
            root = self._root_reason(provenance)
            key = self._root_key(issue,action,provenance,root)
            buckets.setdefault(key, []).append(issue)
        groups = [self._build_group(key, values) for key, values in buckets.items()]
        return sorted(groups, key=self._sort_key), duplicates

    def _build_group(self, key: Tuple[str, str, str, str], issues: Sequence[Mapping[str, Any]]) -> AggregatedIssueGroup:
        issue_type, action_type, conclusion, root = key
        ordered = sorted((copy.deepcopy(dict(x)) for x in issues), key=lambda x: (str(x.get("issue_id") or ""), self._canonical(x)))
        action = ordered[0].get("next_action") or {}
        clauses = self._unique(x.get("clause_id") for x in ordered)
        requirement_groups = self._unique(x.get("requirement_group_id") for x in ordered)
        requirement_ids = self._unique(v for x in ordered for v in (x.get("requirement_ids") or []))
        evidence = self._unique(v for x in ordered for v in (x.get("evidence_refs") or []))
        issue_ids = self._unique(x.get("issue_id") for x in ordered)
        diagnostic_types=self._unique((x.get("diagnostic") or {}).get("finding_type") for x in ordered)
        diagnostic_ids=self._unique((x.get("diagnostic") or {}).get("finding_id") for x in ordered)
        severity_counts = Counter(self._severity(x.get("severity")) for x in ordered)
        highest = max(severity_counts, key=lambda x: self.SEVERITY_RANK.get(x, 0)) if severity_counts else "UNKNOWN"
        blocking = Counter("unknown" if x.get("blocking") is None else "blocking" if x.get("blocking") is True else "non_blocking" for x in ordered)
        conclusions = dict(sorted(Counter(self._value(x.get("compliance_conclusion")) or "UNKNOWN" for x in ordered).items()))
        direct_conclusion = next(iter(conclusions)) if len(conclusions) == 1 else None
        title, summary = self.TEXT.get(issue_type, ("Compliance issue requires review", "One or more structured compliance findings require the stated action."))
        normalized_key = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
        group_id = "AGG-" + hashlib.sha256(normalized_key.encode()).hexdigest()[:20].upper()
        return AggregatedIssueGroup(
            group_id, issue_type, root, title, summary, direct_conclusion, conclusions,
            AggregateAction(action_type, str(action.get("description") or "")), len(ordered), len(requirement_ids),
            len(requirement_groups), len(clauses), clauses,
            AggregateSeveritySummary(highest, severity_counts["CRITICAL"], severity_counts["HIGH"], severity_counts["MEDIUM"], severity_counts["LOW"], severity_counts["INFO"], severity_counts["UNKNOWN"]),
            AggregateBlockingSummary(blocking["blocking"], blocking["non_blocking"], blocking["unknown"]),
            issue_ids, requirement_groups, requirement_ids, evidence, ordered,diagnostic_types,diagnostic_ids,
            {"root_reason":root,"canonical_parameter":self._first(ordered,"canonical_parameter"),
             "test_family":self._first(ordered,"test_family"),"failure_mechanism":self._first(ordered,"failure_mechanism"),
             "missing_product_facts":self._unique(v for x in ordered for v in (x.get("product_fact_ids") or [])),
             "criticality_levels":self._unique(((x.get("criticality") or {}).get("level") if isinstance(x.get("criticality"),dict) else x.get("criticality")) for x in ordered)},
            self._first(ordered,"decision_effect"),"DETERMINISTIC",self._grouping_signals(ordered),
        )

    @classmethod
    def _root_key(cls,issue,action,provenance,root):
        diagnostic=issue.get("diagnostic") or {};metadata=provenance.get("upstream_metadata") or {}
        structure=diagnostic.get("finding_type") in {"STRUCTURE_MISMATCH","REPORT_STANDARD_STRUCTURE_MISMATCH"}
        parameter=issue.get("canonical_parameter") or diagnostic.get("canonical_parameter") or metadata.get("canonical_parameter")
        family=issue.get("test_family") or diagnostic.get("test_family") or metadata.get("test_family")
        mechanism=issue.get("failure_mechanism") or diagnostic.get("failure_mechanism") or metadata.get("failure_mechanism") or root
        scope=issue.get("product_scope") or metadata.get("product_scope") or ""
        evidence_phase=issue.get("evidence_phase") or metadata.get("evidence_phase") or ""
        corrective=cls._value(action.get("type")) or "NO_ACTION"
        identity="REPORT_STANDARD_STRUCTURE_MISMATCH" if structure else str(parameter or family or mechanism)
        original=cls._value(issue.get("issue_type")) or "UNKNOWN"
        kind="REPORT_STANDARD_STRUCTURE_MISMATCH" if structure else "TECHNICAL_ROOT_CAUSE" if parameter or family or diagnostic.get("failure_mechanism") or metadata.get("failure_mechanism") else original
        conclusion=cls._value(issue.get("compliance_conclusion")) or "UNKNOWN"
        return kind,corrective,conclusion,"|".join((identity,str(scope),str(evidence_phase),str(mechanism)))

    @classmethod
    def _grouping_signals(cls,issues):
        signals=[]
        for name,label in (("canonical_parameter","SAME_CANONICAL_PARAMETER"),("test_family","SAME_TEST_FAMILY"),
                           ("failure_mechanism","SAME_FAILURE_MECHANISM"),("evidence_phase","SAME_EVIDENCE_SOURCE")):
            if cls._first(issues,name):signals.append(label)
        diagnostics={v for x in issues for v in [((x.get("diagnostic") or {}).get("finding_type"))] if v}
        if diagnostics & {"STRUCTURE_MISMATCH","REPORT_STANDARD_STRUCTURE_MISMATCH"}:signals.append("SAME_REPORT_STRUCTURE_FAILURE")
        if issues:signals.append("SAME_CORRECTIVE_ACTION")
        return sorted(set(signals))

    @staticmethod
    def _first(issues,name):
        for issue in issues:
            value=issue.get(name) or (issue.get("diagnostic") or {}).get(name) or ((issue.get("provenance") or {}).get("upstream_metadata") or {}).get(name)
            if value is not None:return str(value.value if isinstance(value,Enum) else value)
        return None

    @classmethod
    def _effect_for(cls, group: AggregatedIssueGroup) -> str:
        """Map semantic cause/action to effect without consulting severity or text."""
        issue=str(group.issue_type);action=str(group.primary_action.type)
        if issue=="CONFIRMED_NONCOMPLIANCE":return RootCauseDecisionEffect.CONFIRMED_TECHNICAL_NONCOMPLIANCE.value
        if issue in {"MISSING_EVIDENCE","INSUFFICIENT_EVIDENCE","INVALID_TEST_EVIDENCE"}:return RootCauseDecisionEffect.REQUIRE_ADDITIONAL_EVIDENCE.value
        if action=="PROVIDE_PRODUCT_INFORMATION":return RootCauseDecisionEffect.REQUIRE_PRODUCT_INFORMATION.value
        if action=="LAB_CLARIFICATION":return RootCauseDecisionEffect.REQUIRE_LAB_CLARIFICATION.value
        if action=="TECHNICAL_REVIEW":return RootCauseDecisionEffect.REQUIRE_TECHNICAL_REVIEW.value
        if action=="PROVIDE_EVIDENCE":return RootCauseDecisionEffect.REQUIRE_ADDITIONAL_EVIDENCE.value
        if action=="PROVIDE_NA_JUSTIFICATION":return RootCauseDecisionEffect.BLOCK_AUTHORITATIVE_PASS.value
        return RootCauseDecisionEffect.BLOCK_AUTHORITATIVE_PASS.value if group.blocking_summary.blocking_count else RootCauseDecisionEffect.NO_DIRECT_EFFECT.value

    @classmethod
    def _decision_effects(cls, groups, final_decision, technical):
        finals={str(x.get("effective_requirement_id")):x for x in cls._plain(final_decision or {}).get("results",[]) or []}
        rule_results=list(cls._plain(technical or {}).get("rule_results",[]) or [])
        output=[]
        for group in groups:
            effect=cls._effect_for(group);basis=copy.deepcopy(group.technical_basis)
            if effect==RootCauseDecisionEffect.CONFIRMED_TECHNICAL_NONCOMPLIANCE.value:
                violations=[x for x in rule_results if str(x.get("source_requirement_id")) in set(group.requirement_ids) and str(x.get("decision"))=="VIOLATES"]
                basis.update({"technical_violation":True,"requirement_decisions":[{"requirement_id":rid,"final_decision":finals.get(rid,{}).get("final_decision"),"reason_code":finals.get(rid,{}).get("reason_code")} for rid in group.requirement_ids],"executed_rule_results":[{"evaluation_id":x.get("evaluation_id"),"rule_id":x.get("rule_id"),"requirement_id":x.get("source_requirement_id"),"clause":x.get("source_clause"),"technical_family":x.get("test_family") or x.get("rule_family"),"operands":copy.deepcopy(x.get("operand_values")),"evidence_ids":copy.deepcopy(x.get("evidence_ids") or [])} for x in violations]})
            output.append(replace(group,decision_effect=effect,technical_basis=basis,hierarchy=RootCauseHierarchy.PRIMARY.value))
        return output

    @classmethod
    def _structure_group(cls, structure, groups):
        data=cls._plain(structure or {});compat=str(data.get("overall_compatibility") or "UNKNOWN")
        if compat not in {"STRUCTURE_MISMATCH","INCOMPATIBLE"}:return None
        findings=list(data.get("findings",[]) or []);material=[x for x in findings if str(x.get("compatibility")) in {"SEMANTIC_MISMATCH","NOT_COMPARABLE"}]
        evidence=cls._unique(v for x in material for v in (x.get("evidence_ids") or []));clauses=cls._unique(x.get("report_clause") for x in material)
        downstream=[g for g in groups if g.issue_type in {"MISSING_EVIDENCE","INSUFFICIENT_EVIDENCE","INVALID_TEST_EVIDENCE"}]
        requirements=cls._unique(v for g in downstream for v in g.requirement_ids);issue_ids=cls._unique(v for g in downstream for v in g.issue_ids)
        identity=json.dumps({"compatibility":compat,"evidence_usability_effect":data.get("evidence_usability_effect"),"finding_ids":sorted(str(x.get("finding_id")) for x in material)},sort_keys=True,separators=(",",":"));gid="AGG-STRUCTURE-"+hashlib.sha256(identity.encode()).hexdigest()[:12].upper()
        finding_ids=[x.get("finding_id") for x in material if x.get("finding_id")];genericity=data.get("genericity_audit") or data.get("quality_audit") or {}
        return AggregatedIssueGroup(gid,"REPORT_STANDARD_STRUCTURE_MISMATCH","REPORT_STANDARD_STRUCTURE_MISMATCH","Supplied report structure is incompatible with the governing standard","The material report/standard structure mismatch restricts reliable evidence use.",None,{"NOT_DETERMINED":1},AggregateAction("LAB_CLARIFICATION","Request a corrected or replacement report aligned to the governing standard structure."),1,len(requirements),0,len(clauses),clauses,AggregateSeveritySummary("HIGH",high=1),AggregateBlockingSummary(blocking_count=1),issue_ids,[],requirements,evidence,[],["REPORT_STANDARD_STRUCTURE_MISMATCH"],finding_ids,{"root_reason":"REPORT_STANDARD_STRUCTURE_MISMATCH","compatibility_status":compat,"confidence":data.get("confidence"),"structure_finding_count":len(findings),"material_structure_finding_count":len(material),"unsafe_same_number_matches_blocked":data.get("unsafe_same_number_matches_blocked",genericity.get("unsafe_same_number_matches_blocked")),"evidence_usability_effect":data.get("evidence_usability_effect") or "STRUCTURE_GATE_RESTRICTIONS_RETAINED","representative_structure_finding_ids":finding_ids[:10],"omitted_structure_finding_id_count":max(0,len(finding_ids)-10)},RootCauseDecisionEffect.REPORT_REPLACEMENT_REQUIRED.value,"DETERMINISTIC",["SAME_REPORT_STRUCTURE_FAILURE"],RootCauseHierarchy.PRIMARY.value)

    @staticmethod
    def _link_structure_consequences(groups, structure_id):
        causal={"MISSING_EVIDENCE","INSUFFICIENT_EVIDENCE","INVALID_TEST_EVIDENCE"}
        return [replace(g,hierarchy=RootCauseHierarchy.SECONDARY.value,parent_root_cause_id=structure_id,upstream_cause_ids=[structure_id]) if g.group_id!=structure_id and g.issue_type in causal else g for g in groups]

    @classmethod
    def _professional_judgment(cls,final_decision,coverage,effective,structure,profile,groups):
        source=cls._plain(final_decision or {})
        decisions=list(source.get("results",[]) or [])
        if not decisions and source.get("records") is not None:
            decisions=[{"effective_requirement_id":x.get("requirement_id"),"final_decision":x.get("state"),"reason_code":x.get("reason_code"),"decision_effect":x.get("decision_effect"),"criticality":x.get("criticality")} for x in source.get("records",[]) or [] if x.get("current") is not False]
        eligible=[x for x in decisions if str(x.get("final_decision")) not in {"NOT_APPLICABLE","INACTIVE"}
                  and str(x.get("decision_effect") or "")!="INFORMATIONAL"]
        satisfied=sum(str(x.get("final_decision"))=="COMPLIANT" for x in eligible)
        evaluated=sum(str(x.get("final_decision")) in {"COMPLIANT","NON_COMPLIANT"} for x in eligible)
        def metric(n,d,version,reasons):return {"value":round(100*n/d,2) if d else 0.0,"numerator":n,"denominator":d,"excluded_count":len(decisions)-d,"policy_version":version,"reason_breakdown":reasons}
        compliance=metric(satisfied,len(eligible),"STEP40_COMPLIANCE_V1",dict(Counter(str(x.get("final_decision")) for x in eligible)))
        coverage_metric=metric(evaluated,len(eligible),"STEP40_COVERAGE_V1",dict(Counter(str(x.get("final_decision")) for x in eligible)))
        structure_value=cls._plain(structure or {});compat=str(structure_value.get("overall_compatibility") or "UNKNOWN")
        confidence=100.0
        deductions={"unresolved_requirement_ratio":0.0,"structure_compatibility":0.0,"missing_product_facts":0.0}
        if eligible:deductions["unresolved_requirement_ratio"]=round(40*(len(eligible)-evaluated)/len(eligible),2)
        if compat in {"STRUCTURE_MISMATCH","INCOMPATIBLE"}:deductions["structure_compatibility"]=30.0
        elif compat in {"UNKNOWN","UNRESOLVED"}:deductions["structure_compatibility"]=15.0
        completeness=cls._plain(profile or {}).get("required_fact_completeness") or {}
        completeness_values=(completeness.values() if isinstance(completeness,dict) else completeness)
        missing=sum(str((x or {}).get("status") or "") in {"UNKNOWN","CONFLICT","CONFLICTING"} for x in completeness_values if isinstance(x,dict));deductions["missing_product_facts"]=min(20.0,5.0*missing)
        confidence=max(0.0,round(confidence-sum(deductions.values()),2))
        maturity=((cls._plain(effective or {}).get("maturity") or {}).get("state") or "DRAFT")
        critical=Counter()
        for x in eligible:
            level=((x.get("criticality") or {}).get("level") if isinstance(x.get("criticality"),dict) else None)
            if level!="P0_CRITICAL":continue
            decision=str(x.get("final_decision"));critical["violations" if decision=="NON_COMPLIANT" else "evidence_gaps" if decision=="INSUFFICIENT_EVIDENCE" else "applicability_unresolved" if decision=="UNKNOWN_APPLICABILITY" else "other_unresolved" if decision=="NEEDS_REVIEW" else "satisfied"]+=1
        unresolved=[]
        for x in eligible:
            decision=str(x.get("final_decision"));category={"UNKNOWN_APPLICABILITY":"PRODUCT_FACT_CLARIFICATION_REQUIRED","INSUFFICIENT_EVIDENCE":"EVIDENCE_INTERPRETATION_REQUIRED","NEEDS_REVIEW":"HUMAN_REVIEW_REQUIRED"}.get(decision)
            if category:unresolved.append({"effective_requirement_id":x.get("effective_requirement_id"),"category":category,"reason_code":x.get("reason_code")})
        return {"metrics":{"compliance_score":compliance,"evaluation_coverage":coverage_metric,
                "evaluation_confidence":{"value":confidence,"policy_version":"STEP40_CONFIDENCE_V1","reason_breakdown":deductions}},
                "kb_maturity":maturity,"critical_summary":dict(critical),"report_validity_summary":{"structure_compatibility":compat},
                "pre_llm_unresolved":unresolved,"root_cause_policy_version":"STEP40_ROOT_CAUSE_V1"}

    @staticmethod
    def _root_reason(provenance: Mapping[str, Any]) -> str:
        value = provenance.get("upstream_reason") or provenance.get("originating_issue_type") or "UNSPECIFIED"
        return str(value.value if isinstance(value, Enum) else value).strip() or "UNSPECIFIED"

    @classmethod
    def _sort_key(cls, group: AggregatedIssueGroup) -> Tuple[Any, ...]:
        return (-cls.SEVERITY_RANK.get(group.severity_summary.highest, 0), group.issue_type, group.primary_action.type, group.root_reason, group.group_id)

    @classmethod
    def _severity(cls, value: Any) -> str:
        result = cls._value(value) or "UNKNOWN"
        return result if result in cls.SEVERITY_RANK else "UNKNOWN"

    @staticmethod
    def _unique(values: Any) -> List[str]:
        return sorted({str(v.value if isinstance(v, Enum) else v) for v in values if v is not None and str(v) != ""})

    @staticmethod
    def _value(value: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value.value if isinstance(value, Enum) else value)

    @classmethod
    def _plain(cls, value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if is_dataclass(value):
            return cls._plain(asdict(value))
        if isinstance(value, Mapping):
            return {str(k): cls._plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._plain(v) for v in value]
        return copy.deepcopy(value)

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def to_dict(cls, report: AggregatedComplianceIssueReport) -> Dict[str, Any]:
        """Convert an aggregate report to plain JSON-compatible data."""
        if not is_dataclass(report):
            raise TypeError("aggregated compliance issue report required")
        return cls._plain(asdict(report))

    @classmethod
    def to_json(cls, report: AggregatedComplianceIssueReport, indent: int = 2) -> str:
        """Serialize an aggregate report deterministically."""
        return json.dumps(cls.to_dict(report), ensure_ascii=False, sort_keys=True, indent=indent)

    @classmethod
    def save_json(cls, report: AggregatedComplianceIssueReport, path: Any) -> Path:
        """Write an aggregate report without modifying its source artifact."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(cls.to_json(report) + "\n", encoding="utf-8")
        return target


__all__ = ["AggregateAction", "AggregateBlockingSummary", "AggregatedComplianceIssueReport", "AggregatedIssueGroup", "AggregateSeveritySummary", "GenericReportIssueAggregator"]
