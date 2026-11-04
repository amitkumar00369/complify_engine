"""Generic, dependency-free schemas for evidence stated in test reports."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class _StringEnum(str, Enum):
    """String enum that serializes naturally through ``asdict`` and JSON."""


class ReportedVerdict(_StringEnum):
    """Verdict exactly reported by a laboratory, not an engine decision."""

    PASS = "PASS"
    FAIL = "FAIL"
    NA = "NA"
    NOT_TESTED = "NOT_TESTED"
    NOT_STATED = "NOT_STATED"
    UNKNOWN = "UNKNOWN"


class ReportEvidenceType(_StringEnum):
    """Kind of report-side evidence retained by the extractor."""

    CLAUSE_RESULT = "CLAUSE_RESULT"
    MEASUREMENT = "MEASUREMENT"
    TEST_PARAMETER = "TEST_PARAMETER"
    TEST_DESCRIPTION = "TEST_DESCRIPTION"
    OBSERVATION = "OBSERVATION"
    REMARK = "REMARK"
    MARKING = "MARKING"
    INSTRUCTION = "INSTRUCTION"
    CONSTRUCTION = "CONSTRUCTION"
    TABLE_VALUE = "TABLE_VALUE"
    PRODUCT_DETAIL = "PRODUCT_DETAIL"
    OTHER = "OTHER"
    CLAUSE_ROW = "CLAUSE_ROW"
    SUBROW = "SUBROW"


class SerializableModel:
    """Provide stable recursive dictionary and JSON serialization."""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)  # type: ignore[arg-type]

    def to_json(self, **kwargs: Any) -> str:
        options: Dict[str, Any] = {"ensure_ascii": False, "sort_keys": True}
        options.update(kwargs)
        return json.dumps(self.to_dict(), **options)


@dataclass
class ReportMeasurement(SerializableModel):
    """One value actually observed, reported, or used as a test parameter."""

    measurement_id: str
    parameter: Optional[str] = None
    parameter_text: Optional[str] = None
    value: Optional[Union[int, float, str]] = None
    value_secondary: Optional[Union[int, float, str]] = None
    unit: Optional[str] = None
    unit_normalized: Optional[str] = None
    operator: Optional[str] = None
    raw_text: Optional[str] = None
    page: Optional[int] = None
    table_id: Optional[str] = None
    row_label: Optional[str] = None
    column_label: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class ReportEvidenceItem(SerializableModel):
    """Occurrence-safe evidence attached to a report clause or section."""

    evidence_id: str
    evidence_type: ReportEvidenceType
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    clause_id: Optional[str] = None
    subclause_id: Optional[str] = None
    reported_verdict: ReportedVerdict = ReportedVerdict.NOT_STATED
    raw_text: Optional[str] = None
    remarks: Optional[str] = None
    measurements: List[ReportMeasurement] = field(default_factory=list)
    table_reference: Optional[str] = None
    source_order: int = 0
    notes: Optional[str] = None
    raw_verdict_text: Optional[str] = None
    parent_evidence_id: Optional[str] = None
    child_evidence_ids: List[str] = field(default_factory=list)
    row_ordinal: Optional[int] = None
    subrow_ordinal: Optional[int] = None
    raw_requirement_text: Optional[str] = None
    raw_result_text: Optional[str] = None
    row_group_id: Optional[str] = None
    logical_row_id: Optional[str] = None
    verdict_scope: Optional[str] = None
    evidence_scope_type: Optional[str] = None
    verdict_owner_evidence_id: Optional[str] = None
    result_owner_evidence_id: Optional[str] = None
    measurement_owner_evidence_id: Optional[str] = None


@dataclass
class ReportClauseResult(SerializableModel):
    """Combined occurrences for one report clause, with optional hierarchy."""

    result_id: str
    clause_id: str
    title: Optional[str] = None
    reported_verdict: ReportedVerdict = ReportedVerdict.NOT_STATED
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    raw_text: Optional[str] = None
    remarks: List[str] = field(default_factory=list)
    measurements: List[ReportMeasurement] = field(default_factory=list)
    evidence_items: List[ReportEvidenceItem] = field(default_factory=list)
    children: List["ReportClauseResult"] = field(default_factory=list)
    source_order: int = 0


@dataclass
class ReportEvidenceDocument(SerializableModel):
    """Complete report-side evidence artifact independent of an Effective KB."""

    document_id: str
    schema_version: str = "1.0"
    file_name: Optional[str] = None
    report_number: Optional[str] = None
    standard_numbers: List[str] = field(default_factory=list)
    clauses: List[ReportClauseResult] = field(default_factory=list)
    unmapped_sections: List[ReportEvidenceItem] = field(default_factory=list)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ReportEvidenceDocument":
        """Reconstruct a document for deterministic round-trip validation."""

        def measurement(raw: Dict[str, Any]) -> ReportMeasurement:
            return ReportMeasurement(**raw)
        def evidence(raw: Dict[str, Any]) -> ReportEvidenceItem:
            data = dict(raw); data["evidence_type"] = ReportEvidenceType(data["evidence_type"])
            data["reported_verdict"] = ReportedVerdict(data["reported_verdict"])
            data["measurements"] = [measurement(item) for item in data.get("measurements", [])]
            return ReportEvidenceItem(**data)
        def clause(raw: Dict[str, Any]) -> ReportClauseResult:
            data = dict(raw); data["reported_verdict"] = ReportedVerdict(data["reported_verdict"])
            data["measurements"] = [measurement(item) for item in data.get("measurements", [])]
            data["evidence_items"] = [evidence(item) for item in data.get("evidence_items", [])]
            data["children"] = [clause(item) for item in data.get("children", [])]
            return ReportClauseResult(**data)
        data = dict(payload)
        data["clauses"] = [clause(item) for item in data.get("clauses", [])]
        data["unmapped_sections"] = [evidence(item) for item in data.get("unmapped_sections", [])]
        return cls(**data)


__all__ = [
    "ReportClauseResult", "ReportEvidenceDocument", "ReportEvidenceItem",
    "ReportEvidenceType", "ReportMeasurement", "ReportedVerdict",
]
