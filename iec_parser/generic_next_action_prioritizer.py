"""Build a deterministic remediation plan from aggregated compliance issues."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


class PriorityLevel(IntEnum):
    """Explainable remediation sequence tiers, not a numerical risk score."""

    DO_FIRST = 1
    DO_NEXT = 2
    FOLLOW_UP = 3
    OPTIONAL_OR_REVIEW = 4


@dataclass(frozen=True)
class ActionSeveritySummary:
    """Unchanged aggregate-group severity counts for an action."""

    highest: str
    critical_group_count: int = 0
    high_group_count: int = 0
    medium_group_count: int = 0
    low_group_count: int = 0
    info_group_count: int = 0
    unknown_group_count: int = 0


@dataclass(frozen=True)
class ActionBlockingSummary:
    """Summed upstream blocking states without a new blocking decision."""

    blocking_count: int = 0
    non_blocking_count: int = 0
    unknown_count: int = 0


@dataclass(frozen=True)
class ActionDependency:
    """Explicit action dependencies derived from structured source hints."""

    depends_on: List[str] = field(default_factory=list)
    unlocks: List[str] = field(default_factory=list)
    status: str = "RESOLVED"


@dataclass(frozen=True)
class PrioritizedAction:
    """One consolidated user action and all of its upstream links."""

    action_id: str
    action_type: str
    priority_level: PriorityLevel
    priority_label: str
    title: str
    reason: str
    placement_reason: str
    expected_outcome: str
    source_action_descriptions: List[str]
    affected_aggregate_group_ids: List[str]
    affected_issue_ids: List[str]
    affected_requirement_group_ids: List[str]
    affected_clauses: List[str]
    evidence_refs: List[str]
    aggregate_group_count: int
    affected_issue_count: int
    unique_requirement_group_count: int
    unique_clause_count: int
    severity_summary: ActionSeveritySummary
    blocking_summary: ActionBlockingSummary
    conclusion_summary: Dict[str, int]
    dependency: ActionDependency
    diagnostic_categories: List[str] = field(default_factory=list)


@dataclass
class PrioritizedNextActionPlan:
    """A non-evaluative remediation plan derived from Step 26 groups."""

    schema_version: str
    source_aggregated_report_id: str
    metadata: Dict[str, int]
    actions: List[PrioritizedAction]
    accounting: Dict[str, Any]
    dependency_graph: Dict[str, Any]
    quality_audit: Dict[str, int]
    genericity_audit: Dict[str, int]
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)


class GenericNextActionPrioritizer:
    """Consolidate and sequence upstream actions without reevaluating compliance."""

    SEVERITY_RANK = {"UNKNOWN": 0, "INFO": 1, "LOW": 2, "MEDIUM": 3, "HIGH": 4, "CRITICAL": 5}
    BASELINE_TIER = {
        "PROVIDE_PRODUCT_INFORMATION": PriorityLevel.DO_FIRST,
        "LAB_CLARIFICATION": PriorityLevel.DO_FIRST,
        "PROVIDE_NA_JUSTIFICATION": PriorityLevel.DO_NEXT,
        "PROVIDE_EVIDENCE": PriorityLevel.DO_NEXT,
        "TECHNICAL_REVIEW": PriorityLevel.FOLLOW_UP,
        "RETEST": PriorityLevel.FOLLOW_UP,
        "CORRECT_REPORT": PriorityLevel.FOLLOW_UP,
        "CORRECT_CALCULATION": PriorityLevel.FOLLOW_UP,
        "NO_ACTION": PriorityLevel.OPTIONAL_OR_REVIEW,
    }
    TEXT = {
        "PROVIDE_PRODUCT_INFORMATION": ("Provide missing product information", "Additional product or sample information is required to resolve the affected evaluation scope.", "Allows affected requirements to be reevaluated using a confirmed product and sample scope."),
        "PROVIDE_NA_JUSTIFICATION": ("Provide justification for N/A requirements", "The report marks one or more requirements as not applicable without sufficient supporting justification.", "Allows the system to confirm whether affected requirements are legitimately not applicable."),
        "PROVIDE_EVIDENCE": ("Provide missing or incomplete test evidence", "The available report does not contain sufficient evidence for the affected requirements.", "Allows the affected requirements to proceed to evidence-based evaluation."),
        "LAB_CLARIFICATION": ("Request clarification from the test laboratory", "The available report evidence contains unresolved information that requires confirmation from the issuing laboratory.", "Allows conflicting or ambiguous report evidence to be resolved using an authoritative laboratory response."),
        "TECHNICAL_REVIEW": ("Perform technical review of unresolved evidence", "The available evidence requires technical assessment before a reliable conclusion can be established.", "Allows unresolved technical findings to be assessed using validated evidence."),
        "RETEST": ("Repeat or verify the affected tests", "Upstream findings require the affected tests to be repeated or verified.", "Provides test evidence obtained under the required conditions."),
        "CORRECT_REPORT": ("Correct inconsistent report information", "Structured report information requires correction or reconciliation.", "Provides a corrected authoritative record for subsequent evaluation."),
        "CORRECT_CALCULATION": ("Correct the affected calculations", "One or more structured calculations require correction and verification.", "Provides verified calculation results for subsequent evaluation."),
        "NO_ACTION": ("Review informational findings", "The contributing findings do not currently require a primary user action.", "Keeps informational context available without presenting it as actionable remediation."),
    }
    QUALITY_KEYS = (
        "aggregate_conclusion_modified", "aggregate_severity_modified", "aggregate_primary_action_modified",
        "aggregate_group_lost", "unsupported_dependency_invented", "dependency_cycle_silently_broken",
        "new_noncompliance_created", "new_blocking_decision_created", "readiness_score_created",
        "overall_report_status_created", "certification_claim_created", "standard_specific_production_branch",
        "product_specific_production_branch", "clause_specific_production_branch", "page_specific_production_branch",
        "model_specific_production_branch", "report_specific_production_branch", "fixture_specific_production_branch",
        "upstream_artifact_mutated",
    )

    def prioritize(self, aggregated_report: Any) -> PrioritizedNextActionPlan:
        """Create a stable action plan from actionable aggregate groups."""
        source = self._plain(aggregated_report)
        groups = list(source.get("actionable_groups", []) or [])
        buckets: Dict[Tuple[str, Tuple[str, ...]], List[Dict[str, Any]]] = {}
        for group in groups:
            action = group.get("primary_action") or {}
            action_type = self._value(action.get("type")) or "NO_ACTION"
            hints = tuple(sorted(self._dependency_hints(group)))
            buckets.setdefault((action_type, hints), []).append(copy.deepcopy(group))

        candidates = {key: self._candidate(key, values) for key, values in buckets.items()}
        type_to_ids: Dict[str, List[str]] = {}
        for candidate in candidates.values():
            type_to_ids.setdefault(candidate["action_type"], []).append(candidate["action_id"])
        for ids in type_to_ids.values():
            ids.sort()

        edges: Dict[str, Set[str]] = {c["action_id"]: set() for c in candidates.values()}
        for candidate in candidates.values():
            for prerequisite_type in candidate.pop("dependency_types"):
                edges[candidate["action_id"]].update(type_to_ids.get(prerequisite_type, []))
            edges[candidate["action_id"]].discard(candidate["action_id"])
        cyclic_ids = self._cyclic_nodes(edges)
        unlocks: Dict[str, Set[str]] = {action_id: set() for action_id in edges}
        for dependent, prerequisites in edges.items():
            for prerequisite in prerequisites:
                unlocks.setdefault(prerequisite, set()).add(dependent)

        levels = self._levels(candidates, edges, cyclic_ids)
        actions = []
        for candidate in candidates.values():
            action_id = candidate["action_id"]
            level = levels[action_id]
            dependency = ActionDependency(sorted(edges[action_id]), sorted(unlocks.get(action_id, set())), "UNRESOLVED_CYCLE" if action_id in cyclic_ids else "RESOLVED")
            actions.append(self._materialize(candidate, level, dependency))
        actions.sort(key=lambda x: (int(x.priority_level), -self.SEVERITY_RANK.get(x.severity_summary.highest, 0), x.action_type, x.action_id))

        source_group_ids = sorted({str(x.get("group_id")) for x in groups if x.get("group_id") is not None})
        planned_group_ids = sorted({gid for action in actions for gid in action.affected_aggregate_group_ids})
        unaccounted = sorted(set(source_group_ids) - set(planned_group_ids))
        source_id = "AGGREGATED-ISSUES-" + hashlib.sha256(self._canonical(source).encode()).hexdigest()[:20].upper()
        accounting = {"aggregate_groups_accounted_for": len(set(source_group_ids) & set(planned_group_ids)), "aggregate_groups_unaccounted_for": len(unaccounted), "unaccounted_aggregate_group_ids": unaccounted, "all_actionable_groups_accounted_for": not unaccounted}
        graph = {"status": "UNRESOLVED_CYCLE" if cyclic_ids else "VALID", "cycle_detected": bool(cyclic_ids), "cyclic_action_ids": sorted(cyclic_ids), "edge_count": sum(len(x) for x in edges.values())}
        quality = {key: 0 for key in self.QUALITY_KEYS}
        if unaccounted:
            quality["aggregate_group_lost"] = len(unaccounted)
        genericity = {key: quality[key] for key in quality if key.endswith("_production_branch")}
        metadata = {"source_aggregate_group_count": len(groups), "planned_action_count": len(actions)}
        diagnostics = ([{"code": "DEPENDENCY_CYCLE", "action_ids": sorted(cyclic_ids)}] if cyclic_ids else []) + ([{"code": "UNACCOUNTED_AGGREGATE_GROUPS", "group_ids": unaccounted}] if unaccounted else [])
        return PrioritizedNextActionPlan("1.0", source_id, metadata, actions, accounting, graph, quality, genericity, diagnostics)

    def _candidate(self, key: Tuple[str, Tuple[str, ...]], groups: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        action_type, hints = key
        ordered = sorted((copy.deepcopy(dict(x)) for x in groups), key=lambda x: str(x.get("group_id") or ""))
        group_ids = self._unique(x.get("group_id") for x in ordered)
        normalized = json.dumps({"action_type": action_type, "dependency_types": hints, "group_ids": group_ids}, sort_keys=True, separators=(",", ":"))
        action_id = "ACT-" + hashlib.sha256(normalized.encode()).hexdigest()[:20].upper()
        title, reason, outcome = self.TEXT.get(action_type, ("Complete the required follow-up action", "One or more upstream aggregate groups require this structured action.", "Allows the affected findings to proceed through their existing evaluation workflow."))
        issue_ids = self._unique(v for x in ordered for v in (x.get("issue_ids") or []))
        requirement_groups = self._unique(v for x in ordered for v in (x.get("requirement_group_ids") or []))
        clauses = self._unique(v for x in ordered for v in (x.get("affected_clauses") or []))
        evidence = self._unique(v for x in ordered for v in (x.get("evidence_refs") or []))
        descriptions = self._unique((x.get("primary_action") or {}).get("description") for x in ordered)
        missing_facts=self._unique(v for x in ordered for v in ((x.get("technical_basis") or {}).get("missing_product_facts") or []))
        criticality=self._unique(v for x in ordered for v in ((x.get("technical_basis") or {}).get("criticality_levels") or []))
        if missing_facts and action_type=="PROVIDE_PRODUCT_INFORMATION":
            title="Provide required product facts: "+", ".join(missing_facts)
            reason="The listed product facts are required to resolve applicability or technical evaluation."
        diagnostic_categories=self._unique(v for x in ordered for v in (x.get("diagnostic_finding_types") or []))
        decision_effects=self._unique(x.get("decision_effect") for x in ordered)
        hierarchy_levels=self._unique(x.get("hierarchy") for x in ordered)
        severity_counts = Counter(self._severity((x.get("severity_summary") or {}).get("highest")) for x in ordered)
        highest = max(severity_counts, key=lambda x: self.SEVERITY_RANK.get(x, 0)) if severity_counts else "UNKNOWN"
        blocking = Counter()
        conclusions = Counter()
        for group in ordered:
            state = group.get("blocking_summary") or {}
            blocking["blocking"] += int(state.get("blocking_count") or 0)
            blocking["non_blocking"] += int(state.get("non_blocking_count") or 0)
            blocking["unknown"] += int(state.get("unknown_count") or 0)
            conclusions.update({str(k): int(v) for k, v in (group.get("conclusion_summary") or {}).items()})
        return {"action_id": action_id, "action_type": action_type, "dependency_types": hints, "title": title, "reason": reason, "expected_outcome": outcome, "source_action_descriptions": descriptions, "group_ids": group_ids, "issue_ids": issue_ids, "requirement_groups": requirement_groups, "clauses": clauses, "evidence": evidence, "issue_count": len(issue_ids), "severity_counts": severity_counts, "highest": highest, "blocking": blocking, "conclusions": dict(sorted(conclusions.items())),"diagnostic_categories":diagnostic_categories,"criticality":criticality,"decision_effects":decision_effects,"hierarchy_levels":hierarchy_levels}

    def _materialize(self, value: Mapping[str, Any], level: PriorityLevel, dependency: ActionDependency) -> PrioritizedAction:
        placement = "Placed after its explicit prerequisite actions." if dependency.depends_on else "Placed using the generic baseline action tier because no structured dependency was supplied."
        counts = value["severity_counts"]
        return PrioritizedAction(value["action_id"], value["action_type"], level, level.name, value["title"], value["reason"], placement, value["expected_outcome"], value["source_action_descriptions"], value["group_ids"], value["issue_ids"], value["requirement_groups"], value["clauses"], value["evidence"], len(value["group_ids"]), value["issue_count"], len(value["requirement_groups"]), len(value["clauses"]), ActionSeveritySummary(value["highest"], counts["CRITICAL"], counts["HIGH"], counts["MEDIUM"], counts["LOW"], counts["INFO"], counts["UNKNOWN"]), ActionBlockingSummary(value["blocking"]["blocking"], value["blocking"]["non_blocking"], value["blocking"]["unknown"]), value["conclusions"], dependency,value["diagnostic_categories"])

    def _levels(self, candidates: Mapping[Any, Mapping[str, Any]], edges: Mapping[str, Set[str]], cyclic: Set[str]) -> Dict[str, PriorityLevel]:
        by_id = {x["action_id"]: x for x in candidates.values()}
        levels = {aid: self.BASELINE_TIER.get(x["action_type"], PriorityLevel.OPTIONAL_OR_REVIEW) for aid, x in by_id.items()}
        for aid,value in by_id.items():
            if "PRIMARY_ROOT_CAUSE" in value.get("hierarchy_levels",[]) and set(value.get("decision_effects",[]))&{"CONFIRMED_TECHNICAL_NONCOMPLIANCE","REPORT_REPLACEMENT_REQUIRED"}:levels[aid]=PriorityLevel.DO_FIRST
            elif "P0_CRITICAL" in value.get("criticality",[]):levels[aid]=PriorityLevel.DO_FIRST
            elif "P1_HIGH" in value.get("criticality",[]) and levels[aid]>PriorityLevel.DO_NEXT:levels[aid]=PriorityLevel.DO_NEXT
        if cyclic:
            return levels
        changed = True
        while changed:
            changed = False
            for action_id in sorted(edges):
                if edges[action_id]:
                    required = min(4, max(int(levels[x]) for x in edges[action_id]) + 1)
                    if required > int(levels[action_id]):
                        levels[action_id] = PriorityLevel(required)
                        changed = True
        return levels

    @staticmethod
    def _cyclic_nodes(edges: Mapping[str, Set[str]]) -> Set[str]:
        visiting: Set[str] = set(); visited: Set[str] = set(); cyclic: Set[str] = set()
        def visit(node: str, trail: List[str]) -> None:
            if node in visiting:
                cyclic.update(trail[trail.index(node):]); return
            if node in visited: return
            visiting.add(node); trail.append(node)
            for parent in sorted(edges.get(node, set())): visit(parent, trail)
            trail.pop(); visiting.remove(node); visited.add(node)
        for node in sorted(edges): visit(node, [])
        return cyclic

    @staticmethod
    def _dependency_hints(group: Mapping[str, Any]) -> List[str]:
        dependency = group.get("dependency") or {}
        values = group.get("depends_on_action_types") or dependency.get("depends_on_action_types") or []
        return sorted({str(v.value if isinstance(v, Enum) else v) for v in values if v is not None})

    @classmethod
    def _severity(cls, value: Any) -> str:
        result = cls._value(value) or "UNKNOWN"
        return result if result in cls.SEVERITY_RANK else "UNKNOWN"

    @staticmethod
    def _unique(values: Iterable[Any]) -> List[str]:
        return sorted({str(v.value if isinstance(v, Enum) else v) for v in values if v is not None and str(v) != ""})

    @staticmethod
    def _value(value: Any) -> Optional[str]:
        return None if value is None else str(value.value if isinstance(value, Enum) else value)

    @classmethod
    def _plain(cls, value: Any) -> Any:
        if isinstance(value, Enum): return value.value
        if is_dataclass(value): return cls._plain(asdict(value))
        if isinstance(value, Mapping): return {str(k): cls._plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)): return [cls._plain(v) for v in value]
        return copy.deepcopy(value)

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def to_dict(cls, plan: PrioritizedNextActionPlan) -> Dict[str, Any]:
        """Convert a plan into JSON-compatible primitives."""
        if not is_dataclass(plan): raise TypeError("prioritized next action plan required")
        return cls._plain(asdict(plan))

    @classmethod
    def to_json(cls, plan: PrioritizedNextActionPlan, indent: int = 2) -> str:
        """Serialize a plan deterministically."""
        return json.dumps(cls.to_dict(plan), ensure_ascii=False, sort_keys=True, indent=indent)

    @classmethod
    def save_json(cls, plan: PrioritizedNextActionPlan, path: Any) -> Path:
        """Write a plan without modifying its source artifact."""
        target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(cls.to_json(plan) + "\n", encoding="utf-8"); return target


__all__ = ["ActionBlockingSummary", "ActionDependency", "ActionSeveritySummary", "GenericNextActionPrioritizer", "PrioritizedAction", "PrioritizedNextActionPlan", "PriorityLevel"]
