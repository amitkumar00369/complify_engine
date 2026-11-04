"""Governed, decision-isolated models for Step 46-L visual extraction."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class _StringEnum(str, Enum):
    pass


class VisualRoutingAction(_StringEnum):
    SKIP = "SKIP"
    OCR = "OCR"
    VISION = "VISION"
    OCR_THEN_VISION = "OCR_THEN_VISION"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"


class VisualExtractionStatus(_StringEnum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    SKIPPED = "SKIPPED"


@dataclass
class OCRExtractionResult:
    status: VisualExtractionStatus
    raw_text: Optional[str] = None
    confidence: Optional[float] = None
    tokens: List[Dict[str, Any]] = field(default_factory=list)
    lines: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    provider_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VisualEvidenceCandidate:
    candidate_id: str
    candidate_type: str
    raw_value: str
    normalized_value: Optional[Any]
    unit: Optional[str]
    polarity: str
    scope: str
    source_region_id: str
    source_page: int
    source_bbox: List[float]
    extraction_method: str
    extraction_confidence: Optional[float]
    source_text: str
    authority: str = "EXTRACTED_VISUAL_EVIDENCE"
    decision_authority: str = "NONE"


@dataclass
class VisualRegionExtractionResult:
    region_id: str
    page_number: int
    source_bbox: List[float]
    source_content_hash: str
    inventory_category: str
    processing_priority: str
    routing_action: VisualRoutingAction
    routing_reason: str
    extraction_status: VisualExtractionStatus
    extraction_method: Optional[str]
    raw_text: Optional[str]
    normalized_text: Optional[str]
    extraction_confidence: Optional[float]
    structured_candidates: List[VisualEvidenceCandidate]
    duplicate_of_region_id: Optional[str]
    warnings: List[str]
    errors: List[str]
    provenance: Dict[str, Any]


@dataclass
class VisualEvidenceExtraction:
    schema_version: str
    run_id: str
    source_inventory: Dict[str, Any]
    extraction_policy_version: str
    extractor_config_hash: str
    status: str
    summary: Dict[str, Any]
    regions: List[VisualRegionExtractionResult]
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    authority: str = "EXTRACTED_VISUAL_EVIDENCE"
    decision_authority: str = "NONE"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=indent)
