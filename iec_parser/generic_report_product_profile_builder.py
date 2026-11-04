"""Evidence-driven construction of canonical product profiles from IEC reports."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

from iec_parser.generic_iec_feature_registry import (
    CanonicalProductFeature, CanonicalProductFeatureRegistry, FeatureDataType,
)
from iec_parser.generic_product_profile_models import (
    EvidenceSourceType, FeaturePresenceState, ProductClassification, ProductFact,
    ProductFactEvidence, ProductFactStatus, IdentityCandidate, IdentityCandidateRole,
    ProductFactObservation, ProductIdentity, ProductIdentityObservation,
    ProductIdentityRelationship, ProductIdentityRole, ProductIdentityType,
    ProductProfile, ProductProfileSource, RequiredFactCompleteness,
)
from iec_parser.generic_report_identity_candidate_validator import (
    GenericReportIdentityCandidateValidator,
)


PathLike = Union[str, Path]


class ProfileDiagnosticCategory(str, Enum):
    """Non-fatal reason why report evidence was not mapped automatically."""

    UNMAPPED_REPORT_TERM = "UNMAPPED_REPORT_TERM"
    AMBIGUOUS_FEATURE_MAPPING = "AMBIGUOUS_FEATURE_MAPPING"
    CONFLICTING_REPORT_EVIDENCE = "CONFLICTING_REPORT_EVIDENCE"
    NA_DERIVED_HINT = "NA_DERIVED_HINT"
    MISSING_REPORT_METADATA = "MISSING_REPORT_METADATA"
    PER_MODEL_VARIATION = "PER_MODEL_VARIATION"
    UNSUPPORTED_VALUE = "UNSUPPORTED_VALUE"


@dataclass(frozen=True)
class ProductProfileDiagnostic:
    """One deterministic extraction diagnostic."""

    category: ProfileDiagnosticCategory
    message: str
    page: Optional[int] = None
    raw_text: Optional[str] = None
    candidate_features: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Candidate:
    feature_id: str
    value: Any
    status: ProductFactStatus
    confidence: Optional[float]
    evidence: ProductFactEvidence
    scope_type: str = "REPORT_SCOPE"
    model_scope: Optional[str] = None
    authority_rank: int = 0
    source_authority: str = "NORMAL_BODY_TEXT"
    source_label: Optional[str] = None


@dataclass(frozen=True)
class _StandardTerm:
    term: str
    definition: Optional[str]
    definition_reference: Optional[str]
    scope_reference: Optional[str]
    source_text: str
    source_type: EvidenceSourceType
    page: Optional[int] = None


class GenericReportProductProfileBuilder:
    """Extract report-stated product facts without compliance evaluation."""

    _REPORT_NUMBER_RE = re.compile(
        r"(?:Report\s*(?:No\.?|Number)|Test\s+Report\s+No\.?)"
        r"\s*(?:\.{2,}\s*)?[:：]\s*([^\n]+)", re.IGNORECASE
    )
    _DATE_RE = re.compile(
        r"(?:Date\s+of\s+(?:Report|issue)|Report\s+Date)\s*[^:\n]*:\s*([^\n]+)", re.IGNORECASE
    )
    _STANDARD_RE = re.compile(r"\b(?:US\s+)?IEC\s+\d{3,6}(?:-\d+)*(?::\s*\d{4})?", re.IGNORECASE)
    _CLAUSE_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\s*$")
    _VERDICT_RE = re.compile(r"^(?:P|PASS|F|FAIL|N/?A|NA|N\.A\.|N|NOT APPLICABLE|NOT TESTED)$", re.IGNORECASE)
    _VALUE_RE = r"(?P<a>\d+(?:[.,]\d+)?)(?:\s*(?:-|–|—|to)\s*(?P<b>\d+(?:[.,]\d+)?))?\s*(?P<unit>V|Hz|A|W)\b"
    _KNOWN_METADATA_LABELS = {
        "report no", "report number", "date of report", "date of issue", "testing laboratory",
        "laboratory", "standard", "applicant", "address", "prepared for", "prepared by",
        "tested by", "approved by",
        "model", "model no", "model number", "model designation", "model and/or type",
        "type", "type reference", "type ref", "type designation", "trade mark", "trademark",
        "brand", "manufacturer", "product", "product name", "product description",
        "test item", "test item description", "rating", "ratings",
        "serial number", "serial no", "warning",
    }

    def __init__(self, registry: Optional[CanonicalProductFeatureRegistry] = None) -> None:
        self.registry = registry or CanonicalProductFeatureRegistry()
        self._diagnostics: List[ProductProfileDiagnostic] = []
        self._evidence_sequence = 0
        self.identity_validator = GenericReportIdentityCandidateValidator()

    def build(
        self, pdf_path: PathLike, *, standard_context: Optional[Any] = None,
        effective_kb: Optional[Any] = None,
    ) -> ProductProfile:
        """Extract a ProductProfile from a text-bearing PDF without modifying it."""

        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(f"Report PDF not found: {path}")
        try:
            import fitz
            with fitz.open(path) as document:
                pages = [page.get_text("text") for page in document]
                page_blocks = [[tuple(block[:5]) for block in page.get_text("blocks")]
                               for page in document]
        except (OSError, RuntimeError, ValueError) as error:
            raise ValueError(f"Unable to read report PDF {path}: {error}") from error
        if not any(page.strip() for page in pages):
            raise ValueError(f"No extractable text found in report PDF: {path}")
        return self.build_from_pages(
            pages, file_name=path.name, standard_context=standard_context,
            effective_kb=effective_kb, page_blocks=page_blocks,
        )

    def build_from_pages(
        self, pages: Sequence[str], *, file_name: Optional[str] = None,
        standard_context: Optional[Any] = None, effective_kb: Optional[Any] = None,
        page_blocks: Optional[Sequence[Sequence[Tuple[Any, ...]]]] = None,
    ) -> ProductProfile:
        """Build from page text for deterministic, dependency-light validation."""

        if isinstance(pages, (str, bytes)) or not pages or not all(isinstance(x, str) for x in pages):
            raise TypeError("pages must be a non-empty sequence of strings")
        if not any(page.strip() for page in pages):
            raise ValueError("No extractable report text supplied")
        self._diagnostics = []
        self._evidence_sequence = 0
        text = "\n".join(pages)
        source_candidates, product_candidates = self._extract_identity_candidates(
            pages, page_blocks
        )
        source = self._extract_source(
            "\n".join(pages[: min(3, len(pages))]), file_name, len(pages), source_candidates
        )
        identity = self._extract_identity(pages, product_candidates)
        identity.product_identities = self._extract_identity_observations(
            pages, source.document_id, identity
        )
        identity.relationships = self._extract_identity_relationships(pages, identity)
        candidates: List[_Candidate] = []
        candidates.extend(self._extract_labeled_facts(
            pages, source.document_id, identity=identity
        ))
        candidates.extend(self._extract_operating_context(pages, source.document_id))
        candidates.extend(self._extract_explicit_booleans(pages, source.document_id))
        candidates.extend(self._extract_na_hints(pages, source.document_id))
        facts = self._aggregate_candidates(candidates)
        classifications = self._classify_product(
            identity, pages, source.document_id, standard_context, effective_kb
        )
        required_consumers = self.discover_required_fact_consumers(effective_kb)
        required_keys = sorted(required_consumers)
        for key in required_keys:
            if key not in facts and self.registry.exists(key):
                feature = self.registry.get(key)
                facts[key] = ProductFact(
                    feature_id=key, value=None, status=ProductFactStatus.UNKNOWN,
                    confidence=None, evidence=[],
                    notes="No report evidence establishes this applicability-required fact.",
                    normalized_value=None,
                    value_type=feature.data_type.value if feature else None,
                    unit=feature.unit if feature else None,
                    normalization_basis="REQUIRED_FACT_COMPLETENESS",
                )
        completeness = self._build_fact_completeness(
            required_keys, facts, required_consumers, classifications
        )
        profile = ProductProfile(
            profile_id=self._profile_id(source, file_name, text), identity=identity,
            source=source, facts=facts,
            unknown_features=sorted(key for key, fact in facts.items()
                                    if fact.status is ProductFactStatus.UNKNOWN),
            conflicting_features=sorted(key for key, fact in facts.items()
                                        if fact.status is ProductFactStatus.CONFLICT),
            classifications=classifications,
            required_fact_completeness=completeness,
        )
        unknown_registry = profile.validate_against_registry(self.registry)
        if unknown_registry:
            raise ValueError(f"Builder produced unregistered features: {unknown_registry}")
        self._detect_per_model_variation(pages, identity.model_numbers)
        self._detect_unmapped_labels(pages)
        return profile

    @classmethod
    def discover_required_fact_keys(cls, effective_kb: Optional[Any]) -> List[str]:
        """Collect fact keys referenced by applicability metadata without evaluating it."""

        return sorted(cls.discover_required_fact_consumers(effective_kb))

    @classmethod
    def discover_required_fact_consumers(
        cls, effective_kb: Optional[Any]
    ) -> Dict[str, List[str]]:
        """Map each applicability fact to its effective requirement consumers."""

        payload = cls._as_payload(effective_kb)
        if not isinstance(payload, (dict, list)):
            return {}
        found: Dict[str, Set[str]] = {}

        def add(key: str, requirement_id: Optional[str]) -> None:
            key = key.strip()
            if key:
                found.setdefault(key, set())
                if requirement_id:
                    found[key].add(requirement_id)

        def walk(value: Any, requirement_id: Optional[str] = None) -> None:
            if isinstance(value, dict):
                requirement_id = str(
                    value.get("effective_requirement_id")
                    or value.get("requirement_id")
                    or requirement_id
                    or ""
                ) or None
                field_name = value.get("field")
                if isinstance(field_name, str) and field_name.strip():
                    add(field_name, requirement_id)
                subject = value.get("subject")
                if isinstance(subject, dict):
                    kind = str(subject.get("kind") or "").upper()
                    if kind == "PRODUCT_TYPE":
                        add("product_type", requirement_id)
                    elif kind == "ELECTRICAL_CLASS":
                        add("protection_class", requirement_id)
                for child in value.values():
                    walk(child, requirement_id)
            elif isinstance(value, list):
                for child in value:
                    walk(child, requirement_id)

        walk(payload)
        return {key: sorted(values) for key, values in sorted(found.items())}

    @staticmethod
    def _build_fact_completeness(
        required_keys: Sequence[str], facts: Dict[str, ProductFact],
        requirement_consumers: Optional[Dict[str, List[str]]] = None,
        classifications: Optional[Sequence[ProductClassification]] = None,
    ) -> Dict[str, RequiredFactCompleteness]:
        output: Dict[str, RequiredFactCompleteness] = {}
        for key in sorted(set(required_keys)):
            fact = facts.get(key)
            if key == "canonical_product_classification" and classifications:
                classification = classifications[0]
                output[key] = RequiredFactCompleteness(
                    fact_key=key, status=classification.status,
                    value=classification.canonical_term,
                    reason=classification.reason,
                    evidence_ids=sorted(item.evidence_id for item in classification.evidence),
                    requirement_consumers=list((requirement_consumers or {}).get(key, [])),
                )
                continue
            if fact is None:
                output[key] = RequiredFactCompleteness(
                    fact_key=key, status=ProductFactStatus.UNKNOWN,
                    reason="Applicability references this fact, but no registered report fact exists.",
                    requirement_consumers=list((requirement_consumers or {}).get(key, [])),
                )
                continue
            reason = {
                ProductFactStatus.UNKNOWN: "No report evidence establishes presence, absence, or value.",
                ProductFactStatus.CONFLICT: "Report evidence contains competing values.",
            }.get(fact.status, "Report evidence provides a usable fact without evaluating applicability.")
            output[key] = RequiredFactCompleteness(
                fact_key=key, status=fact.status, value=fact.value, reason=reason,
                evidence_ids=sorted(item.evidence_id for item in fact.evidence),
                requirement_consumers=list((requirement_consumers or {}).get(key, [])),
            )
        return output

    def _classify_product(
        self, identity: ProductIdentity, pages: Sequence[str], document_id: Optional[str],
        standard_context: Optional[Any], effective_kb: Optional[Any],
    ) -> List[ProductClassification]:
        """Classify a report term through supplied definitions and scope terminology."""

        reported = identity.product_type or identity.product_name or identity.product_description
        terms = self._standard_terms(standard_context, effective_kb)
        report_evidence = ProductFactEvidence(
            evidence_id=self._stable_evidence_id("classification-report", reported or "missing"),
            source_type=EvidenceSourceType.REPORT_METADATA,
            source_document_id=document_id, page=self._locate_text_page(pages, reported),
            raw_text=reported, observed_value=reported,
            notes="Reported product terminology used as classification input.",
        )
        if not reported:
            return [ProductClassification(
                reported_term=None, canonical_term=None, status=ProductFactStatus.UNKNOWN,
                classification_basis=["REPORT_IDENTITY_MISSING"], evidence=[],
                reason="The report does not establish a product name or description.",
            )]
        if not terms:
            return [ProductClassification(
                reported_term=reported, canonical_term=None, status=ProductFactStatus.UNKNOWN,
                classification_basis=["REPORT_TERM"], evidence=[report_evidence],
                reason="No standard definition or scope terminology was supplied.",
            )]
        scored = sorted(
            ((self._classification_score(reported, item), item) for item in terms),
            key=lambda pair: (-pair[0], self._normalize_terms(pair[1].term), pair[1].source_text),
        )
        best_score, best = scored[0]
        threshold = .44
        competitors = sorted({
            item.term for score, item in scored[1:]
            if score >= threshold and abs(score - best_score) <= .025
            and self._materially_incompatible_terms(best.term, item.term)
        })
        if best_score < threshold:
            return [ProductClassification(
                reported_term=reported, canonical_term=None, status=ProductFactStatus.UNKNOWN,
                confidence=round(best_score, 4),
                classification_basis=["REPORT_TERM", "STANDARD_TERMINOLOGY_SEARCH"],
                evidence=[report_evidence, self._standard_term_evidence(best)],
                reason="Supplied standard terminology is insufficiently aligned for deterministic classification.",
            )]
        exact = self._normalize_terms(reported) == self._normalize_terms(best.term)
        # Report terminology establishes a candidate, not authoritative proof of
        # a technical subtype.  Stronger classification may still be supplied by
        # an upstream explicit/validated classification source, but this lexical
        # classifier intentionally remains INFERRED even for an exact term.
        status = (ProductFactStatus.CONFLICT if competitors else ProductFactStatus.INFERRED)
        reason = ("The reported and canonical terms normalize identically, but terminology "
                  "alone does not confirm technical subtype construction." if exact else
                  "Canonical term inferred from deterministic terminology overlap.")
        if competitors:
            reason = "Multiple standard terms have indistinguishable deterministic support."
        basis = ["REPORT_TERM", "TOKEN_OVERLAP"]
        if best.definition:
            basis.append("STANDARD_DEFINITION")
        if best.scope_reference or best.source_type is EvidenceSourceType.STANDARD_SCOPE:
            basis.append("STANDARD_SCOPE")
        return [ProductClassification(
            reported_term=reported, canonical_term=best.term, status=status,
            confidence=round(min(.99, best_score), 4), classification_basis=basis,
            definition_reference=best.definition_reference,
            scope_reference=best.scope_reference,
            evidence=[report_evidence, self._standard_term_evidence(best)],
            competing_terms=competitors, reason=reason,
        )]

    @classmethod
    def _standard_terms(
        cls, standard_context: Optional[Any], effective_kb: Optional[Any]
    ) -> List[_StandardTerm]:
        output: Dict[Tuple[str, str, str], _StandardTerm] = {}
        for payload in (cls._as_payload(standard_context), cls._as_payload(effective_kb)):
            if not isinstance(payload, dict):
                continue
            for item in payload.get("definitions", []) or []:
                if not isinstance(item, dict) or not isinstance(item.get("term"), str):
                    continue
                source = item.get("source") if isinstance(item.get("source"), dict) else {}
                reference = item.get("definition_id") or item.get("clause_id") or item["term"]
                candidate = _StandardTerm(
                    term=item["term"], definition=item.get("definition"),
                    definition_reference=str(reference), scope_reference=None,
                    source_text=str(item.get("definition") or item["term"]),
                    source_type=EvidenceSourceType.STANDARD_DEFINITION,
                    page=source.get("page_start"),
                )
                output[(cls._normalize_terms(candidate.term), "DEFINITION", str(reference))] = candidate
                # Some legacy KBs retain several numbered definition entries
                # inside one source-preserving definition block. Recover the
                # standard terms generically without introducing aliases.
                embedded = str(item.get("definition") or "")
                pattern = re.compile(
                    r"(?ms)^\s*(?P<reference>\d+(?:\.\d+)+\s+\d+(?:\.\d+)+)\s*$\n"
                    r"(?P<term>[^\n]{2,100})\n(?P<definition>.*?)"
                    r"(?=^\s*\d+(?:\.\d+)+\s+\d+(?:\.\d+)+\s*$|\Z)"
                )
                for match in pattern.finditer(embedded):
                    term = re.sub(r"\s+", " ", match.group("term")).strip()
                    definition = re.sub(r"\s+", " ", match.group("definition")).strip()
                    nested_reference = match.group("reference").strip()
                    nested = _StandardTerm(
                        term=term, definition=definition,
                        definition_reference=nested_reference, scope_reference=None,
                        source_text=f"{term}\n{definition}",
                        source_type=EvidenceSourceType.STANDARD_DEFINITION,
                        page=source.get("page_start"),
                    )
                    output[(cls._normalize_terms(term), "DEFINITION", nested_reference)] = nested
            for item in payload.get("scope_terms", []) or []:
                if isinstance(item, str):
                    item = {"term": item}
                if not isinstance(item, dict) or not isinstance(item.get("term"), str):
                    continue
                reference = str(item.get("scope_reference") or item.get("clause_id") or "SCOPE")
                candidate = _StandardTerm(
                    term=item["term"], definition=item.get("description"),
                    definition_reference=None, scope_reference=reference,
                    source_text=str(item.get("source_text") or item.get("description") or item["term"]),
                    source_type=EvidenceSourceType.STANDARD_SCOPE, page=item.get("page"),
                )
                output[(cls._normalize_terms(candidate.term), "SCOPE", reference)] = candidate

            def walk(value: Any, clause_id: Optional[str] = None) -> None:
                if isinstance(value, dict):
                    owner = str(value.get("clause_id") or clause_id or "SCOPE")
                    subject = value.get("subject")
                    if isinstance(subject, dict) and str(subject.get("kind") or "").upper() == "PRODUCT_TYPE":
                        term = subject.get("normalized_term") or subject.get("source_text")
                        if isinstance(term, str) and term.strip():
                            candidate = _StandardTerm(
                                term=term, definition=None, definition_reference=None,
                                scope_reference=owner, source_text=str(subject.get("source_text") or term),
                                source_type=EvidenceSourceType.STANDARD_SCOPE,
                            )
                            output[(cls._normalize_terms(term), "SCOPE", owner)] = candidate
                    for child in value.values():
                        walk(child, owner)
                elif isinstance(value, list):
                    for child in value:
                        walk(child, clause_id)
            walk(payload)
        return sorted(output.values(), key=lambda item: (
            cls._normalize_terms(item.term), item.source_type.value,
            item.definition_reference or item.scope_reference or "",
        ))

    @classmethod
    def _classification_score(cls, reported: str, candidate: _StandardTerm) -> float:
        report_tokens = cls._term_tokens(reported)
        term_tokens = cls._term_tokens(candidate.term)
        if not report_tokens or not term_tokens:
            return 0.0
        term_score = 2 * len(report_tokens & term_tokens) / (len(report_tokens) + len(term_tokens))
        definition_tokens = cls._term_tokens(candidate.definition or "")
        source_tokens = cls._term_tokens(candidate.source_text)
        definition_score = len(report_tokens & definition_tokens) / len(report_tokens)
        source_score = len(report_tokens & source_tokens) / len(report_tokens)
        exact_bonus = .15 if cls._normalize_terms(reported) == cls._normalize_terms(candidate.term) else 0
        return min(1.0, .65 * term_score + .2 * definition_score + .15 * source_score + exact_bonus)

    @classmethod
    def _materially_incompatible_terms(cls, first: str, second: str) -> bool:
        """Return true only for competing concepts, not lexical variants.

        Duplicate observations, singular/plural forms, hyphenation, case, and
        a broader phrase that contains the selected concept do not establish a
        semantic conflict.  A conflict requires meaningful, non-contained
        vocabulary on both sides.
        """

        left = cls._term_tokens(first)
        right = cls._term_tokens(second)
        return bool(left and right and not (left <= right or right <= left))

    @staticmethod
    def _term_tokens(value: str) -> Set[str]:
        words = re.findall(r"[a-z0-9]+", value.casefold())
        stop = {"a", "an", "and", "for", "of", "the", "to", "with", "used", "intended"}
        return {word[:-1] if len(word) > 4 and word.endswith("s") else word
                for word in words if word not in stop}

    @classmethod
    def _normalize_terms(cls, value: str) -> str:
        return " ".join(sorted(cls._term_tokens(value)))

    @staticmethod
    def _as_payload(value: Optional[Any]) -> Optional[Any]:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        if hasattr(value, "to_dict") and callable(value.to_dict):
            return value.to_dict()
        return None

    @staticmethod
    def _locate_text_page(pages: Sequence[str], value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        normalized = re.sub(r"\s+", " ", value).casefold()
        return next((number for number, page in enumerate(pages, 1)
                     if normalized in re.sub(r"\s+", " ", page).casefold()), None)

    @staticmethod
    def _stable_evidence_id(namespace: str, value: str) -> str:
        return "PROFILE-EV-" + hashlib.sha256(f"{namespace}|{value}".encode()).hexdigest()[:16].upper()

    def _standard_term_evidence(self, item: _StandardTerm) -> ProductFactEvidence:
        return ProductFactEvidence(
            evidence_id=self._stable_evidence_id(
                item.source_type.value, f"{item.term}|{item.definition_reference}|{item.scope_reference}"
            ),
            source_type=item.source_type, page=item.page, raw_text=item.source_text,
            observed_value=item.term,
            notes="Standard-derived terminology used as classification evidence.",
        )

    @staticmethod
    def to_dict(profile: ProductProfile) -> Dict[str, Any]:
        """Return the Step 14A serialized representation."""

        if not isinstance(profile, ProductProfile):
            raise TypeError("profile must be a ProductProfile")
        return profile.to_dict()

    @staticmethod
    def to_json(profile: ProductProfile, indent: Optional[int] = 2) -> str:
        """Serialize deterministically with Unicode preserved."""

        return json.dumps(profile.to_dict(), ensure_ascii=False, sort_keys=True, indent=indent)

    def save_json(self, profile: ProductProfile, output_path: PathLike) -> Path:
        """Save a deterministic profile JSON artifact."""

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(profile, 2) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def identity_candidate_audit(profile: ProductProfile) -> Dict[str, Any]:
        """Return selected and rejected candidates with stable audit fields."""

        candidates = list(profile.source.identity_candidates) + list(profile.identity.identity_candidates)
        records = [{
            "field": item.candidate_role.value,
            "candidate_value": item.normalized_value,
            "status": "SELECTED" if item.selected and item.accepted else ("ACCEPTED_NOT_SELECTED" if item.accepted else "REJECTED"),
            "source_page": item.source_page,
            "source_text": item.source_text,
            "source_label": item.source_label,
            "source_authority": item.source_authority,
            "confidence_before": item.confidence_before if item.confidence_before is not None else item.confidence,
            "confidence_after": item.confidence_after if item.confidence_after is not None else item.confidence,
            "rejection_reason": item.rejection_reason,
            "selection_reason": item.selection_reason,
            "candidate_id": item.candidate_id,
        } for item in candidates]
        records.sort(key=lambda x: (x["field"], x["source_page"] or 10**9, x["candidate_value"].casefold(), x["candidate_id"]))
        return {
            "schema_version": "REPORT_IDENTITY_CANDIDATE_AUDIT_V1",
            "profile_id": profile.profile_id,
            "summary": {
                "total": len(records),
                "selected": sum(x["status"] == "SELECTED" for x in records),
                "rejected": sum(x["status"] == "REJECTED" for x in records),
                "accepted_not_selected": sum(x["status"] == "ACCEPTED_NOT_SELECTED" for x in records),
            },
            "candidates": records,
        }

    @classmethod
    def save_identity_candidate_audit(cls, profile: ProductProfile, output_path: PathLike) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cls.identity_candidate_audit(profile), ensure_ascii=False,
                                   sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def get_summary(profile: ProductProfile) -> Dict[str, Any]:
        """Return fact-status and evidence counts without interpreting results."""

        statuses = Counter(fact.status.value for fact in profile.facts.values())
        return {
            "profile_id": profile.profile_id,
            "total_facts": len(profile.facts),
            "statuses": {status.value: statuses[status.value] for status in ProductFactStatus},
            "evidence": sum(len(fact.evidence) for fact in profile.facts.values()),
            "unknown_features": len(profile.unknown_features),
            "conflicting_features": len(profile.conflicting_features),
        }

    def get_diagnostics(self) -> List[ProductProfileDiagnostic]:
        """Return an independent copy of diagnostics from the latest build."""

        return copy.deepcopy(self._diagnostics)

    def _extract_source(
        self, text: str, file_name: Optional[str], pages: int,
        candidates: Optional[Sequence[IdentityCandidate]] = None,
    ) -> ProductProfileSource:
        retained = list(candidates or [])
        report_number = self._selected_candidate_value(retained, IdentityCandidateRole.REPORT_NUMBER)
        fallback_report_number = self._first_group(self._REPORT_NUMBER_RE, text)
        if fallback_report_number and self._version_like(fallback_report_number):
            fallback_report_number = None
        report_number = report_number or fallback_report_number
        document_version = self._selected_candidate_value(
            retained, IdentityCandidateRole.DOCUMENT_VERSION
        )
        internal_identifier = self._selected_candidate_value(
            retained, IdentityCandidateRole.INTERNAL_IDENTIFIER
        )
        report_date = (self._selected_candidate_value(retained, IdentityCandidateRole.REPORT_DATE)
                       or self._report_date(text))
        laboratory = (self._selected_candidate_value(retained, IdentityCandidateRole.LABORATORY)
                      or self._label_value(text, ["Testing laboratory", "Test laboratory", "Laboratory"]))
        standards = self._unique(self._normalize_standard(match.group(0))
                                 for match in self._STANDARD_RE.finditer(text))
        if not report_number:
            self._diagnostics.append(ProductProfileDiagnostic(
                ProfileDiagnosticCategory.MISSING_REPORT_METADATA, "Report number was not found"))
        if not report_date:
            self._diagnostics.append(ProductProfileDiagnostic(
                ProfileDiagnosticCategory.MISSING_REPORT_METADATA, "Report date was not found"))
        if not laboratory:
            self._diagnostics.append(ProductProfileDiagnostic(
                ProfileDiagnosticCategory.MISSING_REPORT_METADATA, "Testing laboratory was not found"))
        return ProductProfileSource(
            document_id=report_number, file_name=file_name, report_number=report_number,
            document_version=document_version, internal_identifier=internal_identifier,
            report_date=report_date, laboratory=laboratory, standard_numbers=standards, pages=pages,
            identity_candidates=retained,
            selection_provenance=self._selection_provenance(retained),
        )

    def _extract_identity(
        self, pages: Sequence[str], candidates: Optional[Sequence[IdentityCandidate]] = None
    ) -> ProductIdentity:
        front = "\n".join(pages[: min(8, len(pages))])
        models = self._all_label_values(front, [
            "Model and/or Type", "Model/Type reference", "Model No.", "Model number",
            "Model designation", "Model",
        ])
        types = self._all_label_values(front, ["Type reference", "Type Ref.", "Type designation", "Type"])
        serials = self._all_label_values(front, ["Serial number", "Serial No."])
        retained = list(candidates or [])
        manufacturer = self._selected_candidate_value(retained, IdentityCandidateRole.MANUFACTURER)
        brand = self._selected_candidate_value(retained, IdentityCandidateRole.BRAND)
        product_name = self._selected_candidate_value(retained, IdentityCandidateRole.PRODUCT_NAME)
        product_type = self._selected_candidate_value(retained, IdentityCandidateRole.PRODUCT_TYPE)
        selected_models = self._split_identifiers(
            self._selected_candidate_values(retained, IdentityCandidateRole.DECLARED_MODEL)
        )
        selected_types = self._split_identifiers(
            self._selected_candidate_values(retained, IdentityCandidateRole.TYPE_REFERENCE)
        )
        manufacturer = manufacturer or self._label_value(front, ["Manufacturer"])
        if manufacturer and not self.identity_validator.validate_candidate(
                "MANUFACTURER", manufacturer, "Manufacturer", manufacturer).accepted:
            manufacturer = None
        brand = brand or self._label_value(front, ["Trade Mark", "Trademark", "Brand"])
        if brand and re.search(r"\s+for\s+", brand, re.I):
            head, tail = re.split(r"\s+for\s+", brand, maxsplit=1, flags=re.I)
            if re.search(r"[A-Za-z]+\d|\d+[A-Za-z]|\([^)]{1,8}\)|[,;]", tail):
                brand = head.strip(" ,;:")
        product_name = product_name or self._label_value(
            front, ["Product Name", "Test item description", "Test item", "Product"]
        )
        product_type = product_type or self._label_value(
            front, ["Product type", "Type of equipment", "Equipment type",
                    "Generic product designation", "EUT description"]
        )
        description = self._label_value(front, ["Product description"])
        # Some PDF table extractors emit adjacent labels first and their values
        # afterwards. Preserve only a high-confidence two-label/two-value case.
        if not product_name or not brand:
            adjacent = self._adjacent_label_values(
                front, ("Test item", "Product"), ("Trade Mark", "Trademark", "Brand")
            )
            if adjacent:
                product_name = product_name or adjacent[0]
                brand = brand or adjacent[1]
        if not product_name or not brand:
            columnar = self._columnar_identity_values(pages[: min(8, len(pages))])
            if columnar:
                product_name = product_name or columnar[0]
                brand = brand or columnar[1]
        return ProductIdentity(
            product_name=product_name, product_type=product_type,
            manufacturer=manufacturer, brand=brand,
            model_numbers=self._unique(selected_models + [value for value in self._split_identifiers(models)
                if self.identity_validator.validate_candidate("DECLARED_MODEL", value, "Model", value).accepted]),
            type_references=self._unique(selected_types + [value for value in self._split_identifiers(types)
                if self.identity_validator.validate_candidate("TYPE_REFERENCE", value, "Type reference", value).accepted]),
            serial_numbers=self._split_identifiers(serials),
            product_description=description,
            identity_candidates=retained,
            selection_provenance=self._selection_provenance(retained),
        )

    _IDENTITY_LABEL_ROLES: Tuple[Tuple[IdentityCandidateRole, Tuple[str, ...]], ...] = (
        (IdentityCandidateRole.REPORT_NUMBER, ("report reference no", "report reference", "test report number", "test report no", "report number", "report no", "tr no")),
        (IdentityCandidateRole.DOCUMENT_VERSION, ("document version", "edition of report", "version", "revision", "rev", "issue")),
        (IdentityCandidateRole.REPORT_DATE, ("date of issue", "date of report", "report date")),
        (IdentityCandidateRole.PRODUCT_NAME, ("test item description", "equipment under test", "product name", "test item", "equipment", "product", "eut", "description")),
        (IdentityCandidateRole.PRODUCT_TYPE, ("product type", "type of equipment", "equipment type", "description of equipment", "product description", "generic product designation", "eut description", "equipment description")),
        (IdentityCandidateRole.DECLARED_MODEL, ("model type reference", "model and or type", "model number", "model no", "model designation", "model")),
        (IdentityCandidateRole.TYPE_REFERENCE, ("type reference", "type designation", "type no", "type ref", "type")),
        (IdentityCandidateRole.BRAND, ("trade mark", "trademark", "trade name", "brand")),
        (IdentityCandidateRole.MANUFACTURER, ("applicant manufacturer", "manufactured by", "manufacturer", "factory")),
        (IdentityCandidateRole.LABORATORY, ("testing laboratory", "test laboratory", "laboratory")),
        (IdentityCandidateRole.SAMPLE_IDENTITY, ("sample identification", "sample id", "sample identity")),
    )

    def _extract_identity_candidates(
        self, pages: Sequence[str],
        page_blocks: Optional[Sequence[Sequence[Tuple[Any, ...]]]],
    ) -> Tuple[List[IdentityCandidate], List[IdentityCandidate]]:
        """Retain role candidates and select only source-authoritative values."""

        found: List[IdentityCandidate] = []
        for page_number, page in enumerate(pages[: min(8, len(pages))], 1):
            lines = [re.sub(r"\s+", " ", line).strip() for line in page.splitlines()]
            expanded_roles = (
                (IdentityCandidateRole.LABORATORY,
                 ("name of testing laboratory", "name of testing laboratory preparing the report", "cb testing laboratory")),
                (IdentityCandidateRole.DECLARED_MODEL,
                 ("model type reference", "model and or type", "model type")),
                (IdentityCandidateRole.BRAND, ("trade mark", "trademark", "trademarks")),
                (IdentityCandidateRole.MANUFACTURER, ("manufacturer",)),
                (IdentityCandidateRole.PRODUCT_NAME,
                 ("test item description", "product name", "equipment under test")),
            )
            for index, line in enumerate(lines):
                label_text = self._normalize_label(line)
                matched = next(((candidate_role, candidate_label)
                                for candidate_role, labels in expanded_roles
                                for candidate_label in labels
                                if label_text == candidate_label or label_text.startswith(candidate_label + " ")), None)
                if not matched:
                    continue
                if matched[0] is not IdentityCandidateRole.LABORATORY and ":" not in line:
                    continue
                inline = self._clean_value(line.split(":", 1)[1]) if ":" in line else None
                if inline:
                    continue
                following = [candidate for candidate in lines[index + 1:index + 4] if candidate]
                known_labels = tuple(label for _, labels in expanded_roles for label in labels)
                following_is_label = bool(following and any(
                    self._normalize_label(following[0]).startswith(label) for label in known_labels
                ))
                value = following[0] if following and not following_is_label and not self._looks_like_label(following[0]) else None
                if (not value and matched[0] is IdentityCandidateRole.LABORATORY
                        and following and self._normalize_label(following[0]).startswith("preparing the report")
                        and len(following) > 1 and not self._looks_like_label(following[1])):
                    value = following[1]
                if value:
                    candidate_role, candidate_label = matched
                    found.append(self._identity_candidate(
                        value, candidate_role, candidate_label, page_number,
                        f"{line} {value}", "MULTILINE_STRUCTURED_FIELD", 105, .99,
                    ))
            for embedded in re.finditer(
                r"(?im)^\s*models?\s+(?P<value>[A-Za-z0-9][A-Za-z0-9_./()?-]{2,})\s*:", page
            ):
                found.append(self._identity_candidate(
                    embedded.group("value"), IdentityCandidateRole.DECLARED_MODEL,
                    "Model", page_number, embedded.group(0), "EMBEDDED_LABEL_VALUE", 115, .99,
                ))
            for version_match in re.finditer(
                r"\b(?:ver(?:sion)?|rev(?:ision)?|issue)\.?\s*[-:]?\s*\d+(?:\.\d+)*\b",
                page, re.I,
            ):
                found.append(self._identity_candidate(
                    version_match.group(0), IdentityCandidateRole.DOCUMENT_VERSION,
                    version_match.group(0).split(".", 1)[0], page_number,
                    version_match.group(0), "LEXICAL_EXPLICIT_ROLE", 80, .95,
                ))
            for role, labels in self._IDENTITY_LABEL_ROLES:
                for label in sorted(labels, key=len, reverse=True):
                    pattern = re.compile(
                        rf"(?im)^\s*(?P<label>{re.escape(label)})[\s.…·_-]{{0,45}}[:：]\s*(?P<value>[^\n]*)"
                    )
                    for match in pattern.finditer(page):
                        value = self._clean_value(match.group("value"))
                        if not value or self._looks_like_label(value):
                            continue
                        actual_role = role
                        if role is IdentityCandidateRole.REPORT_NUMBER and self._version_like(value):
                            actual_role = IdentityCandidateRole.DOCUMENT_VERSION
                        elif role is IdentityCandidateRole.REPORT_NUMBER:
                            value = self._report_number_component(value)
                        found.append(self._identity_candidate(
                            value, actual_role, match.group("label"), page_number,
                            match.group(0), "TEXT_LABEL", 90, .99,
                        ))
        if page_blocks:
            found.extend(self._geometry_identity_candidates(page_blocks[: min(8, len(page_blocks))]))

        # An unbound front-page token can be a model candidate only when an
        # explicit model label is present but has no plausible bound value.
        if page_blocks and not any(c.candidate_role is IdentityCandidateRole.DECLARED_MODEL
                                   and self._plausible_model_value(c.raw_value) for c in found):
            front_text = "\n".join(pages[: min(2, len(pages))])
            if re.search(r"(?im)^\s*(?:model(?:\s*(?:/|and/or)\s*type)?(?:\s+(?:no|number|reference|designation))?)\b", front_text):
                occupied = {c.normalized_value.casefold() for c in found}
                for page_number, blocks in enumerate(page_blocks[:2], 1):
                    for index, block in enumerate(blocks):
                        value = self._clean_value(str(block[4]))
                        if (value and self._plausible_model_value(value)
                                and self._normalize_identity(value).casefold() not in occupied):
                            found.append(self._identity_candidate(
                                value, IdentityCandidateRole.DECLARED_MODEL, "Model",
                                page_number, value, "STRUCTURAL_FALLBACK", 55, .72,
                                f"block:{page_number}:{index}",
                            ))

        found = self._dedupe_identity_candidates(found)
        self._select_identity_candidates(found)
        source_roles = {
            IdentityCandidateRole.REPORT_NUMBER, IdentityCandidateRole.DOCUMENT_VERSION,
            IdentityCandidateRole.INTERNAL_IDENTIFIER, IdentityCandidateRole.REPORT_TITLE,
            IdentityCandidateRole.REPORT_DATE, IdentityCandidateRole.LABORATORY,
        }
        return ([c for c in found if c.candidate_role in source_roles],
                [c for c in found if c.candidate_role not in source_roles])

    def _geometry_identity_candidates(
        self, pages: Sequence[Sequence[Tuple[Any, ...]]]
    ) -> List[IdentityCandidate]:
        output: List[IdentityCandidate] = []
        for page_number, blocks in enumerate(pages, 1):
            cleaned: List[Tuple[Any, float, float, float, float, str]] = []
            for i, b in enumerate(blocks):
                if len(b) < 5 or not str(b[4]).strip():
                    continue
                lines = [re.sub(r"\s+", " ", line).strip()
                         for line in str(b[4]).splitlines() if line.strip()]
                height = max(1.0, float(b[3]) - float(b[1]))
                for line_index, line in enumerate(lines):
                    line_y0 = float(b[1]) + height * line_index / len(lines)
                    line_y1 = float(b[1]) + height * (line_index + 1) / len(lines)
                    cleaned.append((f"{i}.{line_index}", float(b[0]), line_y0,
                                    float(b[2]), line_y1, line))
            for index, x0, y0, x1, y1, text in cleaned:
                normalized = self._normalize_label(text.split(":", 1)[0])
                matched = next(((role, label) for role, labels in self._IDENTITY_LABEL_ROLES
                                for label in labels if normalized == label or
                                (label != "type" and normalized.startswith(label + " "))), None)
                if not matched:
                    # Values in an extreme page margin are internal artifacts,
                    # never source report numbers or product names.
                    if page_number == 1 and y0 < 30 and x0 < 60 and len(text) <= 80:
                        output.append(self._identity_candidate(
                            text, IdentityCandidateRole.INTERNAL_IDENTIFIER, None,
                            page_number, text, "PAGE_MARGIN", 40, .75,
                            f"block:{page_number}:{index}",
                        ))
                    continue
                role, label = matched
                inline = self._clean_value(text.split(":", 1)[1]) if ":" in text else None
                if inline and not self._looks_like_label(inline):
                    actual = IdentityCandidateRole.DOCUMENT_VERSION if (
                        role is IdentityCandidateRole.REPORT_NUMBER and self._version_like(inline)
                    ) else role
                    if actual is IdentityCandidateRole.REPORT_NUMBER:
                        inline = self._report_number_component(inline)
                    output.append(self._identity_candidate(
                        inline, actual, label, page_number, text, "GEOMETRY_INLINE",
                        100, .99, f"block:{page_number}:{index}",
                    ))
                    continue
                block_prefix = str(index).split(".", 1)[0]
                aligned = [item for item in cleaned if (
                           item[1] >= x0 + 95 or (
                               str(item[0]).split(".", 1)[0] == block_prefix
                               and item[2] >= y1 - 1
                           ))
                           and (min(y1, item[4]) - max(y0, item[2]) > -3 or
                                str(item[0]).split(".", 1)[0] == block_prefix)
                           and item[0] != index and not self._looks_like_label(item[5])]
                if not aligned:
                    continue
                target = min(aligned, key=lambda item: (abs(item[2] - y0), item[1]))
                value = self._clean_value(target[5])
                if not value:
                    continue
                actual = IdentityCandidateRole.DOCUMENT_VERSION if (
                    role is IdentityCandidateRole.REPORT_NUMBER and self._version_like(value)
                ) else role
                if actual is IdentityCandidateRole.REPORT_NUMBER:
                    value = self._report_number_component(value)
                output.append(self._identity_candidate(
                    value, actual, label, page_number, f"{text} {target[5]}",
                    "GEOMETRY_ADJACENCY", 110, .99,
                    f"block:{page_number}:{index}->block:{page_number}:{target[0]}",
                ))
        return output

    def _identity_candidate(
        self, value: str, role: IdentityCandidateRole, label: Optional[str], page: int,
        source_text: str, method: str, priority: int, confidence: float,
        structure: Optional[str] = None,
    ) -> IdentityCandidate:
        raw = self._clean_value(value) or value.strip()
        if role in {IdentityCandidateRole.DECLARED_MODEL, IdentityCandidateRole.MODEL_NUMBER,
                    IdentityCandidateRole.TESTED_MODEL, IdentityCandidateRole.REPRESENTATIVE_MODEL,
                    IdentityCandidateRole.TYPE_REFERENCE}:
            raw = re.sub(r"^models?\s*:\s*", "", raw, flags=re.I)
            raw = re.sub(r"\s*\([^)]*\b(?:see\s+)?(?:attachment|annex|appendix)\b[^)]*$", "", raw, flags=re.I).strip()
        normalized = self._normalize_identity(raw)
        token = hashlib.sha256(
            f"{role.value}|{normalized}|{page}|{label}|{method}|{structure}".encode()
        ).hexdigest()[:16].upper()
        validation = self.identity_validator.validate_candidate(
            role.value, raw, label, source_text, page,
            source_authority=self.identity_validator.source_authority(role.value, label, source_text),
        )
        return IdentityCandidate(
            candidate_id=f"IDENTITY-CANDIDATE-{token}", raw_value=raw,
            normalized_value=normalized, candidate_role=role, source_label=label,
            source_section="REPORT_FRONT_MATTER", source_page=page,
            source_structure_reference=structure, source_text=source_text,
            confidence=confidence, extraction_method=method,
            candidate_priority=priority,
            accepted=validation.accepted,
            rejection_reason=validation.rejection_reason,
            source_authority=validation.source_authority,
            authority_rank=validation.authority_rank,
            confidence_before=confidence,
            confidence_after=max(0.0, min(1.0, confidence + validation.confidence_adjustment)),
        )

    @staticmethod
    def _version_like(value: str) -> bool:
        return bool(re.fullmatch(r"\s*(?:ver(?:sion)?|rev(?:ision)?|issue)\.?\s*[-:]?\s*\d+(?:\.\d+)*\s*", value, re.I))

    @staticmethod
    def _report_number_component(value: str) -> str:
        """Remove an independently labelled/version-prefixed trailing role."""

        return re.split(r"\s+(?=(?:ver(?:sion)?|rev(?:ision)?|issue)\.?\s*[-:]?\s*\d)",
                        value.strip(), maxsplit=1, flags=re.I)[0].strip()

    @staticmethod
    def _plausible_model_value(value: str) -> bool:
        cleaned = re.sub(r"\s+", " ", value).strip()
        return bool(len(cleaned) <= 80 and re.search(r"[A-Za-z]", cleaned)
                    and (re.search(r"\d", cleaned) or re.search(r"\([A-Za-z]{1,8}\)", cleaned))
                    and not re.search(r"\s{2,}", cleaned)
                    and ":" not in cleaned and "..." not in cleaned
                    and not re.search(r"\b(?:page|report|version|ver|date)\b", cleaned, re.I))

    @staticmethod
    def _dedupe_identity_candidates(items: Sequence[IdentityCandidate]) -> List[IdentityCandidate]:
        unique: Dict[Tuple[str, str, Optional[int], Optional[str]], IdentityCandidate] = {}
        for item in items:
            key = (item.candidate_role.value, item.normalized_value.casefold(),
                   item.source_page, item.source_structure_reference)
            prior = unique.get(key)
            if prior is None or (item.candidate_priority, item.confidence) > (prior.candidate_priority, prior.confidence):
                unique[key] = item
        return sorted(unique.values(), key=lambda item: (
            item.candidate_role.value, -item.candidate_priority,
            item.source_page or 10**9, item.normalized_value.casefold(),
        ))

    def _select_identity_candidates(self, items: List[IdentityCandidate]) -> None:
        for role in IdentityCandidateRole:
            candidates = [item for item in items if item.candidate_role is role]
            if not candidates:
                continue
            plausible = [item for item in candidates if item.accepted]
            if role is IdentityCandidateRole.DECLARED_MODEL:
                plausible = [item for item in plausible if self._plausible_model_value(item.raw_value)]
            if role is IdentityCandidateRole.REPORT_NUMBER:
                non_dates = [item for item in candidates if not self._is_date_value(item.raw_value)]
                if non_dates:
                    plausible = non_dates
                substantive = [item for item in plausible
                               if not re.fullmatch(r"\d{1,3}", item.raw_value)]
                if substantive:
                    plausible = substantive
            if not plausible:
                continue
            support = Counter(item.normalized_value.casefold() for item in plausible)
            ranked = sorted(plausible, key=lambda item: (
                -support[item.normalized_value.casefold()], -item.authority_rank, -item.candidate_priority,
                -item.confidence, item.source_page or 10**9,
                item.normalized_value.casefold(),
            ))
            winner = ranked[0]
            winner.selected = True
            winner.selection_reason = "Highest source-label and structural authority for semantic role."
            if role is IdentityCandidateRole.DECLARED_MODEL:
                for explicit in plausible:
                    if explicit.extraction_method == "EMBEDDED_LABEL_VALUE":
                        explicit.selected = True
                        explicit.selection_reason = "Explicit identifier embedded in a structured model row."
            for alternative in ranked[1:]:
                if alternative.normalized_value.casefold() != winner.normalized_value.casefold():
                    alternative.conflicts.append(winner.candidate_id)

    @staticmethod
    def _selected_candidate_value(
        items: Sequence[IdentityCandidate], role: IdentityCandidateRole
    ) -> Optional[str]:
        return next((item.normalized_value for item in items
                     if item.candidate_role is role and item.selected), None)

    @staticmethod
    def _selected_candidate_values(
        items: Sequence[IdentityCandidate], role: IdentityCandidateRole
    ) -> List[str]:
        return [item.normalized_value for item in items
                if item.candidate_role is role and item.selected]

    @staticmethod
    def _selection_provenance(items: Sequence[IdentityCandidate]) -> Dict[str, Dict[str, Any]]:
        return {item.candidate_role.value: {
            "candidate_id": item.candidate_id, "source_page": item.source_page,
            "source_label": item.source_label, "source_text": item.source_text,
            "selection_rule": item.selection_reason, "confidence": item.confidence,
            "source_authority": item.source_authority, "authority_rank": item.authority_rank,
        } for item in items if item.selected}

    @classmethod
    def _columnar_identity_values(
        cls, pages: Sequence[str]
    ) -> Optional[Tuple[str, str]]:
        """Recover generic product/brand columns emitted after their labels."""

        product_labels = ("test item description", "test item", "product name", "product")
        brand_labels = ("trade mark", "trademark", "brand")
        for page in pages:
            lines = [re.sub(r"\s+", " ", line).strip() for line in page.splitlines()]
            product_index = next((i for i, line in enumerate(lines)
                                  if any(cls._normalize_label(line).startswith(label)
                                         for label in product_labels)), None)
            brand_index = next((i for i, line in enumerate(lines)
                                if any(cls._normalize_label(line).startswith(label)
                                       for label in brand_labels)), None)
            if product_index is None or brand_index is None or product_index >= brand_index:
                continue
            label_indices = [i for i, line in enumerate(lines)
                             if cls._looks_like_label(line)]
            if len(label_indices) < 3:
                continue
            last_label = max(label_indices)
            candidates: List[str] = []
            for line in lines[last_label + 1:]:
                if not line or len(line) > 100 or cls._looks_like_label(line):
                    continue
                if re.fullmatch(r"(?:yes|no|n/?a|pass|fail|\d+)", line, re.I):
                    continue
                if re.search(r"\b(?:page|report\s+no|laboratory|telephone|tel)\b", line, re.I):
                    continue
                candidates.append(line.strip(" .:;"))
            if len(candidates) >= 2:
                return candidates[0], candidates[1]
        return None

    def _extract_identity_relationships(
        self, pages: Sequence[str], identity: ProductIdentity
    ) -> List[ProductIdentityRelationship]:
        """Retain explicit equivalence/test-scope statements without inferring them."""

        relationships: List[ProductIdentityRelationship] = []
        patterns = (
            ("DECLARED_EQUIVALENCE", re.compile(
                r"[^\n]*(?:all\s+models?|models?)\s+(?:are|were)\s+(?:technically\s+)?"
                r"(?:identical|(?:the\s+)?same)\s+except\s+(?:for\s+)?[^\n]+", re.I)),
            ("CONSTRUCTION_CHECK_SCOPE", re.compile(
                r"[^\n]*construction\s+checks?\s+(?:are|were\s+)?performed\s+on\s+all\s+models?[^\n]*", re.I)),
        )
        for page_number, page in enumerate(pages[: min(12, len(pages))], 1):
            for relation_type, pattern in patterns:
                for match in pattern.finditer(page):
                    raw = re.sub(r"\s+", " ", match.group(0)).strip()
                    representative = match.groupdict().get("model")
                    token = hashlib.sha256(
                        f"{relation_type}|{page_number}|{raw}".encode()
                    ).hexdigest()[:16].upper()
                    relationships.append(ProductIdentityRelationship(
                        relationship_id=f"IDENTITY-REL-{token}",
                        relationship_type=relation_type,
                        subject_values=list(identity.model_numbers),
                        representative_value=representative,
                        raw_text=raw,
                        source_page=page_number,
                    ))
        unique = {item.relationship_id: item for item in relationships}
        return sorted(unique.values(), key=lambda item: (item.source_page or 0,
                                                          item.relationship_id))

    def _extract_identity_observations(
        self, pages: Sequence[str], document_id: Optional[str], identity: ProductIdentity
    ) -> List[ProductIdentityObservation]:
        """Retain independently sourced identities without comparing them."""

        found: List[ProductIdentityObservation] = []
        role_patterns = [
            (ProductIdentityRole.TESTED_MODEL,
             re.compile(r"\b(?:(?:all\s+)?tests?\s+(?:(?:are|were)\s+)?performed\s+on\s+(?:the\s+)?(?:model\s+)?|"
                        r"tested\s+model|model\s+tested)\s*[:：]?\s*([^\s,;]+)", re.I)),
            (ProductIdentityRole.REPRESENTATIVE_MODEL,
             re.compile(r"\brepresentative\s+model\s*[:：]?\s*([^\s,;]+)", re.I)),
            (ProductIdentityRole.SAMPLE_MODEL,
             re.compile(r"\bsample\s+model\s*[:：]?\s*([^\s,;]+)", re.I)),
            (ProductIdentityRole.SERIES_MODEL,
             re.compile(r"\bseries\s+model\s*[:：]?\s*([^\s,;]+)", re.I)),
            (ProductIdentityRole.ALTERNATE_MODEL,
             re.compile(r"\balternate\s+model\s*[:：]?\s*([^\s,;]+)", re.I)),
        ]
        # Identity metadata and representative-sample declarations belong to
        # report front matter.  Limiting this scan avoids treating later
        # requirement prose (for example "product designation") as a model.
        for page_number, page in enumerate(pages[: min(8, len(pages))], 1):
            for role, pattern in role_patterns:
                for match in pattern.finditer(page):
                    if not self.identity_validator.validate_candidate(
                        role.value, match.group(1),
                        match.group(0).split(match.group(1), 1)[0].strip(), match.group(0),
                    ).accepted:
                        continue
                    observation=self._identity_observation(
                        ProductIdentityType.MODEL, role, match.group(1), document_id,
                        page_number, match.group(0), match.group(0).split(match.group(1), 1)[0].strip(),
                        "TEST_SUMMARY" if role is ProductIdentityRole.TESTED_MODEL else "REPORT_METADATA",
                    )
                    found.append(observation)
                    if role is ProductIdentityRole.TESTED_MODEL and re.search(
                        r"\ball\s+models?\s+(?:are|were)\s+(?:the\s+)?same\s+except\b|"
                        r"\bmodels?\s+are\s+identical\s+except\b", page, re.I
                    ):
                        found.append(self._identity_observation(
                            ProductIdentityType.MODEL, ProductIdentityRole.REPRESENTATIVE_MODEL,
                            match.group(1), document_id, page_number, match.group(0),
                            "Source-supported representative/tested model", "TEST_SUMMARY",
                        ))
            labelled = [
                (ProductIdentityType.SAMPLE_ID, ProductIdentityRole.UNKNOWN_MODEL_ROLE,
                 r"sample\s+(?:identification|id)"),
                (ProductIdentityType.PRODUCT_CODE, ProductIdentityRole.UNKNOWN_MODEL_ROLE,
                 r"product\s+code"),
                (ProductIdentityType.MODEL, ProductIdentityRole.UNKNOWN_MODEL_ROLE,
                 r"product\s+designation"),
            ]
            for identity_type, role, label in labelled:
                pattern = re.compile(rf"(?im)^\s*(?P<label>{label})\s*[:：]\s*(?P<value>[^\n]+)")
                for match in pattern.finditer(page):
                    if not self._plausible_identity_value(match.group("value")):
                        continue
                    found.append(self._identity_observation(
                        identity_type, role, match.group("value"), document_id,
                        page_number, match.group(0), match.group("label"), "REPORT_METADATA",
                    ))

        def locate(value: str) -> tuple[Optional[int], str]:
            for page_number, page in enumerate(pages, 1):
                if value in page:
                    line = next((line.strip() for line in page.splitlines() if value in line), value)
                    return page_number, line
            return None, value

        represented = {(item.identity_type, item.role, item.normalized_value) for item in found}
        for value in identity.model_numbers:
            normalized = self._normalize_identity(value)
            if (ProductIdentityType.MODEL, ProductIdentityRole.DECLARED_MODEL, normalized) not in represented:
                page, raw = locate(value)
                found.append(self._identity_observation(
                    ProductIdentityType.MODEL, ProductIdentityRole.DECLARED_MODEL, value,
                    document_id, page, raw, "Model", "REPORT_COVER",
                ))
        for value in identity.type_references:
            page, raw = locate(value)
            found.append(self._identity_observation(
                ProductIdentityType.TYPE_REFERENCE, ProductIdentityRole.UNKNOWN_MODEL_ROLE,
                value, document_id, page, raw, "Type reference", "PRODUCT_DESCRIPTION",
            ))
        for value in identity.serial_numbers:
            if not isinstance(value, str):
                continue
            page, raw = locate(value)
            found.append(self._identity_observation(
                ProductIdentityType.SERIAL_NUMBER, ProductIdentityRole.UNKNOWN_MODEL_ROLE,
                value, document_id, page, raw, "Serial number", "REPORT_METADATA",
            ))
        unique: Dict[tuple, ProductIdentityObservation] = {}
        for item in found:
            key = (item.identity_type.value, item.role.value, item.normalized_value,
                   item.evidence[0].page if item.evidence else None, item.source_context)
            unique.setdefault(key, item)
        return sorted(unique.values(), key=lambda item: (
            item.evidence[0].page if item.evidence and item.evidence[0].page is not None else 10**9,
            item.identity_type.value, item.role.value, item.normalized_value,
        ))

    @staticmethod
    def _plausible_identity_value(value: str) -> bool:
        """Reject prose/list rows accidentally following identity-like labels."""

        cleaned = re.sub(r"\s+", " ", value).strip()
        return bool(cleaned and len(cleaned) <= 80 and not cleaned.startswith(("-", "•")))

    def _identity_observation(
        self, identity_type: ProductIdentityType, role: ProductIdentityRole, value: str,
        document_id: Optional[str], page: Optional[int], raw_text: str, raw_label: str,
        source_context: str,
    ) -> ProductIdentityObservation:
        raw_value = re.sub(r"\s+", " ", value).strip().strip(".,;:")
        normalized = self._normalize_identity(raw_value)
        token = hashlib.sha256(
            f"{identity_type.value}|{role.value}|{normalized}|{page}|{source_context}".encode()
        ).hexdigest()[:16].upper()
        evidence_id = f"IDENTITY-EV-{token}"
        evidence = ProductFactEvidence(
            evidence_id=evidence_id, source_type=EvidenceSourceType.REPORT_METADATA,
            source_document_id=document_id, page=page, raw_text=raw_text,
            observed_value=raw_value, notes=f"Identity source context: {source_context}",
        )
        return ProductIdentityObservation(
            identity_id=f"IDENTITY-{token}", identity_type=identity_type, role=role,
            value=raw_value, normalized_value=normalized,
            status=ProductFactStatus.CONFIRMED, source_evidence_ids=[evidence_id],
            evidence=[evidence], raw_label=raw_label, source_context=source_context,
            confidence=.99,
        )

    @staticmethod
    def _normalize_identity(value: str) -> str:
        """Apply Unicode/whitespace normalization without deleting separators."""

        import unicodedata
        return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()

    @staticmethod
    def _normalize_product_type(value: str) -> str:
        """Normalize a report-stated product name for condition matching."""

        words = re.sub(r"\s+", " ", value).strip().casefold().split()
        if words and words[-1].endswith("s") and words[-1] != "class":
            words[-1] = words[-1][:-1]
        return " ".join(words)

    def _extract_labeled_facts(
        self, pages: Sequence[str], document_id: Optional[str],
        *, identity: Optional[ProductIdentity] = None,
    ) -> List[_Candidate]:
        output: List[_Candidate] = []
        front_pages = pages[: min(12, len(pages))]
        enum_patterns = {
            "protection_class": [
                (r"\bclass\s+0I\b", "CLASS_0I"), (r"\bclass\s+III\b", "CLASS_III"),
                (r"\bclass\s+II\b", "CLASS_II"), (r"\bclass\s+I\b", "CLASS_I"),
                (r"\bclass\s+0\b", "CLASS_0"),
            ],
            "attachment_type": [(r"\btype\s+X\b", "TYPE_X"),
                                (r"\btype\s+Y\b", "TYPE_Y"),
                                (r"\btype\s+Z\b", "TYPE_Z")],
            "installation_type": [(r"\bstationary\s+appliance\b", "STATIONARY"),
                                  (r"\bportable\s+appliance\b", "PORTABLE"),
                                  (r"\bfixed\s+appliance\b", "FIXED"),
                                  (r"\bwall[ -]mounted\b", "WALL_MOUNTED"),
                                  (r"\bceiling[ -]mounted\b", "CEILING_MOUNTED"),
                                  (r"\bbuilt[ -]in\b", "BUILT_IN")],
            "loading_type": [(r"\bfront[ -]load(?:ed|ing)?\b", "FRONT"),
                             (r"\btop[ -]load(?:ed|ing)?\b", "TOP")],
        }
        enum_context = {
            "protection_class": re.compile(r"(?:classification|protection\s+class|class\s+of\s+appliance)[^\n]{0,80}", re.IGNORECASE),
            "attachment_type": re.compile(r"(?:supply\s+connection|attachment\s+type)[^\n]{0,80}", re.IGNORECASE),
            "installation_type": re.compile(r"(?:classification\s+of\s+installation(?:\s+and\s+use)?|installation\s+type)[^\n]{0,100}", re.IGNORECASE),
            "loading_type": re.compile(r"(?:loading\s+type|product\s+description)[^\n]{0,100}", re.IGNORECASE),
        }
        for page_number, page in enumerate(front_pages, 1):
            flattened = re.sub(r"\s+", " ", page)
            for feature_id, patterns in enum_patterns.items():
                feature = self.registry.get(feature_id)
                if feature is None:
                    continue
                contexts = [match.group(0) for match in enum_context[feature_id].finditer(flattened)]
                for context in contexts:
                    if feature_id == "protection_class" and re.search(
                        r"class\s+0\s*,\s*0I\s*,\s*I\s*,\s*II\s*,\s*III", context, re.I
                    ):
                        continue
                    matches = [(match.start(), value) for pattern, value in patterns
                               for match in [re.search(pattern, context, re.IGNORECASE)] if match]
                    distinct_values = {value for _, value in matches}
                    if len(distinct_values) == 1:
                        value = next(iter(distinct_values))
                        output.append(self._candidate(feature, value, ProductFactStatus.CONFIRMED,
                            .98, EvidenceSourceType.REPORT_METADATA, document_id,
                            page_number, context, observed=value))
            protection = self.registry.get("protection_class")
            if protection:
                for line in (re.sub(r"\s+", " ", raw).strip() for raw in page.splitlines()):
                    if not re.search(r"\b(?:classification|protection\s+class|supply\s+connection|products?\s+(?:are|is))\b", line, re.I):
                        continue
                    values = [value for pattern, value in enum_patterns["protection_class"]
                              if re.search(pattern, line, re.I)]
                    if len(set(values)) == 1:
                        value = values[0]
                        output.append(self._candidate(
                            protection, value, ProductFactStatus.CONFIRMED, .99,
                            EvidenceSourceType.REPORT_METADATA, document_id, page_number,
                            line, observed=value, notes="Explicit report product-class field or assertion.",
                        ))
            ip_feature = self.registry.get("ip_rating")
            if ip_feature:
                lines = [re.sub(r"\s+", " ", raw).strip() for raw in page.splitlines()]
                for index, line in enumerate(lines):
                    if not re.search(r"\b(?:IP\s+number|ingress\s+protection)\b", line, re.I):
                        continue
                    following = next((item for item in lines[index + 1:index + 4] if item), "")
                    ip_match = re.fullmatch(r"IP\s*[0-9X]{2,4}", following, re.I)
                    if ip_match:
                        value = re.sub(r"\s+", "", ip_match.group(0)).upper()
                        output.append(self._candidate(
                            ip_feature, value, ProductFactStatus.CONFIRMED, .99,
                            EvidenceSourceType.REPORT_METADATA, document_id, page_number,
                            f"{line} {following}", observed=value,
                            notes="Explicit IP classification field.",
                        ))
        measurement_features = [
            self.registry.get("rated_voltage"), self.registry.get("rated_frequency"),
            self.registry.get("rated_current"), self.registry.get("rated_power_input"),
        ]
        for page_number, page in enumerate(front_pages, 1):
            normalized = re.sub(r"[ \t]+", " ", page)
            for feature in measurement_features:
                if feature is None:
                    continue
                aliases = sorted(feature.aliases + [feature.key.replace("_", " ")], key=len, reverse=True)
                for alias in aliases:
                    pattern = re.compile(
                        rf"{re.escape(alias)}[\s\S]{{0,220}}?(?:[:.]|\n)\s*{self._VALUE_RE}", re.IGNORECASE
                    )
                    for match in pattern.finditer(normalized):
                        unit = match.group("unit")
                        if unit.casefold() != (feature.unit or "").casefold():
                            continue
                        a = self._number(match.group("a")); b = self._number(match.group("b")) if match.group("b") else None
                        value: Any = {"value": a, "unit": feature.unit} if b is None else {
                            "min": a, "max": b, "unit": feature.unit,
                        }
                        raw = match.group(0).strip()
                        output.append(self._candidate(feature, value, ProductFactStatus.CONFIRMED,
                            .99, EvidenceSourceType.REPORT_METADATA, document_id,
                            page_number, raw, observed=match.group(0)))
        # Generic product label maps directly to the canonical string feature.
        # Consume the already role-resolved identity.  Re-extracting without
        # structural candidates can demote a brand, model, or internal document
        # identifier into PRODUCT_NAME and thereby contaminate PRODUCT_TYPE.
        product = (identity.product_type or identity.product_name) if identity is not None else None
        feature = self.registry.get("product_type")
        if product and feature:
            normalized_product = self._normalize_product_type(product)
            output.append(self._candidate(feature, normalized_product, ProductFactStatus.CONFIRMED, .99,
                EvidenceSourceType.REPORT_METADATA, document_id, None,
                f"Product: {product}", observed=normalized_product))
        # An explicitly reported product designation may itself be a registry
        # alias (for example, a product function). Map it only when unique.
        if product:
            alias_matches = [item for item in self.registry.search_alias(product)
                             if item.data_type is FeatureDataType.BOOLEAN]
            if len(alias_matches) == 1:
                output.append(self._candidate(alias_matches[0], True,
                    ProductFactStatus.CONFIRMED, .95,
                    EvidenceSourceType.REPORT_METADATA, document_id, None,
                    f"Product: {product}", observed=product,
                    notes="Mapped from an explicit product designation via a unique registry alias."))
            elif len(alias_matches) > 1:
                self._diagnostics.append(ProductProfileDiagnostic(
                    ProfileDiagnosticCategory.AMBIGUOUS_FEATURE_MAPPING,
                    "Product designation maps to multiple canonical Boolean features",
                    raw_text=product,
                    candidate_features=[item.key for item in alias_matches]))
        # Compact rating fields commonly carry several independently useful
        # observations on one source-backed line.
        rating_values = self._all_label_values(
            "\n".join(front_pages),
            ["Product Specifications", "Technical data", "Specifications", "Ratings", "Rating"],
        )
        for page in front_pages:
            for match in re.finditer(
                r"(?im)^\s*(?:ratings?|product specifications|technical data|specifications)"
                r"[\s.…·_-]{0,45}[:：]\s*([^\n]+)", page,
            ):
                value = self._clean_value(match.group(1))
                if value:
                    rating_values.append(value)
        for page in front_pages:
            lines = [re.sub(r"\s+", " ", line).strip() for line in page.splitlines()]
            for index, line in enumerate(lines):
                if not re.match(r"^ratings?\b", self._normalize_label(line)):
                    continue
                values = []
                for following in lines[index + 1:index + 8]:
                    if not following:
                        continue
                    if self._looks_like_label(following):
                        break
                    values.append(following)
                if values:
                    rating_values.append(" ".join(values))
        for rating in self._unique(rating_values):
            page_number = next((number for number, page in enumerate(front_pages, 1)
                                if rating in re.sub(r"\s+", " ", page)), None)
            patterns = [
                ("rated_voltage", r"(\d+(?:[.,]\d+)?)(?:\s*[-–—]\s*(\d+(?:[.,]\d+)?))?\s*V\b", "V"),
                ("rated_capacity", r"(\d+(?:[.,]\d+)?)\s*Ah\b", "Ah"),
                ("rated_frequency", r"(\d+(?:[.,]\d+)?)(?:\s*(?:/|[-–—])\s*(\d+(?:[.,]\d+)?))?\s*Hz\b", "Hz"),
                ("rated_current", r"(\d+(?:[.,]\d+)?)\s*A\b", "A"),
                ("rated_power_input", r"(\d+(?:[.,]\d+)?)(?:\s*/\s*(\d+(?:[.,]\d+)?))?\s*W\b", "W"),
            ]
            for feature_id, pattern, unit in patterns:
                feature = self.registry.get(feature_id)
                if feature is None:
                    continue
                for match in re.finditer(pattern, rating, re.IGNORECASE):
                    first = self._number(match.group(1))
                    second = self._number(match.group(2)) if match.lastindex and match.lastindex > 1 and match.group(2) else None
                    if feature_id == "rated_power_input" and second is not None:
                        for state_value in (first, second):
                            value = {"value": state_value, "unit": unit}
                            output.append(self._candidate(
                                feature, value, ProductFactStatus.CONFIRMED, .99,
                                EvidenceSourceType.REPORT_METADATA, document_id, page_number,
                                f"Ratings: {rating}", observed=value,
                                notes="State-specific observation from compact report rating field.",
                            ))
                        continue
                    value = ({"value": first, "unit": unit} if second is None else
                             {"min": first, "max": second, "unit": unit})
                    output.append(self._candidate(
                        feature, value, ProductFactStatus.CONFIRMED, .99,
                        EvidenceSourceType.REPORT_METADATA, document_id, page_number,
                        f"Ratings: {rating}", observed=value,
                        notes="Observation from compact report rating field.",
                    ))
            additional = [
                ("ip_rating", r"\b(IP\s*[0-9X]{2,4})\b", None),
                ("no_load_speed", r"(?:\bn\s*0\b|no[- ]load\s+speed)\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*[-–—]\s*(\d+(?:[.,]\d+)?)\s*/?\s*min\b", "min-1"),
                ("tool_capacity", r"\b(?:[A-Za-z -]+\s+)?capacity\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*mm\b", "mm"),
                ("sound_pressure_level", r"\b(?:sound|noise)\s+pressure(?:\s+level)?\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*dB\b", "dB"),
                ("vibration_magnitude", r"\bvibration(?:\s+(?:magnitude|emission\s+value))?\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*m/s(?:²|2)\b", "m/s2"),
            ]
            for feature_id, pattern, unit in additional:
                match = re.search(pattern, rating, re.IGNORECASE)
                feature = self.registry.get(feature_id)
                if not match or feature is None:
                    continue
                if feature_id == "ip_rating":
                    value = re.sub(r"\s+", "", match.group(1)).upper()
                elif match.lastindex and match.lastindex > 1 and match.group(2):
                    value = {"min": self._number(match.group(1)),
                             "max": self._number(match.group(2)), "unit": unit}
                else:
                    value = {"value": self._number(match.group(1)), "unit": unit}
                output.append(self._candidate(
                    feature, value, ProductFactStatus.CONFIRMED, .99,
                    EvidenceSourceType.REPORT_METADATA, document_id, page_number,
                    f"Specifications: {rating}", observed=value,
                    notes="Observation from compact report specification field.",
                ))
            phase_feature = self.registry.get("number_of_phases")
            phase_matches = list(re.finditer(
                r"(?:(?:\d+(?:[.,]\d+)?)\s*(?:[-–—]\s*\d+(?:[.,]\d+)?)?\s*V\s*)?"
                r"\b([123])\s*N?\s*~", rating, re.IGNORECASE,
            ))
            distinct_phases = {int(match.group(1)) for match in phase_matches}
            for match in phase_matches:
                prefix = rating[:match.start()]
                scope_match = list(re.finditer(
                    r"\b(?:model|configuration)\s+([A-Za-z0-9_./()\-]+)", prefix, re.IGNORECASE,
                ))
                model_scope = scope_match[-1].group(1) if scope_match else None
                scope_type = ("CONFIGURATION_SCOPE" if len(distinct_phases) > 1 else
                              "MODEL_SCOPE" if model_scope else "REPORT_SCOPE")
                output.append(self._candidate(
                    phase_feature, int(match.group(1)), ProductFactStatus.CONFIRMED, .99,
                    EvidenceSourceType.REPORT_METADATA, document_id, page_number,
                    f"Ratings: {rating}", observed=match.group(0).strip(),
                    notes="Explicit phase count retained from a report supply configuration.",
                    scope_type=scope_type, model_scope=model_scope,
                    source_authority="EXPLICIT_STRUCTURED_FIELD", source_label="Ratings",
                ))
            supply_feature = self.registry.get("supply_type")
            if supply_feature and "~" in rating:
                output.append(self._candidate(
                    supply_feature, "AC", ProductFactStatus.CONFIRMED, .99,
                    EvidenceSourceType.REPORT_METADATA, document_id, page_number,
                    f"Ratings: {rating}", observed="~",
                    notes="Explicit alternating-current symbol in the report rating.",
                ))
        return output

    def _extract_explicit_booleans(
        self, pages: Sequence[str], document_id: Optional[str]
    ) -> List[_Candidate]:
        output: List[_Candidate] = []
        boolean_features = [item for item in self.registry.get_all()
                            if item.data_type is FeatureDataType.BOOLEAN]
        for page_number, page in enumerate(pages, 1):
            clause_id: Optional[str] = None
            raw_lines = page.splitlines()
            recent_features: List[Tuple[int, Any, str]] = []
            for line_index, raw_line in enumerate(raw_lines):
                line = re.sub(r"\s+", " ", raw_line).strip()
                clause = self._CLAUSE_RE.fullmatch(line)
                if clause:
                    clause_id = clause.group(1); continue
                if re.match(r"^(?:report\s+(?:no|number)|note|example)\b", line, re.I):
                    continue
                # Treat an explicit questionnaire/table row as an atomic
                # source observation.  PDF text streams commonly emit the
                # next labelled row immediately after it; joining that next
                # row to a trailing ``No`` can otherwise invert the value of
                # the following feature (``first: No`` / ``second: Yes``).
                labelled_boolean = re.fullmatch(
                    r"(?P<label>.+?)[\s.…·_-]{2,}[:：]\s*(?P<value>yes|no)\s*",
                    line,
                    re.IGNORECASE,
                )
                if labelled_boolean:
                    label_words = " ".join(re.sub(
                        r"[^\w]+", " ", labelled_boolean.group("label").casefold()
                    ).split())
                    matches: List[Tuple[int, CanonicalProductFeature]] = []
                    for feature in boolean_features:
                        for alias in {*feature.aliases, feature.key.replace("_", " ")}:
                            alias_words = " ".join(re.sub(
                                r"[^\w]+", " ", alias.casefold()
                            ).split())
                            if alias_words and alias_words in label_words:
                                matches.append((len(alias_words), feature))
                    if matches:
                        longest = max(length for length, _ in matches)
                        features = {feature.key: feature for length, feature in matches
                                    if length == longest}
                        if len(features) == 1:
                            feature = next(iter(features.values()))
                            value = labelled_boolean.group("value").casefold() == "yes"
                            output.append(self._candidate(
                                feature, value, ProductFactStatus.CONFIRMED, .99,
                                EvidenceSourceType.REPORT_METADATA, document_id,
                                page_number, line, clause_id=clause_id,
                                observed=value,
                                notes="Explicit labelled product-particular value.",
                                scope_type="REPORT_SCOPE",
                            ))
                    # Whether mapped or not, this row has a complete explicit
                    # value and must never consume the following labelled row.
                    continue
                if (":" not in line and re.search(
                    r"\b(?:no|without|not\s+provided|not\s+fitted|not\s+incorporated|not\s+used)\b",
                    line, re.I,
                )):
                    continuation = next((re.sub(r"\s+", " ", value).strip()
                                         for value in raw_lines[line_index + 1:line_index + 3]
                                         if value.strip()), "")
                    if continuation:
                        line = f"{line} {continuation}"
                elif re.search(r"\b(?:is|are|was|were)?\s*used\s+(?:to|for)\b",line,re.I):
                    continuation=" ".join(re.sub(r"\s+"," ",value).strip()
                                           for value in raw_lines[line_index+1:line_index+4] if value.strip())
                    if continuation:line=f"{line} {continuation}"
                lower = line.casefold()
                if not line or re.search(r"\b(?:shall|must|standard\s+does\s+not\s+require|do\s+not\s+use|no\s+test\s+shall)\b", lower):
                    continue
                if lower.startswith(("if ", "when ", "unless ", "for appliances", "appliances intended", "be fitted", "appliances ", "note", "example")):
                    continue
                model_match = re.search(r"\bmodel\s+([A-Za-z0-9_./-]+)\b", line, re.I)
                scope_type = "MODEL_SCOPE" if model_match else "REPORT_SCOPE"
                model_scope = model_match.group(1) if model_match else None
                structured_match = re.match(r"^(?P<label>[A-Za-z][A-Za-z /_-]{2,60})[ .…·_-]{2,}\s*:\s*", line)
                structured = structured_match is not None
                line_words = " ".join(re.sub(r"[^\w]+", " ", lower).split())
                for feature in boolean_features:
                    for alias in sorted({*feature.aliases,feature.key.replace("_"," ")},key=len,reverse=True):
                        alias_words=" ".join(re.sub(r"[^\w]+"," ",alias.casefold()).split())
                        if alias_words and alias_words in line_words:
                            recent_features.append((line_index,feature,alias_words));break
                such=re.search(r"\bno\s+such\s+([a-z][a-z -]*?)(?:[.!?,;:]|$)",lower)
                if such:
                    noun=such.group(1).strip().split()[-1].rstrip("s")
                    compatible=[entry for entry in recent_features if line_index-entry[0]<=6
                                and entry[2].split()[-1].rstrip("s")==noun]
                    if compatible:
                        _,feature,_=max(compatible,key=lambda entry:len(entry[2]))
                        output.append(self._candidate(feature,False,ProductFactStatus.CONFIRMED,.95,
                            EvidenceSourceType.REPORT_CLAUSE,document_id,page_number,line,
                            clause_id=clause_id,observed=False,
                            notes="Explicit source-supported contextual absence statement.",
                            scope_type=scope_type,model_scope=model_scope))
                for feature in boolean_features:
                    aliases = sorted({*feature.aliases, feature.key.replace("_", " ")}, key=len, reverse=True)
                    for alias in aliases:
                        # Avoid compiling and executing hundreds of patterns
                        # for aliases not present on this source line.
                        alias_words = " ".join(re.sub(r"[^\w]+", " ", alias.casefold()).split())
                        if alias_words not in line_words:
                            continue
                        escaped = re.escape(alias)
                        negative = self._feature_is_negated_entity(line, escaped)
                        local_container = re.search(
                            rf"\b(?P<container>[A-Za-z][\w -]{{0,45}}?)\s+(?:is|are)\s+not\s+"
                            rf"(?:fitted|provided)\s+with\s+(?:an?\s+)?{escaped}s?\b",
                            line, re.IGNORECASE,
                        )
                        candidate_scope = scope_type
                        if local_container and not re.search(
                            r"\b(?:product|equipment|machine|appliance|tool|device|unit|sample|test item)\b",
                            local_container.group("container"), re.IGNORECASE,
                        ):
                            candidate_scope = "COMPONENT_SCOPE"
                        if negative and re.search(
                            rf"\b{escaped}s?\s+(?:is\s+)?not\s+(?:fitted|provided|used)\s+"
                            r"(?:in|on|to|with)\s+(?:an?\s+|the\s+)?[A-Za-z]",
                            line, re.IGNORECASE,
                        ):
                            candidate_scope = "COMPONENT_SCOPE"
                        positive = None if negative else re.search(
                            rf"(?<!not\s)\b(?:is\s+provided\s+with|provided\s+with|fitted\s+with|incorporates?|includes?|has|(?<!fitted\s)(?<!provided\s)with)\s+(?:an?\s+)?{escaped}\b",
                            line, re.IGNORECASE,
                        )
                        explicit_construction = None if negative else re.search(
                            rf"\b(?:non[- ]detachable|not\s+detachable|detachable)\s+{escaped}s?\b|"
                            rf"\b{escaped}s?\s+(?:without|with)\s+(?:an?\s+)?[A-Za-z]",
                            line, re.IGNORECASE,
                        )
                        source_window = " ".join(
                            re.sub(r"\s+", " ", value).strip()
                            for value in raw_lines[max(0, line_index - 2):line_index + 1]
                        )
                        if positive and re.search(
                            r"\b(?:shall|must|should|may|could)\b", source_window,
                            re.IGNORECASE,
                        ):
                            positive = None
                        usage = None if negative else re.search(
                            rf"\b{re.escape(alias_words)}\b.*\b(?:is\s+|are\s+|was\s+|were\s+)?used\s+(?:to|for)\b",
                            line_words,re.IGNORECASE,
                        )
                        if negative or positive or usage or explicit_construction:
                            value = False if negative else True
                            output.append(self._candidate(feature, value, ProductFactStatus.CONFIRMED,
                                .99 if structured else .95,
                                EvidenceSourceType.REPORT_METADATA if structured else EvidenceSourceType.REPORT_CLAUSE,
                                document_id,
                                page_number, line, clause_id=clause_id, observed=value,
                                notes="Explicit source-supported feature presence statement.",
                                scope_type=candidate_scope, model_scope=model_scope,
                                source_authority=("EXPLICIT_STRUCTURED_FIELD" if structured else "NORMAL_BODY_TEXT"),
                                source_label=(structured_match.group("label").strip() if structured_match else None)))
                            break
        return output

    @staticmethod
    def _feature_is_negated_entity(line: str, escaped_alias: str) -> Optional[re.Match[str]]:
        """Return a match only when the feature noun phrase itself is absent."""

        patterns = (
            rf"\b(?:without|no)\s+(?:an?\s+)?{escaped_alias}s?"
            rf"(?=\s*(?:is|are|was|were|provided|fitted|present|absent|[.!?,;:]|$))",
            rf"\b(?:supplied|fitted)\s+without\s+(?:an?\s+)?{escaped_alias}s?\b",
            rf"(?:^|[.!?;:]\s+|\b(?:product|equipment|machine|appliance|tool|device|unit|sample|test\s+item|model\s+[A-Za-z0-9_./-]+)\s+)"
            rf"(?:has\s+)?(?:no|without|does\s+not\s+have|is\s+not\s+provided\s+with|not\s+provided\s+with)\s+"
            rf"(?:an?\s+)?{escaped_alias}s?(?=\s*(?:is|are|was|were|provided|fitted|present|absent|[.!?,;:]|$))",
            rf"\b{escaped_alias}s?\s+(?:is|are)?\s*(?:not\s+provided|not\s+fitted|"
            rf"not\s+incorporated|not\s+used|absent)\b",
        )
        return next((match for pattern in patterns
                     for match in [re.search(pattern, line, re.IGNORECASE)] if match), None)

    def _extract_operating_context(
        self, pages: Sequence[str], document_id: Optional[str]
    ) -> List[_Candidate]:
        """Extract explicit labelled operating limits; never infer from product names."""

        output: List[_Candidate] = []
        definitions = [
            ("maximum_operating_depth", r"maximum\s+operating\s+depth", "m"),
        ]
        for page_number, page in enumerate(pages, 1):
            normalized = re.sub(r"[ \t]+", " ", page)
            for feature_id, label, expected_unit in definitions:
                feature = self.registry.get(feature_id)
                if feature is None:
                    continue
                pattern = re.compile(
                    rf"(?im)^\s*(?P<label>{label})[^\n]*?[:：]\s*(?:\n\s*)?"
                    rf"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>{re.escape(expected_unit)})\b"
                )
                for match in pattern.finditer(normalized):
                    value = {"value": self._number(match.group("value")), "unit": expected_unit}
                    output.append(self._candidate(
                        feature, value, ProductFactStatus.CONFIRMED, .99,
                        EvidenceSourceType.REPORT_METADATA, document_id, page_number,
                        match.group(0).strip(), observed=value,
                        notes="Explicit operating-context label and value.",
                    ))
        return output

    def _extract_na_hints(
        self, pages: Sequence[str], document_id: Optional[str]
    ) -> List[_Candidate]:
        """Retain only explicit absence remarks paired with N/A; never derive false."""

        output: List[_Candidate] = []
        boolean_features = [item for item in self.registry.get_all()
                            if item.data_type is FeatureDataType.BOOLEAN]
        for page_number, page in enumerate(pages, 1):
            lines = [re.sub(r"\s+", " ", line).strip() for line in page.splitlines() if line.strip()]
            clause_id: Optional[str] = None
            for index, line in enumerate(lines):
                clause = self._CLAUSE_RE.fullmatch(line)
                if clause:
                    clause_id = clause.group(1); continue
                if not re.search(r"\b(?:not\s+provided|not\s+fitted|absent)\b", line, re.IGNORECASE):
                    continue
                nearby = lines[index + 1:index + 4]
                verdict = next((item for item in nearby if self._normalize_verdict(item) == "N/A"), None)
                if verdict is None:
                    continue
                matches = [feature for feature in boolean_features
                           if any(re.search(rf"\b{re.escape(alias)}\b", line, re.IGNORECASE)
                                  for alias in feature.aliases)]
                if len(matches) != 1:
                    if matches:
                        self._diagnostics.append(ProductProfileDiagnostic(
                            ProfileDiagnosticCategory.AMBIGUOUS_FEATURE_MAPPING,
                            "N/A absence remark maps to multiple canonical features",
                            page_number, line, [item.key for item in matches]))
                    continue
                feature = matches[0]
                candidate = self._candidate(feature, None, ProductFactStatus.INFERRED_FROM_NA,
                    .5, EvidenceSourceType.REPORT_CLAUSE, document_id, page_number,
                    line, clause_id=clause_id, verdict="N/A", observed=None,
                    notes="Explicit absence remark accompanied by report N/A; no Boolean value inferred.")
                output.append(candidate)
                self._diagnostics.append(ProductProfileDiagnostic(
                    ProfileDiagnosticCategory.NA_DERIVED_HINT,
                    "N/A retained as a feature hint with value=None", page_number, line, [feature.key]))
        return output

    def _aggregate_candidates(self, candidates: Sequence[_Candidate]) -> Dict[str, ProductFact]:
        grouped: Dict[str, List[_Candidate]] = {}
        for item in candidates:
            grouped.setdefault(item.feature_id, []).append(item)
        facts: Dict[str, ProductFact] = {}
        for feature_id, items in grouped.items():
            promotable = [item for item in items if item.status in {
                ProductFactStatus.CONFIRMED, ProductFactStatus.INFERRED_STRONG,
                ProductFactStatus.INFERRED,
            } and item.value is not None]
            report_explicit = [item for item in promotable if item.scope_type == "REPORT_SCOPE"]
            if report_explicit:
                highest_authority = max(item.authority_rank for item in report_explicit)
                explicit = [item for item in report_explicit if item.authority_rank == highest_authority]
            else:
                scoped = [item for item in promotable
                          if item.scope_type in {"MODEL_SCOPE", "CONFIGURATION_SCOPE"}]
                scoped_values = {json.dumps(item.value, sort_keys=True, ensure_ascii=False)
                                 for item in scoped}
                scoped_owners = {(item.scope_type, item.model_scope,
                                  item.evidence.page, item.evidence.raw_text) for item in scoped}
                explicit = (list(scoped) if len(scoped_values) == 1
                            and len(scoped_owners) > 1 else [])
            unique_values = {json.dumps(item.value, sort_keys=True, ensure_ascii=False) for item in explicit}
            evidence = self._deduplicate_evidence([item.evidence for item in items])
            if feature_id == "rated_capacity" and len(unique_values) > 1:
                status, value = ProductFactStatus.CONFIRMED, None
                confidence = max((item.confidence or 0) for item in explicit)
            elif len(unique_values) > 1 and self._is_single_source_multistate_rating(feature_id, explicit):
                ordered_values = []
                for item in explicit:
                    if item.value not in ordered_values:
                        ordered_values.append(copy.deepcopy(item.value))
                unit = next((value.get("unit") for value in ordered_values
                             if isinstance(value, dict) and value.get("unit")), None)
                status = ProductFactStatus.CONFIRMED
                value = {"representation": "MULTI_STATE", "values": ordered_values,
                         "unit": unit, "state_semantics": "UNSPECIFIED"}
                confidence = max((item.confidence or 0) for item in explicit)
            elif len(unique_values) > 1:
                status, value, confidence = ProductFactStatus.CONFLICT, None, None
                self._diagnostics.append(ProductProfileDiagnostic(
                    ProfileDiagnosticCategory.CONFLICTING_REPORT_EVIDENCE,
                    f"Conflicting explicit values for {feature_id}",
                    candidate_features=[feature_id]))
            elif explicit:
                value = explicit[0].value
                confirmed = any(item.status is ProductFactStatus.CONFIRMED for item in explicit)
                status = ProductFactStatus.CONFIRMED if confirmed else (
                    ProductFactStatus.INFERRED_STRONG if len(explicit) > 1 else explicit[0].status)
                confidence = max((item.confidence or 0) for item in explicit)
            elif any(item.status is ProductFactStatus.INFERRED_FROM_NA for item in items):
                status, value, confidence = ProductFactStatus.INFERRED_FROM_NA, None, .5
            else:
                status, value, confidence = ProductFactStatus.UNKNOWN, None, None
            feature = self.registry.get(feature_id)
            conflict_values = ([{
                "value": item.value,
                "evidence_id": item.evidence.evidence_id,
                "page": item.evidence.page,
                "polarity": self._polarity(item.value),
                "source_authority": item.source_authority,
                "scope_type": item.scope_type,
                "model_scope": item.model_scope,
            } for item in explicit] if status is ProductFactStatus.CONFLICT else [])
            facts[feature_id] = ProductFact(
                feature_id=feature_id, value=value, status=status,
                confidence=confidence, evidence=evidence,
                observations=self._fact_observations(feature_id, items),
                normalized_value=copy.deepcopy(value),
                value_type=feature.data_type.value if feature else None,
                unit=(value.get("unit") if isinstance(value, dict) else
                      feature.unit if feature else None),
                normalization_basis="CANONICAL_FEATURE_REGISTRY",
                conflicts=conflict_values,
            )
        return facts

    @staticmethod
    def _is_single_source_multistate_rating(
        feature_id: str, items: Sequence[_Candidate]
    ) -> bool:
        """Recognize an explicit compact multi-state rating without scalarizing it."""

        if feature_id not in {"rated_voltage", "rated_frequency", "rated_current",
                              "rated_power_input", "rated_capacity"} or len(items) < 2:
            return False
        source_lines = {re.sub(r"\s+", " ", item.evidence.raw_text or "").strip()
                        for item in items}
        units = {item.value.get("unit") for item in items if isinstance(item.value, dict)}
        return len(source_lines) == 1 and len(units) == 1 and None not in units

    @classmethod
    def _fact_observations(
        cls, feature_id: str, items: Sequence[_Candidate]
    ) -> List[ProductFactObservation]:
        observations = [cls._fact_observation(feature_id, item) for item in items]
        unique = {item.fact_id: item for item in observations}
        return [unique[key] for key in sorted(unique)]

    @staticmethod
    def _fact_observation(feature_id: str, item: _Candidate) -> ProductFactObservation:
        evidence = copy.deepcopy(item.evidence)
        value = copy.deepcopy(item.value)
        unit = value.get("unit") if isinstance(value, dict) else None
        token = hashlib.sha256(
            f"{feature_id}|{json.dumps(value, sort_keys=True, ensure_ascii=False)}|"
            f"{item.evidence.source_type.value}|{item.evidence.page}|{item.evidence.raw_text}|"
            f"{item.scope_type}|{item.model_scope}".encode()
        ).hexdigest()[:16].upper()
        return ProductFactObservation(
            fact_id=f"FACT-OBS-{token}", parameter=feature_id, value=value,
            status=item.status, unit=unit,
            source_context=item.evidence.source_type.value,
            confidence=item.confidence, evidence=[evidence],
            presence=value if isinstance(value, bool) else None,
            presence_state=(FeaturePresenceState.PRESENT if value is True else
                            FeaturePresenceState.ABSENT if value is False else
                            FeaturePresenceState.UNKNOWN),
            source_strength="CONFIRMED_SOURCE_ASSERTION" if item.status is ProductFactStatus.CONFIRMED else None,
            scope_type=item.scope_type, model_scope=item.model_scope,
            polarity=GenericReportProductProfileBuilder._polarity(value),
            source_authority=item.source_authority,
        )

    @staticmethod
    def _polarity(value: Any) -> str:
        return "POSITIVE" if value is True else "NEGATIVE" if value is False else "UNKNOWN"

    def _candidate(
        self, feature: CanonicalProductFeature, value: Any, status: ProductFactStatus,
        confidence: Optional[float], source_type: EvidenceSourceType,
        document_id: Optional[str], page: Optional[int], raw_text: str,
        *, clause_id: Optional[str] = None, verdict: Optional[str] = None,
        observed: Any = None, notes: Optional[str] = None,
        scope_type: str = "REPORT_SCOPE", model_scope: Optional[str] = None,
        source_authority: Optional[str] = None, source_label: Optional[str] = None,
    ) -> _Candidate:
        self._evidence_sequence += 1
        page_token = str(page) if page is not None else "META"
        authority = source_authority or (
            "EXPLICIT_STRUCTURED_FIELD" if source_type is EvidenceSourceType.REPORT_METADATA
            else "MARKING_TABLE" if source_type is EvidenceSourceType.REPORT_MARKING
            else "NORMAL_BODY_TEXT"
        )
        authority_rank = {
            "EXPLICIT_STRUCTURED_FIELD": 900, "TEST_ITEM_PARTICULARS": 800,
            "REPORT_HEADER_IDENTITY": 700, "GENERAL_PRODUCT_INFORMATION": 600,
            "MARKING_TABLE": 500, "NORMAL_BODY_TEXT": 400,
            "HEADER_FOOTER": 300, "DISCLAIMER": 200, "SIGNATURE_METADATA": 100,
        }.get(authority, 0)
        evidence = ProductFactEvidence(
            evidence_id=f"EV-{page_token}-{self._evidence_sequence:04d}",
            source_type=source_type, source_document_id=document_id, page=page,
            clause_id=clause_id, reported_verdict=verdict, raw_text=raw_text,
            observed_value=observed, notes=notes,
            source_authority=authority, source_label=source_label,
        )
        return _Candidate(feature.key, value, status, confidence, evidence, scope_type,
                          model_scope, authority_rank, authority, source_label)

    def _detect_unmapped_labels(self, pages: Sequence[str]) -> None:
        for page_number, page in enumerate(pages[: min(10, len(pages))], 1):
            for raw_line in page.splitlines():
                match = re.fullmatch(r"\s*([A-Za-z][A-Za-z /_-]{2,50})\s*:\s*(\S.+)\s*", raw_line)
                if not match:
                    continue
                label = re.sub(r"\s+", " ", match.group(1)).strip().casefold()
                if label in self._KNOWN_METADATA_LABELS:
                    continue
                aliases = self.registry.search_alias(label)
                if not aliases:
                    self._diagnostics.append(ProductProfileDiagnostic(
                        ProfileDiagnosticCategory.UNMAPPED_REPORT_TERM,
                        f"Unmapped report label: {match.group(1).strip()}", page_number,
                        raw_line.strip()))
                elif len(aliases) > 1:
                    self._diagnostics.append(ProductProfileDiagnostic(
                        ProfileDiagnosticCategory.AMBIGUOUS_FEATURE_MAPPING,
                        f"Ambiguous report label: {match.group(1).strip()}", page_number,
                        raw_line.strip(), [item.key for item in aliases]))

    def _detect_per_model_variation(
        self, pages: Sequence[str], model_numbers: Sequence[str]
    ) -> None:
        """Flag clearly model-qualified differing values without flattening them."""

        if len(model_numbers) < 2:
            return
        text = "\n".join(pages)
        observations: Dict[str, Set[str]] = {}
        for model in model_numbers:
            pattern = re.compile(
                rf"(?im)^.*\b{re.escape(model)}\b.*?(?:class\s+(?:0I|III|II|I|0)|"
                rf"\d+(?:[.,]\d+)?\s*(?:V|Hz|A|W)|type\s+[XYZ]).*$"
            )
            observations[model] = {re.sub(r"\s+", " ", match.group(0)).strip()
                                   for match in pattern.finditer(text)}
        represented = [model for model, values in observations.items() if values]
        if len(represented) >= 2:
            self._diagnostics.append(ProductProfileDiagnostic(
                ProfileDiagnosticCategory.PER_MODEL_VARIATION,
                "Model-qualified product facts require per-model review",
                raw_text=" | ".join(value for model in represented
                                    for value in sorted(observations[model])),
            ))

    @classmethod
    def _label_value(cls, text: str, labels: Sequence[str]) -> Optional[str]:
        values = cls._all_label_values(text, labels)
        return values[0] if values else None

    @classmethod
    def _all_label_values(cls, text: str, labels: Sequence[str]) -> List[str]:
        values: List[str] = []
        for label in sorted(labels, key=len, reverse=True):
            pattern = re.compile(
                rf"(?im)^\s*{re.escape(label)}[\s.…·_-]{{0,45}}[:：]\s*(?:\n\s*)?([^\n]+)"
            )
            for match in pattern.finditer(text):
                value = cls._clean_value(match.group(1))
                if value and not cls._looks_like_label(value):
                    values.append(value)
        # PDF tables often place the label, colon, and a wrapped value on
        # separate lines.  Continue only until the next recognizable label.
        if not any("model" in label.casefold() or "type reference" in label.casefold()
                   for label in labels):
            return cls._unique(values)
        lines = [line.strip() for line in text.splitlines()]
        normalized_labels = {cls._normalize_label(label) for label in labels}
        for index, line in enumerate(lines):
            label_part = re.sub(r"[\s.…·_-]+[:：]?\s*$", "", line)
            if cls._normalize_label(label_part) not in normalized_labels:
                continue
            parts: List[str] = []
            for following in lines[index + 1:index + 11]:
                value = cls._clean_value(following)
                if not value:
                    continue
                if cls._looks_like_label(value):
                    break
                parts.append(value)
            if parts:
                values.append(" ".join(parts))
        return cls._unique(values)

    @classmethod
    def _adjacent_label_values(
        cls, text: str, first_labels: Sequence[str], second_labels: Sequence[str]
    ) -> Optional[Tuple[str, str]]:
        """Read a conservative labels-first/value-rows PDF table layout."""

        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()
                 if line.strip()]
        first = {cls._normalize_label(label) for label in first_labels}
        second = {cls._normalize_label(label) for label in second_labels}
        for index, line in enumerate(lines):
            if cls._normalize_label(line) not in first:
                continue
            second_index = next((position for position in range(index + 1, min(index + 5, len(lines)))
                                 if cls._normalize_label(lines[position]) in second), None)
            if second_index is None:
                continue
            values: List[str] = []
            for value_line in lines[second_index + 1:min(second_index + 7, len(lines))]:
                value = cls._clean_value(value_line)
                if not value or cls._looks_like_label(value):
                    continue
                if re.fullmatch(r"(?:page\s+)?\d+(?:\s+of\s+\d+)?", value, re.IGNORECASE):
                    continue
                values.append(value)
                if len(values) == 2:
                    return values[0], values[1]
        return None

    @classmethod
    def _report_date(cls, text: str) -> Optional[str]:
        """Return the first syntactically date-like value from report-date labels."""

        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()
                 if line.strip()]
        normalized = [cls._normalize_label(line) for line in lines]
        # Support a common PDF table extraction order where several labels are
        # emitted first and their corresponding values follow in the same order.
        for index in range(len(lines) - 2):
            if normalized[index:index + 3] != ["date of test", "date of report", "report number"]:
                continue
            values = lines[index + 3:index + 6]
            if len(values) == 3 and cls._is_date_value(values[1]):
                return cls._clean_value(values[1])
        for match in cls._DATE_RE.finditer(text):
            value = cls._clean_value(match.group(1))
            if value and cls._is_date_value(value):
                return value
        return None

    @staticmethod
    def _is_date_value(value: str) -> bool:
        return bool(re.search(
            r"(?:\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b|"
            r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b|"
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*"
            r"\d{1,2}[,./ -]+\d{2,4}\b)", value, re.IGNORECASE
        ))

    @staticmethod
    def _normalize_label(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

    @classmethod
    def _looks_like_label(cls, value: str) -> bool:
        normalized = cls._normalize_label(value)
        return bool(re.search(r"\.{3,}|:\s*$", value) or
                    any(normalized == cls._normalize_label(label) or
                        normalized.startswith(cls._normalize_label(label) + " ")
                        for label in cls._KNOWN_METADATA_LABELS))

    @staticmethod
    def _clean_value(value: str) -> Optional[str]:
        cleaned = re.sub(r"\s+", " ", value).strip(" .:")
        return cleaned or None

    @classmethod
    def _split_identifiers(cls, values: Sequence[str]) -> List[str]:
        output: List[str] = []
        for value in values:
            for item in re.split(r"\s*(?:,|;|；|/\s+|\band\b)\s*", value, flags=re.IGNORECASE):
                cleaned = cls._clean_value(item)
                if cleaned:
                    cleaned = re.sub(r"\s*\([^)]*$", "", cleaned).strip()
                    cleaned = re.sub(r"(?<=\w)-\s+(?=\w)", "-", cleaned)
                if (cleaned and len(cleaned) <= 80
                        and (re.search(r"\d", cleaned) or re.search(r"\([A-Za-z]{1,8}\)", cleaned))
                        and not re.search(r"\b(?:they|same|different|except)\b", cleaned, re.I)):
                    output.append(cleaned)
        return cls._unique(output)

    @staticmethod
    def _first_group(pattern: re.Pattern[str], text: str) -> Optional[str]:
        match = pattern.search(text)
        return GenericReportProductProfileBuilder._clean_value(match.group(1)) if match else None

    @staticmethod
    def _normalize_standard(value: str) -> str:
        normalized = re.sub(r"\s+", " ", value).upper().strip()
        return re.sub(r":\s*", ":", normalized)

    @staticmethod
    def _normalize_verdict(value: str) -> Optional[str]:
        cleaned = re.sub(r"[.\s]", "", value).upper()
        if cleaned in {"N/A", "NA", "N", "NOTAPPLICABLE"}: return "N/A"
        if cleaned in {"P", "PASS"}: return "PASS"
        if cleaned in {"F", "FAIL"}: return "FAIL"
        if cleaned == "NOTTESTED": return "NOT_TESTED"
        return None

    @staticmethod
    def _number(value: str) -> Union[int, float]:
        number = float(value.replace(",", "."))
        return int(number) if number.is_integer() else number

    @staticmethod
    def _unique(values: Iterable[str]) -> List[str]:
        output: List[str] = []
        seen = set()
        for value in values:
            if value not in seen:
                seen.add(value); output.append(value)
        return output

    @staticmethod
    def _deduplicate_evidence(items: Sequence[ProductFactEvidence]) -> List[ProductFactEvidence]:
        output: List[ProductFactEvidence] = []
        seen = set()
        for item in items:
            signature = (item.source_type.value, item.page, item.clause_id,
                         item.reported_verdict, item.raw_text, json.dumps(item.observed_value,
                         sort_keys=True, ensure_ascii=False))
            if signature not in seen:
                seen.add(signature); output.append(item)
        return output

    @classmethod
    def _profile_id(
        cls, source: ProductProfileSource, file_name: Optional[str], text: str
    ) -> str:
        identity = source.report_number or (Path(file_name).stem if file_name else None)
        if not identity:
            identity = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        normalized = re.sub(r"[^A-Za-z0-9]+", "_", identity).strip("_")
        return f"PROFILE_{normalized}"


__all__ = [
    "GenericReportProductProfileBuilder", "ProductProfileDiagnostic",
    "ProfileDiagnosticCategory",
]
