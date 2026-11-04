"""Versioned, decision-isolated models for deterministic PDF visual inventory."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class _StringEnum(str, Enum):
    pass


class VisualRegionCategory(_StringEnum):
    MARKING_LABEL = "MARKING_LABEL"
    NAMEPLATE = "NAMEPLATE"
    TEST_SETUP = "TEST_SETUP"
    MEASUREMENT_TABLE = "MEASUREMENT_TABLE"
    MEASUREMENT_SCREENSHOT = "MEASUREMENT_SCREENSHOT"
    CIRCUIT_DIAGRAM = "CIRCUIT_DIAGRAM"
    TECHNICAL_DRAWING = "TECHNICAL_DRAWING"
    PRODUCT_PHOTO = "PRODUCT_PHOTO"
    SCANNED_TEXT = "SCANNED_TEXT"
    OTHER_VISUAL = "OTHER_VISUAL"
    UNKNOWN_VISUAL = "UNKNOWN_VISUAL"


class VisualObjectType(_StringEnum):
    RASTER_IMAGE = "RASTER_IMAGE"
    VECTOR_DRAWING = "VECTOR_DRAWING"
    MERGED_VISUAL = "MERGED_VISUAL"
    UNSAFE_OBJECT = "UNSAFE_OBJECT"


class VisualProcessingPriority(_StringEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    IGNORE = "IGNORE"


@dataclass
class VisualEvidenceRegion:
    region_id: str
    page_number: int
    bbox: List[float]
    normalized_bbox: List[float]
    coordinate_system: str
    object_type: VisualObjectType
    category: VisualRegionCategory
    category_confidence: float
    classification_reason: str
    source_object_ids: List[str]
    width: float
    height: float
    area_ratio: float
    native_text_available: bool
    nearby_native_text: Optional[str]
    nearby_heading: Optional[str]
    ocr_candidate: bool
    ocr_candidate_reason: str
    vision_candidate: bool
    vision_candidate_reason: str
    processing_priority: VisualProcessingPriority
    priority_reason: str
    stable_content_hash: str
    provenance: Dict[str, Any]
    filtered: bool = False
    filter_reason: Optional[str] = None
    repeated_template_visual: bool = False


@dataclass
class VisualEvidencePage:
    page_number: int
    page_width: float
    page_height: float
    native_text_available: bool
    native_text_density: float
    visual_regions: List[VisualEvidenceRegion] = field(default_factory=list)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class VisualEvidenceInventory:
    schema_version: str
    run_id: str
    source_report: Dict[str, Any]
    status: str
    summary: Dict[str, Any]
    pages: List[VisualEvidencePage]
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    authority: str = "VISUAL_INVENTORY"
    decision_authority: str = "NONE"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=indent)

