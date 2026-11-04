"""Generic, dependency-free data models for IEC knowledge bases."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class _StringEnum(str, Enum):
    """Base class for JSON-friendly string enumerations."""


class DocumentType(_StringEnum):
    """Role of a standards document in a standards family."""

    BASE = "BASE"
    PART_2 = "PART_2"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class RelationshipType(_StringEnum):
    """Relationship between a clause and its parent-standard clause."""

    NONE = "NONE"
    APPLICABLE = "APPLICABLE"
    APPLICABLE_EXCEPT = "APPLICABLE_EXCEPT"
    ADDITION = "ADDITION"
    MODIFICATION = "MODIFICATION"
    REPLACEMENT = "REPLACEMENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NEW_REQUIREMENT = "NEW_REQUIREMENT"
    UNRESOLVED = "UNRESOLVED"


class OperationQualifierType(_StringEnum):
    """Meaning of an optional qualifier on a Delta operation directive."""

    NONE = "NONE"
    CONDITION = "CONDITION"
    TARGET = "TARGET"


class OperationTargetScope(_StringEnum):
    """Structural scope addressed by a Delta operation directive."""

    WHOLE_CLAUSE = "WHOLE_CLAUSE"
    CLAUSE = "CLAUSE"
    TABLE = "TABLE"
    PARTIAL_CONTENT = "PARTIAL_CONTENT"
    UNKNOWN_TARGET = "UNKNOWN_TARGET"


class ApplicabilityStatus(_StringEnum):
    """Resolution state of an applicability rule."""

    ALWAYS = "ALWAYS"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ApplicabilityEffect(_StringEnum):
    """Meaning of a satisfied applicability condition."""

    APPLIES = "APPLIES"
    DOES_NOT_APPLY = "DOES_NOT_APPLY"


class RequirementSemanticType(_StringEnum):
    """Normative semantic carried by a requirement statement."""

    REQUIREMENT = "REQUIREMENT"
    EXCLUSION = "EXCLUSION"
    CONDITIONAL_EXCLUSION = "CONDITIONAL_EXCLUSION"
    PROHIBITION = "PROHIBITION"


class RequirementType(_StringEnum):
    """Broad semantic category of a requirement."""

    GENERAL = "GENERAL"
    CONDITIONAL = "CONDITIONAL"
    TEST = "TEST"
    LIMIT = "LIMIT"
    MARKING = "MARKING"
    INSTRUCTION = "INSTRUCTION"
    CONSTRUCTION = "CONSTRUCTION"
    SAFETY = "SAFETY"
    INFORMATIVE = "INFORMATIVE"
    UNKNOWN = "UNKNOWN"


class ClauseType(_StringEnum):
    """Normative status of a clause."""

    NORMATIVE = "NORMATIVE"
    INFORMATIVE = "INFORMATIVE"
    VOID = "VOID"
    UNKNOWN = "UNKNOWN"


class ConstraintType(_StringEnum):
    """Semantic kind of an extracted technical constraint."""

    SIMPLE_LIMIT = "SIMPLE_LIMIT"
    RANGE = "RANGE"
    MINIMUM = "MINIMUM"
    MAXIMUM = "MAXIMUM"
    EXACT = "EXACT"
    TOLERANCE = "TOLERANCE"
    COMPOUND = "COMPOUND"
    FORMULA = "FORMULA"
    TEST_PARAMETER = "TEST_PARAMETER"
    TIME_LIMIT = "TIME_LIMIT"
    DISTANCE_LIMIT = "DISTANCE_LIMIT"
    TEMPERATURE_LIMIT = "TEMPERATURE_LIMIT"
    CURRENT_LIMIT = "CURRENT_LIMIT"
    VOLTAGE_LIMIT = "VOLTAGE_LIMIT"
    POWER_LIMIT = "POWER_LIMIT"
    SPEED_LIMIT = "SPEED_LIMIT"
    FLOW_LIMIT = "FLOW_LIMIT"
    FORCE_LIMIT = "FORCE_LIMIT"
    COUNT_LIMIT = "COUNT_LIMIT"
    PERCENTAGE_LIMIT = "PERCENTAGE_LIMIT"
    OTHER = "OTHER"


class ConstraintStatus(_StringEnum):
    """Resolution state of an extracted technical constraint."""

    RESOLVED = "RESOLVED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    UNRESOLVED = "UNRESOLVED"


class TechnicalRuleFamily(_StringEnum):
    NUMERIC_LIMIT="NUMERIC_LIMIT";RANGE_TOLERANCE="RANGE_TOLERANCE"
    PRESENCE_ABSENCE="PRESENCE_ABSENCE";CLASSIFICATION="CLASSIFICATION"
    CONDITIONAL="CONDITIONAL";SEQUENCE_ENDURANCE="SEQUENCE_ENDURANCE"
    DIMENSION="DIMENSION";QUALITATIVE_OBSERVATION="QUALITATIVE_OBSERVATION"
    CROSS_CLAUSE="CROSS_CLAUSE";COMPONENT_COMPLIANCE="COMPONENT_COMPLIANCE"
    UNSUPPORTED="UNSUPPORTED"


class RequirementCriticalityLevel(_StringEnum):
    P0_CRITICAL = "P0_CRITICAL"
    P1_HIGH = "P1_HIGH"
    P2_NORMAL = "P2_NORMAL"
    CONTROL = "CONTROL"


class RequirementDecisionEffect(_StringEnum):
    BLOCKING = "BLOCKING"
    MATERIAL = "MATERIAL"
    NON_BLOCKING = "NON_BLOCKING"
    INFORMATIONAL = "INFORMATIONAL"


class CriticalitySource(_StringEnum):
    REVIEWED_KB_METADATA = "REVIEWED_KB_METADATA"
    STANDARD_METADATA = "STANDARD_METADATA"
    AUTHORIZED_OVERRIDE = "AUTHORIZED_OVERRIDE"


class CriticalityReviewStatus(_StringEnum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"


class KBMaturityState(_StringEnum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    PRODUCTION = "PRODUCTION"


class SerializableModel:
    """Supply recursive dictionary and JSON serialization for models."""

    def to_dict(self) -> Dict[str, Any]:
        """Return a recursively serialized dictionary."""

        return asdict(self)  # type: ignore[arg-type]

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON representation of this model."""

        return json.dumps(self.to_dict(), **kwargs)

    def dict(self) -> Dict[str, Any]:
        """Compatibility alias for dictionary serialization."""

        return self.to_dict()

    def json(self, **kwargs: Any) -> str:
        """Compatibility alias for JSON serialization."""

        return self.to_json(**kwargs)

    def model_dump(self) -> Dict[str, Any]:
        """Compatibility alias matching modern model APIs."""

        return self.to_dict()

    def model_dump_json(self, **kwargs: Any) -> str:
        """Compatibility alias matching modern model APIs."""

        return self.to_json(**kwargs)


@dataclass
class RequirementCriticality(SerializableModel):
    """Explicit reviewed metadata; never inferred from requirement prose."""

    level: RequirementCriticalityLevel
    source: CriticalitySource
    review_status: CriticalityReviewStatus
    rationale: Optional[str] = None
    reviewer: Optional[str] = None
    review_date: Optional[str] = None
    metadata_version: Optional[str] = None


@dataclass
class KBMaturityMetadata(SerializableModel):
    """Authority metadata kept independent from semantic coverage."""

    state: KBMaturityState = KBMaturityState.DRAFT
    provenance: List[Dict[str, Any]] = field(default_factory=list)
    review_scope: List[str] = field(default_factory=list)
    reviewed_requirement_ids: List[str] = field(default_factory=list)
    reviewer: Optional[str] = None
    review_date: Optional[str] = None
    version: Optional[str] = None
    build_id: Optional[str] = None
    limitations: List[str] = field(default_factory=list)


@dataclass
class ExecutableTechnicalRule(SerializableModel):
    """Generic executable metadata compiled from one atomic requirement."""

    rule_id: str
    rule_family: TechnicalRuleFamily
    source_requirement_id: str
    source_clause: Optional[str] = None
    parameter: Optional[str] = None
    operator: Optional[str] = None
    expected_value: Any = None
    minimum: Any = None
    maximum: Any = None
    tolerance: Any = None
    unit: Optional[str] = None
    formula: Optional[Dict[str, Any]] = None
    required_operands: List[str] = field(default_factory=list)
    required_product_facts: List[str] = field(default_factory=list)
    required_evidence_type: Optional[str] = None
    test_family: Optional[str] = None
    test_phase: Optional[str] = None
    conditioning_state: Optional[str] = None
    cross_clause_dependencies: List[str] = field(default_factory=list)
    component_dependency: Optional[Dict[str, Any]] = None
    applicability_condition: Optional[Dict[str, Any]] = None
    result_semantics: Optional[Dict[str, Any]] = None
    logic_group: str = "ALL_OF"
    provenance: List[Dict[str, Any]] = field(default_factory=list)
    supported: bool = True
    unsupported_reason: Optional[str] = None


@dataclass
class StandardDocument(SerializableModel):
    """Metadata identifying a standards document."""

    document_type: DocumentType
    standard_id: Optional[str] = None
    standard_number: Optional[str] = None
    title: Optional[str] = None
    edition: Optional[str] = None
    year: Optional[int] = None
    part_number: Optional[str] = None
    parent_standard: Optional[str] = None
    language: Optional[str] = None
    maturity: KBMaturityMetadata = field(default_factory=KBMaturityMetadata)


@dataclass
class SourceReference(SerializableModel):
    """Location and original text associated with extracted content."""

    page_start: Optional[int] = None
    page_end: Optional[int] = None
    raw_text: Optional[str] = None


@dataclass
class DeltaOperationDirective(SerializableModel):
    """Structured, source-preserving interpretation of a Delta directive."""

    raw_text: str
    qualifier_type: OperationQualifierType = OperationQualifierType.NONE
    qualifier_text: Optional[str] = None
    target_scope: OperationTargetScope = OperationTargetScope.WHOLE_CLAUSE
    target_text: Optional[str] = None
    preposition: Optional[str] = None


@dataclass
class ParentRelationship(SerializableModel):
    """How content relates to a clause in a parent document."""

    type: RelationshipType
    parent_clause_id: Optional[str] = None
    notes: Optional[str] = None
    directive: Optional[DeltaOperationDirective] = None


@dataclass
class ApplicabilityRule(SerializableModel):
    """Explicit applicability state and machine-readable condition data."""

    status: ApplicabilityStatus
    condition_text: Optional[str] = None
    logic: Optional[Dict[str, Any]] = None
    unresolved_features: List[str] = field(default_factory=list)
    effect: ApplicabilityEffect = ApplicabilityEffect.APPLIES
    scope: Optional[Dict[str, Any]] = None


NumericValue = Union[int, float, str]


@dataclass
class NumericLimit(SerializableModel):
    """A structured numeric or textual constraint."""

    parameter: Optional[str] = None
    operator: Optional[str] = None
    value: Optional[NumericValue] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    unit: Optional[str] = None
    tolerance: Optional[NumericValue] = None
    raw_text: Optional[str] = None
    table_reference: Optional[str] = None


@dataclass
class TechnicalConstraint(SerializableModel):
    """A traceable technical limit, formula, or test parameter."""

    constraint_id: str
    parameter: Optional[str] = None
    parameter_text: Optional[str] = None
    operator: Optional[str] = None
    value: Optional[NumericValue] = None
    value_secondary: Optional[NumericValue] = None
    unit: Optional[str] = None
    unit_normalized: Optional[str] = None
    tolerance: Optional[Dict[str, Any]] = None
    expression: Optional[Dict[str, Any]] = None
    condition_text: Optional[str] = None
    raw_text: Optional[str] = None
    constraint_type: ConstraintType = ConstraintType.OTHER
    status: ConstraintStatus = ConstraintStatus.UNRESOLVED
    source_requirement_id: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class Requirement(SerializableModel):
    """An individual normative or informative statement."""

    requirement_id: str
    text: str
    requirement_type: RequirementType
    normative: bool
    applicability: ApplicabilityRule
    condition_text: Optional[str] = None
    test_method: Optional[Union[Dict[str, Any], str]] = None
    limits: List[NumericLimit] = field(default_factory=list)
    references: List[Any] = field(default_factory=list)
    technical_constraints: List[TechnicalConstraint] = field(default_factory=list)
    semantic_type: RequirementSemanticType = RequirementSemanticType.REQUIREMENT
    executable_rules: List[ExecutableTechnicalRule] = field(default_factory=list)
    criticality: Optional[RequirementCriticality] = None
    decision_effect: Optional[RequirementDecisionEffect] = None


@dataclass
class Clause(SerializableModel):
    """A standards clause containing requirements and child clauses."""

    clause_id: str
    clause_type: ClauseType
    source: SourceReference
    relationship_to_parent: ParentRelationship
    title: Optional[str] = None
    requirements: List[Requirement] = field(default_factory=list)
    children: List[Clause] = field(default_factory=list)


@dataclass
class Annex(SerializableModel):
    """An annex and its requirements."""

    annex_id: str
    normative: bool
    source: SourceReference
    applicability: ApplicabilityRule
    title: Optional[str] = None
    requirements: List[Requirement] = field(default_factory=list)
    clauses: List[Clause] = field(default_factory=list)


@dataclass
class StandardTable(SerializableModel):
    """A table preserved as raw and optionally structured data."""

    table_id: str
    source: SourceReference
    title: Optional[str] = None
    raw_text: Optional[str] = None
    structured_data: Optional[Union[Dict[str, Any], List[Any]]] = None


@dataclass
class Definition(SerializableModel):
    """A term definition from a standards document."""

    term: str
    definition: str
    source: SourceReference
    clause_id: Optional[str] = None
    relationship_to_parent: ParentRelationship = field(
        default_factory=lambda: ParentRelationship(type=RelationshipType.NONE)
    )


@dataclass
class ExternalReference(SerializableModel):
    """A reference to another clause, standard, or external resource."""

    target: str
    reference_type: Optional[str] = None
    source_clause_id: Optional[str] = None
    raw_text: Optional[str] = None


@dataclass
class KnowledgeBase(SerializableModel):
    """Complete generic representation of a standards knowledge base."""

    document: StandardDocument
    schema_version: str = "1.0"
    clauses: List[Clause] = field(default_factory=list)
    annexes: List[Annex] = field(default_factory=list)
    tables: List[StandardTable] = field(default_factory=list)
    definitions: List[Definition] = field(default_factory=list)
    references: List[ExternalReference] = field(default_factory=list)
