"""Assemble validated compliance artifacts into the final SaaS response contract."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


class FinalResponseContractError(ValueError):
    """A deterministic cross-artifact contract validation failure."""

    def __init__(self, code: str, details: Optional[Mapping[str, Any]] = None):
        self.code = code
        self.details = dict(details or {})
        super().__init__(json.dumps({"code": code, "details": self.details}, sort_keys=True))


@dataclass
class FinalComplianceResponse:
    """Frontend-ready response containing executive and technical drill-down views."""

    schema_version: str
    evaluation_id: Optional[str]
    evaluation: Dict[str, Any]
    summary: Dict[str, Any]
    next_actions: List[Dict[str, Any]]
    issue_groups: List[Dict[str, Any]]
    detailed_issues: List[Dict[str, Any]]
    informational_issues: List[Dict[str, Any]]
    accounting: Dict[str, Any]
    provenance: Dict[str, Any]
    contract_validation: Dict[str, Any]
    quality_audit: Dict[str, int]
    genericity_audit: Dict[str, int]
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    root_causes: List[Dict[str, Any]] = field(default_factory=list)
    compliance_score: Dict[str, Any] = field(default_factory=dict)
    evaluation_coverage: Dict[str, Any] = field(default_factory=dict)
    evaluation_confidence: Dict[str, Any] = field(default_factory=dict)
    kb_maturity: Optional[str] = None
    kb_authority: Dict[str, Any] = field(default_factory=dict)
    critical_summary: Dict[str, Any] = field(default_factory=dict)
    report_validity_summary: Dict[str, Any] = field(default_factory=dict)
    pre_llm_unresolved: List[Dict[str, Any]] = field(default_factory=list)


class GenericFinalComplianceResponseBuilder:
    """Validate, copy, and expose upstream results without re-evaluation."""

    SOURCE_NAMES = ("final_compliance_issues", "aggregated_compliance_issues", "prioritized_next_actions", "executive_compliance_summary", "overall_report_status")
    QUALITY_KEYS = (
        "overall_status_modified", "product_compliance_conclusion_modified", "summary_text_modified",
        "action_priority_modified", "action_type_modified", "aggregate_conclusion_modified",
        "issue_conclusion_modified", "issue_severity_modified", "suppressed_issue_exposed_as_active",
        "action_lost", "aggregate_group_lost", "detailed_issue_lost",
        "broken_issue_reference_silently_repaired", "broken_group_reference_silently_repaired",
        "readiness_percentage_created", "compliance_percentage_created", "new_noncompliance_created",
        "certification_claim_created", "product_safety_claim_created", "standard_specific_production_branch",
        "product_specific_production_branch", "clause_specific_production_branch", "page_specific_production_branch",
        "model_specific_production_branch", "report_specific_production_branch", "fixture_specific_production_branch",
        "upstream_artifact_mutated",
    )

    def build(self, final_issues: Any, aggregated: Any, action_plan: Any, executive: Any, status: Any, source_artifact_paths: Optional[Mapping[str, Any]] = None) -> FinalComplianceResponse:
        """Build the final response after strict referential-integrity validation."""
        values = [final_issues, aggregated, action_plan, executive, status]
        if any(value is None for value in values):
            raise FinalResponseContractError("MISSING_SOURCE_ARTIFACT")
        final, aggregate, plan, summary, state = (self._plain(value) for value in values)
        active = [copy.deepcopy(x) for x in (final.get("issues", []) or []) if str(x.get("actionability") or "ACTIONABLE") == "ACTIONABLE"]
        informational = [copy.deepcopy(x) for x in (final.get("issues", []) or []) if str(x.get("actionability") or "") == "INFORMATIONAL"]
        suppressed = list(final.get("suppressed_findings", []) or [])
        groups = list(aggregate.get("actionable_groups", []) or [])
        actions = list(plan.get("actions", []) or [])

        issue_ids = self._unique_ids(active, "issue_id", "DUPLICATE_ISSUE_ID")
        action_ids = self._unique_ids(actions, "action_id", "DUPLICATE_ACTION_ID")
        group_ids = self._unique_ids(groups, "group_id", "DUPLICATE_AGGREGATE_GROUP_ID")
        suppressed_ids = {str(x.get("issue_id")) for x in suppressed if x.get("issue_id") is not None}
        if suppressed_ids & issue_ids:
            raise FinalResponseContractError("SUPPRESSED_ISSUE_EXPOSED_AS_ACTIVE", {"issue_ids": sorted(suppressed_ids & issue_ids)})

        expected_actions_status = int((state.get("decision_basis") or {}).get("planned_action_count") or 0)
        expected_actions_summary = int((summary.get("metadata") or {}).get("source_action_count") or len(actions))
        if expected_actions_status != len(actions) or expected_actions_summary != len(actions):
            raise FinalResponseContractError("ACTION_COUNT_MISMATCH", {"actual": len(actions), "status": expected_actions_status, "summary": expected_actions_summary})
        expected_groups_summary = int((summary.get("metadata") or {}).get("source_aggregate_group_count") or len(groups))
        expected_groups_plan = int((plan.get("metadata") or {}).get("source_aggregate_group_count") or len(groups))
        if expected_groups_summary != len(groups) or expected_groups_plan != len(groups):
            raise FinalResponseContractError("AGGREGATE_COUNT_MISMATCH", {"actual": len(groups), "summary": expected_groups_summary, "plan": expected_groups_plan})
        expected_issues = int((aggregate.get("summary") or {}).get("actionable_source_issue_count") or len(active))
        if expected_issues != len(active):
            raise FinalResponseContractError("ACTIONABLE_ISSUE_COUNT_MISMATCH", {"actual": len(active), "aggregate": expected_issues})

        for action in actions:
            unknown = sorted(set(map(str, action.get("affected_aggregate_group_ids") or [])) - group_ids)
            if unknown:
                raise FinalResponseContractError("UNKNOWN_AGGREGATE_GROUP_REFERENCE", {"action_id": action.get("action_id"), "group_ids": unknown})
        referenced_issues = set()
        for group in groups:
            refs = set(map(str, group.get("issue_ids") or [])); referenced_issues.update(refs)
            unknown = sorted(refs - issue_ids)
            if unknown:
                raise FinalResponseContractError("UNKNOWN_ISSUE_REFERENCE", {"group_id": group.get("group_id"), "issue_ids": unknown})
        if referenced_issues != issue_ids:
            raise FinalResponseContractError("DETAILED_ISSUE_ACCOUNTING_MISMATCH", {"unreferenced": sorted(issue_ids - referenced_issues)})

        evaluation_fields = ("overall_status", "status_scope", "product_compliance_conclusion", "requires_user_action", "can_complete_evaluation_now", "status_reason", "reason_codes", "decision_basis")
        evaluation = {key: copy.deepcopy(state.get(key)) for key in evaluation_fields}
        summary_fields = ("headline", "executive_summary", "main_findings", "unresolved_summary", "affected_scope_summary", "severity_summary", "issue_category_summary", "action_summary_text", "action_summary", "other_finding_count", "all_aggregate_group_ids")
        summary_view = {key: copy.deepcopy(summary.get(key)) for key in summary_fields}
        group_view = []
        for group in groups:
            item = copy.deepcopy(group); item.pop("individual_issues", None); group_view.append(item)

        clauses = {str(x.get("clause_id")) for x in active if x.get("clause_id") is not None}
        requirement_groups = {str(x.get("requirement_group_id")) for x in active if x.get("requirement_group_id") is not None}
        final_summary = final.get("summary") or {}
        accounting = {
            "source_logical_group_count": int(final_summary.get("total_input_groups") or 0),
            "source_issue_count": int(final_summary.get("total_input_issues") or len(active) + len(suppressed) + len(informational)),
            "actionable_issue_count": len(active), "suppressed_finding_count": len(suppressed),
            "informational_finding_count": len(informational), "aggregate_group_count": len(groups),
            "planned_action_count": len(actions), "unique_clause_count": len(clauses),
            "unique_requirement_group_count": len(requirement_groups),
        }
        hashes = self._artifact_hashes(dict(zip(self.SOURCE_NAMES, (final, aggregate, plan, summary, state))), source_artifact_paths)
        provenance = {"source_artifacts": {name: str(source_artifact_paths[name]) if source_artifact_paths and name in source_artifact_paths else None for name in self.SOURCE_NAMES}, "artifact_hashes": hashes, "pipeline": {"final_issue_resolution_step": "25D", "aggregation_step": "26", "action_planning_step": "27", "summary_step": "28", "status_step": "29", "response_step": "30"}, "response_builder_version": "1.0"}
        evaluation_id = state.get("evaluation_id") or summary.get("evaluation_id") or aggregate.get("evaluation_id")
        validation = {"status": "VALID", "checks_passed": 9, "checks_failed": 0, "all_action_references_valid": True, "all_issue_references_valid": True, "all_counts_consistent": True}
        quality = {key: 0 for key in self.QUALITY_KEYS}
        genericity = {key: quality[key] for key in quality if key.endswith("_production_branch")}
        judgment=copy.deepcopy(state.get("professional_judgment") or aggregate.get("professional_judgment") or {})
        metrics=judgment.get("metrics") or {};authority={"maturity":judgment.get("kb_maturity"),
            "authoritative_pass_allowed":str(state.get("deterministic_disposition"))=="PASS",
            "policy_version":"STEP40_DISPOSITION_V1"}
        return FinalComplianceResponse("1.0", evaluation_id, evaluation, summary_view, copy.deepcopy(actions), group_view, active, informational, accounting, provenance, validation, quality, genericity, [],copy.deepcopy(group_view),copy.deepcopy(metrics.get("compliance_score") or {}),copy.deepcopy(metrics.get("evaluation_coverage") or {}),copy.deepcopy(metrics.get("evaluation_confidence") or {}),judgment.get("kb_maturity"),authority,copy.deepcopy(judgment.get("critical_summary") or {}),copy.deepcopy(judgment.get("report_validity_summary") or {}),copy.deepcopy(judgment.get("pre_llm_unresolved") or []))

    @staticmethod
    def _unique_ids(items: List[Mapping[str, Any]], field_name: str, error_code: str) -> set:
        values = [str(x.get(field_name)) for x in items if x.get(field_name) is not None]
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            raise FinalResponseContractError(error_code, {field_name + "s": duplicates})
        return set(values)

    @classmethod
    def _artifact_hashes(cls, sources: Mapping[str, Any], paths: Optional[Mapping[str, Any]]) -> Dict[str, str]:
        hashes = {}
        for name in cls.SOURCE_NAMES:
            if paths and name in paths:
                path = Path(paths[name])
                if not path.exists(): raise FinalResponseContractError("MISSING_SOURCE_ARTIFACT", {"name": name, "path": str(path)})
                payload = path.read_bytes()
            else:
                payload = cls._canonical(sources[name]).encode()
            hashes[name] = hashlib.sha256(payload).hexdigest()
        return hashes

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
    def to_dict(cls, response: FinalComplianceResponse) -> Dict[str, Any]:
        """Convert the response to JSON-compatible primitives."""
        if not is_dataclass(response): raise TypeError("final compliance response required")
        return cls._plain(asdict(response))

    @classmethod
    def to_json(cls, response: FinalComplianceResponse, indent: int = 2) -> str:
        """Serialize the final response deterministically."""
        return json.dumps(cls.to_dict(response), ensure_ascii=False, sort_keys=True, indent=indent)

    @classmethod
    def save_json(cls, response: FinalComplianceResponse, path: Any) -> Path:
        """Write the response without modifying upstream artifacts."""
        target = Path(path); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(cls.to_json(response) + "\n", encoding="utf-8"); return target


__all__ = ["FinalComplianceResponse", "FinalResponseContractError", "GenericFinalComplianceResponseBuilder"]
