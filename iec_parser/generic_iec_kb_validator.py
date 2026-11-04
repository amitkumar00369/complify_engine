"""Read-only integrity validation for generic IEC knowledge-base artifacts."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

from iec_parser.generic_iec_feature_registry import CanonicalProductFeatureRegistry
from iec_parser.generic_iec_kb_models import (
    Annex, ApplicabilityRule, ApplicabilityStatus, Clause, ClauseType,
    ConstraintStatus, ConstraintType, Definition, DocumentType, ExternalReference,
    KnowledgeBase, NumericLimit, ParentRelationship, RelationshipType, Requirement,
    RequirementType, SourceReference, StandardDocument, StandardTable,
    ExecutableTechnicalRule, TechnicalConstraint, TechnicalRuleFamily,
)


class ValidationSeverity(str, Enum):
    """Severity of a validation finding."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INFO = "INFO"


@dataclass(frozen=True)
class ValidationFinding:
    """One stable, machine-readable validation observation."""

    code: str
    severity: ValidationSeverity
    message: str
    standard_id: Optional[str] = None
    clause_id: Optional[str] = None
    requirement_id: Optional[str] = None
    constraint_id: Optional[str] = None
    source_page: Optional[int] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    """Complete result of a non-mutating validation run."""

    findings: List[ValidationFinding] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> List[ValidationFinding]:
        return [item for item in self.findings if item.severity is ValidationSeverity.ERROR]

    @property
    def warnings(self) -> List[ValidationFinding]:
        return [item for item in self.findings if item.severity is ValidationSeverity.WARNING]

    @property
    def review_required(self) -> List[ValidationFinding]:
        return [item for item in self.findings if item.severity is ValidationSeverity.REVIEW_REQUIRED]

    @property
    def info(self) -> List[ValidationFinding]:
        return [item for item in self.findings if item.severity is ValidationSeverity.INFO]

    @property
    def valid(self) -> bool:
        return not self.errors


class ReconciliationClassification(str, Enum):
    """Disposition of one pre-assembly relationship occurrence."""

    PRESERVED_MAIN = "PRESERVED_MAIN"
    PRESERVED_ANNEX = "PRESERVED_ANNEX"
    PRESERVED_DEFINITION_CONTEXT = "PRESERVED_DEFINITION_CONTEXT"
    EXCLUDED_NON_CLAUSE_CONTEXT = "EXCLUDED_NON_CLAUSE_CONTEXT"
    INTENTIONALLY_TRANSFORMED = "INTENTIONALLY_TRANSFORMED"
    MISSING_ERROR = "MISSING_ERROR"


@dataclass(frozen=True)
class RelationshipReconciliation:
    """Accounting record for a pre-assembly relationship occurrence."""

    clause_id: str
    relationship_type: str
    parent_clause_id: Optional[str]
    semantic_context: Optional[str]
    classification: ReconciliationClassification
    artifact_location: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class GenericIECKnowledgeBaseValidator:
    """Validate in-memory or serialized generic IEC KBs without modifying them."""

    LOGIC_KEYS = {"field", "operator", "value", "all", "any", "not"}
    LOGIC_OPERATORS = {
        "equals", "not_equals", "greater_than", "greater_than_or_equal",
        "less_than", "less_than_or_equal", "in", "not_in", "exists",
    }
    RELATIONSHIPS_REQUIRING_TARGET = {
        RelationshipType.APPLICABLE, RelationshipType.APPLICABLE_EXCEPT,
        RelationshipType.ADDITION, RelationshipType.MODIFICATION,
        RelationshipType.REPLACEMENT, RelationshipType.NOT_APPLICABLE,
    }
    MEASUREMENT_CONSTRAINTS = {
        ConstraintType.TIME_LIMIT, ConstraintType.DISTANCE_LIMIT,
        ConstraintType.TEMPERATURE_LIMIT, ConstraintType.CURRENT_LIMIT,
        ConstraintType.VOLTAGE_LIMIT, ConstraintType.POWER_LIMIT,
        ConstraintType.SPEED_LIMIT, ConstraintType.FLOW_LIMIT,
        ConstraintType.FORCE_LIMIT, ConstraintType.PERCENTAGE_LIMIT,
    }

    def __init__(self, feature_registry: Optional[CanonicalProductFeatureRegistry] = None) -> None:
        self.feature_registry = feature_registry or CanonicalProductFeatureRegistry()

    def validate(self, kb: KnowledgeBase) -> ValidationReport:
        """Validate one KB and return findings; never mutate the input."""

        findings: List[ValidationFinding] = []
        if not isinstance(kb, KnowledgeBase):
            self._add(findings, "KB_INVALID_TYPE", ValidationSeverity.ERROR,
                      "Object is not a KnowledgeBase")
            return self._report(findings, None)
        document = kb.document
        if not isinstance(document, StandardDocument):
            self._add(findings, "KB_DOCUMENT_MISSING", ValidationSeverity.ERROR,
                      "Knowledge base document metadata is missing")
            return self._report(findings, kb)
        standard_id = document.standard_id
        if not self._text(standard_id):
            self._add(findings, "KB_STANDARD_ID_MISSING", ValidationSeverity.ERROR,
                      "Document standard_id is required", standard_id=standard_id)
        if not self._text(document.standard_number):
            self._add(findings, "KB_STANDARD_NUMBER_MISSING", ValidationSeverity.ERROR,
                      "Document standard_number is required", standard_id=standard_id)
        if not isinstance(document.document_type, DocumentType):
            self._add(findings, "KB_DOCUMENT_TYPE_INVALID", ValidationSeverity.ERROR,
                      "Document type is not recognized", standard_id=standard_id)
        elif document.document_type not in {
            DocumentType.BASE, DocumentType.PART_2, DocumentType.OTHER
        }:
            self._add(findings, "KB_DOCUMENT_TYPE_UNSUPPORTED", ValidationSeverity.ERROR,
                      "Knowledge-base validation requires an identified normative document",
                      standard_id=standard_id)
        if not self._text(kb.schema_version):
            self._add(findings, "KB_SCHEMA_VERSION_MISSING", ValidationSeverity.ERROR,
                      "schema_version is required", standard_id=standard_id)
        if document.document_type is DocumentType.PART_2 and not self._text(document.parent_standard):
            self._add(findings, "KB_PARENT_STANDARD_MISSING", ValidationSeverity.ERROR,
                      "PART_2 document requires parent_standard", standard_id=standard_id)
        if document.year is not None and (not isinstance(document.year, int) or not 1800 <= document.year <= 2200):
            self._add(findings, "KB_YEAR_UNUSUAL", ValidationSeverity.WARNING,
                      "Document year has an unusual format or range", standard_id=standard_id)
        if document.edition is not None and not self._text(document.edition):
            self._add(findings, "KB_EDITION_INVALID", ValidationSeverity.WARNING,
                      "Document edition is empty", standard_id=standard_id)

        self._validate_clauses(kb, findings)
        self._validate_annexes(kb, findings)
        self._validate_tables(kb, findings)
        self._validate_definitions(kb, findings)
        if not kb.definitions:
            self._add(findings, "KB_DEFINITIONS_EMPTY", ValidationSeverity.INFO,
                      "Definition collection is empty", standard_id=standard_id)
        if not kb.references:
            self._add(findings, "KB_REFERENCES_EMPTY", ValidationSeverity.INFO,
                      "External-reference collection is empty", standard_id=standard_id)
        return self._report(findings, kb)

    def validate_json(self, path: Union[str, Path]) -> ValidationReport:
        """Load and validate a JSON artifact without rebuilding its source PDF."""

        findings: List[ValidationFinding] = []
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            self._add(findings, "JSON_READ_ERROR", ValidationSeverity.ERROR,
                      "JSON artifact could not be read as UTF-8", details={"error": str(error)})
            return self._report(findings, None)
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, UnicodeError) as error:
            self._add(findings, "JSON_INVALID", ValidationSeverity.ERROR,
                      "Artifact is not valid JSON", details={"error": str(error)})
            return self._report(findings, None)
        for location, value in self._walk_json(payload):
            if isinstance(value, str) and re.search(
                r"(?:DocumentType|RelationshipType|ApplicabilityStatus|RequirementType|"
                r"ClauseType|ConstraintType|ConstraintStatus)\.[A-Z_]", value
            ):
                self._add(findings, "JSON_ENUM_ARTIFACT", ValidationSeverity.ERROR,
                          "Python enum representation leaked into JSON", details={"path": location, "value": value})
        try:
            kb = self._kb_from_dict(payload)
        except (TypeError, ValueError, KeyError) as error:
            self._add(findings, "JSON_SCHEMA_INVALID", ValidationSeverity.ERROR,
                      "JSON cannot be reconstructed as a KnowledgeBase", details={"error": str(error)})
            return self._report(findings, None)
        report = self.validate(kb)
        findings.extend(report.findings)
        try:
            json.dumps(kb.to_dict(), ensure_ascii=False)
        except (TypeError, ValueError) as error:
            self._add(findings, "JSON_ROUND_TRIP_FAILED", ValidationSeverity.ERROR,
                      "Reconstructed KB is not JSON serializable", details={"error": str(error)})
        return self._report(findings, kb)

    def validate_pair(self, base_kb: KnowledgeBase, delta_kb: KnowledgeBase) -> ValidationReport:
        """Validate BASE/PART_2 compatibility and relationship targets."""

        findings = list(self.validate(base_kb).findings) + list(self.validate(delta_kb).findings)
        base_doc = getattr(base_kb, "document", None)
        delta_doc = getattr(delta_kb, "document", None)
        if not isinstance(base_doc, StandardDocument) or base_doc.document_type is not DocumentType.BASE:
            self._add(findings, "REL_PAIR_BASE_TYPE", ValidationSeverity.ERROR,
                      "First member of a KB pair must be BASE")
        if not isinstance(delta_doc, StandardDocument) or delta_doc.document_type is not DocumentType.PART_2:
            self._add(findings, "REL_PAIR_DELTA_TYPE", ValidationSeverity.ERROR,
                      "Second member of a KB pair must be PART_2")
        if not isinstance(base_doc, StandardDocument) or not isinstance(delta_doc, StandardDocument):
            return self._report(findings, delta_kb)
        if base_doc.standard_id and delta_doc.standard_id and base_doc.standard_id == delta_doc.standard_id:
            self._add(findings, "REL_SAME_DOCUMENT_PAIR", ValidationSeverity.ERROR,
                      "BASE and PART_2 resolve to the same standard_id", standard_id=delta_doc.standard_id)
        if not self._standards_match(delta_doc.parent_standard, base_doc.standard_number):
            self._add(findings, "REL_PARENT_STANDARD_MISMATCH", ValidationSeverity.ERROR,
                      "Delta parent_standard does not match BASE standard_number",
                      standard_id=delta_doc.standard_id,
                      details={"parent_standard": delta_doc.parent_standard,
                               "base_standard_number": base_doc.standard_number})
        base_ids = {clause.clause_id for clause in self._safe_walk(base_kb.clauses)}
        definition_ids = {item.clause_id for item in base_kb.definitions if item.clause_id}
        for clause in self._safe_walk(delta_kb.clauses):
            relationship = clause.relationship_to_parent
            if not isinstance(relationship, ParentRelationship):
                continue
            if relationship.type is RelationshipType.NEW_REQUIREMENT:
                continue
            if relationship.type in self.RELATIONSHIPS_REQUIRING_TARGET:
                target = relationship.parent_clause_id
                if target in base_ids:
                    continue
                details = {"target": target, "reason": "unconfirmed base target"}
                if target in definition_ids:
                    details["reason"] = "target exists in definition context"
                self._add(findings, "REL_TARGET_MISSING", ValidationSeverity.REVIEW_REQUIRED,
                          "Relationship target is not an ordinary BASE clause",
                          standard_id=delta_doc.standard_id, clause_id=clause.clause_id,
                          source_page=self._page(clause.source), details=details)
        for definition in delta_kb.definitions:
            relationship = definition.relationship_to_parent
            if relationship.type in self.RELATIONSHIPS_REQUIRING_TARGET:
                target = relationship.parent_clause_id
                if target not in definition_ids:
                    self._add(findings, "DEF_TARGET_MISSING", ValidationSeverity.REVIEW_REQUIRED,
                              "Delta definition target is absent from BASE definitions",
                              standard_id=delta_doc.standard_id, clause_id=definition.clause_id,
                              source_page=self._page(definition.source), details={"target": target})
        return self._report(findings, delta_kb)

    def reconcile_pipeline(
        self, source_relationship_records: Iterable[Any], kb: KnowledgeBase
    ) -> List[RelationshipReconciliation]:
        """Account for each pre-assembly relationship occurrence in a final KB."""

        main = self._relationship_index(self._safe_walk(kb.clauses), "main")
        annex_req_ids = {
            req.requirement_id: annex.annex_id
            for annex in kb.annexes for req in annex.requirements
        }
        definition_ids = {item.clause_id for item in kb.definitions if item.clause_id}
        results: List[RelationshipReconciliation] = []
        for raw in source_relationship_records:
            clause_id = str(self._get(raw, "clause_id", self._get(raw, "block_id", "")))
            rel_obj = self._get(raw, "relationship_to_parent", None)
            rel_type = self._get(raw, "relationship_type", self._get(rel_obj, "type", RelationshipType.NONE))
            rel_value = rel_type.value if isinstance(rel_type, RelationshipType) else str(rel_type)
            parent = self._get(raw, "parent_clause_id", self._get(rel_obj, "parent_clause_id", None))
            context = self._get(raw, "semantic_context", None)
            key = (clause_id, rel_value, parent)
            classification = ReconciliationClassification.MISSING_ERROR
            location: Optional[str] = None
            details: Dict[str, Any] = {}
            if key in main and main[key]:
                main[key].pop()
                classification = ReconciliationClassification.PRESERVED_MAIN
                location = f"main clause {clause_id}"
            else:
                matching_annex = next(
                    (annex_id for req_id, annex_id in annex_req_ids.items()
                     if req_id == clause_id or req_id.startswith(f"{clause_id}-R")), None
                )
                upper_context = str(context or "").upper()
                if matching_annex:
                    classification = ReconciliationClassification.PRESERVED_ANNEX
                    location = f"annex {matching_annex}"
                elif "DEFINITION" in upper_context:
                    if clause_id in definition_ids:
                        classification = ReconciliationClassification.PRESERVED_DEFINITION_CONTEXT
                        location = "definition collection"
                    else:
                        classification = ReconciliationClassification.EXCLUDED_NON_CLAUSE_CONTEXT
                        location = "definition context excluded from artifact"
                elif upper_context == "ANNEX":
                    classification = ReconciliationClassification.INTENTIONALLY_TRANSFORMED
                    location = "annex source context without a serialized requirement"
                elif upper_context and upper_context not in {"MAIN_CLAUSE", "CLAUSE"}:
                    classification = ReconciliationClassification.EXCLUDED_NON_CLAUSE_CONTEXT
                    location = upper_context.lower()
                else:
                    details["finding_code"] = "PIPELINE_RELATIONSHIP_MISSING"
            results.append(RelationshipReconciliation(
                clause_id, rel_value, parent, context, classification, location, details
            ))
        return results

    @staticmethod
    def stable_core_representation(kb: KnowledgeBase) -> str:
        """Return a canonical representation suitable for deterministic comparison."""

        return json.dumps(kb.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def compare_deterministic(cls, first: KnowledgeBase, second: KnowledgeBase) -> bool:
        """Return whether two KBs have identical stable core representations."""

        return cls.stable_core_representation(first) == cls.stable_core_representation(second)

    def _validate_clauses(self, kb: KnowledgeBase, findings: List[ValidationFinding]) -> None:
        seen_ids: Set[str] = set()
        seen_objects: Set[int] = set()

        def visit(clause: Clause, parent: Optional[Clause], ancestors: Set[int]) -> None:
            if not isinstance(clause, Clause):
                self._add(findings, "CLAUSE_INVALID", ValidationSeverity.ERROR,
                          "Clause collection contains an invalid object")
                return
            oid = id(clause)
            if oid in ancestors:
                self._add(findings, "CLAUSE_CIRCULAR", ValidationSeverity.ERROR,
                          "Circular clause hierarchy detected", clause_id=clause.clause_id)
                return
            if oid in seen_objects:
                self._add(findings, "CLAUSE_REUSED_OBJECT", ValidationSeverity.ERROR,
                          "Clause object occurs more than once", clause_id=clause.clause_id)
                return
            seen_objects.add(oid)
            if not self._text(clause.clause_id):
                self._add(findings, "CLAUSE_ID_MISSING", ValidationSeverity.ERROR,
                          "Clause ID is required")
            elif clause.clause_id in seen_ids:
                self._add(findings, "CLAUSE_DUPLICATE", ValidationSeverity.ERROR,
                          "Clause ID is duplicated in the main namespace", clause_id=clause.clause_id)
            seen_ids.add(clause.clause_id)
            if parent and clause.clause_id and not clause.clause_id.startswith(parent.clause_id + "."):
                self._add(findings, "CLAUSE_HIERARCHY_IMPLAUSIBLE", ValidationSeverity.WARNING,
                          "Child clause ID is not a plausible descendant of its parent",
                          clause_id=clause.clause_id, details={"parent_id": parent.clause_id})
            self._validate_source(clause.source, findings, "CLAUSE", clause.clause_id,
                                  require_raw=clause.clause_type is ClauseType.NORMATIVE)
            child_ids: Set[str] = set()
            for child in clause.children:
                if child is clause:
                    self._add(findings, "CLAUSE_SELF_CHILD", ValidationSeverity.ERROR,
                              "Clause directly references itself", clause_id=clause.clause_id)
                    continue
                if isinstance(child, Clause) and child.clause_id in child_ids:
                    self._add(findings, "CLAUSE_DUPLICATE_CHILD", ValidationSeverity.ERROR,
                              "Parent contains a duplicate child entry", clause_id=child.clause_id,
                              details={"parent_id": clause.clause_id})
                elif isinstance(child, Clause):
                    child_ids.add(child.clause_id)
                visit(child, clause, ancestors | {oid})
            self._validate_requirements(clause.requirements, findings, clause.clause_id,
                                        self._page(clause.source))
            self._validate_relationship(kb.document, clause, findings)

        for clause in kb.clauses:
            visit(clause, None, set())

    def _validate_requirements(
        self, requirements: Sequence[Requirement], findings: List[ValidationFinding],
        owner_id: str, source_page: Optional[int]
    ) -> None:
        seen: Set[str] = set()
        for requirement in requirements:
            if not isinstance(requirement, Requirement):
                self._add(findings, "REQ_INVALID", ValidationSeverity.ERROR,
                          "Requirement collection contains an invalid object", clause_id=owner_id)
                continue
            rid = requirement.requirement_id
            if not self._text(rid):
                self._add(findings, "REQ_ID_MISSING", ValidationSeverity.ERROR,
                          "Requirement ID is required", clause_id=owner_id, source_page=source_page)
            elif rid in seen:
                self._add(findings, "REQ_DUPLICATE", ValidationSeverity.ERROR,
                          "Requirement ID is duplicated within its owner", clause_id=owner_id,
                          requirement_id=rid, source_page=source_page)
            seen.add(rid)
            if not self._text(requirement.text):
                self._add(findings, "REQ_TEXT_EMPTY", ValidationSeverity.ERROR,
                          "Requirement text is empty", clause_id=owner_id,
                          requirement_id=rid, source_page=source_page)
            if not isinstance(requirement.requirement_type, RequirementType):
                self._add(findings, "REQ_TYPE_INVALID", ValidationSeverity.ERROR,
                          "Requirement type is not recognized", clause_id=owner_id, requirement_id=rid)
            if not isinstance(requirement.normative, bool):
                self._add(findings, "REQ_NORMATIVE_INVALID", ValidationSeverity.ERROR,
                          "Requirement normative flag must be boolean", clause_id=owner_id, requirement_id=rid)
            if rid and owner_id and not (rid.startswith(f"{owner_id}-R") or rid.startswith(f"{owner_id}.")):
                self._add(findings, "REQ_ID_PATTERN_UNUSUAL", ValidationSeverity.WARNING,
                          "Requirement ID does not follow its owner ID", clause_id=owner_id, requirement_id=rid)
            self._validate_applicability(
                requirement.applicability, findings, owner_id, rid, requirement.text,
                source_page,
            )
            self._validate_constraints(requirement, findings, owner_id)
            self._validate_executable_rules(requirement, findings, owner_id)

    def _validate_applicability(
        self, rule: Any, findings: List[ValidationFinding], clause_id: str, rid: str,
        requirement_text: str = "", source_page: Optional[int] = None,
    ) -> None:
        if not isinstance(rule, ApplicabilityRule):
            self._add(findings, "APP_MISSING", ValidationSeverity.ERROR,
                      "Requirement applicability is missing", clause_id=clause_id, requirement_id=rid)
            return
        if not isinstance(rule.status, ApplicabilityStatus):
            self._add(findings, "APP_STATUS_INVALID", ValidationSeverity.ERROR,
                      "Applicability status is not recognized", clause_id=clause_id, requirement_id=rid)
            return
        if rule.status is ApplicabilityStatus.ALWAYS:
            if rule.logic is not None:
                self._add(findings, "APP_ALWAYS_HAS_LOGIC", ValidationSeverity.ERROR,
                          "ALWAYS applicability cannot contain executable logic",
                          clause_id=clause_id, requirement_id=rid)
            if self._text(rule.condition_text):
                self._add(findings, "APP_ALWAYS_HAS_CONDITION", ValidationSeverity.WARNING,
                          "ALWAYS applicability normally has no condition text",
                          clause_id=clause_id, requirement_id=rid)
            from iec_parser.generic_iec_applicability_extractor import (
                GenericIECApplicabilityExtractor,
            )
            detected, detected_status, detected_scope = (
                GenericIECApplicabilityExtractor.discover_scope(requirement_text)
            )
            if detected_status is not ApplicabilityStatus.ALWAYS:
                self._add(
                    findings, "APPLICABILITY_SCOPE_LOST_TO_ALWAYS",
                    ValidationSeverity.REVIEW_REQUIRED,
                    "Recognized applicability scope must not be represented as ALWAYS",
                    clause_id=clause_id, requirement_id=rid, source_page=source_page,
                    details={"source_text": requirement_text,
                             "detected_scope_text": detected,
                             "detected_scope": detected_scope,
                             "parser_stage": "KB_VALIDATION"},
                )
        elif rule.status is ApplicabilityStatus.RESOLVED:
            if not self._text(rule.condition_text):
                self._add(findings, "APP_RESOLVED_WITHOUT_CONDITION", ValidationSeverity.ERROR,
                          "RESOLVED applicability requires condition text",
                          clause_id=clause_id, requirement_id=rid)
            if rule.logic is None:
                self._add(findings, "APP_RESOLVED_WITHOUT_LOGIC", ValidationSeverity.ERROR,
                          "RESOLVED applicability requires executable logic",
                          clause_id=clause_id, requirement_id=rid)
            else:
                self._validate_logic(rule.logic, findings, clause_id, rid)
                if self._logic_depth(rule.logic) > 4:
                    self._add(findings, "APP_COMPLEX_RESOLVED", ValidationSeverity.REVIEW_REQUIRED,
                              "Resolved applicability is unusually complex",
                              clause_id=clause_id, requirement_id=rid)
        elif rule.status is ApplicabilityStatus.UNRESOLVED:
            if rule.logic is not None:
                self._add(findings, "APP_UNRESOLVED_HAS_LOGIC", ValidationSeverity.ERROR,
                          "UNRESOLVED applicability cannot contain executable logic",
                          clause_id=clause_id, requirement_id=rid)
            if not self._text(rule.condition_text):
                self._add(findings, "APP_UNRESOLVED_WITHOUT_CONDITION", ValidationSeverity.WARNING,
                          "UNRESOLVED applicability normally retains condition text",
                          clause_id=clause_id, requirement_id=rid)
        elif rule.status is ApplicabilityStatus.NEEDS_REVIEW and rule.logic is not None:
            self._add(findings, "APP_REVIEW_HAS_LOGIC", ValidationSeverity.ERROR,
                      "NEEDS_REVIEW applicability must not pretend to be executable",
                      clause_id=clause_id, requirement_id=rid)

    def _validate_logic(
        self, node: Any, findings: List[ValidationFinding], clause_id: str, rid: str
    ) -> None:
        context = {"clause_id": clause_id, "requirement_id": rid}
        if not isinstance(node, dict) or not node:
            self._add(findings, "APP_PARTIAL_LOGIC", ValidationSeverity.ERROR,
                      "Applicability logic node must be a non-empty object", **context)
            return
        unknown = set(node) - self.LOGIC_KEYS
        if unknown:
            self._add(findings, "APP_PARTIAL_LOGIC", ValidationSeverity.ERROR,
                      "Applicability logic contains unknown keys", **context,
                      details={"keys": sorted(unknown)})
        families = ["field" in node, "all" in node, "any" in node, "not" in node]
        if sum(families) != 1:
            self._add(findings, "APP_PARTIAL_LOGIC", ValidationSeverity.ERROR,
                      "Logic node must contain exactly one field/all/any/not form", **context)
            return
        if "field" in node:
            if set(node) - {"field", "operator", "value"}:
                self._add(findings, "APP_PARTIAL_LOGIC", ValidationSeverity.ERROR,
                          "Field logic has incompatible keys", **context)
            feature_key = node.get("field")
            operator = node.get("operator")
            classification_operand = feature_key == "canonical_product_classification"
            if not self._text(feature_key) or (
                not classification_operand and not self.feature_registry.exists(feature_key)
            ):
                self._add(findings, "APP_UNKNOWN_FEATURE", ValidationSeverity.ERROR,
                          "Logic references an unknown canonical feature", **context,
                          details={"field": feature_key})
            if operator not in self.LOGIC_OPERATORS:
                self._add(findings, "APP_INVALID_OPERATOR", ValidationSeverity.ERROR,
                          "Logic uses an unknown operator", **context,
                          details={"operator": operator})
            if operator != "exists" and "value" not in node:
                self._add(findings, "APP_PARTIAL_LOGIC", ValidationSeverity.ERROR,
                          "Non-existence logic requires a value", **context)
            if operator == "exists" and "value" in node:
                self._add(findings, "APP_PARTIAL_LOGIC", ValidationSeverity.ERROR,
                          "exists logic must not include a value", **context)
            if classification_operand and "value" in node:
                value = node["value"]
                values = value if operator in {"in", "not_in"} and isinstance(value, list) else [value]
                if operator in {"in", "not_in"} and not isinstance(value, list):
                    self._add(findings, "APP_INVALID_VALUE", ValidationSeverity.ERROR,
                              "Classification set operators require a value list", **context)
                elif any(not self._text(item) for item in values):
                    self._add(findings, "APP_INVALID_VALUE", ValidationSeverity.ERROR,
                              "Classification operands require non-empty text values", **context)
            elif self.feature_registry.exists(feature_key) and "value" in node:
                value = node["value"]
                values = value if operator in {"in", "not_in"} and isinstance(value, list) else [value]
                if operator in {"in", "not_in"} and not isinstance(value, list):
                    values = []
                    self._add(findings, "APP_PARTIAL_LOGIC", ValidationSeverity.ERROR,
                              "in/not_in operators require a list value", **context)
                for item in values:
                    if not self.feature_registry.validate_feature_value(feature_key, item):
                        self._add(findings, "APP_INVALID_ENUM_VALUE", ValidationSeverity.ERROR,
                                  "Logic value is invalid for its canonical feature", **context,
                                  details={"field": feature_key, "value": item})
        elif "not" in node:
            if len(node) != 1 or not isinstance(node["not"], dict):
                self._add(findings, "APP_PARTIAL_LOGIC", ValidationSeverity.ERROR,
                          "not must contain exactly one nested expression", **context)
            else:
                self._validate_logic(node["not"], findings, clause_id, rid)
        else:
            key = "all" if "all" in node else "any"
            branches = node.get(key)
            if len(node) != 1 or not isinstance(branches, list) or not branches:
                self._add(findings, f"APP_EMPTY_{key.upper()}", ValidationSeverity.ERROR,
                          f"{key} must contain a non-empty expression list", **context)
            elif not all(isinstance(item, dict) for item in branches):
                self._add(findings, "APP_PARTIAL_LOGIC", ValidationSeverity.ERROR,
                          f"{key} contains a non-object branch", **context)
            else:
                for item in branches:
                    self._validate_logic(item, findings, clause_id, rid)

    def _validate_constraints(
        self, requirement: Requirement, findings: List[ValidationFinding], clause_id: str
    ) -> None:
        seen: Set[str] = set()
        for constraint in requirement.technical_constraints:
            cid = constraint.constraint_id
            ctx = {"clause_id": clause_id, "requirement_id": requirement.requirement_id,
                   "constraint_id": cid}
            if not self._text(cid):
                self._add(findings, "CONSTRAINT_ID_MISSING", ValidationSeverity.ERROR,
                          "Constraint ID is required", **ctx)
            elif cid in seen:
                self._add(findings, "CONSTRAINT_DUPLICATE", ValidationSeverity.ERROR,
                          "Constraint ID is duplicated within its requirement", **ctx)
            seen.add(cid)
            if constraint.source_requirement_id != requirement.requirement_id:
                self._add(findings, "CONSTRAINT_SOURCE_MISMATCH", ValidationSeverity.ERROR,
                          "Constraint source_requirement_id does not match its owner", **ctx)
            if not isinstance(constraint.constraint_type, ConstraintType):
                self._add(findings, "CONSTRAINT_TYPE_INVALID", ValidationSeverity.ERROR,
                          "Constraint type is not recognized", **ctx)
                continue
            if not isinstance(constraint.status, ConstraintStatus):
                self._add(findings, "CONSTRAINT_STATUS_INVALID", ValidationSeverity.ERROR,
                          "Constraint status is not recognized", **ctx)
                continue
            complete, code, reason = self._constraint_complete(constraint)
            if constraint.status is ConstraintStatus.RESOLVED and not complete:
                self._add(findings, code, ValidationSeverity.ERROR, reason, **ctx)
            elif constraint.status is ConstraintStatus.NEEDS_REVIEW and complete:
                self._add(findings, "CONSTRAINT_REVIEW_EXECUTABLE", ValidationSeverity.REVIEW_REQUIRED,
                          "NEEDS_REVIEW constraint appears fully executable", **ctx)
            elif (constraint.status is ConstraintStatus.UNRESOLVED and
                  re.search(r"\d", requirement.text or "")):
                self._add(findings, "CONSTRAINT_NUMERIC_UNRESOLVED", ValidationSeverity.REVIEW_REQUIRED,
                          "Numeric requirement contains only an unresolved constraint", **ctx)
            if constraint.status is ConstraintStatus.RESOLVED and not self._text(constraint.raw_text):
                self._add(findings, "CONSTRAINT_RAW_TEXT_MISSING", ValidationSeverity.WARNING,
                          "Resolved constraint lacks raw source text", **ctx)

    def _validate_executable_rules(self, requirement, findings, clause_id):
        seen=set();constraint_ids={x.constraint_id for x in requirement.technical_constraints}
        for rule in requirement.executable_rules:
            ctx={"clause_id":clause_id,"requirement_id":requirement.requirement_id}
            if not self._text(rule.rule_id) or rule.rule_id in seen:self._add(findings,"TECH_RULE_ID_INVALID",ValidationSeverity.ERROR,"Executable rule ID is missing or duplicated.",**ctx)
            seen.add(rule.rule_id)
            if rule.source_requirement_id!=requirement.requirement_id:self._add(findings,"TECH_RULE_SOURCE_MISMATCH",ValidationSeverity.ERROR,"Executable rule source does not match its owner.",**ctx)
            if not isinstance(rule.rule_family,TechnicalRuleFamily):self._add(findings,"TECH_RULE_FAMILY_INVALID",ValidationSeverity.ERROR,"Executable rule family is unsupported.",**ctx);continue
            if rule.rule_family in {TechnicalRuleFamily.NUMERIC_LIMIT,TechnicalRuleFamily.RANGE_TOLERANCE,TechnicalRuleFamily.DIMENSION} and (not self._text(rule.parameter) or not self._text(rule.operator)):
                self._add(findings,"TECH_RULE_OPERAND_MISSING",ValidationSeverity.ERROR,"Numeric executable rule lacks parameter or operator.",**ctx)
            if rule.rule_family is TechnicalRuleFamily.CROSS_CLAUSE and not rule.cross_clause_dependencies:self._add(findings,"TECH_RULE_DEPENDENCY_MISSING",ValidationSeverity.ERROR,"Cross-clause rule lacks a dependency ID.",**ctx)
            if rule.rule_family is TechnicalRuleFamily.UNSUPPORTED and rule.supported:self._add(findings,"TECH_RULE_UNSUPPORTED_STATE_INVALID",ValidationSeverity.ERROR,"Unsupported rule cannot be marked supported.",**ctx)

    def _constraint_complete(self, item: TechnicalConstraint) -> Tuple[bool, str, str]:
        generic = (self._text(item.parameter) and self._text(item.operator) and item.value is not None)
        if item.constraint_type is ConstraintType.RANGE:
            valid = item.operator in {"between", "not_between"} and item.value is not None and item.value_secondary is not None
            if valid and self._number(item.value) and self._number(item.value_secondary):
                valid = float(item.value) <= float(item.value_secondary)
            return valid, "CONSTRAINT_RESOLVED_INCOMPLETE", "Resolved range is incomplete or reversed"
        if item.constraint_type is ConstraintType.TOLERANCE:
            valid = isinstance(item.tolerance, dict) and item.tolerance.get("value") is not None
            return valid, "CONSTRAINT_RESOLVED_INCOMPLETE", "Resolved tolerance requires a tolerance value"
        if item.constraint_type is ConstraintType.FORMULA:
            valid = self._valid_formula(item.expression)
            return valid, "CONSTRAINT_INVALID_FORMULA", "Resolved formula expression is incomplete"
        if item.constraint_type is ConstraintType.COMPOUND:
            valid = self._valid_compound(item.expression)
            return valid, "CONSTRAINT_INVALID_COMPOUND", "Resolved compound expression is invalid"
        if item.constraint_type is ConstraintType.TEST_PARAMETER:
            valid = self._text(item.parameter) and item.value is not None and self._text(item.unit)
            return valid, "CONSTRAINT_RESOLVED_INCOMPLETE", "Resolved test parameter requires parameter, value, and unit"
        if item.constraint_type in self.MEASUREMENT_CONSTRAINTS:
            generic = generic and self._text(item.unit)
        return bool(generic), "CONSTRAINT_RESOLVED_INCOMPLETE", "Resolved constraint lacks executable fields"

    def _validate_relationship(
        self, document: StandardDocument, clause: Clause, findings: List[ValidationFinding]
    ) -> None:
        relationship = clause.relationship_to_parent
        if not isinstance(relationship, ParentRelationship) or not isinstance(relationship.type, RelationshipType):
            self._add(findings, "REL_TYPE_INVALID", ValidationSeverity.ERROR,
                      "Clause relationship type is not recognized", clause_id=clause.clause_id)
            return
        if document.document_type is DocumentType.BASE and relationship.type is not RelationshipType.NONE:
            self._add(findings, "REL_BASE_NON_NONE", ValidationSeverity.ERROR,
                      "BASE clauses must not have semantic parent relationships",
                      standard_id=document.standard_id, clause_id=clause.clause_id)
        if (document.document_type is DocumentType.PART_2 and
                relationship.type in self.RELATIONSHIPS_REQUIRING_TARGET and
                not self._text(relationship.parent_clause_id)):
            self._add(findings, "REL_TARGET_MISSING", ValidationSeverity.ERROR,
                      "PART_2 relationship requires parent_clause_id",
                      standard_id=document.standard_id, clause_id=clause.clause_id)

    def _validate_annexes(self, kb: KnowledgeBase, findings: List[ValidationFinding]) -> None:
        seen: Set[str] = set()
        main_pairs = {(req.requirement_id, req.text) for clause in self._safe_walk(kb.clauses)
                      for req in clause.requirements}
        for annex in kb.annexes:
            if not self._text(annex.annex_id) or annex.annex_id in seen:
                self._add(findings, "ANNEX_DUPLICATE", ValidationSeverity.ERROR,
                          "Annex ID is missing or duplicated", clause_id=annex.annex_id)
            seen.add(annex.annex_id)
            if not isinstance(annex.normative, bool):
                self._add(findings, "ANNEX_NORMATIVE_INVALID", ValidationSeverity.ERROR,
                          "Annex normative flag must be boolean", clause_id=annex.annex_id)
            self._validate_source(annex.source, findings, "ANNEX", annex.annex_id)
            self._validate_requirements(annex.requirements, findings, annex.annex_id,
                                        self._page(annex.source))
            for req in annex.requirements:
                if (req.requirement_id, req.text) in main_pairs:
                    self._add(findings, "ANNEX_CONTENT_DUPLICATED", ValidationSeverity.ERROR,
                              "Annex requirement duplicates a main-clause requirement",
                              clause_id=annex.annex_id, requirement_id=req.requirement_id)

    def _validate_tables(self, kb: KnowledgeBase, findings: List[ValidationFinding]) -> None:
        seen: Set[str] = set()
        for table in kb.tables:
            if not self._text(table.table_id) or table.table_id in seen:
                self._add(findings, "TABLE_DUPLICATE", ValidationSeverity.ERROR,
                          "Table ID is missing or duplicated", clause_id=table.table_id)
            seen.add(table.table_id)
            self._validate_source(table.source, findings, "TABLE", table.table_id)

    def _validate_definitions(self, kb: KnowledgeBase, findings: List[ValidationFinding]) -> None:
        seen: Set[str] = set()
        for definition in kb.definitions:
            definition_id = definition.clause_id or ""
            if not self._text(definition_id):
                self._add(findings, "DEF_ID_MISSING", ValidationSeverity.ERROR,
                          "Definition clause ID is required")
            elif definition_id in seen:
                self._add(findings, "DEF_DUPLICATE", ValidationSeverity.ERROR,
                          "Definition ID is duplicated", clause_id=definition_id)
            seen.add(definition_id)
            if not self._text(definition.term):
                self._add(findings, "DEF_TERM_EMPTY", ValidationSeverity.ERROR,
                          "Definition term is empty", clause_id=definition_id)
            if not self._text(definition.definition):
                self._add(findings, "DEF_BODY_EMPTY", ValidationSeverity.ERROR,
                          "Definition body is empty", clause_id=definition_id)
            self._validate_source(definition.source, findings, "DEF", definition_id)
            relationship = definition.relationship_to_parent
            if not isinstance(relationship, ParentRelationship) or not isinstance(
                relationship.type, RelationshipType
            ):
                self._add(findings, "DEF_RELATIONSHIP_INVALID", ValidationSeverity.ERROR,
                          "Definition relationship is invalid", clause_id=definition_id)
            elif (kb.document.document_type is DocumentType.BASE and
                  relationship.type is not RelationshipType.NONE):
                self._add(findings, "DEF_BASE_NON_NONE", ValidationSeverity.ERROR,
                          "BASE definitions must have relationship NONE", clause_id=definition_id)
            elif (kb.document.document_type is DocumentType.PART_2 and
                  relationship.type in self.RELATIONSHIPS_REQUIRING_TARGET and
                  not self._text(relationship.parent_clause_id)):
                self._add(findings, "DEF_TARGET_MISSING", ValidationSeverity.ERROR,
                          "Delta definition operation requires a target", clause_id=definition_id)

    def _validate_source(
        self, source: Any, findings: List[ValidationFinding], owner_type: str,
        owner_id: str, require_raw: bool = False
    ) -> None:
        if not isinstance(source, SourceReference):
            self._add(findings, f"{owner_type}_SOURCE_MISSING", ValidationSeverity.ERROR,
                      f"{owner_type.title()} source reference is missing", clause_id=owner_id)
            return
        if source.page_start is not None and (not isinstance(source.page_start, int) or source.page_start < 1):
            self._add(findings, f"{owner_type}_INVALID_PAGE_RANGE", ValidationSeverity.ERROR,
                      "Source page_start must be a positive integer", clause_id=owner_id)
        if source.page_end is not None and (not isinstance(source.page_end, int) or source.page_end < 1):
            self._add(findings, f"{owner_type}_INVALID_PAGE_RANGE", ValidationSeverity.ERROR,
                      "Source page_end must be a positive integer", clause_id=owner_id)
        if (isinstance(source.page_start, int) and isinstance(source.page_end, int)
                and source.page_start > source.page_end):
            self._add(findings, f"{owner_type}_INVALID_PAGE_RANGE", ValidationSeverity.ERROR,
                      "Source page_start exceeds page_end", clause_id=owner_id,
                      source_page=source.page_start)
        if require_raw and not self._text(source.raw_text):
            self._add(findings, f"{owner_type}_SOURCE_EMPTY", ValidationSeverity.WARNING,
                      "Normative source raw_text is empty", clause_id=owner_id,
                      source_page=source.page_start)

    def _report(self, findings: List[ValidationFinding], kb: Optional[KnowledgeBase]) -> ValidationReport:
        summary = self._summary(kb)
        counts = Counter(item.severity.value for item in findings)
        summary.update({"valid": counts["ERROR"] == 0, "counts": {
            "errors": counts["ERROR"], "warnings": counts["WARNING"],
            "review_required": counts["REVIEW_REQUIRED"], "info": counts["INFO"],
        }})
        return ValidationReport(findings=findings, summary=summary)

    def _summary(self, kb: Optional[KnowledgeBase]) -> Dict[str, Any]:
        if not isinstance(kb, KnowledgeBase):
            return {"standard_id": None, "document_type": None, "structural": {},
                    "applicability": {}, "constraints": {}, "relationships": {}}
        clauses = list(self._safe_walk(kb.clauses))
        requirements = [req for clause in clauses for req in clause.requirements]
        requirements.extend(req for annex in kb.annexes for req in annex.requirements)
        constraints = [c for req in requirements for c in req.technical_constraints]
        return {
            "standard_id": getattr(kb.document, "standard_id", None),
            "document_type": self._enum_value(getattr(kb.document, "document_type", None)),
            "structural": {"clauses": len(clauses), "requirements": len(requirements),
                           "annexes": len(kb.annexes), "tables": len(kb.tables),
                           "definitions": len(kb.definitions)},
            "applicability": dict(Counter(self._enum_value(req.applicability.status)
                                           for req in requirements if isinstance(req.applicability, ApplicabilityRule))),
            "constraints": {"total": len(constraints), **dict(Counter(
                self._enum_value(c.status) for c in constraints))},
            "relationships": dict(Counter(self._enum_value(c.relationship_to_parent.type)
                                          for c in clauses if isinstance(c.relationship_to_parent, ParentRelationship))),
        }

    @staticmethod
    def _valid_formula(expression: Any) -> bool:
        if not isinstance(expression, dict) or not expression:
            return False
        selection = expression.get("selection")
        if selection is not None and str(selection).upper() not in {"MIN", "MAX", "MINIMUM", "MAXIMUM"}:
            return False
        operands = expression.get("operands")
        if operands is not None:
            if not isinstance(operands, list) or not operands:
                return False
            for operand in operands:
                if not isinstance(operand, dict):
                    return False
                if str(operand.get("type", "")).upper() == "FORMULA" and not operand.get("variable"):
                    return False
                if str(operand.get("type", "")).upper() == "CONSTANT" and operand.get("value") is None:
                    return False
        cap = expression.get("cap")
        if cap is not None and (not isinstance(cap, dict) or cap.get("operator") is None or
                                cap.get("value") is None or not cap.get("unit")):
            return False
        return operands is not None or "formula" in expression or "variable" in expression

    @classmethod
    def _valid_compound(cls, node: Any) -> bool:
        if not isinstance(node, dict) or not node:
            return False
        if set(node) == {"all"} or set(node) == {"any"}:
            branches = next(iter(node.values()))
            return isinstance(branches, list) and bool(branches) and all(cls._valid_compound(x) for x in branches)
        if "field" in node or "parameter" in node:
            allowed = {"field", "parameter", "operator", "value", "unit"}
            return (not (set(node) - allowed) and node.get("operator") in
                    cls.LOGIC_OPERATORS | {"between", "not_between"} and "value" in node)
        if "operator" in node:
            # The containing key may supply the parameter name (for example,
            # ``time_window``); retain that source representation as executable.
            return (not (set(node) - {"operator", "value", "unit"}) and
                    node.get("operator") in cls.LOGIC_OPERATORS | {"between", "not_between"}
                    and "value" in node)
        # Contextual compound structures (time_window/trigger) are valid if every branch is a leaf.
        return all(cls._valid_compound(value) for value in node.values())

    @classmethod
    def _logic_depth(cls, node: Any) -> int:
        if not isinstance(node, dict):
            return 0
        children: List[Any] = []
        if isinstance(node.get("all"), list): children.extend(node["all"])
        if isinstance(node.get("any"), list): children.extend(node["any"])
        if isinstance(node.get("not"), dict): children.append(node["not"])
        return 1 + max((cls._logic_depth(child) for child in children), default=0)

    @staticmethod
    def _standards_match(parent: Optional[str], base: Optional[str]) -> bool:
        def normalize(value: Optional[str]) -> str:
            return re.sub(r"[^A-Z0-9]", "", (value or "").upper())
        return bool(normalize(parent)) and normalize(parent) == normalize(base)

    @staticmethod
    def _relationship_index(clauses: Iterable[Clause], location: str) -> Dict[Tuple[str, str, Optional[str]], List[str]]:
        index: Dict[Tuple[str, str, Optional[str]], List[str]] = {}
        for clause in clauses:
            rel = clause.relationship_to_parent
            if isinstance(rel, ParentRelationship):
                index.setdefault((clause.clause_id, rel.type.value, rel.parent_clause_id), []).append(location)
        return index

    @staticmethod
    def _safe_walk(clauses: Sequence[Clause]) -> Iterable[Clause]:
        seen: Set[int] = set()
        stack = list(reversed(clauses))
        while stack:
            clause = stack.pop()
            if not isinstance(clause, Clause) or id(clause) in seen:
                continue
            seen.add(id(clause))
            yield clause
            stack.extend(reversed(clause.children))

    @staticmethod
    def _walk_json(value: Any, path: str = "$") -> Iterable[Tuple[str, Any]]:
        yield path, value
        if isinstance(value, dict):
            for key, child in value.items():
                yield from GenericIECKnowledgeBaseValidator._walk_json(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from GenericIECKnowledgeBaseValidator._walk_json(child, f"{path}[{index}]")

    @classmethod
    def _kb_from_dict(cls, raw: Any) -> KnowledgeBase:
        if not isinstance(raw, dict):
            raise TypeError("Top-level JSON value must be an object")
        def source(value: Any) -> SourceReference:
            if not isinstance(value, dict): raise TypeError("source must be an object")
            return SourceReference(value.get("page_start"), value.get("page_end"), value.get("raw_text"))
        def app(value: Any) -> ApplicabilityRule:
            if not isinstance(value, dict): raise TypeError("applicability must be an object")
            from iec_parser.generic_iec_kb_models import ApplicabilityEffect
            return ApplicabilityRule(ApplicabilityStatus(value["status"]), value.get("condition_text"),
                                     value.get("logic"), list(value.get("unresolved_features", [])),
                                     ApplicabilityEffect(value.get("effect", "APPLIES")),
                                     value.get("scope"))
        def constraint(value: Any) -> TechnicalConstraint:
            data = dict(value)
            data["constraint_type"] = ConstraintType(data.get("constraint_type", "OTHER"))
            data["status"] = ConstraintStatus(data.get("status", "UNRESOLVED"))
            return TechnicalConstraint(**data)
        def executable_rule(value: Any) -> ExecutableTechnicalRule:
            data=dict(value);data["rule_family"]=TechnicalRuleFamily(data.get("rule_family","UNSUPPORTED"));return ExecutableTechnicalRule(**data)
        def requirement(value: Any) -> Requirement:
            data = dict(value)
            data["requirement_type"] = RequirementType(data["requirement_type"])
            from iec_parser.generic_iec_kb_models import RequirementSemanticType
            data["semantic_type"] = RequirementSemanticType(data.get("semantic_type", "REQUIREMENT"))
            data["applicability"] = app(data["applicability"])
            data["limits"] = [NumericLimit(**x) for x in data.get("limits", [])]
            data["technical_constraints"] = [constraint(x) for x in data.get("technical_constraints", [])]
            data["executable_rules"] = [executable_rule(x) for x in data.get("executable_rules", [])]
            if data.get("criticality"):
                from iec_parser.generic_iec_kb_models import (CriticalityReviewStatus,
                    CriticalitySource, RequirementCriticality, RequirementCriticalityLevel,
                    RequirementDecisionEffect)
                item=dict(data["criticality"]);item["level"]=RequirementCriticalityLevel(item["level"])
                item["source"]=CriticalitySource(item["source"]);item["review_status"]=CriticalityReviewStatus(item["review_status"])
                data["criticality"]=RequirementCriticality(**item)
                if data.get("decision_effect"): data["decision_effect"]=RequirementDecisionEffect(data["decision_effect"])
            return Requirement(**data)
        def clause(value: Any) -> Clause:
            data = dict(value)
            data["clause_type"] = ClauseType(data["clause_type"])
            data["source"] = source(data["source"])
            rel = data["relationship_to_parent"]
            directive = cls._directive_from_dict(rel.get("directive"))
            data["relationship_to_parent"] = ParentRelationship(RelationshipType(rel["type"]),
                                                                  rel.get("parent_clause_id"), rel.get("notes"),
                                                                  directive)
            data["requirements"] = [requirement(x) for x in data.get("requirements", [])]
            data["children"] = [clause(x) for x in data.get("children", [])]
            return Clause(**data)
        doc = dict(raw["document"])
        doc["document_type"] = DocumentType(doc["document_type"])
        if doc.get("maturity"):
            from iec_parser.generic_iec_kb_models import KBMaturityMetadata, KBMaturityState
            maturity=dict(doc["maturity"]);maturity["state"]=KBMaturityState(maturity.get("state","DRAFT"))
            doc["maturity"]=KBMaturityMetadata(**maturity)
        document = StandardDocument(**doc)
        annexes = [Annex(annex_id=x["annex_id"], normative=x["normative"], source=source(x["source"]),
                          applicability=app(x["applicability"]), title=x.get("title"),
                          requirements=[requirement(r) for r in x.get("requirements", [])],
                          clauses=[clause(c) for c in x.get("clauses", [])])
                   for x in raw.get("annexes", [])]
        tables = [StandardTable(table_id=x["table_id"], source=source(x["source"]), title=x.get("title"),
                                raw_text=x.get("raw_text"), structured_data=x.get("structured_data"))
                  for x in raw.get("tables", [])]
        definitions = []
        for x in raw.get("definitions", []):
            relationship = x.get("relationship_to_parent") or {"type": "NONE"}
            definitions.append(Definition(
                term=x["term"], definition=x["definition"], source=source(x["source"]),
                clause_id=x.get("clause_id"),
                relationship_to_parent=ParentRelationship(
                    RelationshipType(relationship.get("type", "NONE")),
                    relationship.get("parent_clause_id"), relationship.get("notes"),
                    cls._directive_from_dict(relationship.get("directive")),
                ),
            ))
        references = [ExternalReference(**x) for x in raw.get("references", [])]
        return KnowledgeBase(document=document, schema_version=raw.get("schema_version", ""),
                             clauses=[clause(x) for x in raw.get("clauses", [])], annexes=annexes,
                             tables=tables, definitions=definitions, references=references)

    @staticmethod
    def _directive_from_dict(value: Any) -> Any:
        if not isinstance(value, dict):
            return None
        from iec_parser.generic_iec_kb_models import (
            DeltaOperationDirective, OperationQualifierType, OperationTargetScope,
        )
        data = dict(value)
        data["qualifier_type"] = OperationQualifierType(data.get("qualifier_type", "NONE"))
        data["target_scope"] = OperationTargetScope(data.get("target_scope", "WHOLE_CLAUSE"))
        return DeltaOperationDirective(**data)

    @staticmethod
    def _add(findings: List[ValidationFinding], code: str, severity: ValidationSeverity,
             message: str, **kwargs: Any) -> None:
        findings.append(ValidationFinding(code, severity, message, **kwargs))

    @staticmethod
    def _text(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @staticmethod
    def _page(source: Any) -> Optional[int]:
        return source.page_start if isinstance(source, SourceReference) else None

    @staticmethod
    def _enum_value(value: Any) -> str:
        return value.value if isinstance(value, Enum) else str(value)

    @staticmethod
    def _get(obj: Any, name: str, default: Any = None) -> Any:
        return obj.get(name, default) if isinstance(obj, Mapping) else getattr(obj, name, default)


__all__ = [
    "GenericIECKnowledgeBaseValidator", "ReconciliationClassification",
    "RelationshipReconciliation", "ValidationFinding", "ValidationReport",
    "ValidationSeverity",
]
