"""Generic semantic validation and authority ranking for report identities."""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


AUTHORITY_RANKS = {
    "EXPLICIT_STRUCTURED_FIELD": 900,
    "TEST_ITEM_PARTICULARS": 800,
    "REPORT_HEADER_IDENTITY": 700,
    "GENERAL_PRODUCT_INFORMATION": 600,
    "MARKING_TABLE": 500,
    "NORMAL_BODY_TEXT": 400,
    "HEADER_FOOTER": 300,
    "DISCLAIMER": 200,
    "SIGNATURE_METADATA": 100,
}


@dataclass(frozen=True)
class IdentityCandidateValidation:
    accepted: bool
    field_type: str
    value: str
    rejection_reason: Optional[str]
    confidence_adjustment: float
    source_authority: str
    authority_rank: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GenericReportIdentityCandidateValidator:
    """Reject values whose shape is incompatible with their proposed role."""

    _DATE = re.compile(
        r"^(?:\d{1,4}[./-]){2}\d{1,4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?(?:\s*(?:UTC|GMT))?$",
        re.I,
    )
    _TIME = re.compile(r"^(?:\d{1,2}:){1,2}\d{2}(?:\s*(?:UTC|GMT))?$", re.I)
    _ADDRESS = re.compile(
        r"(?:\b(?:street|st\.?|road|rd\.?|avenue|ave\.?|boulevard|blvd\.?|corso|via|"
        r"postcode|postal|zip)\b|\b[A-Z]{1,3}-?\d{4,6}\b.*\b(?:street|road|corso|via|Italy|China|Germany|USA|UK)\b|"
        r"\b\d{5}\b.*\b(?:Italy|China|Germany|USA|UK)\b)",
        re.I,
    )
    _ORG = re.compile(
        r"\b(?:laborator(?:y|ies)|testing|test house|certification|institute|institution|"
        r"company|co\.?|corp(?:oration)?|inc\.?|ltd\.?|limited|s\.?r\.?l\.?|s\.?p\.?a\.?|"
        r"gmbh|llc|bv|nv|sas|ag|kiwa|tuv|tüv|intertek|sgs|ul)\b",
        re.I,
    )
    _DISCLAIMER = re.compile(
        r"\b(?:uncertainty|instruction|procedure|operational|license agreement|disclaimer|"
        r"shall not be reproduced|subject to|definition of|user\(s\))\b",
        re.I,
    )
    _JOB_TITLE = re.compile(
        r"^(?:laboratory|lab|technical|quality|test)\s+(?:director|manager|engineer|technician)$",
        re.I,
    )
    _ATTACHMENT = re.compile(r"^(?:see\s+)?(?:attachment|annex|appendix)\s*(?:no\.?\s*)?[A-Za-z0-9.-]+$", re.I)
    _CLAUSE = re.compile(r"^(?:cl(?:ause)?\.?\s*)?\d+(?:\.\d+)*(?:\s+marking)?$", re.I)
    _PROCEDURE = re.compile(r"^(?:IECEE\s*)?(?:OD|CTL|TRF|OP|IO|LAB)[-_ ]?[A-Z0-9.-]*\d[A-Z0-9.-]*$", re.I)
    _NAVIGATION_REFERENCE = re.compile(
        r"^(?:see|refer(?:red)?\s+to|as\s+(?:shown|specified)\s+(?:on|in))\s+"
        r"(?:the\s+)?(?:page|clause|annex|appendix|attachment|table|figure)\b",
        re.I,
    )

    def validate_candidate(
        self, field_type: str, candidate_value: str, source_label: Optional[str] = None,
        source_text: Optional[str] = None, page: Optional[int] = None,
        bbox: Any = None, surrounding_context: Optional[str] = None,
        source_authority: Optional[str] = None,
    ) -> IdentityCandidateValidation:
        del page, bbox
        role = str(field_type).upper()
        value = re.sub(r"\s+", " ", str(candidate_value or "")).strip(" .:;")
        context = " ".join(x for x in (source_label, source_text, surrounding_context) if x)
        authority = source_authority or self.source_authority(role, source_label, source_text)
        reason: Optional[str] = None
        if not value:
            reason = "EMPTY_VALUE"
        elif role == "LABORATORY":
            if self._DATE.fullmatch(value) or self._TIME.fullmatch(value):
                reason = "TIMESTAMP_SEMANTIC_ROLE_MISMATCH"
            elif re.fullmatch(r"\d{1,3}", value):
                reason = "NUMERIC_IDENTIFIER_SEMANTIC_ROLE_MISMATCH"
            elif self._PROCEDURE.fullmatch(value) or self._DISCLAIMER.search(value):
                reason = "PROCEDURE_OR_DISCLAIMER_SEMANTIC_ROLE_MISMATCH"
            elif self._JOB_TITLE.fullmatch(value):
                reason = "JOB_TITLE_SEMANTIC_ROLE_MISMATCH"
            elif self._ADDRESS.search(value) and not self._ORG.search(value):
                reason = "ADDRESS_SEMANTIC_ROLE_MISMATCH"
            elif not self._ORG.search(value) and (len(value.split()) > 4 or re.search(
                r"\b(?:this|throughout|responsible|report|contents|contacting|performed|used)\b", value, re.I
            )):
                reason = "PROSE_SEMANTIC_ROLE_MISMATCH"
        elif role in {"DECLARED_MODEL", "MODEL", "MODEL_NUMBER", "TESTED_MODEL", "REPRESENTATIVE_MODEL", "TYPE_REFERENCE"}:
            if self._ATTACHMENT.fullmatch(value) or re.search(r"\b(?:see\s+)?(?:attachment|annex|appendix)\b", value, re.I):
                reason = "ATTACHMENT_REFERENCE_SEMANTIC_ROLE_MISMATCH"
            elif self._CLAUSE.fullmatch(value) or re.match(r"^(?:cl(?:ause)?\.?\s*)\d+(?:\.\d+)*(?:\s|$)", value, re.I):
                reason = "CLAUSE_REFERENCE_SEMANTIC_ROLE_MISMATCH"
            elif re.fullmatch(r"\d{1,3}[).]?", value):
                reason = "ENUMERATION_SEMANTIC_ROLE_MISMATCH"
            elif self._ADDRESS.search(value):
                reason = "ADDRESS_SEMANTIC_ROLE_MISMATCH"
            elif re.fullmatch(r"(?:model|type|model number|model no)\.?", value, re.I):
                reason = "GENERIC_LABEL_SEMANTIC_ROLE_MISMATCH"
            elif re.search(r"\b\d+(?:\.\d+)?\s*(?:V|Hz|A|W)\b", value, re.I) or len(value.split()) > 10:
                reason = "NON_IDENTIFIER_PROSE_SEMANTIC_ROLE_MISMATCH"
            elif re.match(r"^(?:TRF|report|test report)\s+(?:no\.?\s*)", value, re.I):
                reason = "REPORT_IDENTIFIER_SEMANTIC_ROLE_MISMATCH"
            elif len(value) < 2:
                reason = "INSUBSTANTIAL_IDENTIFIER"
        elif role == "DOCUMENT_VERSION":
            if self._ADDRESS.search(value):
                reason = "ADDRESS_SEMANTIC_ROLE_MISMATCH"
            elif self._DATE.fullmatch(value) or self._TIME.fullmatch(value):
                reason = "TIMESTAMP_SEMANTIC_ROLE_MISMATCH"
            elif len(value) > 60 or (len(value.split()) > 6 and not re.search(r"\b(?:rev|revision|ver|version|issue|edition)\b", value, re.I)):
                reason = "PROSE_SEMANTIC_ROLE_MISMATCH"
        elif role == "REPORT_DATE" and not (self._DATE.search(value) or re.search(
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b", value, re.I
        )):
            reason = "DATE_FORMAT_SEMANTIC_ROLE_MISMATCH"
        elif role == "REPORT_NUMBER" and (self._DATE.fullmatch(value) or re.fullmatch(r"\d{1,2}", value)):
            reason = "REPORT_NUMBER_SEMANTIC_ROLE_MISMATCH"
        elif role in {"BRAND", "MANUFACTURER"}:
            if self._NAVIGATION_REFERENCE.search(value):
                reason = "NAVIGATION_REFERENCE_SEMANTIC_ROLE_MISMATCH"
            elif self._DISCLAIMER.search(value):
                reason = "DESCRIPTIVE_PROSE_SEMANTIC_ROLE_MISMATCH"
        accepted = reason is None
        return IdentityCandidateValidation(
            accepted, role, value, reason, 0.0 if accepted else -1.0,
            authority, AUTHORITY_RANKS.get(authority, 0),
        )

    @classmethod
    def source_authority(cls, field_type: str, source_label: Optional[str], source_text: Optional[str]) -> str:
        label = (source_label or "").casefold()
        text = (source_text or "").casefold()
        if re.search(r"\b(?:signature|signed|director|approved by)\b", text):
            return "SIGNATURE_METADATA"
        if cls._DISCLAIMER.search(text):
            return "DISCLAIMER"
        if label and re.search(r"\b(?:report|date|laboratory|laboratories|model|type|brand|trade|manufacturer|product)\b", label):
            return "EXPLICIT_STRUCTURED_FIELD"
        return "NORMAL_BODY_TEXT"
