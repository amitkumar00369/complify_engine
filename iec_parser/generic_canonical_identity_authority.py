"""Deterministic field-semantic authority for report and product identity."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .generic_report_identity_candidate_validator import GenericReportIdentityCandidateValidator


SCHEMA_VERSION = "CANONICAL_IDENTITY_AUTHORITY_V1"
POLICY_VERSION = "STEP55G_IDENTITY_SEMANTIC_AUTHORITY_V1"
SEMANTIC_STATUSES = ("VALID", "MISSING", "NEEDS_REVIEW", "REJECTED_AS_CONTAMINATED")
AUTHORITY_STATUSES = ("AUTHORITATIVE", "NOT_AVAILABLE", "REVIEW_REQUIRED", "REJECTED")

PRODUCT_SPECIFIC_IDENTITY_RULES = 0
REPORT_SPECIFIC_IDENTITY_RULES = 0
STANDARD_SPECIFIC_IDENTITY_RULES = 0


class GenericCanonicalIdentityAuthority:
    """Validate identity values by semantic role without inventing replacements."""

    MODEL_FIELDS = {
        "MODEL", "MODEL_NUMBER", "DECLARED_MODEL", "TESTED_MODEL",
        "REPRESENTATIVE_MODEL", "MODEL_FAMILY", "VARIANT", "SERIES",
        "TYPE_REFERENCE", "SAMPLE_IDENTIFIER", "BATCH_IDENTIFIER",
    }
    ORGANIZATION_FIELDS = {"MANUFACTURER", "BRAND", "LABORATORY"}
    REPORT_FIELDS = {"REPORT_NUMBER", "REPORT_IDENTIFIER", "INTERNAL_IDENTIFIER"}
    _PUNCTUATION_ONLY = re.compile(r"^[\W_]+$", re.UNICODE)
    _STANDARD_REFERENCE = re.compile(
        r"\b(?:IEC|ISO|EN|UL|CSA|CAN/CSA|GB(?:/T)?|DIN|BS|AS/NZS)\s*[-:]?\s*\d{3,}(?:[-.:/]\d+)*\b",
        re.I,
    )
    _ADDRESS_TEXT = re.compile(
        r"(?:\b\d+(?:st|nd|rd|th)\s+floor\b|\bfloor\b|\bdistrict\b|\binternational\s+trade\s+city\b|"
        r"\b(?:street|road|avenue|boulevard|building|room|suite|postcode|postal|zip)\b)",
        re.I,
    )
    _RATING_TEXT = re.compile(
        r"\b(?:rated\s+)?(?:voltage|current|power|frequency|capacity|input|output)\b",
        re.I,
    )
    _RATING_ONLY = re.compile(
        r"^(?:\d{1,4}(?:\.\d+)?\s*(?:V|A|W|kW|Hz|Ah|mAh)\s*[,;/+-]?\s*)+$",
        re.I,
    )
    _DIMENSION_TEXT = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mm|cm|m|in(?:ch)?|kg|g)\b", re.I)
    _CLAUSE_TEXT = re.compile(r"^(?:cl(?:ause)?\.?\s*)?\d+(?:\.\d+){1,}(?:\s+.+)?$", re.I)
    _TABLE_HEADER = re.compile(r"\b(?:rated\s+current|output\s+power|model\s+no\.?\s+rating|table\s+\d+)\b", re.I)
    _PAGE_HEADER = re.compile(r"^(?:page\s+\d+(?:\s+of\s+\d+)?|test\s+report|contents)$", re.I)
    _NAVIGATION = re.compile(r"^(?:see|refer(?:red)?\s+to)\s+(?:page|clause|annex|appendix|table|figure)\b", re.I)
    _DATE_FRAGMENT = re.compile(
        r"^(?:\d{1,4}[./-]){2}\d{1,4}$|^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}$",
        re.I,
    )
    _MULTI_FIELD = re.compile(
        r"\b(?:brand\s*name|trade\s*mark|manufacturer)\s*[:#]|"
        r"\b(?:batch|serial)\s*(?:no|number)\.?\s*[:#]?\s*[A-Za-z0-9]",
        re.I,
    )
    _PROSE = re.compile(
        r"\b(?:shall|should|must|according\s+to|performed|tested|equipment\s+under\s+test|"
        r"this\s+report|the\s+product|is\s+intended\s+for)\b",
        re.I,
    )

    def __init__(self) -> None:
        self._candidate_validator = GenericReportIdentityCandidateValidator()

    def build(
        self,
        identity_store: Any,
        product_profile: Any = None,
        identity_relationships: Any = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        store = self._plain(identity_store or {})
        profile = self._plain(product_profile or {})
        relationships = self._plain(identity_relationships or {})
        records = []

        for field_name, value in sorted((store.get("product") or {}).items()):
            records.append(self._record(field_name.upper(), value, profile, section="product"))
        for model in store.get("models") or []:
            records.append(self._record(str(model.get("role") or "MODEL"), model, profile, section="models"))

        report = store.get("report") or {}
        report_fields = (
            "report_identifier", "report_number", "laboratory", "internal_identifier",
            "document_version", "report_date",
        )
        for field_name in report_fields:
            records.append(self._report_record(field_name.upper(), report.get(field_name), report, profile))

        by_field: Dict[str, list] = defaultdict(list)
        for row in records:
            if row.get("canonical_value") is not None:
                by_field[str(row.get("field_name"))].append(row.get("canonical_value"))
        for row in records:
            row["alternatives"] = [
                value for value in by_field.get(str(row.get("field_name")), [])
                if value != row.get("canonical_value")
            ]

        canonical = self._canonical_store(store, records, run_id)
        result = {
            "schema_version": SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "run_id": run_id,
            "source_profile_id": store.get("source_profile_id") or profile.get("profile_id"),
            "semantic_statuses": list(SEMANTIC_STATUSES),
            "authority_statuses": list(AUTHORITY_STATUSES),
            "identity_records": records,
            "canonical_identity": canonical,
            "relationship_authority": relationships,
            "summary": {
                "record_count": len(records),
                "semantic_status_counts": dict(sorted(Counter(row["semantic_status"] for row in records).items())),
                "authority_status_counts": dict(sorted(Counter(row["authority_status"] for row in records).items())),
            },
        }
        result["identity_sha256"] = self._hash(result)
        return result

    def validate(self, authority: Any) -> Dict[str, Any]:
        data = self._plain(authority or {})
        diagnostics = []
        records = data.get("identity_records") or []
        if data.get("schema_version") != SCHEMA_VERSION:
            diagnostics.append({"code": "INVALID_IDENTITY_AUTHORITY_SCHEMA"})
        if data.get("identity_sha256") != self._hash({k: v for k, v in data.items() if k != "identity_sha256"}):
            diagnostics.append({"code": "INVALID_IDENTITY_AUTHORITY_HASH"})
        rejected_values = []
        for row in records:
            semantic = row.get("semantic_status")
            authority_status = row.get("authority_status")
            canonical = row.get("canonical_value")
            source = row.get("source_reference") or {}
            if semantic not in SEMANTIC_STATUSES or authority_status not in AUTHORITY_STATUSES:
                diagnostics.append({"code": "INVALID_IDENTITY_AUTHORITY_STATE", "identity_id": row.get("identity_id")})
            if authority_status == "AUTHORITATIVE":
                if canonical is None:
                    diagnostics.append({"code": "AUTHORITATIVE_IDENTITY_WITHOUT_VALUE", "identity_id": row.get("identity_id")})
                if not source.get("source_document") or not source.get("source_field") or source.get("raw_text") is None:
                    diagnostics.append({"code": "IDENTITY_SOURCE_REFERENCE_MISSING", "identity_id": row.get("identity_id")})
            if semantic == "REJECTED_AS_CONTAMINATED":
                rejected_values.append(row.get("normalized_value"))
                if canonical is not None or authority_status != "REJECTED":
                    diagnostics.append({"code": "CONTAMINATED_IDENTITY_REMAINS_AUTHORITATIVE", "identity_id": row.get("identity_id")})
        canonical_text = json.dumps(data.get("canonical_identity") or {}, sort_keys=True, ensure_ascii=False)
        for value in rejected_values:
            if value is not None and json.dumps(value, ensure_ascii=False) in canonical_text:
                diagnostics.append({"code": "CONTAMINATED_IDENTITY_USED_DOWNSTREAM", "value": value})
        counts = Counter(row["code"] for row in diagnostics)
        return {
            "schema_version": "CANONICAL_IDENTITY_AUTHORITY_INTEGRITY_V1",
            "policy_version": POLICY_VERSION,
            "valid": not diagnostics,
            "diagnostic_count": len(diagnostics),
            "diagnostic_counts": dict(sorted(counts.items())),
            "diagnostics": diagnostics,
            "source_identity_sha256": data.get("identity_sha256"),
        }

    def filter_relationships(self, relationships: Any, identity_store: Any) -> Dict[str, Any]:
        """Retain only relationships whose subjects survive identity authority."""
        data = self._plain(relationships or {})
        store = self._plain(identity_store or {})
        allowed = {str(row.get("identity_id")) for row in store.get("models") or [] if row.get("identity_id")}
        retained = []
        for row in data.get("relationships") or []:
            explicit = {str(value) for value in row.get("identity_ids") or [] if value}
            left = str(row.get("left_identity_id") or "")
            right = str(row.get("right_identity_id") or "")
            if explicit and explicit.issubset(allowed):
                retained.append(copy.deepcopy(row))
            elif left and right and left in allowed and right in allowed:
                retained.append(copy.deepcopy(row))
        result = {
            "schema_version": data.get("schema_version") or "CANONICAL_IDENTITY_RELATIONSHIPS_V1",
            "policy_version": POLICY_VERSION,
            "relationships": retained,
            "evidence_usability": copy.deepcopy(data.get("evidence_usability") or {}),
            "rejected_relationship_count": len(data.get("relationships") or []) - len(retained),
        }
        result["relationships_sha256"] = self._hash(result)
        return result

    def _record(self, field_name: str, value_record: Any, profile: Mapping[str, Any], *, section: str) -> Dict[str, Any]:
        item = self._plain(value_record or {})
        value = item.get("value")
        source_reference = {
            "source_document": item.get("source_document") or (profile.get("source") or {}).get("document_id"),
            "page": item.get("page"),
            "source_field": field_name,
            "source_label": self._source_label(profile, field_name),
            "raw_text": item.get("source_text") if item.get("source_text") is not None else value,
            "source_ids": copy.deepcopy(item.get("source_ids") or []),
            "normalization": "WHITESPACE_AND_EDGE_PUNCTUATION_ONLY",
            "source_kind": item.get("authority"),
        }
        return self._decision(
            field_name, value, source_reference, item.get("confidence"),
            role=item.get("role"), legacy_identity_id=item.get("identity_id"), section=section,
        )

    def _report_record(
        self, field_name: str, value: Any, report: Mapping[str, Any], profile: Mapping[str, Any]
    ) -> Dict[str, Any]:
        provenance_key = "REPORT_NUMBER" if field_name == "REPORT_IDENTIFIER" else field_name
        provenance = (report.get("selection_provenance") or {}).get(provenance_key) or {}
        raw_text = provenance.get("source_text") if provenance.get("source_text") is not None else value
        source_reference = {
            "source_document": report.get("report_identifier") or (profile.get("source") or {}).get("document_id"),
            "page": provenance.get("source_page"),
            "source_field": field_name,
            "source_label": provenance.get("source_label") or field_name,
            "raw_text": raw_text,
            "source_ids": [provenance["candidate_id"]] if provenance.get("candidate_id") else [],
            "normalization": "WHITESPACE_AND_EDGE_PUNCTUATION_ONLY",
            "source_kind": provenance.get("source_authority") or report.get("authority"),
        }
        return self._decision(field_name, value, source_reference, provenance.get("confidence"), section="report")

    def _decision(
        self, field_name: str, raw_value: Any, source_reference: Mapping[str, Any],
        confidence: Any, *, role: Any = None, legacy_identity_id: Any = None, section: str,
    ) -> Dict[str, Any]:
        normalized = self._normalize(raw_value)
        contamination = self._contamination(field_name, normalized, source_reference)
        if raw_value is None or normalized == "":
            semantic_status = "MISSING"
            authority_status = "NOT_AVAILABLE"
            reason_code = "IDENTITY_VALUE_NOT_REPORTED"
            canonical = None
        elif contamination:
            semantic_status = "REJECTED_AS_CONTAMINATED"
            authority_status = "REJECTED"
            reason_code = contamination
            canonical = None
        elif not source_reference.get("source_document") or source_reference.get("raw_text") is None:
            semantic_status = "NEEDS_REVIEW"
            authority_status = "REVIEW_REQUIRED"
            reason_code = "IDENTITY_SOURCE_REFERENCE_INCOMPLETE"
            canonical = None
        else:
            semantic_status = "VALID"
            authority_status = "AUTHORITATIVE"
            reason_code = "FIELD_SEMANTICS_AND_SOURCE_VALIDATED"
            canonical = normalized
        identity_id = "CANONICAL-IDENTITY-AUTHORITY-" + self._hash({
            "field": field_name, "value": normalized, "role": role, "source": source_reference,
        })[:20].upper()
        return {
            "identity_id": identity_id,
            "legacy_identity_id": legacy_identity_id,
            "field_name": field_name,
            "semantic_type": self._semantic_type(field_name),
            "role": role,
            "section": section,
            "raw_value": raw_value,
            "normalized_value": normalized if raw_value is not None else None,
            "semantic_status": semantic_status,
            "authority_status": authority_status,
            "reason_code": reason_code,
            "source_reference": copy.deepcopy(dict(source_reference)),
            "source_confidence": confidence,
            "canonical_value": canonical,
            "alternatives": [],
            "schema_version": SCHEMA_VERSION,
        }

    def _contamination(
        self, field_name: str, value: str, source_reference: Mapping[str, Any]
    ) -> Optional[str]:
        if not value:
            return None
        source_text = str(source_reference.get("raw_text") or value)
        if self._PUNCTUATION_ONLY.fullmatch(value):
            return "OCR_GARBAGE"
        if self._PAGE_HEADER.fullmatch(value):
            return "PAGE_HEADER_FOOTER"
        if self._NAVIGATION.search(value):
            return "NAVIGATION_TEXT"
        if self._STANDARD_REFERENCE.search(value):
            return "STANDARD_REFERENCE"
        if self._DATE_FRAGMENT.fullmatch(value) and field_name not in {"REPORT_DATE", "DOCUMENT_VERSION"}:
            return "DATE_FRAGMENT"
        if field_name in self.MODEL_FIELDS:
            if self._MULTI_FIELD.search(value) or self._MULTI_FIELD.search(source_text) and self._MULTI_FIELD.search(value):
                return "MULTI_FIELD_CONCATENATION"
            if self._ADDRESS_TEXT.search(value) or (
                self._ADDRESS_TEXT.search(source_text) and value.casefold() in source_text.casefold()
                and re.search(r"\b(?:floor|room|building|district)\b", value, re.I)
            ):
                return "ADDRESS_TEXT"
            if self._TABLE_HEADER.search(value) or self._RATING_TEXT.search(value) or self._RATING_ONLY.fullmatch(value):
                return "VOLTAGE_OR_RATING_TEXT"
            if self._DIMENSION_TEXT.search(value):
                return "DIMENSION_TEXT"
            if self._CLAUSE_TEXT.fullmatch(value):
                return "CLAUSE_TEXT"
            if self._PROSE.search(value) or len(value.split()) > 6:
                return "PROSE_FRAGMENT"
            if not re.search(r"[A-Za-z]", value) or not re.search(r"[A-Za-z0-9]", value):
                return "UNRELATED_NUMERIC_STRING"
            validation = self._candidate_validator.validate_candidate(field_name, value, field_name, source_text)
            if not validation.accepted:
                return self._map_legacy_reason(validation.rejection_reason)
        elif field_name in self.ORGANIZATION_FIELDS:
            if self._RATING_TEXT.search(value) or self._RATING_ONLY.fullmatch(value) or self._DIMENSION_TEXT.search(value):
                return "VOLTAGE_OR_RATING_TEXT"
            if self._ADDRESS_TEXT.search(value) and not re.search(
                r"\b(?:co\.?|company|ltd\.?|limited|inc\.?|corp\.?|gmbh|llc|laborator(?:y|ies)|testing|institute|certification)\b",
                value,
                re.I,
            ):
                return "ADDRESS_TEXT"
            if self._PROSE.search(value) or len(value.split()) > 15:
                return "PROSE_FRAGMENT"
            validation = self._candidate_validator.validate_candidate(field_name, value, field_name, source_text)
            if not validation.accepted:
                return self._map_legacy_reason(validation.rejection_reason)
        elif field_name in self.REPORT_FIELDS:
            if self._CLAUSE_TEXT.fullmatch(value) or self._STANDARD_REFERENCE.fullmatch(value):
                return "STANDARD_REFERENCE" if self._STANDARD_REFERENCE.fullmatch(value) else "CLAUSE_TEXT"
            if self._PROSE.search(value) or len(value.split()) > 4:
                return "PROSE_FRAGMENT"
            if field_name == "REPORT_NUMBER" and (self._DATE_FRAGMENT.fullmatch(value) or len(value) < 3):
                return "REPORT_IDENTIFIER_SEMANTIC_ERROR"
        elif field_name in {"PRODUCT_NAME", "PRODUCT_TYPE"}:
            if self._ADDRESS_TEXT.search(value):
                return "ADDRESS_TEXT"
            if self._TABLE_HEADER.search(value) or self._RATING_TEXT.search(value) or self._RATING_ONLY.fullmatch(value):
                return "VOLTAGE_OR_RATING_TEXT"
            if self._STANDARD_REFERENCE.fullmatch(value):
                return "STANDARD_REFERENCE"
        return None

    @staticmethod
    def _map_legacy_reason(reason: Optional[str]) -> str:
        value = str(reason or "PROSE_SEMANTIC_ROLE_MISMATCH")
        if "ADDRESS" in value:
            return "ADDRESS_TEXT"
        if "CLAUSE" in value:
            return "CLAUSE_TEXT"
        if "REPORT_IDENTIFIER" in value:
            return "REPORT_IDENTIFIER_SEMANTIC_ERROR"
        if "ATTACHMENT" in value or "NAVIGATION" in value:
            return "NAVIGATION_TEXT"
        if "TIMESTAMP" in value or "DATE" in value:
            return "DATE_FRAGMENT"
        if "NUMERIC" in value or "ENUMERATION" in value:
            return "UNRELATED_NUMERIC_STRING"
        return "PROSE_FRAGMENT"

    @staticmethod
    def _semantic_type(field_name: str) -> str:
        if field_name in GenericCanonicalIdentityAuthority.MODEL_FIELDS:
            return "PRODUCT_IDENTIFIER"
        if field_name in GenericCanonicalIdentityAuthority.ORGANIZATION_FIELDS:
            return "ORGANIZATION_IDENTITY"
        if field_name in GenericCanonicalIdentityAuthority.REPORT_FIELDS:
            return "REPORT_IDENTIFIER"
        if field_name in {"PRODUCT_NAME", "PRODUCT_TYPE"}:
            return "PRODUCT_DESIGNATION"
        return "REPORT_METADATA"

    @staticmethod
    def _normalize(value: Any) -> str:
        if value is None:
            return ""
        return re.sub(r"\s+", " ", str(value)).strip(" .:;")

    @staticmethod
    def _source_label(profile: Mapping[str, Any], field_name: str) -> Optional[str]:
        provenance = ((profile.get("identity") or {}).get("selection_provenance") or {}).get(field_name) or {}
        return provenance.get("source_label") or field_name

    def _canonical_store(
        self, source: Mapping[str, Any], records: list[Mapping[str, Any]], run_id: Optional[str]
    ) -> Dict[str, Any]:
        product_records = {row["field_name"].lower(): row for row in records if row.get("section") == "product"}
        product = {}
        for field_name in sorted((source.get("product") or {}).keys()):
            row = product_records.get(field_name)
            original = copy.deepcopy((source.get("product") or {}).get(field_name) or {})
            if row:
                original.update({
                    "value": row.get("canonical_value"),
                    "status": "CONFIRMED" if row.get("authority_status") == "AUTHORITATIVE" else "UNKNOWN",
                    "authority": row.get("authority_status"),
                    "semantic_status": row.get("semantic_status"),
                    "semantic_reason_code": row.get("reason_code"),
                    "identity_authority_id": row.get("identity_id"),
                })
            product[field_name] = original
        models = []
        for row in records:
            if row.get("section") != "models" or row.get("authority_status") != "AUTHORITATIVE":
                continue
            original = next(
                (copy.deepcopy(item) for item in source.get("models") or [] if item.get("identity_id") == row.get("legacy_identity_id")),
                {},
            )
            original.update({
                "identity_id": row.get("identity_id"),
                "source_identity_id": row.get("legacy_identity_id"),
                "value": row.get("canonical_value"),
                "status": "CONFIRMED",
                "authority": "CANONICAL_IDENTITY_AUTHORITY",
                "semantic_reason_code": row.get("reason_code"),
            })
            models.append(original)
        report = copy.deepcopy(source.get("report") or {})
        report_records = {row["field_name"].lower(): row for row in records if row.get("section") == "report"}
        for field_name, row in report_records.items():
            if field_name in report:
                report[field_name] = row.get("canonical_value")
        report["run_id"] = run_id
        result = {
            "schema_version": "CANONICAL_IDENTITY_STORE_V2",
            "policy_version": POLICY_VERSION,
            "source_profile_id": source.get("source_profile_id"),
            "product": product,
            "models": sorted(models, key=lambda row: (str(row.get("role")), str(row.get("value")), str(row.get("identity_id")))),
            "report": report,
        }
        result["identity_store_sha256"] = self._hash(result)
        return result

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")).encode()).hexdigest()

    @classmethod
    def _plain(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): cls._plain(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._plain(item) for item in value]
        if hasattr(value, "value"):
            return value.value
        if hasattr(value, "__dict__"):
            return cls._plain(vars(value))
        return copy.deepcopy(value)

    @classmethod
    def save_json(cls, value: Any, path: Any) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(cls._plain(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        return target


__all__ = [
    "GenericCanonicalIdentityAuthority", "SCHEMA_VERSION", "POLICY_VERSION",
    "SEMANTIC_STATUSES", "AUTHORITY_STATUSES",
]
