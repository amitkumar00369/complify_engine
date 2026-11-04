"""Independent schemas for a future effective IEC knowledge base."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from iec_parser.generic_iec_kb_models import (
    ApplicabilityRule, DeltaOperationDirective, ExternalReference, NumericLimit, RequirementType,
    RequirementSemanticType, SerializableModel, StandardDocument, StandardTable,
    ExecutableTechnicalRule, TechnicalConstraint,
    KBMaturityMetadata, RequirementCriticality, RequirementDecisionEffect,
)


class _StringEnum(str, Enum):
    """JSON-friendly enumeration base."""


class EffectiveStatus(_StringEnum):
    """Whether effective content participates in later evaluation."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class EffectiveSourceType(_StringEnum):
    """Origin and semantic role of effective content."""

    BASE = "BASE"
    PART_2_ADDITION = "PART_2_ADDITION"
    PART_2_MODIFICATION = "PART_2_MODIFICATION"
    PART_2_REPLACEMENT = "PART_2_REPLACEMENT"
    PART_2_NEW_REQUIREMENT = "PART_2_NEW_REQUIREMENT"
    PART_2_NOT_APPLICABLE = "PART_2_NOT_APPLICABLE"
    COMBINED = "COMBINED"


class EffectiveBuildStatus(_StringEnum):
    """Overall completeness state of a future effective artifact."""

    VALID = "VALID"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class EffectiveOperationType(_StringEnum):
    """Supported Part 2 operations recorded on effective content."""

    APPLICABLE = "APPLICABLE"
    APPLICABLE_EXCEPT = "APPLICABLE_EXCEPT"
    ADDITION = "ADDITION"
    MODIFICATION = "MODIFICATION"
    REPLACEMENT = "REPLACEMENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NEW_REQUIREMENT = "NEW_REQUIREMENT"
    UNRESOLVED = "UNRESOLVED"


@dataclass
class EffectiveSourceReference(SerializableModel):
    """Trace one effective object to an immutable Base or Delta source."""

    standard_id: Optional[str] = None
    standard_number: Optional[str] = None
    clause_id: Optional[str] = None
    requirement_id: Optional[str] = None
    annex_id: Optional[str] = None
    definition_id: Optional[str] = None
    relationship_type: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None


@dataclass
class EffectiveRequirement(SerializableModel):
    """Requirement plus deterministic identity, state, and source provenance."""

    effective_requirement_id: str
    clause_id: str
    text: str
    requirement_type: RequirementType
    normative: bool
    applicability: ApplicabilityRule
    effective_status: EffectiveStatus
    effective_source_type: EffectiveSourceType
    condition_text: Optional[str] = None
    test_method: Optional[Union[Dict[str, Any], str]] = None
    limits: List[NumericLimit] = field(default_factory=list)
    technical_constraints: List[TechnicalConstraint] = field(default_factory=list)
    references: List[Any] = field(default_factory=list)
    base_sources: List[EffectiveSourceReference] = field(default_factory=list)
    delta_sources: List[EffectiveSourceReference] = field(default_factory=list)
    supersedes: List[EffectiveSourceReference] = field(default_factory=list)
    superseded_by: Optional[str] = None
    review_reason: Optional[str] = None
    semantic_type: RequirementSemanticType = RequirementSemanticType.REQUIREMENT
    executable_rules: List[ExecutableTechnicalRule] = field(default_factory=list)
    criticality: Optional[RequirementCriticality] = None
    decision_effect: Optional[RequirementDecisionEffect] = None

    def __post_init__(self) -> None:
        """Own independent copies of all reused Base/Delta structures."""

        self.applicability = copy.deepcopy(self.applicability)
        self.test_method = copy.deepcopy(self.test_method)
        self.limits = copy.deepcopy(self.limits)
        self.technical_constraints = copy.deepcopy(self.technical_constraints)
        self.references = copy.deepcopy(self.references)
        self.base_sources = copy.deepcopy(self.base_sources)
        self.delta_sources = copy.deepcopy(self.delta_sources)
        self.supersedes = copy.deepcopy(self.supersedes)
        self.executable_rules = copy.deepcopy(self.executable_rules)
        self.criticality = copy.deepcopy(self.criticality)


@dataclass
class EffectiveOperation(SerializableModel):
    """One auditable Part 2 operation applied to effective content."""

    operation_type: EffectiveOperationType
    delta_standard_id: Optional[str] = None
    delta_clause_id: Optional[str] = None
    target_base_clause_id: Optional[str] = None
    status: EffectiveStatus = EffectiveStatus.ACTIVE
    notes: Optional[str] = None
    directive: Optional[DeltaOperationDirective] = None


@dataclass
class EffectiveClause(SerializableModel):
    """Clause container retaining active state and both source lineages."""

    effective_clause_id: str
    clause_id: str
    effective_status: EffectiveStatus
    title: Optional[str] = None
    base_sources: List[EffectiveSourceReference] = field(default_factory=list)
    delta_sources: List[EffectiveSourceReference] = field(default_factory=list)
    applied_operations: List[EffectiveOperation] = field(default_factory=list)
    requirements: List[EffectiveRequirement] = field(default_factory=list)
    children: List["EffectiveClause"] = field(default_factory=list)
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    raw_text: Optional[str] = None
    review_reason: Optional[str] = None


@dataclass
class EffectiveDefinition(SerializableModel):
    """Definition with effective state and replacement provenance."""

    effective_definition_id: str
    term: str
    definition: str
    clause_id: Optional[str]
    effective_status: EffectiveStatus
    effective_source_type: EffectiveSourceType
    base_sources: List[EffectiveSourceReference] = field(default_factory=list)
    delta_sources: List[EffectiveSourceReference] = field(default_factory=list)
    supersedes: List[EffectiveSourceReference] = field(default_factory=list)
    review_reason: Optional[str] = None


@dataclass
class EffectiveAnnex(SerializableModel):
    """Effective annex that remains separate from the main clause namespace."""

    effective_annex_id: str
    annex_id: str
    normative: bool
    effective_status: EffectiveStatus
    title: Optional[str] = None
    base_sources: List[EffectiveSourceReference] = field(default_factory=list)
    delta_sources: List[EffectiveSourceReference] = field(default_factory=list)
    requirements: List[EffectiveRequirement] = field(default_factory=list)
    applied_operations: List[EffectiveOperation] = field(default_factory=list)
    clauses: List[EffectiveClause] = field(default_factory=list)
    review_reason: Optional[str] = None


@dataclass
class EffectiveKnowledgeBase(SerializableModel):
    """Schema-only representation for a future effective knowledge base."""

    schema_version: str
    effective_kb_id: str
    base_standard: StandardDocument
    delta_standard: Optional[StandardDocument]
    build_status: EffectiveBuildStatus
    clauses: List[EffectiveClause] = field(default_factory=list)
    annexes: List[EffectiveAnnex] = field(default_factory=list)
    tables: List[StandardTable] = field(default_factory=list)
    definitions: List[EffectiveDefinition] = field(default_factory=list)
    references: List[ExternalReference] = field(default_factory=list)
    unresolved_operations: List[Any] = field(default_factory=list)
    maturity: KBMaturityMetadata = field(default_factory=KBMaturityMetadata)


__all__ = [
    "EffectiveAnnex", "EffectiveBuildStatus", "EffectiveClause",
    "EffectiveDefinition", "EffectiveKnowledgeBase", "EffectiveOperation",
    "EffectiveOperationType",
    "EffectiveRequirement", "EffectiveSourceReference", "EffectiveSourceType",
    "EffectiveStatus",
]
