"""Build a conservative, generic readiness result from locked pipeline outputs."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


class OverallReadinessStatus(str, Enum):
    READY = "READY"
    PARTIALLY_READY = "PARTIALLY_READY"
    NOT_READY = "NOT_READY"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ReadinessDimensionStatus(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class StrictReadinessPolicy:
    """Deterministic policy; absence and uncertainty never prove failure."""

    block_on_non_compliance: bool = True
    block_on_na_conflict: bool = True
    block_on_kb_high_review: bool = True
    block_on_conflicting_evidence: bool = True
    do_not_fail_on_missing_evidence: bool = True
    do_not_fail_on_unknown_applicability: bool = True
    mostly_unknown_ratio: float = 0.80
    broadly_missing_ratio: float = 0.80


STRICT_READINESS_POLICY = StrictReadinessPolicy()


@dataclass
class ReadinessDimensionResult:
    dimension: str
    status: ReadinessDimensionStatus
    reason_code: str
    reason: str
    total_items: int = 0
    resolved_items: int = 0
    unresolved_items: int = 0
    blocking_items: int = 0
    supporting_metrics: Dict[str, Any] = field(default_factory=dict)
    blocker_ids: List[str] = field(default_factory=list)
    recommended_actions: List[str] = field(default_factory=list)


@dataclass
class OverallComplianceFinding:
    finding_id: str
    finding_type: str
    severity: str
    clause_id: Optional[str] = None
    group_id: Optional[str] = None
    summary: str = ""
    reason: str = ""
    source_gap_type: Optional[str] = None
    resolution_actions: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    notes: Optional[str] = None


@dataclass
class OverallReadinessBlocker:
    blocker_id: str
    blocker_type: str
    severity: str
    affected_groups: List[str] = field(default_factory=list)
    affected_clauses: List[str] = field(default_factory=list)
    summary: str = ""
    resolution_actions: List[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class OverallReadinessResult:
    schema_version: str
    result_id: str
    effective_kb_id: str
    profile_id: str
    report_document_id: str
    overall_status: OverallReadinessStatus
    status_reason_code: str
    status_reason: str
    dimensions: List[ReadinessDimensionResult] = field(default_factory=list)
    findings: List[OverallComplianceFinding] = field(default_factory=list)
    blockers: List[OverallReadinessBlocker] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    informational_items: List[str] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    coverage_metrics: Dict[str, Any] = field(default_factory=dict)
    decision_metrics: Dict[str, Any] = field(default_factory=dict)
    gap_metrics: Dict[str, Any] = field(default_factory=dict)
    recommended_actions: List[str] = field(default_factory=list)
    notes: Optional[str] = None


class GenericOverallReadinessBuilder:
    """Summarize upstream decisions without recomputing their semantics."""

    DECISIONS = ("COMPLIANT", "NON_COMPLIANT", "NOT_APPLICABLE", "INSUFFICIENT_EVIDENCE", "UNKNOWN_APPLICABILITY", "NEEDS_REVIEW", "INACTIVE")
    GAPS = ("NO_GAP", "NON_COMPLIANCE_GAP", "EVIDENCE_GAP", "TECHNICAL_MEASUREMENT_GAP", "PRODUCT_DATA_GAP", "APPLICABILITY_GAP", "REPORT_SCOPE_GAP", "KB_REVIEW_GAP", "NA_CONFLICT_GAP", "CONFLICTING_EVIDENCE_GAP", "TEST_METHOD_EVIDENCE_GAP", "NOT_APPLICABLE", "INACTIVE")
    BLOCKER_TYPES = {
        "NON_COMPLIANCE_GAP": "PROVEN_NON_COMPLIANCE",
        "NA_CONFLICT_GAP": "NA_CONFLICT_REVIEW",
        "KB_REVIEW_GAP": "KB_SEMANTIC_REVIEW",
        "APPLICABILITY_GAP": "APPLICABILITY_UNRESOLVED",
        "PRODUCT_DATA_GAP": "PRODUCT_INFORMATION_REQUIRED",
        "EVIDENCE_GAP": "REPORT_EVIDENCE_REQUIRED",
        "REPORT_SCOPE_GAP": "REPORT_SCOPE_REVIEW",
        "TECHNICAL_MEASUREMENT_GAP": "TECHNICAL_MEASUREMENT_REQUIRED",
        "CONFLICTING_EVIDENCE_GAP": "CONFLICTING_EVIDENCE_REVIEW",
        "TEST_METHOD_EVIDENCE_GAP": "TEST_METHOD_REVIEW",
    }
    FINDING_TYPES = {
        "NON_COMPLIANCE_GAP": "PROVEN_NON_COMPLIANCE", "NA_CONFLICT_GAP": "NA_CONFLICT",
        "KB_REVIEW_GAP": "KB_REVIEW", "APPLICABILITY_GAP": "APPLICABILITY_UNRESOLVED",
        "PRODUCT_DATA_GAP": "PRODUCT_DATA_MISSING", "EVIDENCE_GAP": "REPORT_EVIDENCE_MISSING",
        "REPORT_SCOPE_GAP": "REPORT_SCOPE_AMBIGUITY", "TECHNICAL_MEASUREMENT_GAP": "TECHNICAL_MEASUREMENT_MISSING",
        "CONFLICTING_EVIDENCE_GAP": "CONFLICTING_REPORT_EVIDENCE", "TEST_METHOD_EVIDENCE_GAP": "TEST_METHOD_EVIDENCE_INCOMPLETE",
    }
    ACTION_PRIORITY = ("MANUAL_TECHNICAL_REVIEW", "REVIEW_REPORTED_NA", "REVIEW_KB_REQUIREMENT", "REVIEW_CONFLICTING_EVIDENCE", "REVIEW_REPORT_SCOPE", "PROVIDE_PRODUCT_INFORMATION", "PROVIDE_REPORT_EVIDENCE", "PROVIDE_MEASUREMENT", "REVIEW_APPLICABILITY", "REPEAT_OR_VERIFY_TEST")

    def __init__(self, policy: StrictReadinessPolicy = STRICT_READINESS_POLICY):
        self.policy = policy

    def build(self, effective_kb: Any, product_profile: Any, final_decision: Any,
              coverage_gap_analysis: Any, group_aware_applicability: Any,
              technical_constraint_result: Any, scope_aware_na_validation: Any,
              requirement_grouping: Any, report_evidence_scope: Any) -> OverallReadinessResult:
        group_decisions = list(self._get(final_decision, "group_decisions", []) or [])
        clause_decisions = list(self._get(final_decision, "clause_decisions", []) or [])
        group_gaps = list(self._get(coverage_gap_analysis, "group_gaps", []) or [])
        clause_gaps = list(self._get(coverage_gap_analysis, "clause_gaps", []) or [])
        req_gaps = list(self._get(coverage_gap_analysis, "requirement_gaps", []) or [])
        gd = self._counts(group_decisions, "group_decision", self.DECISIONS)
        cd = self._counts(clause_decisions, "decision", self.DECISIONS)
        gg = self._counts(group_gaps, "primary_gap_type", self.GAPS)
        cg = self._counts(clause_gaps, "primary_gap_type", self.GAPS)
        rg = self._counts(req_gaps, "primary_gap_type", self.GAPS)
        findings = self._findings(group_gaps)
        blockers = self._blockers(group_gaps)
        dimensions = self._dimensions(gd, gg, group_aware_applicability, technical_constraint_result, scope_aware_na_validation, report_evidence_scope, blockers)
        status, code, reason = self._overall(gd, gg, dimensions)
        actions = self._actions(group_gaps)
        effective_id = str(self._get(final_decision, "effective_kb_id", self._get(effective_kb, "effective_kb_id", "")) or "")
        profile_id = str(self._get(final_decision, "profile_id", self._get(product_profile, "profile_id", "")) or "")
        report_id = str(self._get(final_decision, "report_document_id", "") or "")
        identity = json.dumps([effective_id, profile_id, report_id, gd, gg, status.value], sort_keys=True, separators=(",", ":"))
        result_id = "READINESS-" + hashlib.sha256(identity.encode()).hexdigest()[:20].upper()
        coverage = self._get(self._get(coverage_gap_analysis, "summary", {}), "coverage", {}) or {}
        summary = {
            "overall_status": status.value, "primary_reason": code,
            "logical_group_decisions": gd, "logical_group_gaps": gg,
            "high_priority_blockers": dict(Counter(x.blocker_type for x in blockers if x.severity in {"HIGH", "CRITICAL"})),
            "next_actions": actions,
            "zero_inflation": {"atomic_findings": rg, "logical_group_findings": gg, "unique_clause_findings": cg},
        }
        warnings = [x.summary for x in blockers if x.severity in {"HIGH", "CRITICAL"}]
        return OverallReadinessResult("1.0", result_id, effective_id, profile_id, report_id, status, code, reason,
                                      dimensions, findings, blockers, warnings, [], summary, self._plain(coverage),
                                      {"logical_groups": gd, "clauses": cd}, {"logical_groups": gg, "clauses": cg, "requirements_traceability": rg},
                                      actions, "Operational readiness only; this result is not a certification decision.")

    def _overall(self, decisions: Dict[str, int], gaps: Dict[str, int], dimensions: Sequence[ReadinessDimensionResult]) -> Tuple[OverallReadinessStatus, str, str]:
        if decisions["NON_COMPLIANT"] or gaps["NON_COMPLIANCE_GAP"]:
            return OverallReadinessStatus.NOT_READY, "PROVEN_NON_COMPLIANCE_PRESENT", "At least one logical group has a proven non-compliance decision."
        high_review = gaps["NA_CONFLICT_GAP"] + gaps["KB_REVIEW_GAP"] + gaps["CONFLICTING_EVIDENCE_GAP"]
        if high_review:
            return OverallReadinessStatus.NEEDS_REVIEW, "MATERIAL_REVIEW_BLOCKERS_PRESENT", "Material logical-group review blockers prevent a reliable final conclusion."
        if any(x.status is ReadinessDimensionStatus.INSUFFICIENT_DATA for x in dimensions):
            return OverallReadinessStatus.INSUFFICIENT_DATA, "INSUFFICIENT_DATA_FOR_MEANINGFUL_ASSESSMENT", "Required product, applicability, or report information is too incomplete for meaningful assessment."
        unresolved = sum(gaps[x] for x in ("EVIDENCE_GAP", "TECHNICAL_MEASUREMENT_GAP", "PRODUCT_DATA_GAP", "APPLICABILITY_GAP", "REPORT_SCOPE_GAP", "TEST_METHOD_EVIDENCE_GAP"))
        if unresolved or decisions["INSUFFICIENT_EVIDENCE"] or decisions["UNKNOWN_APPLICABILITY"] or decisions["NEEDS_REVIEW"]:
            return OverallReadinessStatus.PARTIALLY_READY, "ACTIONABLE_GAPS_REMAIN", "No proven failure exists, but actionable logical-group gaps remain."
        return OverallReadinessStatus.READY, "READINESS_CRITERIA_SATISFIED", "All material logical groups have usable decisions with no unresolved blockers."

    def _dimensions(self, d: Dict[str, int], g: Dict[str, int], app: Any, tech: Any, na: Any, scope: Any, blockers: Sequence[OverallReadinessBlocker]) -> List[ReadinessDimensionResult]:
        total = d["total"]; useful = d["COMPLIANT"] + d["NON_COMPLIANT"]
        def dim(name: str, status: ReadinessDimensionStatus, code: str, total_items: int, resolved: int, unresolved: int, blocking: int, metrics: Dict[str, Any], actions: Sequence[str]) -> ReadinessDimensionResult:
            ids = [x.blocker_id for x in blockers if any(a in x.resolution_actions for a in actions)]
            return ReadinessDimensionResult(name, status, code, code.replace("_", " ").capitalize(), total_items, resolved, unresolved, blocking, self._plain(metrics), ids, list(actions))
        kb_n=g["KB_REVIEW_GAP"]
        kb_s=ReadinessDimensionStatus.NEEDS_REVIEW if kb_n else ReadinessDimensionStatus.READY
        product_n=g["PRODUCT_DATA_GAP"]; product_s=ReadinessDimensionStatus.INSUFFICIENT_DATA if total and product_n/total >= self.policy.broadly_missing_ratio else ReadinessDimensionStatus.PARTIAL if product_n else ReadinessDimensionStatus.READY
        app_n=d["UNKNOWN_APPLICABILITY"] + g["APPLICABILITY_GAP"]; app_s=ReadinessDimensionStatus.INSUFFICIENT_DATA if total and d["UNKNOWN_APPLICABILITY"]/total >= self.policy.mostly_unknown_ratio else ReadinessDimensionStatus.NEEDS_REVIEW if g["APPLICABILITY_GAP"] else ReadinessDimensionStatus.PARTIAL if app_n else ReadinessDimensionStatus.READY
        report_n=g["EVIDENCE_GAP"]+g["REPORT_SCOPE_GAP"]+g["CONFLICTING_EVIDENCE_GAP"]+g["TEST_METHOD_EVIDENCE_GAP"]
        if g["CONFLICTING_EVIDENCE_GAP"] or g["REPORT_SCOPE_GAP"]: report_s=ReadinessDimensionStatus.NEEDS_REVIEW
        elif total and useful == 0 and report_n: report_s=ReadinessDimensionStatus.INSUFFICIENT_DATA
        else: report_s=ReadinessDimensionStatus.PARTIAL if report_n else ReadinessDimensionStatus.READY
        ts=self._get(tech,"summary",{}) or {}; ttotal=int(self._get(ts,"total_effective_technical_constraints_considered",0) or 0); treview=sum(int(self._get(ts,x,0) or 0) for x in ("NEEDS_REVIEW","UNKNOWN","INCOMPARABLE")); tmissing=int(self._get(ts,"NO_MEASUREMENT",0) or 0); tresolved=sum(int(self._get(ts,x,0) or 0) for x in ("SATISFIES","VIOLATES","NOT_APPLICABLE","INACTIVE")); tech_s=ReadinessDimensionStatus.NEEDS_REVIEW if treview else ReadinessDimensionStatus.PARTIAL if tmissing else ReadinessDimensionStatus.READY if ttotal else ReadinessDimensionStatus.NOT_APPLICABLE
        ns=self._get(self._get(na,"summary",{}),"logical_group_level",{}) or {}; nconf=int(self._get(ns,"POTENTIAL_CONFLICT",0) or 0); nreview=int(self._get(ns,"NEEDS_REVIEW",0) or 0); npart=sum(int(self._get(ns,x,0) or 0) for x in ("INSUFFICIENT_PRODUCT_DATA","INSUFFICIENT_REPORT_EVIDENCE","INSUFFICIENT_KB_RULE")); ntotal=int(self._get(ns,"groups_receiving_na",0) or 0); nresolved=int(self._get(ns,"JUSTIFIED",0) or 0); na_s=ReadinessDimensionStatus.NEEDS_REVIEW if nconf or nreview else ReadinessDimensionStatus.PARTIAL if npart else ReadinessDimensionStatus.READY
        decision_s=ReadinessDimensionStatus.BLOCKED if d["NON_COMPLIANT"] else ReadinessDimensionStatus.NEEDS_REVIEW if d["NEEDS_REVIEW"] else ReadinessDimensionStatus.PARTIAL if d["INSUFFICIENT_EVIDENCE"] or d["UNKNOWN_APPLICABILITY"] else ReadinessDimensionStatus.READY
        return [
            dim("STANDARD_KB_READINESS",kb_s,"KB_REVIEW_REQUIRED" if kb_n else "KB_READY",total,total-kb_n,kb_n,kb_n,{"KB_REVIEW_GAP":kb_n},["REVIEW_KB_REQUIREMENT"]),
            dim("PRODUCT_PROFILE_READINESS",product_s,"PRODUCT_DATA_INCOMPLETE" if product_n else "PRODUCT_PROFILE_READY",total,total-product_n,product_n,0,{"PRODUCT_DATA_GAP":product_n},["PROVIDE_PRODUCT_INFORMATION"]),
            dim("APPLICABILITY_READINESS",app_s,"APPLICABILITY_UNRESOLVED" if app_n else "APPLICABILITY_READY",total,total-app_n,app_n,g["APPLICABILITY_GAP"],self._get(app,"summary",{}) or {},["REVIEW_APPLICABILITY"]),
            dim("REPORT_EVIDENCE_READINESS",report_s,"REPORT_EVIDENCE_REVIEW_REQUIRED" if report_s is ReadinessDimensionStatus.NEEDS_REVIEW else "REPORT_EVIDENCE_INCOMPLETE" if report_n else "REPORT_EVIDENCE_READY",total,useful,report_n,g["CONFLICTING_EVIDENCE_GAP"]+g["REPORT_SCOPE_GAP"],self._get(scope,"summary",{}) or {},["PROVIDE_REPORT_EVIDENCE","REVIEW_REPORT_SCOPE","REVIEW_CONFLICTING_EVIDENCE","REPEAT_OR_VERIFY_TEST"]),
            ReadinessDimensionResult("TECHNICAL_EVIDENCE_READINESS",tech_s,"TECHNICAL_REVIEW_REQUIRED" if treview else "TECHNICAL_MEASUREMENTS_INCOMPLETE" if tmissing else "TECHNICAL_EVIDENCE_READY", "Technical evidence status follows preserved constraint decisions.",ttotal,tresolved,tmissing+treview,treview,self._plain(ts),[x.blocker_id for x in blockers if x.blocker_type=="TECHNICAL_MEASUREMENT_REQUIRED"],["PROVIDE_MEASUREMENT"] if tmissing else []),
            ReadinessDimensionResult("NA_VALIDATION_READINESS",na_s,"NA_REVIEW_REQUIRED" if nconf or nreview else "NA_INFORMATION_INCOMPLETE" if npart else "NA_VALIDATION_READY","Reported N/A status follows scope-aware validation.",ntotal,nresolved,npart+nreview,nconf,self._plain(ns),[x.blocker_id for x in blockers if x.blocker_type=="NA_CONFLICT_REVIEW"],["REVIEW_REPORTED_NA"] if nconf or nreview else []),
            dim("COMPLIANCE_DECISION_READINESS",decision_s,"PROVEN_NON_COMPLIANCE_PRESENT" if d["NON_COMPLIANT"] else "DECISIONS_NEED_REVIEW" if d["NEEDS_REVIEW"] else "DECISIONS_INCOMPLETE" if d["INSUFFICIENT_EVIDENCE"] or d["UNKNOWN_APPLICABILITY"] else "DECISIONS_READY",total,d["COMPLIANT"]+d["NON_COMPLIANT"]+d["NOT_APPLICABLE"]+d["INACTIVE"],d["INSUFFICIENT_EVIDENCE"]+d["UNKNOWN_APPLICABILITY"]+d["NEEDS_REVIEW"],d["NON_COMPLIANT"],d,["MANUAL_TECHNICAL_REVIEW"]),
        ]

    def _findings(self, gaps: Sequence[Any]) -> List[OverallComplianceFinding]:
        out=[]
        for x in gaps:
            gt=self._enum(self._get(x,"primary_gap_type"));
            if gt not in self.FINDING_TYPES: continue
            gid=str(self._get(x,"group_id","") or ""); cid=self._get(x,"clause_id"); sev=self._enum(self._get(x,"severity")) or "NONE"; actions=sorted({self._enum(a) for a in self._get(x,"resolution_actions",[]) or []})
            out.append(OverallComplianceFinding("FINDING-"+self._digest(gt,gid,str(cid)),self.FINDING_TYPES[gt],sev,cid,gid,f"{gt} affects logical group {gid}.",str(self._get(x,"reason","") or ""),gt,actions,[],"Logical-group finding; atomic members are traceability only."))
        return sorted(out,key=lambda x:(x.finding_type,x.clause_id or "",x.group_id or ""))

    def _blockers(self, gaps: Sequence[Any]) -> List[OverallReadinessBlocker]:
        buckets=defaultdict(lambda:{"groups":set(),"clauses":set(),"actions":set()})
        for x in gaps:
            gt=self._enum(self._get(x,"primary_gap_type"));
            if gt not in self.BLOCKER_TYPES: continue
            severity=self._enum(self._get(x,"severity")) or "NONE"; key=(self.BLOCKER_TYPES[gt],severity)
            buckets[key]["groups"].add(str(self._get(x,"group_id","") or "")); cid=self._get(x,"clause_id")
            if cid is not None:buckets[key]["clauses"].add(str(cid))
            buckets[key]["actions"].update(self._enum(a) for a in self._get(x,"resolution_actions",[]) or [])
        out=[]
        for (bt,sev),v in sorted(buckets.items()):
            groups=sorted(x for x in v["groups"] if x); clauses=sorted(v["clauses"]); actions=self._sort_actions(v["actions"])
            out.append(OverallReadinessBlocker("BLOCKER-"+self._digest(bt,sev),bt,sev,groups,clauses,f"{len(groups)} logical groups across {len(clauses)} clauses require resolution.",actions,"Aggregated from Step 21 logical-group gaps."))
        return out

    def _actions(self,gaps:Sequence[Any])->List[str]:
        return self._sort_actions({self._enum(a) for x in gaps for a in self._get(x,"resolution_actions",[]) or [] if self._enum(a)!="NONE"})
    def _sort_actions(self,actions:Sequence[str])->List[str]:
        rank={x:i for i,x in enumerate(self.ACTION_PRIORITY)};return sorted(set(actions),key=lambda x:(rank.get(x,999),x))
    @classmethod
    def _counts(cls,items:Sequence[Any],field_name:str,values:Sequence[str])->Dict[str,int]:
        c=Counter(cls._enum(cls._get(x,field_name)) for x in items);return {"total":len(items),**{x:c[x] for x in values}}
    @staticmethod
    def _digest(*parts:str)->str:return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16].upper()
    @staticmethod
    def _get(value:Any,name:str,default:Any=None)->Any:return value.get(name,default) if isinstance(value,Mapping) else getattr(value,name,default) if value is not None else default
    @staticmethod
    def _enum(value:Any)->Optional[str]:return None if value is None else str(value.value if isinstance(value,Enum) else value)
    @classmethod
    def _plain(cls,value:Any)->Any:
        if isinstance(value,Enum):return value.value
        if is_dataclass(value):return cls._plain(asdict(value))
        if isinstance(value,Mapping):return {str(k):cls._plain(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [cls._plain(v) for v in value]
        return value
    @classmethod
    def to_dict(cls,value:OverallReadinessResult)->Dict[str,Any]:
        if not is_dataclass(value):raise TypeError("overall readiness model required")
        return cls._plain(asdict(value))
    @classmethod
    def to_json(cls,value:OverallReadinessResult,indent:int=2)->str:return json.dumps(cls.to_dict(value),ensure_ascii=False,sort_keys=True,indent=indent)
    @classmethod
    def save_json(cls,value:OverallReadinessResult,path:Any)->Path:
        target=Path(path);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(cls.to_json(value)+"\n",encoding="utf-8");return target


__all__=["GenericOverallReadinessBuilder","OverallComplianceFinding","OverallReadinessBlocker","OverallReadinessResult","OverallReadinessStatus","ReadinessDimensionResult","ReadinessDimensionStatus","STRICT_READINESS_POLICY","StrictReadinessPolicy"]
