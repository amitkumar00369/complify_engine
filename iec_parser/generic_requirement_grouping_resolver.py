"""Resolve logical requirement groups and inherited applicability scope."""
from __future__ import annotations

import copy
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


class RequirementGroupMemberRole(str, Enum):
    PRIMARY = "PRIMARY"
    CONTINUATION = "CONTINUATION"
    TEST_METHOD = "TEST_METHOD"
    ACCEPTANCE_CRITERION = "ACCEPTANCE_CRITERION"
    POST_TEST_CONDITION = "POST_TEST_CONDITION"
    EXCEPTION = "EXCEPTION"
    DEPENDENT_REQUIREMENT = "DEPENDENT_REQUIREMENT"
    INDEPENDENT = "INDEPENDENT"
    UNRESOLVED = "UNRESOLVED"


class ApplicabilityScopeType(str, Enum):
    OWN = "OWN"
    INHERIT_PRIMARY = "INHERIT_PRIMARY"
    INHERIT_PREVIOUS = "INHERIT_PREVIOUS"
    SHARED_GROUP = "SHARED_GROUP"
    INDEPENDENT = "INDEPENDENT"
    UNRESOLVED = "UNRESOLVED"


class RequirementGroupStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    UNRESOLVED = "UNRESOLVED"


@dataclass
class RequirementGroupMember:
    effective_requirement_id: str
    source_requirement_id: Optional[str]
    source_order: int
    role: RequirementGroupMemberRole
    applicability_scope: ApplicabilityScopeType
    applicability_source_requirement_id: Optional[str]
    reason: str
    confidence: Optional[float] = None


@dataclass
class RequirementGroup:
    group_id: str
    effective_clause_id: Optional[str]
    clause_id: str
    group_status: RequirementGroupStatus
    primary_requirement_id: Optional[str]
    members: List[RequirementGroupMember] = field(default_factory=list)
    shared_condition_text: Optional[str] = None
    shared_applicability_rule: Optional[Dict[str, Any]] = None
    report_scope_clause_ids: List[str] = field(default_factory=list)
    effective_source_types: List[str] = field(default_factory=list)
    reason: str = ""
    review_reason: Optional[str] = None


@dataclass
class RequirementGroupingReport:
    effective_kb_id: str
    groups: List[RequirementGroup] = field(default_factory=list)
    ungrouped_requirements: List[str] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)


class GenericRequirementGroupingResolver:
    """Create read-only structural grouping metadata for active requirements."""

    TEST_PATTERNS = (
        r"^compliance\s+(?:with\s+.+?\s+)?is\s+(?:checked|verified)\b",
        r"^conformity\s+is\s+checked\b", r"^the\s+tests?\s+(?:is|are)\s+carried\s+out\b")
    POST_TEST_PATTERNS = (r"^after\s+(?:this\s+|the\s+)?tests?\b", r"^at\s+the\s+end\s+of\s+the\s+test\b")
    CONTINUATION_PATTERNS = (r"^(?:these|such)\s+(?:parts|devices|components|means)\b", r"^they\s+shall\b",
                             r"^it\s+shall\s+only\s+be\s+possible\b", r"^(?:this|the)\s+requirement\b",
                             r"^for\s+this\s+purpose\b", r"^in\s+this\s+case\b")
    CROSS_REFERENCE_PATTERNS = (r"compliance\s+with\s+(?:this|the above)\s+requirement", r"the\s+test\s+of\s+this\s+subclause")
    ACCEPTANCE_PATTERNS = (r"^during\s+the\s+test\b", r"^there\s+shall\s+be\s+no\b",
                           r"\bshall\s+not\s+exceed\b", r"^the\s+appliance\s+shall\s+not\b")
    EXCEPTION_PATTERNS = (r"^(?:however|except|unless)\b",)
    PRIMARY_TYPES = {"GENERAL", "CONDITIONAL", "LIMIT", "MARKING", "INSTRUCTION", "CONSTRUCTION", "SAFETY"}

    def __init__(self) -> None:
        self._diagnostics: List[Dict[str, Any]] = []

    def resolve(self, effective_kb: Any, applicability_report: Any,
                evidence_match_report: Any = None) -> RequirementGroupingReport:
        self._diagnostics = []
        apps = {str(self._get(x, "effective_requirement_id")): x
                for x in self._get(applicability_report, "results", [])}
        matches = {str(self._get(x, "effective_requirement_id")): x
                   for x in self._get(evidence_match_report, "matches", [])} if evidence_match_report else {}
        groups: List[RequirementGroup] = []
        ungrouped: List[str] = []
        active_count = 0
        total_count = 0
        for namespace, clause in self._clauses(effective_kb):
            requirements = list(self._get(clause, "requirements", []))
            total_count += len(requirements)
            active = [r for r in requirements if self._enum(self._get(r, "effective_status", "ACTIVE")) == "ACTIVE"]
            active_count += len(active)
            ungrouped.extend(str(self._get(r, "effective_requirement_id")) for r in requirements if r not in active)
            groups.extend(self._resolve_clause(namespace, clause, active, apps, matches))
        report = RequirementGroupingReport(str(self._get(effective_kb, "effective_kb_id", "")), groups,
                                           sorted(ungrouped), diagnostics=copy.deepcopy(self._diagnostics))
        report.summary = self.get_summary(report, total_count, active_count, apps)
        return report

    def _resolve_clause(self, namespace: str, clause: Any, requirements: Sequence[Any],
                        apps: Mapping[str, Any], matches: Mapping[str, Any]) -> List[RequirementGroup]:
        if not requirements:
            return []
        clause_id = str(self._get(clause, "clause_id") or self._get(clause, "annex_id") or "UNKNOWN")
        effective_clause_id = self._get(clause, "effective_clause_id") or self._get(clause, "effective_annex_id")
        provisional: List[List[Tuple[Any, RequirementGroupMemberRole, ApplicabilityScopeType, str, float]]] = []
        current: List[Tuple[Any, RequirementGroupMemberRole, ApplicabilityScopeType, str, float]] = []
        for index, req in enumerate(requirements):
            text = self._clean(self._get(req, "text", ""))
            role = self._dependent_role(text, req, bool(current))
            if role is RequirementGroupMemberRole.ACCEPTANCE_CRITERION and current[-1][1] is not RequirementGroupMemberRole.TEST_METHOD:
                role = None
            own_condition = self._has_own_scope(req, apps.get(str(self._get(req, "effective_requirement_id"))))
            source = self._enum(self._get(req, "effective_source_type"))
            previous_source = self._enum(self._get(current[-1][0], "effective_source_type")) if current else None
            part_boundary = bool(current and source != previous_source and role is None)
            if own_condition and current and role not in {RequirementGroupMemberRole.POST_TEST_CONDITION}:
                role = None
            if role is None or part_boundary:
                if current:
                    provisional.append(current)
                    self._diagnostics.append({"code": "GROUP_BOUNDARY_CREATED", "clause_id": clause_id,
                                              "requirement_id": self._get(req, "effective_requirement_id")})
                if part_boundary:
                    self._diagnostics.append({"code": "GROUP_PART2_BOUNDARY", "clause_id": clause_id,
                                              "requirement_id": self._get(req, "effective_requirement_id")})
                current = [(req, RequirementGroupMemberRole.PRIMARY, ApplicabilityScopeType.OWN if own_condition else ApplicabilityScopeType.INDEPENDENT,
                            "Active normative or standalone requirement starts a logical group.", .9)]
            else:
                scope = ApplicabilityScopeType.OWN if own_condition else ApplicabilityScopeType.INHERIT_PRIMARY
                reason = self._role_reason(role)
                current.append((req, role, scope, reason, .95 if role in {RequirementGroupMemberRole.TEST_METHOD, RequirementGroupMemberRole.POST_TEST_CONDITION} else .85))
                self._diagnostics.append({"code": self._diagnostic(role), "clause_id": clause_id,
                                          "requirement_id": self._get(req, "effective_requirement_id")})
        if current:
            provisional.append(current)
        output = []
        safe_namespace = re.sub(r"[^A-Za-z0-9]+", "_", namespace).strip("_") or "MAIN"
        safe_clause = re.sub(r"[^A-Za-z0-9.]+", "_", clause_id).strip("_")
        for number, items in enumerate(provisional, 1):
            primary_req = items[0][0]
            primary_id = str(self._get(primary_req, "effective_requirement_id"))
            primary_app = apps.get(primary_id, {})
            members = []
            for order, (req, role, scope, reason, confidence) in enumerate(items, 1):
                rid = str(self._get(req, "effective_requirement_id"))
                members.append(RequirementGroupMember(rid, self._source_requirement_id(req), order, role, scope,
                                                      primary_id if scope is ApplicabilityScopeType.INHERIT_PRIMARY else rid if scope is ApplicabilityScopeType.OWN else None,
                                                      reason, confidence))
                if scope is ApplicabilityScopeType.INHERIT_PRIMARY:
                    self._diagnostics.append({"code": "GROUP_APPLICABILITY_INHERITANCE", "clause_id": clause_id,
                                              "requirement_id": rid, "source_requirement_id": primary_id})
            report_scopes = self._shared_report_scopes(items, matches)
            if report_scopes and len(items) > 1:
                self._diagnostics.append({"code": "GROUP_SHARED_REPORT_SCOPE", "clause_id": clause_id,
                                          "group_number": number, "report_clause_ids": report_scopes})
            source_types = sorted({self._enum(self._get(x[0], "effective_source_type")) or "UNKNOWN" for x in items})
            group_status = RequirementGroupStatus.RESOLVED
            review_reason = None
            if items[0][1] is RequirementGroupMemberRole.PRIMARY and self._enum(self._get(primary_req, "requirement_type")) == "TEST" and len(items) == 1:
                members[0].role = RequirementGroupMemberRole.INDEPENDENT
                members[0].applicability_scope = ApplicabilityScopeType.INDEPENDENT
                members[0].applicability_source_requirement_id = None
            output.append(RequirementGroup(f"RG-{safe_namespace}-{safe_clause}-{number:03d}", effective_clause_id,
                                           clause_id, group_status, primary_id, members,
                                           self._get(primary_app, "condition_text") or self._get(primary_req, "condition_text"),
                                           copy.deepcopy(self._get(primary_app, "rule") or self._get(self._get(primary_req, "applicability", {}), "logic")),
                                           report_scopes, source_types,
                                           "Members are adjacent and connected by explicit structural dependency signals." if len(items) > 1 else "Independent active requirement group.",
                                           review_reason))
        return output

    def reconcile_conflicts(self, report: RequirementGroupingReport, na_conflict_audit: Any,
                            applicability_report: Any = None) -> Dict[str, Any]:
        member_index = {m.effective_requirement_id: (g, m) for g in report.groups for m in g.members}
        counts = Counter()
        always_counts = Counter()
        apps = {str(self._get(x, "effective_requirement_id")): x for x in self._get(applicability_report, "results", [])} if applicability_report else {}
        for item in self._get(na_conflict_audit, "results", []):
            rid = str(self._get(item, "effective_requirement_id"))
            pair = member_index.get(rid)
            category = "unresolved_grouping"
            if pair:
                member = pair[1]
                if member.role is RequirementGroupMemberRole.PRIMARY:
                    category = "primary_requirement"
                elif member.applicability_scope in {ApplicabilityScopeType.INHERIT_PRIMARY, ApplicabilityScopeType.INHERIT_PREVIOUS, ApplicabilityScopeType.SHARED_GROUP}:
                    category = "dependent_inherited_requirement"
                elif member.role is RequirementGroupMemberRole.INDEPENDENT or member.applicability_scope is ApplicabilityScopeType.INDEPENDENT:
                    category = "independent_requirement"
            counts[category] += 1
            app = apps.get(rid, {})
            if self._enum(self._get(app, "applicability_status_from_kb")) == "ALWAYS":
                always_counts[category] += 1
        return {"potential_conflicts_total": sum(counts.values()), **dict(counts),
                "always_potential_conflicts_total": sum(always_counts.values()),
                "always_conflicts_by_grouping": dict(always_counts)}

    @classmethod
    def get_summary(cls, report: RequirementGroupingReport, total: Optional[int] = None,
                    active: Optional[int] = None, apps: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        members = [m for g in report.groups for m in g.members]
        roles = Counter(m.role.value for m in members)
        scopes = Counter(m.applicability_scope.value for m in members)
        app_map = apps or {}
        inherited_always = sum(m.applicability_scope is ApplicabilityScopeType.INHERIT_PRIMARY and
                               cls._enum(cls._get(app_map.get(m.effective_requirement_id, {}), "applicability_status_from_kb")) == "ALWAYS"
                               for m in members)
        return {"total_effective_requirements": total if total is not None else len(members) + len(report.ungrouped_requirements),
                "active_requirements_considered": active if active is not None else len(members),
                "groups_created": len(report.groups), "single_member_groups": sum(len(g.members) == 1 for g in report.groups),
                "multi_member_groups": sum(len(g.members) > 1 for g in report.groups),
                "ungrouped_requirements": len(report.ungrouped_requirements),
                "members_by_role": {x.value: roles[x.value] for x in RequirementGroupMemberRole},
                "applicability_scopes": {x.value: scopes[x.value] for x in ApplicabilityScopeType},
                "always_requirements_reclassified_as_inherited_scope": inherited_always,
                "groups_needing_review": sum(g.group_status is not RequirementGroupStatus.RESOLVED for g in report.groups)}

    @classmethod
    def _dependent_role(cls, text: str, req: Any, has_previous: bool) -> Optional[RequirementGroupMemberRole]:
        if not has_previous:
            return None
        if cls._matches(text, cls.POST_TEST_PATTERNS):
            return RequirementGroupMemberRole.POST_TEST_CONDITION
        if cls._matches(text, cls.TEST_PATTERNS) or cls._matches(text, cls.CROSS_REFERENCE_PATTERNS):
            return RequirementGroupMemberRole.TEST_METHOD
        if cls._matches(text, cls.ACCEPTANCE_PATTERNS):
            return RequirementGroupMemberRole.ACCEPTANCE_CRITERION
        if cls._matches(text, cls.EXCEPTION_PATTERNS):
            return RequirementGroupMemberRole.EXCEPTION
        if cls._matches(text, cls.CONTINUATION_PATTERNS):
            return RequirementGroupMemberRole.CONTINUATION
        if cls._enum(cls._get(req, "requirement_type")) == "TEST":
            return RequirementGroupMemberRole.TEST_METHOD
        return None

    @classmethod
    def _has_own_scope(cls, req: Any, app: Any) -> bool:
        applicability = cls._get(req, "applicability", {})
        return bool(cls._get(req, "condition_text") or cls._get(app, "condition_text") or
                    cls._get(app, "rule") or cls._get(applicability, "logic"))

    @staticmethod
    def _role_reason(role: RequirementGroupMemberRole) -> str:
        return {RequirementGroupMemberRole.TEST_METHOD: "Explicit compliance/test wording depends on the preceding obligation.",
                RequirementGroupMemberRole.POST_TEST_CONDITION: "Explicit post-test wording depends on the preceding test group.",
                RequirementGroupMemberRole.ACCEPTANCE_CRITERION: "Acceptance wording follows and qualifies the preceding test.",
                RequirementGroupMemberRole.CONTINUATION: "Conservative anaphoric continuation refers to the preceding obligation.",
                RequirementGroupMemberRole.EXCEPTION: "Explicit exception wording qualifies the preceding obligation."}.get(role, "Structural dependency detected.")

    @staticmethod
    def _diagnostic(role: RequirementGroupMemberRole) -> str:
        return {RequirementGroupMemberRole.TEST_METHOD: "GROUP_TEST_METHOD_ATTACHED",
                RequirementGroupMemberRole.POST_TEST_CONDITION: "GROUP_POST_TEST_ATTACHED",
                RequirementGroupMemberRole.CONTINUATION: "GROUP_CONTINUATION_ATTACHED"}.get(role, "GROUP_DEPENDENT_ATTACHED")

    @classmethod
    def _shared_report_scopes(cls, items: Sequence[Tuple[Any, Any, Any, Any, Any]], matches: Mapping[str, Any]) -> List[str]:
        scopes = []
        for req, *_ in items:
            match = matches.get(str(cls._get(req, "effective_requirement_id")), {})
            scopes.append({str(cls._get(x, "report_clause_id")) for x in cls._get(match, "evidence_refs", []) if cls._get(x, "report_clause_id")})
        return sorted(set.intersection(*scopes)) if scopes and all(scopes) else []

    @classmethod
    def _source_requirement_id(cls, req: Any) -> Optional[str]:
        sources = list(cls._get(req, "delta_sources", [])) or list(cls._get(req, "base_sources", []))
        return cls._get(sources[0], "requirement_id") if sources else None

    @classmethod
    def _clauses(cls, kb: Any) -> Iterable[Tuple[str, Any]]:
        def walk(items: Sequence[Any], namespace: str) -> Iterable[Tuple[str, Any]]:
            for clause in items:
                yield namespace, clause
                yield from walk(cls._get(clause, "children", []), namespace)
        yield from walk(cls._get(kb, "clauses", []), "MAIN")
        for annex in cls._get(kb, "annexes", []):
            annex_id = str(cls._get(annex, "annex_id", "ANNEX"))
            yield "ANNEX_" + annex_id, annex
            yield from walk(cls._get(annex, "children", []), "ANNEX_" + annex_id)

    @staticmethod
    def _matches(text: str, patterns: Sequence[str]) -> bool:
        return any(re.search(pattern, text, re.I) for pattern in patterns)

    @staticmethod
    def _clean(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @staticmethod
    def _get(value: Any, name: str, default: Any = None) -> Any:
        return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default) if value is not None else default

    @staticmethod
    def _enum(value: Any) -> Optional[str]:
        return None if value is None else str(value.value if isinstance(value, Enum) else value)

    def get_diagnostics(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._diagnostics)

    @classmethod
    def to_dict(cls, value: Any) -> Dict[str, Any]:
        if not is_dataclass(value):
            raise TypeError("grouping model required")
        return cls._safe(asdict(value))

    @classmethod
    def _safe(cls, value: Any) -> Any:
        if isinstance(value, Enum): return value.value
        if isinstance(value, dict): return {k: cls._safe(v) for k, v in value.items()}
        if isinstance(value, list): return [cls._safe(v) for v in value]
        return value

    @classmethod
    def to_json(cls, value: Any, indent: int = 2) -> str:
        return json.dumps(cls.to_dict(value), ensure_ascii=False, sort_keys=True, indent=indent)

    @classmethod
    def save_json(cls, report: RequirementGroupingReport, path: Any) -> Path:
        target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(cls.to_json(report) + "\n", encoding="utf-8"); return target


__all__ = ["ApplicabilityScopeType", "GenericRequirementGroupingResolver", "RequirementGroup",
           "RequirementGroupMember", "RequirementGroupMemberRole", "RequirementGroupingReport",
           "RequirementGroupStatus"]
