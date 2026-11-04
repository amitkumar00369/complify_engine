"""Conservative schemas for generic cross-evidence consistency findings."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class _StringEnum(str, Enum): pass


class ConsistencyFindingType(_StringEnum):
    IDENTITY_CONFLICT="IDENTITY_CONFLICT"
    IDENTITY_RELATIONSHIP_UNRESOLVED="IDENTITY_RELATIONSHIP_UNRESOLVED"
    RATING_CONFLICT="RATING_CONFLICT"
    TEST_CONDITION_MISMATCH="TEST_CONDITION_MISMATCH"
    VALUE_CONFLICT="VALUE_CONFLICT"
    CALCULATION_MISMATCH="CALCULATION_MISMATCH"
    LIMIT_EXCEEDED="LIMIT_EXCEEDED"
    VERDICT_CONFLICT="VERDICT_CONFLICT"
    APPLICABILITY_EXECUTION_CONFLICT="APPLICABILITY_EXECUTION_CONFLICT"
    MODEL_SCOPE_CONFLICT="MODEL_SCOPE_CONFLICT"
    SAMPLE_SCOPE_CONFLICT="SAMPLE_SCOPE_CONFLICT"
    PRODUCT_CONTEXT_CONFLICT="PRODUCT_CONTEXT_CONFLICT"
    UNIT_OR_PARAMETER_AMBIGUITY="UNIT_OR_PARAMETER_AMBIGUITY"


class ConsistencyStatus(_StringEnum):
    CONSISTENT="CONSISTENT";RECONCILED="RECONCILED";MATERIAL_CONFLICT="MATERIAL_CONFLICT"
    UNRESOLVED="UNRESOLVED";NOT_COMPARABLE="NOT_COMPARABLE"


class ParameterSemanticRole(_StringEnum):
    """Meaning of a value independent from its physical document position."""

    DECLARED="DECLARED";TEST_BASIS="TEST_BASIS";APPLIED="APPLIED"
    MEASURED="MEASURED";CALCULATED="CALCULATED";LIMIT="LIMIT"
    REFERENCE="REFERENCE";UNKNOWN_ROLE="UNKNOWN_ROLE"


class ParameterReconciliationStatus(_StringEnum):
    CONSISTENT="CONSISTENT";CONFLICTING="CONFLICTING"
    INSUFFICIENT_EVIDENCE="INSUFFICIENT_EVIDENCE"
    NOT_COMPARABLE="NOT_COMPARABLE"
    ROLE_COMPATIBLE_VARIATION="ROLE_COMPATIBLE_VARIATION"


@dataclass
class CanonicalParameterObservation:
    """One provenance-preserving value in the canonical parameter view."""

    observation_id: str
    canonical_parameter: str
    raw_parameter_text: Optional[str] = None
    raw_value: Any = None
    normalized_value: Any = None
    unit: Optional[str] = None
    normalized_unit: Optional[str] = None
    semantic_role: ParameterSemanticRole = ParameterSemanticRole.UNKNOWN_ROLE
    source_type: str = "UNKNOWN"
    source_page: Optional[int] = None
    source_clause: Optional[str] = None
    source_location: Optional[str] = None
    evidence_id: Optional[str] = None
    product_scope: Optional[str] = None
    model_scope: List[str] = field(default_factory=list)
    sample_scope: Optional[str] = None
    test_family: Optional[str] = None
    test_phase: Optional[str] = None
    conditioning_state: Optional[str] = None
    confidence: float = 0.0
    normalization_confidence: float = 0.0
    ownership_confidence: float = 0.0
    physical_clause: Optional[str] = None
    evidence_owner_id: Optional[str] = None
    ownership_basis: List[str] = field(default_factory=list)
    component_scope: Optional[str] = None
    evidence_status: str = "UNASSESSED"
    requirement_ids: List[str] = field(default_factory=list)
    formula_operand_links: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class CanonicalParameterLedgerEntry:
    """All bounded observations and their non-compliance reconciliation."""

    canonical_parameter: str
    observations: List[CanonicalParameterObservation] = field(default_factory=list)
    reconciliation_status: ParameterReconciliationStatus = ParameterReconciliationStatus.INSUFFICIENT_EVIDENCE
    findings: List[Dict[str, Any]] = field(default_factory=list)
    semantic_relationships: List[Dict[str, Any]] = field(default_factory=list)
    authority_state: str = "UNRESOLVED"
    comparability_state: str = "INSUFFICIENT_CONTEXT"
    formula_operand_links: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ConsistencyObservation:
    value: Any = None
    normalized_value: Any = None
    unit: Optional[str] = None
    role: Optional[str] = None
    source_evidence_ids: List[str] = field(default_factory=list)
    source_context: Optional[str] = None
    page_refs: List[int] = field(default_factory=list)


@dataclass
class ConsistencyFinding:
    finding_id: str
    finding_type: ConsistencyFindingType
    status: ConsistencyStatus
    materiality: str
    subject: Dict[str, Any]
    observations: List[ConsistencyObservation]
    comparison: Dict[str, Any]
    reconciliation: Dict[str, Any]
    effect: Dict[str, Any]
    severity_hint: Optional[str] = None
    product_fact_ids: List[str] = field(default_factory=list)
    product_identity_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    requirement_ids: List[str] = field(default_factory=list)
    requirement_group_ids: List[str] = field(default_factory=list)
    clause_ids: List[str] = field(default_factory=list)
    standard_semantic_ids: List[str] = field(default_factory=list)


@dataclass
class CrossEvidenceConsistencyResult:
    schema_version: str
    result_id: str
    findings: List[ConsistencyFinding] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    quality_audit: Dict[str, int] = field(default_factory=dict)
    parameter_ledger: List[CanonicalParameterLedgerEntry] = field(default_factory=list)

    def to_dict(self): return asdict(self)
    def to_json(self, indent=2): return json.dumps(self.to_dict(),ensure_ascii=False,sort_keys=True,indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CrossEvidenceConsistencyResult":
        """Load current or older compatible consistency artifacts."""
        findings = []
        for raw in data.get("findings", []) or []:
            item = dict(raw)
            item["finding_type"] = ConsistencyFindingType(item["finding_type"])
            item["status"] = ConsistencyStatus(item["status"])
            item["observations"] = [ConsistencyObservation(**value) for value in item.get("observations", [])]
            findings.append(ConsistencyFinding(**item))
        return cls(
            schema_version=str(data.get("schema_version", "1.0")),
            result_id=str(data.get("result_id", "")),
            findings=findings,
            summary=dict(data.get("summary", {}) or {}),
            diagnostics=list(data.get("diagnostics", []) or []),
            quality_audit=dict(data.get("quality_audit", {}) or {}),
            parameter_ledger=[CanonicalParameterLedgerEntry(
                canonical_parameter=str(entry.get("canonical_parameter", "")),
                observations=[CanonicalParameterObservation(
                    **{**dict(observation), "semantic_role": ParameterSemanticRole(
                        observation.get("semantic_role", "UNKNOWN_ROLE"))}
                ) for observation in entry.get("observations", []) or []],
                reconciliation_status=ParameterReconciliationStatus(
                    entry.get("reconciliation_status", "INSUFFICIENT_EVIDENCE")),
                findings=list(entry.get("findings", []) or []),
                semantic_relationships=list(entry.get("semantic_relationships", []) or []),
                authority_state=str(entry.get("authority_state", "UNRESOLVED")),
                comparability_state=str(entry.get("comparability_state", "INSUFFICIENT_CONTEXT")),
                formula_operand_links=list(entry.get("formula_operand_links", []) or []),
            ) for entry in data.get("parameter_ledger", []) or []],
        )


__all__=["CanonicalParameterLedgerEntry","CanonicalParameterObservation","ConsistencyFindingType","ConsistencyStatus","ConsistencyObservation","ConsistencyFinding","CrossEvidenceConsistencyResult","ParameterReconciliationStatus","ParameterSemanticRole"]
