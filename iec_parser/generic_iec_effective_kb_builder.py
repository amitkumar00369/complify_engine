"""Deterministic, provenance-preserving construction of effective IEC KBs."""

from __future__ import annotations

import copy
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

from iec_parser.generic_iec_effective_kb_models import (
    EffectiveAnnex, EffectiveBuildStatus, EffectiveClause, EffectiveDefinition,
    EffectiveKnowledgeBase, EffectiveOperation, EffectiveOperationType,
    EffectiveRequirement, EffectiveSourceReference, EffectiveSourceType,
    EffectiveStatus,
)
from iec_parser.generic_iec_feature_registry import CanonicalProductFeatureRegistry
from iec_parser.generic_iec_kb_models import (
    Annex, ApplicabilityEffect, ApplicabilityStatus, Clause, Definition,
    DocumentType, KnowledgeBase, OperationQualifierType, OperationTargetScope,
    RelationshipType, Requirement,
    RequirementSemanticType, StandardDocument,
)
from iec_parser.generic_iec_kb_validator import GenericIECKnowledgeBaseValidator


PathLike = Union[str, Path]


class GenericIECEffectiveKnowledgeBaseBuilder:
    """Apply validated Part 2 operations without mutating either source KB."""

    _STOP_WORDS = {
        "a", "an", "and", "as", "be", "by", "for", "from", "in", "is", "it",
        "of", "on", "or", "shall", "that", "the", "this", "to", "with",
    }

    def __init__(
        self, validator: Optional[GenericIECKnowledgeBaseValidator] = None
    ) -> None:
        self.validator = validator or GenericIECKnowledgeBaseValidator(
            CanonicalProductFeatureRegistry()
        )

    def build(self, base_kb: KnowledgeBase, delta_kb: KnowledgeBase) -> EffectiveKnowledgeBase:
        """Build a new effective artifact after enforcing the pair validation gate."""

        report = self.validator.validate_pair(base_kb, delta_kb)
        if report.errors:
            codes = ", ".join(sorted({item.code for item in report.errors}))
            raise ValueError(f"Base/Delta validation failed; effective merge stopped: {codes}")

        base = copy.deepcopy(base_kb)
        delta = copy.deepcopy(delta_kb)
        effective_id = self._effective_kb_id(base.document, delta.document)
        effective = EffectiveKnowledgeBase(
            schema_version="1.0",
            effective_kb_id=effective_id,
            base_standard=copy.deepcopy(base.document),
            delta_standard=copy.deepcopy(delta.document),
            build_status=EffectiveBuildStatus.VALID,
            clauses=[self._project_base_clause(item, base.document) for item in base.clauses],
            annexes=[self._project_base_annex(item, base.document) for item in base.annexes],
            tables=copy.deepcopy(base.tables),
            definitions=[self._project_base_definition(item, base.document) for item in base.definitions],
            references=copy.deepcopy(base.references),
            maturity=copy.deepcopy(base.document.maturity),
        )
        clause_index = {item.clause_id: item for item in self._walk_effective(effective.clauses)}
        self._apply_delta_clauses(delta, effective, clause_index)
        self._apply_delta_definitions(delta, effective)
        self._apply_delta_annexes(delta, effective)
        self._apply_delta_tables(delta, effective)
        if effective.unresolved_operations:
            effective.build_status = EffectiveBuildStatus.NEEDS_REVIEW
        self._assert_effective_integrity(effective)
        return effective

    def build_from_json(self, base_path: PathLike, delta_path: PathLike) -> EffectiveKnowledgeBase:
        """Load validated artifacts and build without source-PDF reconstruction."""

        base_report = self.validator.validate_json(base_path)
        delta_report = self.validator.validate_json(delta_path)
        errors = base_report.errors + delta_report.errors
        if errors:
            codes = ", ".join(sorted({item.code for item in errors}))
            raise ValueError(f"JSON validation failed; effective merge stopped: {codes}")
        base_raw = json.loads(Path(base_path).read_text(encoding="utf-8"))
        delta_raw = json.loads(Path(delta_path).read_text(encoding="utf-8"))
        # Step 12 owns the canonical, backwards-compatible JSON reconstruction.
        base = self.validator._kb_from_dict(base_raw)
        delta = self.validator._kb_from_dict(delta_raw)
        return self.build(base, delta)

    @staticmethod
    def to_dict(effective: EffectiveKnowledgeBase) -> Dict[str, Any]:
        """Return the recursive effective representation."""

        if not isinstance(effective, EffectiveKnowledgeBase):
            raise TypeError("effective must be an EffectiveKnowledgeBase")
        return effective.to_dict()

    def to_json(self, effective: EffectiveKnowledgeBase, indent: Optional[int] = 2) -> str:
        """Serialize deterministically with Unicode preserved."""

        return json.dumps(self.to_dict(effective), ensure_ascii=False, indent=indent, sort_keys=False)

    def save_json(self, effective: EffectiveKnowledgeBase, output_path: PathLike) -> Path:
        """Write an effective artifact to the requested path."""

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(effective, indent=2) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def generate_output_filename(effective: EffectiveKnowledgeBase) -> str:
        """Return a deterministic filename derived from the effective identity."""

        identity = re.sub(r"[^A-Za-z0-9]+", "_", effective.effective_kb_id).strip("_")
        if not identity:
            raise ValueError("effective_kb_id is required for output filename")
        return f"{identity}_effective_kb.json"

    def get_active_requirements(
        self, effective: EffectiveKnowledgeBase, include_review: bool = False
    ) -> List[EffectiveRequirement]:
        """Return active requirements, optionally including review-only content."""

        allowed = {EffectiveStatus.ACTIVE}
        if include_review:
            allowed.add(EffectiveStatus.NEEDS_REVIEW)
        requirements = [
            req for clause in self._walk_effective(effective.clauses)
            for req in clause.requirements if req.effective_status in allowed
        ]
        requirements.extend(
            req for annex in effective.annexes for req in annex.requirements
            if req.effective_status in allowed
        )
        return requirements

    def get_summary(self, effective: EffectiveKnowledgeBase) -> Dict[str, Any]:
        """Return status, operation, applicability, and technical-data counts."""

        clauses = list(self._walk_effective(effective.clauses))
        requirements = [req for clause in clauses for req in clause.requirements]
        requirements.extend(req for annex in effective.annexes for req in annex.requirements)
        active = [req for req in requirements if req.effective_status is EffectiveStatus.ACTIVE]
        operations = [operation for clause in clauses for operation in clause.applied_operations]
        operations.extend(operation for annex in effective.annexes for operation in annex.applied_operations)
        operation_counts = Counter(item.operation_type.value for item in operations)
        operation_counts.update(
            source.relationship_type for definition in effective.definitions
            for source in definition.delta_sources if source.relationship_type
        )
        status_counts = lambda items: dict(Counter(item.effective_status.value for item in items))
        return {
            "effective_kb_id": effective.effective_kb_id,
            "base_standard": effective.base_standard.standard_id,
            "delta_standard": effective.delta_standard.standard_id,
            "build_status": effective.build_status.value,
            "clauses": {"total": len(clauses), **self._expanded_status_counts(clauses)},
            "requirements": {"total": len(requirements), **self._expanded_status_counts(requirements)},
            "definitions": {"total": len(effective.definitions),
                            **self._expanded_status_counts(effective.definitions)},
            "annexes": len(effective.annexes),
            "tables": len(effective.tables),
            "operations": dict(operation_counts),
            "unresolved_operations": len(effective.unresolved_operations),
            "technical_constraints_active": sum(len(req.technical_constraints) for req in active),
            "applicability_active": dict(Counter(req.applicability.status.value for req in active)),
        }

    def audit(
        self, effective: EffectiveKnowledgeBase, base_kb: KnowledgeBase, delta_kb: KnowledgeBase
    ) -> Dict[str, Any]:
        """Return non-evaluative completeness and provenance diagnostics."""

        clauses = list(self._walk_effective(effective.clauses))
        requirements = [req for clause in clauses for req in clause.requirements]
        requirements.extend(req for annex in effective.annexes for req in annex.requirements)
        ids = [c.effective_clause_id for c in clauses] + [r.effective_requirement_id for r in requirements]
        ids += [d.effective_definition_id for d in effective.definitions]
        effective_ids = set(ids)
        delta_sources = {
            (source.clause_id, source.requirement_id)
            for req in requirements for source in req.delta_sources
        }
        delta_requirements = [
            (clause.clause_id, req.requirement_id)
            for clause in self._walk_clauses(delta_kb.clauses) for req in clause.requirements
        ]
        delta_requirements.extend(
            (None, req.requirement_id) for annex in delta_kb.annexes for req in annex.requirements
        )
        delta_definition_ids = {source.definition_id for item in effective.definitions
                                for source in item.delta_sources}
        main_ids = {clause.clause_id for clause in clauses}
        main_delta_pairs = {(source.clause_id, source.requirement_id)
                            for clause in clauses for req in clause.requirements
                            for source in req.delta_sources}
        annex_delta_pairs = {(source.clause_id, source.requirement_id)
                             for annex in effective.annexes for req in annex.requirements
                             for source in req.delta_sources}
        represented_delta_requirement_ids = {source.requirement_id for req in requirements
                                              for source in req.delta_sources}
        source_requirements: Dict[Tuple[Optional[str], Optional[str], Optional[str]], Requirement] = {}
        for source_kb in (base_kb, delta_kb):
            for source_clause in self._walk_clauses(source_kb.clauses):
                for source_req in source_clause.requirements:
                    source_requirements[(source_kb.document.standard_id, source_clause.clause_id,
                                         source_req.requirement_id)] = source_req
            for source_annex in source_kb.annexes:
                for source_req in source_annex.requirements:
                    source_requirements[(source_kb.document.standard_id,
                                         self._requirement_clause_id(source_req.requirement_id),
                                         source_req.requirement_id)] = source_req
        formula_changes: List[str] = []
        applicability_changes: List[str] = []
        for effective_req in requirements:
            for source in [*effective_req.base_sources, *effective_req.delta_sources]:
                source_req = source_requirements.get(
                    (source.standard_id, source.clause_id, source.requirement_id)
                )
                if source_req is None:
                    continue
                if effective_req.applicability.to_dict() != source_req.applicability.to_dict():
                    applicability_changes.append(effective_req.effective_requirement_id)
                if ([item.to_dict() for item in effective_req.technical_constraints] !=
                        [item.to_dict() for item in source_req.technical_constraints]):
                    formula_changes.append(effective_req.effective_requirement_id)
        return {
            "active_replaced_base_requirements": [r.effective_requirement_id for r in requirements
                if r.effective_source_type is EffectiveSourceType.BASE and r.superseded_by
                and r.effective_status is EffectiveStatus.ACTIVE],
            "active_not_applicable_base_requirements": [r.effective_requirement_id for r in requirements
                if r.effective_source_type is EffectiveSourceType.BASE and r.effective_status is EffectiveStatus.ACTIVE
                and any(s.relationship_type == "NOT_APPLICABLE" for s in r.delta_sources)],
            "dropped_delta_normative_requirements": [item for item in delta_requirements
                if item not in delta_sources and item[1] not in represented_delta_requirement_ids],
            "dropped_delta_definitions": [d.clause_id for d in delta_kb.definitions
                                          if d.clause_id not in delta_definition_ids],
            "duplicate_effective_ids": sorted(key for key, value in Counter(ids).items() if value > 1),
            "missing_provenance": [r.effective_requirement_id for r in requirements
                                   if not r.base_sources and not r.delta_sources],
            "invalid_superseded_by_references": [r.effective_requirement_id for r in requirements
                                                  if r.superseded_by and r.superseded_by not in effective_ids],
            "unresolved_modification_operations": [item for item in effective.unresolved_operations
                                                     if item.get("operation") == "MODIFICATION"],
            "part_2_none_clauses_dropped": [c.clause_id for c in self._walk_clauses(delta_kb.clauses)
                if c.relationship_to_parent.type is RelationshipType.NONE and c.requirements
                and c.clause_id not in main_ids],
            "annex_content_duplicated_in_main": sorted(main_delta_pairs & annex_delta_pairs),
            "formula_changes": sorted(set(formula_changes)),
            "applicability_changes": sorted(set(applicability_changes)),
        }

    def _project_base_clause(self, clause: Clause, document: StandardDocument) -> EffectiveClause:
        source = self._clause_source(document, clause)
        return EffectiveClause(
            effective_clause_id=self._clause_id("MAIN", clause.clause_id),
            clause_id=clause.clause_id,
            title=clause.title,
            effective_status=EffectiveStatus.ACTIVE,
            base_sources=[source],
            requirements=[self._effective_requirement(req, clause, document, "MAIN",
                EffectiveSourceType.BASE, EffectiveStatus.ACTIVE) for req in clause.requirements],
            children=[self._project_base_clause(child, document) for child in clause.children],
            page_start=clause.source.page_start, page_end=clause.source.page_end,
            raw_text=clause.source.raw_text,
        )

    def _project_base_definition(
        self, definition: Definition, document: StandardDocument
    ) -> EffectiveDefinition:
        source = self._definition_source(document, definition)
        return EffectiveDefinition(
            effective_definition_id=f"E-D-{self._token(definition.clause_id or definition.term)}",
            term=definition.term, definition=definition.definition, clause_id=definition.clause_id,
            effective_status=EffectiveStatus.ACTIVE,
            effective_source_type=EffectiveSourceType.BASE, base_sources=[source],
        )

    def _project_base_annex(self, annex: Annex, document: StandardDocument) -> EffectiveAnnex:
        source = self._annex_source(document, annex)
        requirements = [self._effective_requirement(
            req, None, document, f"ANNEX_{annex.annex_id}",
            EffectiveSourceType.BASE, EffectiveStatus.ACTIVE, annex=annex
        ) for req in annex.requirements]
        return EffectiveAnnex(
            effective_annex_id=f"E-A-{self._token(annex.annex_id)}",
            annex_id=annex.annex_id, title=annex.title, normative=annex.normative,
            effective_status=EffectiveStatus.ACTIVE, base_sources=[source],
            requirements=requirements,
            clauses=[self._project_annex_clause(item, document, annex, EffectiveSourceType.BASE)
                     for item in annex.clauses],
        )

    def _project_annex_clause(
        self, clause: Clause, document: StandardDocument, annex: Annex,
        source_type: EffectiveSourceType,
    ) -> EffectiveClause:
        namespace = f"ANNEX_{annex.annex_id}"
        status = EffectiveStatus.ACTIVE
        return EffectiveClause(
            effective_clause_id=self._clause_id(namespace, clause.clause_id),
            clause_id=clause.clause_id, title=clause.title, effective_status=status,
            base_sources=([self._clause_source(document, clause)]
                          if source_type is EffectiveSourceType.BASE else []),
            delta_sources=([self._clause_source(document, clause,
                                                clause.relationship_to_parent.type)]
                           if source_type is not EffectiveSourceType.BASE else []),
            # Annex.requirements is the canonical flattened semantic owner used by
            # every downstream requirement engine.  Annex clauses retain structure
            # and provenance only; serializing their requirements here as well
            # creates a second active object (and, for some operations, the same ID).
            requirements=[],
            children=[self._project_annex_clause(child, document, annex, source_type)
                      for child in clause.children],
            page_start=clause.source.page_start, page_end=clause.source.page_end,
            raw_text=clause.source.raw_text,
        )

    def _apply_delta_clauses(
        self, delta: KnowledgeBase, effective: EffectiveKnowledgeBase,
        index: Dict[str, EffectiveClause]
    ) -> None:
        def apply(clause: Clause, delta_parent: Optional[Clause]) -> None:
            relation = clause.relationship_to_parent.type
            target_id = (clause.clause_id if relation is RelationshipType.NONE else
                         clause.relationship_to_parent.parent_clause_id or clause.clause_id)
            target = index.get(target_id)
            if target is None and clause.clause_id in index:
                target = index[clause.clause_id]
            if target is None:
                target = self._create_delta_extension(clause, delta_parent, delta, effective, index)
            elif relation is not RelationshipType.NONE:
                if relation is RelationshipType.UNRESOLVED:
                    self._preserve_unresolved_operation(target, clause, delta.document, effective)
                elif self._requires_scoped_review(clause):
                    self._preserve_scoped_operation(target, clause, delta.document, effective)
                else:
                    self._record_operation(target, clause, delta.document, relation)
                if relation is RelationshipType.UNRESOLVED or self._requires_scoped_review(clause):
                    pass
                elif relation is RelationshipType.ADDITION:
                    self._append_delta_requirements(target, clause, delta.document,
                                                    EffectiveSourceType.PART_2_ADDITION, "ADD")
                elif relation is RelationshipType.REPLACEMENT:
                    self._apply_replacement(target, clause, delta.document)
                elif relation is RelationshipType.NOT_APPLICABLE:
                    self._deactivate_subtree(target, clause, delta.document)
                elif relation is RelationshipType.MODIFICATION:
                    self._apply_modification(target, clause, delta.document, effective)
                elif relation is RelationshipType.NEW_REQUIREMENT:
                    self._append_delta_requirements(target, clause, delta.document,
                                                    EffectiveSourceType.PART_2_NEW_REQUIREMENT, "NEW")
            if target is not None:
                self._propagate_delta_semantics(target, clause, delta.document)
            for child in clause.children:
                apply(child, clause)
        for clause in delta.clauses:
            apply(clause, None)

    def _create_delta_extension(
        self, clause: Clause, parent: Optional[Clause], delta: KnowledgeBase,
        effective: EffectiveKnowledgeBase, index: Dict[str, EffectiveClause]
    ) -> Optional[EffectiveClause]:
        normative_requirements = [req for req in clause.requirements if req.normative]
        descendant_requirements = [
            req for child in self._walk_clauses(clause.children)
            for req in child.requirements if req.normative
        ]
        relation = clause.relationship_to_parent.type
        parent_effective = index.get(parent.clause_id) if parent else None
        contextual = parent_effective is not None and bool(parent_effective.delta_sources or parent_effective.applied_operations)
        explicit = relation in {RelationshipType.ADDITION, RelationshipType.REPLACEMENT,
                                RelationshipType.NEW_REQUIREMENT, RelationshipType.MODIFICATION}
        if not (normative_requirements or descendant_requirements) or not (contextual or explicit):
            return None
        status = EffectiveStatus.ACTIVE if (contextual or explicit) else EffectiveStatus.NEEDS_REVIEW
        source_type, marker = self._source_type_marker(relation)
        if relation is RelationshipType.NONE:
            source_type, marker = EffectiveSourceType.PART_2_NEW_REQUIREMENT, "NEW"
        item = EffectiveClause(
            effective_clause_id=self._clause_id("MAIN", clause.clause_id), clause_id=clause.clause_id,
            title=clause.title, effective_status=status,
            delta_sources=[self._clause_source(delta.document, clause, relation)],
            applied_operations=[EffectiveOperation(
                EffectiveOperationType.NEW_REQUIREMENT, delta.document.standard_id,
                clause.clause_id, None, status,
                "Part 2 normative extension preserved; no exact Base clause target.")],
            requirements=[self._effective_requirement(req, clause, delta.document, "MAIN",
                source_type, status, marker=marker, relationship=relation) for req in clause.requirements],
            page_start=clause.source.page_start, page_end=clause.source.page_end,
            raw_text=clause.source.raw_text,
            review_reason=(None if status is EffectiveStatus.ACTIVE else
                           "Ambiguous Part 2 normative extension context."),
        )
        if parent_effective is not None:
            parent_effective.children.append(item)
        else:
            effective.clauses.append(item)
        index[item.clause_id] = item
        return item

    def _record_operation(
        self, target: EffectiveClause, delta_clause: Clause,
        document: StandardDocument, relationship: RelationshipType,
        status: EffectiveStatus = EffectiveStatus.ACTIVE,
    ) -> None:
        operation_type = EffectiveOperationType(relationship.value)
        target.applied_operations.append(EffectiveOperation(
            operation_type, document.standard_id, delta_clause.clause_id,
            delta_clause.relationship_to_parent.parent_clause_id, status,
            delta_clause.relationship_to_parent.notes,
            copy.deepcopy(delta_clause.relationship_to_parent.directive),
        ))
        target.delta_sources.append(self._clause_source(document, delta_clause, relationship))

    @staticmethod
    def _requires_scoped_review(delta_clause: Clause) -> bool:
        directive = delta_clause.relationship_to_parent.directive
        if directive is None:
            return False
        return (
            directive.qualifier_type is OperationQualifierType.CONDITION
            or directive.target_scope in {
                OperationTargetScope.TABLE,
                OperationTargetScope.PARTIAL_CONTENT,
                OperationTargetScope.UNKNOWN_TARGET,
            }
        )

    def _preserve_scoped_operation(
        self, target: EffectiveClause, delta_clause: Clause,
        document: StandardDocument, effective: EffectiveKnowledgeBase,
    ) -> None:
        """Preserve scoped Delta content without deleting unaffected Base content."""

        relation = delta_clause.relationship_to_parent.type
        self._record_operation(
            target, delta_clause, document, relation, EffectiveStatus.NEEDS_REVIEW
        )
        source_type, marker = self._source_type_marker(relation)
        added = self._append_delta_requirements(
            target, delta_clause, document, source_type, marker,
            EffectiveStatus.NEEDS_REVIEW,
        )
        reason = "Qualified Delta operation preserved for scoped applicability/target review."
        for requirement in added:
            requirement.review_reason = reason
        target.effective_status = EffectiveStatus.NEEDS_REVIEW
        target.review_reason = reason
        directive = delta_clause.relationship_to_parent.directive
        effective.unresolved_operations.append({
            "operation": relation.value,
            "delta_clause_id": delta_clause.clause_id,
            "target_base_clause_id": target.clause_id,
            "reason": reason,
            "directive": directive.to_dict() if directive else None,
        })

    def _preserve_unresolved_operation(
        self, target: EffectiveClause, delta_clause: Clause,
        document: StandardDocument, effective: EffectiveKnowledgeBase,
    ) -> None:
        """Represent an ambiguous relationship without guessing its operation."""

        self._record_operation(
            target, delta_clause, document, RelationshipType.UNRESOLVED,
            EffectiveStatus.NEEDS_REVIEW,
        )
        added = self._append_delta_requirements(
            target, delta_clause, document, EffectiveSourceType.COMBINED, "UNRESOLVED",
            EffectiveStatus.NEEDS_REVIEW,
        )
        reason = "Delta relationship operation is unresolved; Base content remains active."
        for requirement in added:
            requirement.review_reason = reason
        target.effective_status = EffectiveStatus.NEEDS_REVIEW
        target.review_reason = reason
        effective.unresolved_operations.append({
            "operation": "UNRESOLVED",
            "delta_clause_id": delta_clause.clause_id,
            "target_base_clause_id": target.clause_id,
            "reason": reason,
            "source_text": delta_clause.source.raw_text,
        })

    def _append_delta_requirements(
        self, target: EffectiveClause, delta_clause: Clause, document: StandardDocument,
        source_type: EffectiveSourceType, marker: str,
        status: EffectiveStatus = EffectiveStatus.ACTIVE
    ) -> List[EffectiveRequirement]:
        added = [self._effective_requirement(req, delta_clause, document, "MAIN", source_type,
                 status, marker=marker, relationship=delta_clause.relationship_to_parent.type)
                 for req in delta_clause.requirements]
        target.requirements.extend(added)
        return added

    def _apply_replacement(
        self, target: EffectiveClause, delta_clause: Clause, document: StandardDocument
    ) -> None:
        base_requirements = [req for req in self._requirements_in_subtree(target)
                             if req.effective_source_type is EffectiveSourceType.BASE
                             and req.effective_status is EffectiveStatus.ACTIVE]
        replacements = self._append_delta_requirements(
            target, delta_clause, document, EffectiveSourceType.PART_2_REPLACEMENT, "REP"
        )
        target.title = delta_clause.title
        target.page_start = delta_clause.source.page_start
        target.page_end = delta_clause.source.page_end
        target.raw_text = delta_clause.source.raw_text
        replacement_id = replacements[0].effective_requirement_id if replacements else (
            f"E-OP-MAIN-{self._token(target.clause_id)}-REPLACEMENT"
        )
        for base_req in base_requirements:
            base_req.effective_status = EffectiveStatus.INACTIVE
            base_req.superseded_by = replacement_id
        for replacement in replacements:
            replacement.supersedes.extend(source for req in base_requirements for source in req.base_sources)

    def _apply_modification(
        self, target: EffectiveClause, delta_clause: Clause, document: StandardDocument,
        effective: EffectiveKnowledgeBase
    ) -> None:
        base_requirements = [req for req in target.requirements
                             if req.effective_source_type is EffectiveSourceType.BASE
                             and req.effective_status is EffectiveStatus.ACTIVE]
        for delta_req in delta_clause.requirements:
            match = self._map_modification(delta_req, base_requirements)
            if match is None:
                item = self._effective_requirement(
                    delta_req, delta_clause, document, "MAIN",
                    EffectiveSourceType.PART_2_MODIFICATION, EffectiveStatus.NEEDS_REVIEW,
                    marker="MOD", relationship=RelationshipType.MODIFICATION,
                    review_reason="Ambiguous Base requirement mapping for Part 2 modification.",
                )
                target.requirements.append(item)
                target.effective_status = EffectiveStatus.NEEDS_REVIEW
                target.review_reason = "Ambiguous Base requirement mapping for Part 2 modification."
                effective.unresolved_operations.append({
                    "operation": "MODIFICATION", "delta_clause_id": delta_clause.clause_id,
                    "delta_requirement_id": delta_req.requirement_id,
                    "target_base_clause_id": target.clause_id,
                    "reason": "Ambiguous requirement mapping",
                })
                continue
            item = self._effective_requirement(
                delta_req, delta_clause, document, "MAIN",
                EffectiveSourceType.PART_2_MODIFICATION, EffectiveStatus.ACTIVE,
                marker="MOD", relationship=RelationshipType.MODIFICATION,
            )
            item.supersedes.extend(copy.deepcopy(match.base_sources))
            match.effective_status = EffectiveStatus.INACTIVE
            match.superseded_by = item.effective_requirement_id
            target.requirements.append(item)
            base_requirements.remove(match)

    def _map_modification(
        self, delta: Requirement, candidates: Sequence[EffectiveRequirement]
    ) -> Optional[EffectiveRequirement]:
        if len(candidates) == 1:
            return candidates[0]
        typed = [item for item in candidates if item.requirement_type is delta.requirement_type]
        pool = typed or list(candidates)
        if not pool:
            return None
        scored = sorted(((self._overlap(delta.text, item.text), item) for item in pool),
                        key=lambda pair: pair[0], reverse=True)
        if scored[0][0] < 0.35:
            return None
        if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.15:
            return None
        return scored[0][1]

    def _deactivate_subtree(
        self, target: EffectiveClause, delta_clause: Clause, document: StandardDocument
    ) -> None:
        delta_source = self._clause_source(document, delta_clause, RelationshipType.NOT_APPLICABLE)
        if target.applied_operations:
            target.applied_operations[-1].status = EffectiveStatus.INACTIVE
        for clause in self._walk_effective([target]):
            clause.effective_status = EffectiveStatus.INACTIVE
            if clause is not target:
                clause.delta_sources.append(copy.deepcopy(delta_source))
            for req in clause.requirements:
                req.effective_status = EffectiveStatus.INACTIVE
                req.delta_sources.append(copy.deepcopy(delta_source))

    def _apply_delta_definitions(
        self, delta: KnowledgeBase, effective: EffectiveKnowledgeBase
    ) -> None:
        index = {item.clause_id: item for item in effective.definitions}
        for definition in delta.definitions:
            relation = definition.relationship_to_parent.type
            target_id = definition.relationship_to_parent.parent_clause_id or definition.clause_id
            target = index.get(target_id)
            delta_source = self._definition_source(delta.document, definition)
            if relation is RelationshipType.REPLACEMENT and target:
                replacement = EffectiveDefinition(
                    effective_definition_id=f"E-D-{self._token(definition.clause_id or definition.term)}",
                    term=definition.term, definition=definition.definition,
                    clause_id=definition.clause_id, effective_status=EffectiveStatus.ACTIVE,
                    effective_source_type=EffectiveSourceType.PART_2_REPLACEMENT,
                    base_sources=copy.deepcopy(target.base_sources), delta_sources=[delta_source],
                    supersedes=copy.deepcopy(target.base_sources),
                )
                effective.definitions[effective.definitions.index(target)] = replacement
                index[definition.clause_id] = replacement
            elif relation is RelationshipType.NOT_APPLICABLE and target:
                target.effective_status = EffectiveStatus.INACTIVE
                target.delta_sources.append(delta_source)
            elif relation in {RelationshipType.ADDITION, RelationshipType.NEW_REQUIREMENT} or target is None:
                status = EffectiveStatus.ACTIVE if relation in {
                    RelationshipType.ADDITION, RelationshipType.NEW_REQUIREMENT
                } else EffectiveStatus.NEEDS_REVIEW
                item = EffectiveDefinition(
                    effective_definition_id=f"E-D-{self._token(definition.clause_id or definition.term)}-P2",
                    term=definition.term, definition=definition.definition, clause_id=definition.clause_id,
                    effective_status=status,
                    effective_source_type=EffectiveSourceType.PART_2_NEW_REQUIREMENT,
                    delta_sources=[delta_source],
                    review_reason=None if status is EffectiveStatus.ACTIVE else "Unmapped Delta definition operation.",
                )
                effective.definitions.append(item)
                index[definition.clause_id] = item
                if status is EffectiveStatus.NEEDS_REVIEW:
                    effective.unresolved_operations.append({"operation": relation.value,
                        "delta_definition_id": definition.clause_id,
                        "reason": "Unmapped Delta definition operation"})
            elif relation is RelationshipType.MODIFICATION and target:
                target.effective_status = EffectiveStatus.NEEDS_REVIEW
                target.delta_sources.append(delta_source)
                target.review_reason = "Definition modification requires semantic review."
                effective.unresolved_operations.append({"operation": "MODIFICATION",
                    "delta_definition_id": definition.clause_id,
                    "reason": "Definition modification requires semantic review"})

    def _apply_delta_annexes(
        self, delta: KnowledgeBase, effective: EffectiveKnowledgeBase
    ) -> None:
        index = {annex.annex_id: annex for annex in effective.annexes}
        for annex in delta.annexes:
            source = self._annex_source(delta.document, annex)
            target = index.get(annex.annex_id)
            if target is None and not annex.normative and not any(
                requirement.normative for requirement in annex.requirements
            ):
                continue
            clause_index = {clause.clause_id: clause
                            for clause in self._walk_clauses(annex.clauses)}
            requirements = []
            for req in annex.requirements:
                clause_id = self._requirement_clause_id(req.requirement_id)
                source_clause = clause_index.get(clause_id)
                relation = (source_clause.relationship_to_parent.type
                            if source_clause else RelationshipType.NONE)
                source_type, marker = self._source_type_marker(relation)
                if relation is RelationshipType.NONE:
                    source_type, marker = EffectiveSourceType.PART_2_NEW_REQUIREMENT, "NEW"
                requirements.append(self._effective_requirement(
                    req, source_clause, delta.document, f"ANNEX_{annex.annex_id}",
                    source_type, EffectiveStatus.ACTIVE, marker=marker,
                    annex=annex, relationship=relation,
                ))
            delta_clauses = [self._project_annex_clause(
                item, delta.document, annex, EffectiveSourceType.PART_2_NEW_REQUIREMENT
            ) for item in annex.clauses]
            if target is None:
                target = EffectiveAnnex(
                    effective_annex_id=f"E-A-{self._token(annex.annex_id)}-P2",
                    annex_id=annex.annex_id, title=annex.title, normative=annex.normative,
                    effective_status=EffectiveStatus.ACTIVE, delta_sources=[source],
                    requirements=requirements,
                    clauses=delta_clauses,
                    applied_operations=[EffectiveOperation(
                        EffectiveOperationType.NEW_REQUIREMENT, delta.document.standard_id,
                        annex.annex_id, None, EffectiveStatus.ACTIVE,
                        "Part 2 annex preserved in annex namespace.")],
                )
                effective.annexes.append(target)
                index[annex.annex_id] = target
            else:
                target.delta_sources.append(source)
                target.requirements.extend(requirements)
                self._apply_delta_annex_clauses(annex, target, delta.document)

    def _apply_delta_annex_clauses(
        self, annex: Annex, target: EffectiveAnnex, document: StandardDocument
    ) -> None:
        """Apply explicit annex-clause operations within the annex namespace."""

        index = {item.clause_id: item for item in self._walk_effective(target.clauses)}
        namespace = f"ANNEX_{annex.annex_id}"
        for source_clause in self._walk_clauses(annex.clauses):
            relation = source_clause.relationship_to_parent.type
            target_id = (source_clause.relationship_to_parent.parent_clause_id
                         or source_clause.clause_id)
            existing = index.get(target_id)
            if existing is None:
                created = self._project_annex_clause(
                    source_clause, document, annex,
                    EffectiveSourceType.PART_2_NEW_REQUIREMENT,
                )
                target.clauses.append(created)
                index.update({node.clause_id: node for node in self._walk_effective([created])})
                continue
            if relation is RelationshipType.NONE:
                continue
            self._record_operation(existing, source_clause, document, relation)
            if relation is RelationshipType.NOT_APPLICABLE:
                for node in self._walk_effective([existing]):
                    node.effective_status = EffectiveStatus.INACTIVE
                for requirement in target.requirements:
                    if requirement.clause_id == existing.clause_id:
                        requirement.effective_status = EffectiveStatus.INACTIVE
            elif relation is RelationshipType.REPLACEMENT:
                base = [req for req in target.requirements
                        if req.clause_id == existing.clause_id
                        if req.effective_source_type is EffectiveSourceType.BASE
                        and req.effective_status is EffectiveStatus.ACTIVE]
                added = [req for req in target.requirements
                         if req.clause_id == source_clause.clause_id
                         and req.effective_source_type is EffectiveSourceType.PART_2_REPLACEMENT]
                replacement_id = added[0].effective_requirement_id if added else None
                for requirement in base:
                    requirement.effective_status = EffectiveStatus.INACTIVE
                    requirement.superseded_by = replacement_id
            elif relation in {RelationshipType.ADDITION, RelationshipType.NEW_REQUIREMENT,
                              RelationshipType.MODIFICATION}:
                # Semantic requirements were already flattened once into
                # EffectiveAnnex.requirements above. Annex clauses own only
                # structure and operation provenance.
                continue

    def _apply_delta_tables(self, delta: KnowledgeBase, effective: EffectiveKnowledgeBase) -> None:
        replacement_targets = set()
        for clause in self._walk_clauses(delta.clauses):
            directive = clause.relationship_to_parent.directive
            if (clause.relationship_to_parent.type is RelationshipType.REPLACEMENT
                    and directive and directive.target_scope is OperationTargetScope.TABLE):
                target_text = directive.target_text or ""
                match = re.search(r"\btable\s+([A-Za-z0-9.-]+)", target_text, re.IGNORECASE)
                if match:
                    replacement_targets.add(match.group(1).casefold())
        seen = {table.table_id for table in effective.tables}
        for table in delta.tables:
            if table.table_id not in seen:
                effective.tables.append(copy.deepcopy(table)); seen.add(table.table_id)
            elif table.table_id.casefold() in replacement_targets:
                effective.tables = [copy.deepcopy(table) if item.table_id == table.table_id else item
                                    for item in effective.tables]
            else:
                effective.tables.append(copy.deepcopy(table))
                effective.unresolved_operations.append({"operation": "TABLE_REVIEW",
                    "table_id": table.table_id, "reason": "Base and Delta table IDs collide"})

    def _propagate_delta_semantics(
        self, target: EffectiveClause, delta_clause: Clause, document: StandardDocument
    ) -> None:
        """Apply explicit Delta exclusions to the requirements they qualify."""

        exclusions = [req for req in delta_clause.requirements if req.semantic_type in {
            RequirementSemanticType.EXCLUSION,
            RequirementSemanticType.CONDITIONAL_EXCLUSION,
        }]
        for exclusion in exclusions:
            test_scoped = bool(re.search(r"\b(?:test|tested|subjected)\b", exclusion.text,
                                         re.IGNORECASE))
            candidates = [req for req in target.requirements
                          if req.semantic_type not in {
                              RequirementSemanticType.EXCLUSION,
                              RequirementSemanticType.CONDITIONAL_EXCLUSION,
                          } and (not test_scoped or req.requirement_type.value == "TEST")]
            source = EffectiveSourceReference(
                standard_id=document.standard_id, standard_number=document.standard_number,
                clause_id=delta_clause.clause_id, requirement_id=exclusion.requirement_id,
                relationship_type=delta_clause.relationship_to_parent.type.value,
                page_start=delta_clause.source.page_start, page_end=delta_clause.source.page_end,
            )
            for requirement in candidates:
                rule = copy.deepcopy(exclusion.applicability)
                existing = requirement.applicability
                if (existing.status is ApplicabilityStatus.RESOLVED
                        and existing.logic and rule.status is ApplicabilityStatus.RESOLVED
                        and rule.logic):
                    # Existing positive scope remains mandatory; the Delta
                    # exclusion removes only the documented subset.
                    requirement.applicability = copy.deepcopy(existing)
                    requirement.applicability.logic = {
                        "all": [copy.deepcopy(existing.logic), {"not": copy.deepcopy(rule.logic)}]
                    }
                    requirement.applicability.effect = ApplicabilityEffect.APPLIES
                    requirement.condition_text = (
                        f"{existing.condition_text}; excluding {rule.condition_text}"
                    )
                    requirement.applicability.condition_text = requirement.condition_text
                elif existing.status is ApplicabilityStatus.ALWAYS:
                    if rule.condition_text:
                        requirement.condition_text = rule.condition_text
                    requirement.applicability = rule
                else:
                    # A resolved Part-2 exclusion has priority for the test it
                    # excludes. If its condition is false, the requirement is
                    # active; if facts are missing, it remains unresolved.
                    if rule.condition_text:
                        requirement.condition_text = rule.condition_text
                    requirement.applicability = rule
                if not any(item.requirement_id == source.requirement_id
                           and item.standard_id == source.standard_id
                           for item in requirement.delta_sources):
                    requirement.delta_sources.append(copy.deepcopy(source))

    def _effective_requirement(
        self, requirement: Requirement, clause: Optional[Clause], document: StandardDocument,
        namespace: str, source_type: EffectiveSourceType, status: EffectiveStatus,
        marker: str = "BASE", relationship: RelationshipType = RelationshipType.NONE,
        annex: Optional[Annex] = None, review_reason: Optional[str] = None
    ) -> EffectiveRequirement:
        clause_id = clause.clause_id if clause else self._requirement_clause_id(requirement.requirement_id)
        source = EffectiveSourceReference(
            standard_id=document.standard_id, standard_number=document.standard_number,
            clause_id=clause_id, requirement_id=requirement.requirement_id,
            annex_id=annex.annex_id if annex else None,
            relationship_type=relationship.value if relationship is not RelationshipType.NONE else None,
            page_start=(clause.source.page_start if clause else annex.source.page_start if annex else None),
            page_end=(clause.source.page_end if clause else annex.source.page_end if annex else None),
        )
        eid = self._requirement_id(namespace, clause_id, requirement.requirement_id, marker)
        return EffectiveRequirement(
            effective_requirement_id=eid, clause_id=clause_id, text=requirement.text,
            requirement_type=requirement.requirement_type, normative=requirement.normative,
            applicability=copy.deepcopy(requirement.applicability),
            effective_status=status, effective_source_type=source_type,
            condition_text=requirement.condition_text, test_method=copy.deepcopy(requirement.test_method),
            limits=copy.deepcopy(requirement.limits),
            technical_constraints=copy.deepcopy(requirement.technical_constraints),
            references=copy.deepcopy(requirement.references),
            base_sources=[source] if source_type is EffectiveSourceType.BASE else [],
            delta_sources=[] if source_type is EffectiveSourceType.BASE else [source],
            review_reason=review_reason,
            semantic_type=requirement.semantic_type,
            executable_rules=copy.deepcopy(requirement.executable_rules),
            criticality=copy.deepcopy(requirement.criticality),
            decision_effect=requirement.decision_effect,
        )

    @staticmethod
    def _source_type_marker(relation: RelationshipType) -> Tuple[EffectiveSourceType, str]:
        return {
            RelationshipType.ADDITION: (EffectiveSourceType.PART_2_ADDITION, "ADD"),
            RelationshipType.MODIFICATION: (EffectiveSourceType.PART_2_MODIFICATION, "MOD"),
            RelationshipType.REPLACEMENT: (EffectiveSourceType.PART_2_REPLACEMENT, "REP"),
            RelationshipType.NEW_REQUIREMENT: (EffectiveSourceType.PART_2_NEW_REQUIREMENT, "NEW"),
        }.get(relation, (EffectiveSourceType.PART_2_NEW_REQUIREMENT, "NEW"))

    @staticmethod
    def _clause_source(
        document: StandardDocument, clause: Clause,
        relationship: RelationshipType = RelationshipType.NONE
    ) -> EffectiveSourceReference:
        return EffectiveSourceReference(
            standard_id=document.standard_id, standard_number=document.standard_number,
            clause_id=clause.clause_id,
            relationship_type=relationship.value if relationship is not RelationshipType.NONE else None,
            page_start=clause.source.page_start, page_end=clause.source.page_end,
        )

    @staticmethod
    def _definition_source(document: StandardDocument, definition: Definition) -> EffectiveSourceReference:
        relationship = definition.relationship_to_parent.type
        return EffectiveSourceReference(
            standard_id=document.standard_id, standard_number=document.standard_number,
            clause_id=definition.clause_id, definition_id=definition.clause_id,
            relationship_type=relationship.value if relationship is not RelationshipType.NONE else None,
            page_start=definition.source.page_start, page_end=definition.source.page_end,
        )

    @staticmethod
    def _annex_source(document: StandardDocument, annex: Annex) -> EffectiveSourceReference:
        return EffectiveSourceReference(
            standard_id=document.standard_id, standard_number=document.standard_number,
            annex_id=annex.annex_id, page_start=annex.source.page_start, page_end=annex.source.page_end,
        )

    @classmethod
    def _requirements_in_subtree(cls, clause: EffectiveClause) -> Iterable[EffectiveRequirement]:
        for item in cls._walk_effective([clause]):
            yield from item.requirements

    @staticmethod
    def _walk_effective(clauses: Sequence[EffectiveClause]) -> Iterable[EffectiveClause]:
        for clause in clauses:
            yield clause
            yield from GenericIECEffectiveKnowledgeBaseBuilder._walk_effective(clause.children)

    @staticmethod
    def _walk_clauses(clauses: Sequence[Clause]) -> Iterable[Clause]:
        for clause in clauses:
            yield clause
            yield from GenericIECEffectiveKnowledgeBaseBuilder._walk_clauses(clause.children)

    @staticmethod
    def _expanded_status_counts(items: Sequence[Any]) -> Dict[str, int]:
        counts = Counter(item.effective_status.value for item in items)
        return {"active": counts["ACTIVE"], "inactive": counts["INACTIVE"],
                "needs_review": counts["NEEDS_REVIEW"]}

    @classmethod
    def _overlap(cls, first: str, second: str) -> float:
        tokenize = lambda text: {word for word in re.findall(r"[a-z0-9]+", text.casefold())
                                 if word not in cls._STOP_WORDS and len(word) > 1}
        left, right = tokenize(first), tokenize(second)
        return len(left & right) / len(left | right) if left | right else 0.0

    @classmethod
    def _effective_kb_id(cls, base: StandardDocument, delta: StandardDocument) -> str:
        return f"{cls._token(base.standard_id or base.standard_number or 'BASE')}__{cls._token(delta.standard_id or delta.standard_number or 'PART_2')}"

    @classmethod
    def _clause_id(cls, namespace: str, clause_id: str) -> str:
        return f"E-C-{cls._token(namespace)}-{cls._token(clause_id)}"

    @classmethod
    def _requirement_id(cls, namespace: str, clause_id: str, requirement_id: str, marker: str) -> str:
        return f"E-R-{cls._token(namespace)}-{cls._token(clause_id)}-{cls._token(requirement_id)}-{marker}"

    @staticmethod
    def _requirement_clause_id(requirement_id: str) -> str:
        return re.sub(r"-R\d+$", "", requirement_id)

    @staticmethod
    def _token(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9.]+", "_", str(value)).strip("_")

    @staticmethod
    def _deactivate_clause_requirements(clause: EffectiveClause) -> None:
        for req in clause.requirements:
            req.effective_status = EffectiveStatus.INACTIVE

    @staticmethod
    def _assert_effective_integrity(effective: EffectiveKnowledgeBase) -> None:
        clauses = list(GenericIECEffectiveKnowledgeBaseBuilder._walk_effective(effective.clauses))
        requirements = [req for clause in clauses for req in clause.requirements]
        requirements.extend(req for annex in effective.annexes for req in annex.requirements)
        annex_clause_requirements = [
            req for annex in effective.annexes
            for clause in GenericIECEffectiveKnowledgeBaseBuilder._walk_effective(annex.clauses)
            for req in clause.requirements
        ]
        if annex_clause_requirements:
            raise ValueError(
                "Effective annex requirements must have one canonical annex-level owner"
            )
        identifiers = [item.effective_clause_id for item in clauses]
        identifiers.extend(item.effective_requirement_id for item in requirements)
        identifiers.extend(item.effective_definition_id for item in effective.definitions)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Effective KB contains duplicate deterministic IDs")
        valid_ids = set(identifiers)
        for req in requirements:
            if not req.base_sources and not req.delta_sources:
                raise ValueError(f"Effective requirement lacks provenance: {req.effective_requirement_id}")
            if req.superseded_by and req.superseded_by not in valid_ids:
                # Operation-only replacement with no Delta requirement is auditable but unresolved.
                if not req.superseded_by.startswith("E-OP-"):
                    raise ValueError(f"Invalid superseded_by reference: {req.superseded_by}")


__all__ = ["GenericIECEffectiveKnowledgeBaseBuilder"]
