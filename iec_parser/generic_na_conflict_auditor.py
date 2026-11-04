"""Deterministic root-cause audit for requirement-level report N/A conflicts."""
from __future__ import annotations

import copy
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote


class NAConflictRootCause(str, Enum):
    TRUE_NA_CONFLICT = "TRUE_NA_CONFLICT"
    CLAUSE_LEVEL_REPORTING_MISMATCH = "CLAUSE_LEVEL_REPORTING_MISMATCH"
    REQUIREMENT_GRANULARITY_MISMATCH = "REQUIREMENT_GRANULARITY_MISMATCH"
    PART1_PART2_MAPPING_EFFECT = "PART1_PART2_MAPPING_EFFECT"
    MISSING_PRODUCT_CONTEXT = "MISSING_PRODUCT_CONTEXT"
    REPORT_EVIDENCE_SCOPE_AMBIGUITY = "REPORT_EVIDENCE_SCOPE_AMBIGUITY"
    KB_REQUIREMENT_SEGMENTATION_ISSUE = "KB_REQUIREMENT_SEGMENTATION_ISSUE"
    KB_APPLICABILITY_RULE_ISSUE = "KB_APPLICABILITY_RULE_ISSUE"
    REPORT_PARSER_VERDICT_ISSUE = "REPORT_PARSER_VERDICT_ISSUE"
    MULTIPLE_CAUSES = "MULTIPLE_CAUSES"
    NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"


@dataclass
class NAConflictAuditResult:
    audit_id: str
    effective_requirement_id: str
    effective_clause_id: Optional[str]
    source_clause_id: Optional[str]
    na_validation_status: Optional[str]
    applicability_decision: Optional[str]
    root_cause: NAConflictRootCause
    secondary_causes: List[NAConflictRootCause] = field(default_factory=list)
    confidence: Optional[float] = None
    reason: str = ""
    effective_requirement_text: str = ""
    condition_text: Optional[str] = None
    applicability_rule: Optional[Dict[str, Any]] = None
    required_features: List[str] = field(default_factory=list)
    product_facts_used: List[Dict[str, Any]] = field(default_factory=list)
    missing_features: List[str] = field(default_factory=list)
    effective_source_type: Optional[str] = None
    base_sources: List[Dict[str, Any]] = field(default_factory=list)
    delta_sources: List[Dict[str, Any]] = field(default_factory=list)
    report_match_status: Optional[str] = None
    report_clause_ids: List[str] = field(default_factory=list)
    report_verdicts: List[str] = field(default_factory=list)
    report_pages: List[int] = field(default_factory=list)
    report_evidence_ids: List[str] = field(default_factory=list)
    report_raw_excerpt: List[str] = field(default_factory=list)
    technical_constraint_decisions: List[str] = field(default_factory=list)
    recommended_action: str = "MANUAL_REVIEW"
    notes: Optional[str] = None


@dataclass
class NAConflictClauseAuditSummary:
    clause_id: str
    potential_conflict_requirements: int
    root_cause_counts: Dict[str, int] = field(default_factory=dict)
    dominant_root_cause: Optional[str] = None
    true_conflict_count: int = 0
    scope_mismatch_count: int = 0
    granularity_mismatch_count: int = 0
    mapping_effect_count: int = 0
    kb_rule_issue_count: int = 0
    parser_issue_count: int = 0
    manual_review_count: int = 0


@dataclass
class NAConflictAuditReport:
    effective_kb_id: str
    profile_id: str
    report_document_id: str
    total_potential_conflicts: int
    results: List[NAConflictAuditResult] = field(default_factory=list)
    clause_summaries: List[NAConflictClauseAuditSummary] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)


class GenericNAConflictAuditor:
    """Explain existing POTENTIAL_CONFLICT results without changing upstream truth."""

    STRONG_MATCHES = {"EXACT_CLAUSE", "EXACT_SUBCLAUSE", "ANNEX_EXACT"}
    WEAK_MATCHES = {"PARENT_CLAUSE", "CHILD_CLAUSE", "MULTIPLE_CANDIDATES", "NEEDS_REVIEW"}
    PART2_TYPES = {"PART_2_ADDITION", "PART_2_MODIFICATION", "PART_2_REPLACEMENT", "PART_2_NEW_REQUIREMENT"}
    BOILERPLATE = {"compliance", "checked", "check", "test", "testing", "inspection", "accordance"}

    def audit(self, effective_kb: Any, product_profile: Any, applicability_report: Any,
              report_evidence: Any, evidence_match_report: Any,
              technical_constraint_report: Any, na_validation_report: Any) -> NAConflictAuditReport:
        requirements = {self._get(r, "effective_requirement_id"): r for r in self._requirements(effective_kb)}
        applications = {self._get(x, "effective_requirement_id"): x for x in self._get(applicability_report, "results", [])}
        matches = {self._get(x, "effective_requirement_id"): x for x in self._get(evidence_match_report, "matches", [])}
        technical: Dict[str, List[Any]] = defaultdict(list)
        for item in self._get(technical_constraint_report, "results", []):
            technical[str(self._get(item, "effective_requirement_id"))].append(item)
        conflicts = [x for x in self._get(na_validation_report, "results", [])
                     if self._enum(self._get(x, "status")) == "POTENTIAL_CONFLICT"]
        evidence_requirements: Dict[str, set[str]] = defaultdict(set)
        clause_requirements: Dict[str, set[str]] = defaultdict(set)
        for item in conflicts:
            rid = str(self._get(item, "effective_requirement_id"))
            match = matches.get(rid, {})
            for ref in self._get(match, "evidence_refs", []):
                if self._enum(self._get(ref, "reported_verdict")) == "NA":
                    evidence_requirements[str(self._get(ref, "evidence_id"))].add(rid)
                    clause_requirements[str(self._get(ref, "report_clause_id"))].add(rid)
        evidence_fanout = {key: len(value) for key, value in evidence_requirements.items()}
        clause_fanout = {key: len(value) for key, value in clause_requirements.items()}
        results = []
        for item in conflicts:
            rid = str(self._get(item, "effective_requirement_id"))
            results.append(self.audit_requirement(item, requirements.get(rid, {}), applications.get(rid, {}),
                                                   matches.get(rid, {}), technical.get(rid, []),
                                                   evidence_fanout, clause_fanout))
        clauses = self._group_clauses(results)
        report = NAConflictAuditReport(
            str(self._get(effective_kb, "effective_kb_id", "")),
            str(self._get(product_profile, "profile_id", "")),
            str(self._get(report_evidence, "document_id", "")), len(results), results, clauses)
        report.summary = self._summary(results, evidence_fanout, clause_fanout)
        report.diagnostics = self._diagnostics(results)
        return report

    def audit_requirement(self, na: Any, requirement: Any, app: Any, match: Any,
                          technical: Sequence[Any] = (), evidence_fanout: Optional[Mapping[str, int]] = None,
                          clause_fanout: Optional[Mapping[str, int]] = None) -> NAConflictAuditResult:
        evidence_fanout, clause_fanout = evidence_fanout or {}, clause_fanout or {}
        refs = [x for x in self._get(match, "evidence_refs", []) if self._enum(self._get(x, "reported_verdict")) == "NA"]
        all_refs = list(self._get(match, "evidence_refs", []))
        verdicts = sorted({self._enum(self._get(x, "reported_verdict")) for x in all_refs if self._get(x, "reported_verdict")})
        status = self._enum(self._get(match, "match_status"))
        source_type = self._enum(self._get(app, "effective_source_type")) or self._enum(self._get(requirement, "effective_source_type"))
        req_text = str(self._get(requirement, "text", ""))
        req_type = self._enum(self._get(requirement, "requirement_type"))
        shared_evidence = max([evidence_fanout.get(str(self._get(x, "evidence_id")), 1) for x in refs] or [1])
        shared_clause = max([clause_fanout.get(str(self._get(x, "report_clause_id")), 1) for x in refs] or [1])
        causes: List[NAConflictRootCause] = []
        if len(set(verdicts)) > 1:
            causes.append(NAConflictRootCause.REPORT_PARSER_VERDICT_ISSUE)
        if status in self.WEAK_MATCHES:
            causes.append(NAConflictRootCause.REPORT_EVIDENCE_SCOPE_AMBIGUITY)
        if shared_evidence > 1 or shared_clause > 1:
            causes.append(NAConflictRootCause.CLAUSE_LEVEL_REPORTING_MISMATCH)
        if req_type == "TEST" and (shared_evidence > 1 or shared_clause > 1):
            causes.append(NAConflictRootCause.KB_REQUIREMENT_SEGMENTATION_ISSUE)
        overlap = self._phrase_overlap(req_text, " ".join(str(self._get(x, "raw_text_excerpt", "")) for x in refs))
        if shared_evidence > 1 and overlap < .15:
            causes.append(NAConflictRootCause.REQUIREMENT_GRANULARITY_MISMATCH)
        if source_type in self.PART2_TYPES and shared_clause > 1:
            causes.append(NAConflictRootCause.PART1_PART2_MAPPING_EFFECT)
        rule = self._get(app, "rule")
        condition = self._get(app, "condition_text")
        if condition and self._enum(self._get(app, "applicability_status_from_kb")) == "ALWAYS":
            causes.append(NAConflictRootCause.KB_APPLICABILITY_RULE_ISSUE)
        if self._get(app, "missing_features"):
            causes.append(NAConflictRootCause.MISSING_PRODUCT_CONTEXT)
        causes = list(dict.fromkeys(causes))
        if not causes:
            confirmed = all(self._enum(self._get(f, "status")) in {"CONFIRMED", "INFERRED_STRONG"}
                            for f in self._get(app, "facts_used", []))
            reliable_rule = self._enum(self._get(app, "applicability_status_from_kb")) == "ALWAYS" or (rule and confirmed)
            if status in self.STRONG_MATCHES and len(verdicts) == 1 and reliable_rule and shared_evidence == 1:
                causes = [NAConflictRootCause.TRUE_NA_CONFLICT]
            else:
                causes = [NAConflictRootCause.NEEDS_MANUAL_REVIEW]
        primary = causes[0] if len(causes) == 1 else NAConflictRootCause.MULTIPLE_CAUSES
        secondary = causes if primary is NAConflictRootCause.MULTIPLE_CAUSES else causes[1:]
        action = self._action(primary, causes)
        reason = self._reason(primary, causes, status, shared_evidence, overlap)
        rid = str(self._get(na, "effective_requirement_id"))
        return NAConflictAuditResult(
            "NA-CONFLICT-AUDIT-" + quote(rid, safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"),
            rid, self._get(na, "effective_clause_id"), self._get(na, "source_clause_id"),
            self._enum(self._get(na, "status")), self._enum(self._get(app, "decision")), primary,
            secondary, self._confidence(primary, status, shared_evidence), reason, req_text, condition,
            copy.deepcopy(rule), sorted(self._get(app, "required_features", [])),
            copy.deepcopy(self._get(app, "facts_used", [])), sorted(self._get(app, "missing_features", [])),
            source_type, copy.deepcopy(self._get(app, "base_sources", [])), copy.deepcopy(self._get(app, "delta_sources", [])),
            status, sorted({str(self._get(x, "report_clause_id")) for x in refs}), verdicts,
            sorted({p for x in refs for p in [self._get(x, "page_start"), self._get(x, "page_end")] if p is not None}),
            sorted({str(self._get(x, "evidence_id")) for x in refs}),
            [str(self._get(x, "raw_text_excerpt", "")) for x in refs],
            sorted({str(self._get(x, "decision")) for x in technical}), action,
            "Technical outcomes are diagnostic only." if technical else None)

    @classmethod
    def _reason(cls, primary: NAConflictRootCause, causes: Sequence[NAConflictRootCause],
                match: Optional[str], fanout: int, overlap: float) -> str:
        if primary is NAConflictRootCause.TRUE_NA_CONFLICT:
            return "Applicable requirement has a reliable one-to-one N/A match and no detected structural explanation."
        labels = ", ".join(x.value for x in causes)
        return f"Detected diagnostic signals: {labels}; match={match}; evidence_fanout={fanout}; phrase_overlap={overlap:.3f}."

    @staticmethod
    def _action(primary: NAConflictRootCause, causes: Sequence[NAConflictRootCause]) -> str:
        all_causes = set(causes) | {primary}
        order = [
            (NAConflictRootCause.REPORT_PARSER_VERDICT_ISSUE, "REVIEW_REPORT_PARSER"),
            (NAConflictRootCause.KB_APPLICABILITY_RULE_ISSUE, "REVIEW_APPLICABILITY_RULE"),
            (NAConflictRootCause.KB_REQUIREMENT_SEGMENTATION_ISSUE, "REVIEW_REQUIREMENT_SPLITTING"),
            (NAConflictRootCause.PART1_PART2_MAPPING_EFFECT, "REVIEW_PART1_PART2_MAPPING"),
            (NAConflictRootCause.MISSING_PRODUCT_CONTEXT, "IMPROVE_PRODUCT_PROFILE"),
            (NAConflictRootCause.REPORT_EVIDENCE_SCOPE_AMBIGUITY, "REVIEW_REPORT_VERDICT_SCOPE"),
            (NAConflictRootCause.CLAUSE_LEVEL_REPORTING_MISMATCH, "REVIEW_REPORT_VERDICT_SCOPE")]
        for cause, action in order:
            if cause in all_causes:
                return action
        return "NO_ENGINE_CHANGE_REPORT_REVIEW" if primary is NAConflictRootCause.TRUE_NA_CONFLICT else "MANUAL_REVIEW"

    @staticmethod
    def _confidence(primary: NAConflictRootCause, match: Optional[str], fanout: int) -> float:
        if primary is NAConflictRootCause.TRUE_NA_CONFLICT:
            return .95
        if primary is NAConflictRootCause.MULTIPLE_CAUSES:
            return .85
        return .8 if match in GenericNAConflictAuditor.STRONG_MATCHES and fanout == 1 else .7

    @classmethod
    def _phrase_overlap(cls, left: str, right: str) -> float:
        def tokens(value: str) -> set[str]:
            return {x for x in re.findall(r"[a-z0-9]+", value.lower()) if len(x) > 2 and x not in cls.BOILERPLATE}
        a, b = tokens(left), tokens(right)
        return len(a & b) / len(a) if a else 0.0

    @classmethod
    def _group_clauses(cls, results: Sequence[NAConflictAuditResult]) -> List[NAConflictClauseAuditSummary]:
        groups: Dict[str, List[NAConflictAuditResult]] = defaultdict(list)
        for item in results:
            groups[str(item.source_clause_id)].append(item)
        output = []
        for clause, items in sorted(groups.items(), key=lambda x: cls._natural(x[0])):
            counts = Counter(x.root_cause.value for x in items)
            dominant = sorted(counts, key=lambda x: (-counts[x], x))[0]
            output.append(NAConflictClauseAuditSummary(
                clause, len(items), dict(sorted(counts.items())), dominant,
                counts[NAConflictRootCause.TRUE_NA_CONFLICT.value],
                counts[NAConflictRootCause.CLAUSE_LEVEL_REPORTING_MISMATCH.value] + counts[NAConflictRootCause.REPORT_EVIDENCE_SCOPE_AMBIGUITY.value],
                counts[NAConflictRootCause.REQUIREMENT_GRANULARITY_MISMATCH.value],
                counts[NAConflictRootCause.PART1_PART2_MAPPING_EFFECT.value],
                counts[NAConflictRootCause.KB_APPLICABILITY_RULE_ISSUE.value],
                counts[NAConflictRootCause.REPORT_PARSER_VERDICT_ISSUE.value],
                counts[NAConflictRootCause.NEEDS_MANUAL_REVIEW.value]))
        return output

    @classmethod
    def _summary(cls, results: Sequence[NAConflictAuditResult], evidence_fanout: Mapping[str, int],
                 clause_fanout: Mapping[str, int]) -> Dict[str, Any]:
        roots = Counter(x.root_cause.value for x in results)
        app_groups = Counter("ALWAYS" if not x.condition_text and x.applicability_rule is None else "RESOLVED_TRUE" for x in results)
        sources = Counter(x.effective_source_type or "UNKNOWN" for x in results)
        actions = Counter(x.recommended_action for x in results)
        top = [{"report_clause_id": k, "potential_conflicts": v} for k, v in sorted(clause_fanout.items(), key=lambda x: (-x[1], cls._natural(x[0])))[:20]]
        return {
            "root_cause_counts": {x.value: roots[x.value] for x in NAConflictRootCause},
            "unique_effective_clauses": len({x.source_clause_id for x in results}),
            "unique_report_clauses": len({c for x in results for c in x.report_clause_ids}),
            "unique_na_evidence_records": len(evidence_fanout),
            "average_conflicting_requirements_per_report_na_clause": round(sum(clause_fanout.values()) / len(clause_fanout), 6) if clause_fanout else 0.0,
            "maximum_conflicting_requirements_per_report_clause": max(clause_fanout.values(), default=0),
            "top_report_clauses_by_fanout": top,
            "applicability_basis_counts": dict(sorted(app_groups.items())),
            "effective_source_type_counts": dict(sorted(sources.items())),
            "recommended_action_counts": dict(sorted(actions.items())),
        }

    @staticmethod
    def _diagnostics(results: Sequence[NAConflictAuditResult]) -> List[Dict[str, Any]]:
        return [{"code": "AUDIT_MANUAL_REVIEW", "effective_requirement_id": x.effective_requirement_id}
                for x in results if x.root_cause is NAConflictRootCause.NEEDS_MANUAL_REVIEW]

    @classmethod
    def _requirements(cls, kb: Any) -> Iterable[Any]:
        def walk(items: Sequence[Any]) -> Iterable[Any]:
            for clause in items:
                yield from cls._get(clause, "requirements", [])
                yield from walk(cls._get(clause, "children", []))
        yield from walk(cls._get(kb, "clauses", []))
        for annex in cls._get(kb, "annexes", []):
            yield from cls._get(annex, "requirements", [])

    @staticmethod
    def _natural(value: str) -> Tuple[Any, ...]:
        return tuple(int(x) if x.isdigit() else x for x in re.split(r"(\d+)", value or ""))

    @staticmethod
    def _get(value: Any, name: str, default: Any = None) -> Any:
        return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default) if value is not None else default

    @staticmethod
    def _enum(value: Any) -> Optional[str]:
        return None if value is None else str(value.value if isinstance(value, Enum) else value)

    @classmethod
    def to_dict(cls, value: Any) -> Dict[str, Any]:
        if not is_dataclass(value):
            raise TypeError("audit model required")
        return cls._safe(asdict(value))

    @classmethod
    def _safe(cls, value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, dict):
            return {k: cls._safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [cls._safe(v) for v in value]
        return value

    @classmethod
    def to_json(cls, value: Any, indent: int = 2) -> str:
        return json.dumps(cls.to_dict(value), ensure_ascii=False, sort_keys=True, indent=indent)

    @classmethod
    def save_json(cls, report: NAConflictAuditReport, path: Any) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(cls.to_json(report) + "\n", encoding="utf-8")
        return target


__all__ = ["GenericNAConflictAuditor", "NAConflictAuditReport", "NAConflictAuditResult",
           "NAConflictClauseAuditSummary", "NAConflictRootCause"]
