"""Generic, traceable product-profile schemas for IEC-family reports."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from iec_parser.generic_iec_feature_registry import CanonicalProductFeatureRegistry


class _StringEnum(str, Enum):
    """Base for enums that serialize as their plain string values."""


class ProductFactStatus(_StringEnum):
    """Confidence and resolution state of a product fact."""

    CONFIRMED = "CONFIRMED"
    INFERRED_STRONG = "INFERRED_STRONG"
    INFERRED = "INFERRED"
    INFERRED_FROM_NA = "INFERRED_FROM_NA"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class FeaturePresenceState(_StringEnum):
    """Three-state source-backed presence of a product feature."""

    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class EvidenceSourceType(_StringEnum):
    """Location category from which report evidence originated."""

    REPORT_METADATA = "REPORT_METADATA"
    REPORT_CLAUSE = "REPORT_CLAUSE"
    REPORT_TABLE = "REPORT_TABLE"
    REPORT_MEASUREMENT = "REPORT_MEASUREMENT"
    REPORT_MARKING = "REPORT_MARKING"
    REPORT_INSTRUCTION = "REPORT_INSTRUCTION"
    STANDARD_SCOPE = "STANDARD_SCOPE"
    STANDARD_DEFINITION = "STANDARD_DEFINITION"
    OTHER = "OTHER"


class ProductIdentityType(_StringEnum):
    """Kind of identifier stated by a report."""

    MODEL = "MODEL"
    TYPE_REFERENCE = "TYPE_REFERENCE"
    PRODUCT_CODE = "PRODUCT_CODE"
    SAMPLE_ID = "SAMPLE_ID"
    SERIAL_NUMBER = "SERIAL_NUMBER"


class ProductIdentityRole(_StringEnum):
    """Source-supported role of an identifier."""

    DECLARED_MODEL = "DECLARED_MODEL"
    TESTED_MODEL = "TESTED_MODEL"
    SAMPLE_MODEL = "SAMPLE_MODEL"
    SERIES_MODEL = "SERIES_MODEL"
    REPRESENTATIVE_MODEL = "REPRESENTATIVE_MODEL"
    ALTERNATE_MODEL = "ALTERNATE_MODEL"
    UNKNOWN_MODEL_ROLE = "UNKNOWN_MODEL_ROLE"


class IdentityCandidateRole(_StringEnum):
    """Semantic role proposed for a source identity observation."""

    REPORT_NUMBER = "REPORT_NUMBER"
    DOCUMENT_VERSION = "DOCUMENT_VERSION"
    INTERNAL_IDENTIFIER = "INTERNAL_IDENTIFIER"
    REPORT_TITLE = "REPORT_TITLE"
    REPORT_DATE = "REPORT_DATE"
    LABORATORY = "LABORATORY"
    PRODUCT_NAME = "PRODUCT_NAME"
    PRODUCT_TYPE = "PRODUCT_TYPE"
    BRAND = "BRAND"
    MANUFACTURER = "MANUFACTURER"
    MODEL_NUMBER = "MODEL_NUMBER"
    TYPE_REFERENCE = "TYPE_REFERENCE"
    DECLARED_MODEL = "DECLARED_MODEL"
    TESTED_MODEL = "TESTED_MODEL"
    REPRESENTATIVE_MODEL = "REPRESENTATIVE_MODEL"
    SAMPLE_IDENTITY = "SAMPLE_IDENTITY"
    UNKNOWN = "UNKNOWN"


class SerializableModel:
    """Provide deterministic recursive dictionary and JSON serialization."""

    def to_dict(self) -> Dict[str, Any]:
        """Return the recursively serialized representation."""

        return asdict(self)  # type: ignore[arg-type]

    def to_json(self, **kwargs: Any) -> str:
        """Return deterministic JSON while preserving Unicode and null values."""

        options: Dict[str, Any] = {"ensure_ascii": False, "sort_keys": True}
        options.update(kwargs)
        return json.dumps(self.to_dict(), **options)

    def dict(self) -> Dict[str, Any]:
        """Compatibility alias for dictionary serialization."""

        return self.to_dict()

    def json(self, **kwargs: Any) -> str:
        """Compatibility alias for JSON serialization."""

        return self.to_json(**kwargs)


@dataclass
class ProductFactEvidence(SerializableModel):
    """Uninterpreted evidence traceable to a location in a source report."""

    evidence_id: str
    source_type: EvidenceSourceType
    source_document_id: Optional[str] = None
    page: Optional[int] = None
    clause_id: Optional[str] = None
    requirement_id: Optional[str] = None
    reported_verdict: Optional[str] = None
    raw_text: Optional[str] = None
    observed_value: Optional[Any] = None
    notes: Optional[str] = None
    source_authority: Optional[str] = None
    source_label: Optional[str] = None


@dataclass
class ProductFact(SerializableModel):
    """One canonical product feature value with status and report evidence."""

    feature_id: str
    value: Optional[Any]
    status: ProductFactStatus
    confidence: Optional[float] = None
    evidence: List[ProductFactEvidence] = field(default_factory=list)
    notes: Optional[str] = None
    observations: List["ProductFactObservation"] = field(default_factory=list)
    normalized_value: Optional[Any] = None
    value_type: Optional[str] = None
    unit: Optional[str] = None
    normalization_basis: Optional[str] = None
    conflicts: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Reject invalid confidence and duplicate evidence identities."""

        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
                raise ValueError("confidence must be a number between 0 and 1")
            if not 0 <= self.confidence <= 1:
                raise ValueError("confidence must be between 0 and 1")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError(f"Duplicate evidence_id within feature {self.feature_id}")


@dataclass
class ProductFactObservation(SerializableModel):
    """One source-preserving observation of a canonical product feature."""

    fact_id: str
    parameter: str
    value: Optional[Any]
    status: ProductFactStatus
    unit: Optional[str] = None
    qualifier: Optional[str] = None
    source_context: Optional[str] = None
    confidence: Optional[float] = None
    evidence: List[ProductFactEvidence] = field(default_factory=list)
    presence: Optional[bool] = None
    presence_state: FeaturePresenceState = FeaturePresenceState.UNKNOWN
    source_strength: Optional[str] = None
    scope_type: str = "REPORT_SCOPE"
    model_scope: Optional[str] = None
    polarity: str = "UNKNOWN"
    source_authority: Optional[str] = None


@dataclass
class ProductIdentityObservation(SerializableModel):
    """One independently retained report identity with role and provenance."""

    identity_id: str
    identity_type: ProductIdentityType
    role: ProductIdentityRole
    value: str
    normalized_value: str
    status: ProductFactStatus
    source_evidence_ids: List[str] = field(default_factory=list)
    evidence: List[ProductFactEvidence] = field(default_factory=list)
    raw_label: Optional[str] = None
    source_context: Optional[str] = None
    confidence: Optional[float] = None


@dataclass
class ProductIdentityRelationship(SerializableModel):
    """A source-stated relationship among declared or tested identities."""

    relationship_id: str
    relationship_type: str
    subject_values: List[str] = field(default_factory=list)
    representative_value: Optional[str] = None
    raw_text: Optional[str] = None
    source_page: Optional[int] = None
    source_evidence_ids: List[str] = field(default_factory=list)


@dataclass
class IdentityCandidate(SerializableModel):
    """A raw identity candidate retained before canonical role selection."""

    candidate_id: str
    raw_value: str
    normalized_value: str
    candidate_role: IdentityCandidateRole
    source_label: Optional[str] = None
    source_section: Optional[str] = None
    source_page: Optional[int] = None
    source_structure_reference: Optional[str] = None
    source_text: Optional[str] = None
    confidence: float = 0.0
    extraction_method: str = "TEXT_LABEL"
    candidate_priority: int = 0
    conflicts: List[str] = field(default_factory=list)
    selected: bool = False
    selection_reason: Optional[str] = None
    accepted: bool = True
    rejection_reason: Optional[str] = None
    source_authority: Optional[str] = None
    authority_rank: int = 0
    confidence_before: Optional[float] = None
    confidence_after: Optional[float] = None


@dataclass
class ProductIdentityValue(SerializableModel):
    """One identity value with optional source provenance."""

    value: str
    source_type: Optional[EvidenceSourceType] = None
    evidence_id: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    confidence: Optional[float] = None
    status: ProductFactStatus = ProductFactStatus.UNKNOWN
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        if self.confidence is not None and (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence must be between 0 and 1")


@dataclass
class ProductIdentity(SerializableModel):
    """Product identity fields preserved without conflating identifier types."""

    product_name: Optional[str] = None
    product_type: Optional[str] = None
    manufacturer: Optional[str] = None
    brand: Optional[str] = None
    model_numbers: List[str] = field(default_factory=list)
    type_references: List[str] = field(default_factory=list)
    serial_numbers: List[Union[str, ProductIdentityValue]] = field(default_factory=list)
    sample_identifiers: List[ProductIdentityValue] = field(default_factory=list)
    product_description: Optional[str] = None
    product_identities: List[ProductIdentityObservation] = field(default_factory=list)
    relationships: List[ProductIdentityRelationship] = field(default_factory=list)
    identity_candidates: List[IdentityCandidate] = field(default_factory=list)
    selection_provenance: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class ProductClassification(SerializableModel):
    """A report term classified only through supplied standard terminology."""

    reported_term: Optional[str]
    canonical_term: Optional[str]
    status: ProductFactStatus
    confidence: Optional[float] = None
    classification_basis: List[str] = field(default_factory=list)
    definition_reference: Optional[str] = None
    scope_reference: Optional[str] = None
    evidence: List[ProductFactEvidence] = field(default_factory=list)
    competing_terms: List[str] = field(default_factory=list)
    reason: Optional[str] = None


@dataclass
class RequiredFactCompleteness(SerializableModel):
    """Availability of one fact referenced by standard applicability metadata."""

    fact_key: str
    status: ProductFactStatus
    value: Optional[Any] = None
    reason: Optional[str] = None
    evidence_ids: List[str] = field(default_factory=list)
    requirement_consumers: List[str] = field(default_factory=list)


@dataclass
class ProductProfileSource(SerializableModel):
    """Metadata identifying the report from which a profile was derived."""

    document_id: Optional[str] = None
    file_name: Optional[str] = None
    report_number: Optional[str] = None
    document_version: Optional[str] = None
    internal_identifier: Optional[str] = None
    report_title: Optional[str] = None
    report_date: Optional[str] = None
    laboratory: Optional[str] = None
    standard_numbers: List[str] = field(default_factory=list)
    pages: Optional[int] = None
    identity_candidates: List[IdentityCandidate] = field(default_factory=list)
    selection_provenance: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class ProductProfile(SerializableModel):
    """Canonical feature map plus product identity and source traceability."""

    profile_id: str
    identity: ProductIdentity = field(default_factory=ProductIdentity)
    source: ProductProfileSource = field(default_factory=ProductProfileSource)
    facts: Dict[str, ProductFact] = field(default_factory=dict)
    unknown_features: List[str] = field(default_factory=list)
    conflicting_features: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    classifications: List[ProductClassification] = field(default_factory=list)
    required_fact_completeness: Dict[str, RequiredFactCompleteness] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Ensure each canonical map key agrees with its contained fact."""

        self.validate_structure()

    def validate_structure(self) -> None:
        """Validate profile-local invariants after construction or mutation."""

        for key, fact in self.facts.items():
            if not isinstance(fact, ProductFact):
                raise ValueError(f"facts[{key!r}] must be a ProductFact")
            if key != fact.feature_id:
                raise ValueError(
                    f"Fact dictionary key {key!r} does not match feature_id {fact.feature_id!r}"
                )
        for key, item in self.required_fact_completeness.items():
            if key != item.fact_key:
                raise ValueError(
                    f"Completeness key {key!r} does not match fact_key {item.fact_key!r}"
                )

    def validate_against_registry(
        self,
        registry: CanonicalProductFeatureRegistry,
        *,
        raise_on_error: bool = False,
    ) -> List[str]:
        """Return unknown canonical feature IDs, optionally raising a controlled error."""

        if not isinstance(registry, CanonicalProductFeatureRegistry):
            raise TypeError("registry must be a CanonicalProductFeatureRegistry")
        self.validate_structure()
        unknown = sorted(key for key in self.facts if not registry.exists(key))
        if unknown and raise_on_error:
            raise ValueError(f"Unregistered canonical feature IDs: {', '.join(unknown)}")
        return unknown

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ProductProfile":
        """Reconstruct a profile from its serialized representation."""

        if not isinstance(payload, dict):
            raise TypeError("payload must be a dictionary")
        identity_data = dict(payload.get("identity", {}))
        identity_data["serial_numbers"] = [
            ProductIdentityValue(
                **{**dict(item),
                   "source_type": EvidenceSourceType(item["source_type"]) if item.get("source_type") else None,
                   "status": ProductFactStatus(item.get("status", "UNKNOWN"))}
            ) if isinstance(item, dict) else item
            for item in identity_data.get("serial_numbers", [])
        ]
        identity_data["sample_identifiers"] = [
            ProductIdentityValue(
                **{**dict(item),
                   "source_type": EvidenceSourceType(item["source_type"]) if item.get("source_type") else None,
                   "status": ProductFactStatus(item.get("status", "UNKNOWN"))}
            )
            for item in identity_data.get("sample_identifiers", [])
        ]
        identity_data["product_identities"] = [
            ProductIdentityObservation(
                **{**dict(item),
                   "identity_type": ProductIdentityType(item["identity_type"]),
                   "role": ProductIdentityRole(item.get("role", "UNKNOWN_MODEL_ROLE")),
                   "status": ProductFactStatus(item.get("status", "UNKNOWN")),
                   "evidence": [ProductFactEvidence(
                       **{**dict(ev), "source_type": EvidenceSourceType(ev["source_type"])}
                   ) for ev in item.get("evidence", [])]}
            ) for item in identity_data.get("product_identities", [])
        ]
        identity_data["identity_candidates"] = [
            IdentityCandidate(
                **{**dict(item), "candidate_role": IdentityCandidateRole(item["candidate_role"])}
            ) for item in identity_data.get("identity_candidates", [])
        ]
        identity = ProductIdentity(**identity_data)
        source_data = dict(payload.get("source", {}))
        source_data["identity_candidates"] = [
            IdentityCandidate(
                **{**dict(item), "candidate_role": IdentityCandidateRole(item["candidate_role"])}
            ) for item in source_data.get("identity_candidates", [])
        ]
        source = ProductProfileSource(**source_data)
        facts: Dict[str, ProductFact] = {}
        for key, raw_fact in dict(payload.get("facts", {})).items():
            fact_data = dict(raw_fact)
            fact_data["status"] = ProductFactStatus(fact_data["status"])
            fact_data["evidence"] = [
                ProductFactEvidence(
                    **{**dict(item), "source_type": EvidenceSourceType(item["source_type"])}
                )
                for item in fact_data.get("evidence", [])
            ]
            fact_data["observations"] = [
                ProductFactObservation(
                    **{**dict(item),
                       "status": ProductFactStatus(item["status"]),
                       "presence_state": FeaturePresenceState(item.get("presence_state", "UNKNOWN")),
                       "evidence": [ProductFactEvidence(
                           **{**dict(ev), "source_type": EvidenceSourceType(ev["source_type"])}
                       ) for ev in item.get("evidence", [])]}
                ) for item in fact_data.get("observations", [])
            ]
            facts[key] = ProductFact(**fact_data)
        classifications = [
            ProductClassification(
                **{**dict(item),
                   "status": ProductFactStatus(item.get("status", "UNKNOWN")),
                   "evidence": [ProductFactEvidence(
                       **{**dict(ev), "source_type": EvidenceSourceType(ev["source_type"])}
                   ) for ev in item.get("evidence", [])]}
            ) for item in payload.get("classifications", [])
        ]
        completeness = {
            key: RequiredFactCompleteness(
                **{**dict(item), "status": ProductFactStatus(item.get("status", "UNKNOWN"))}
            ) for key, item in dict(payload.get("required_fact_completeness", {})).items()
        }
        return cls(
            profile_id=payload["profile_id"],
            identity=identity,
            source=source,
            facts=facts,
            unknown_features=list(payload.get("unknown_features", [])),
            conflicting_features=list(payload.get("conflicting_features", [])),
            classifications=classifications,
            required_fact_completeness=completeness,
            notes=payload.get("notes"),
        )


__all__ = [
    "EvidenceSourceType", "FeaturePresenceState", "IdentityCandidate", "IdentityCandidateRole", "ProductClassification", "ProductFact", "ProductFactEvidence", "ProductFactObservation",
    "ProductFactStatus", "ProductIdentity", "ProductIdentityObservation",
    "ProductIdentityRole", "ProductIdentityType", "ProductIdentityValue", "ProductProfile",
    "ProductProfileSource", "RequiredFactCompleteness",
]
