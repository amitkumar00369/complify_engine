"""Serializable models for the deterministic Step 32-A reference layer."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ResolutionIntegrity:
    status: str = "COMPLETE"
    all_required_references_resolved: bool = True
    missing_references: List[Dict[str, Any]] = field(default_factory=list)
    ambiguous_references: List[Dict[str, Any]] = field(default_factory=list)
    duplicate_ids: List[Dict[str, Any]] = field(default_factory=list)
    cross_scope_conflicts: List[Dict[str, Any]] = field(default_factory=list)
    artifact_availability: Dict[str, str] = field(default_factory=dict)


@dataclass
class ResolvedComplianceContext:
    context_id: str
    final_issue_id: str
    clause_id: Optional[str]
    final_issue: Dict[str, Any]
    originating_issue: Optional[Dict[str, Any]] = None
    originating_issue_resolution: str = "UNAVAILABLE"
    requirement_group: Optional[Dict[str, Any]] = None
    requirements: List[Dict[str, Any]] = field(default_factory=list)
    report_evidence: List[Dict[str, Any]] = field(default_factory=list)
    evidence_resolution: List[Dict[str, Any]] = field(default_factory=list)
    product_facts: List[Dict[str, Any]] = field(default_factory=list)
    product_identity: List[Dict[str, Any]] = field(default_factory=list)
    applicability_results: List[Dict[str, Any]] = field(default_factory=list)
    technical_results: List[Dict[str, Any]] = field(default_factory=list)
    na_results: List[Dict[str, Any]] = field(default_factory=list)
    scope_results: List[Dict[str, Any]] = field(default_factory=list)
    final_requirement_decisions: List[Dict[str, Any]] = field(default_factory=list)
    aggregate_context: List[Dict[str, Any]] = field(default_factory=list)
    action_context: List[Dict[str, Any]] = field(default_factory=list)
    source_provenance: Dict[str, Any] = field(default_factory=dict)
    resolution_integrity: ResolutionIntegrity = field(default_factory=ResolutionIntegrity)


@dataclass
class ResolvedComplianceContextBundle:
    schema_version: str
    run_id: Optional[str]
    generated_from: Dict[str, Any]
    accounting: Dict[str, Any]
    contexts: List[ResolvedComplianceContext]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


__all__ = ["ResolutionIntegrity", "ResolvedComplianceContext", "ResolvedComplianceContextBundle"]
