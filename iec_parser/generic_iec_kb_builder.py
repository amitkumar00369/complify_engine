"""Orchestration and deterministic assembly for generic IEC knowledge bases."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Type, Union

from iec_parser.generic_iec_applicability_extractor import (
    GenericIECApplicabilityExtractor,
)
from iec_parser.generic_iec_applicability_normalizer import (
    GenericIECApplicabilityNormalizer,
)
from iec_parser.generic_iec_clause_builder import GenericIECClauseBuilder
from iec_parser.generic_iec_constraint_extractor import (
    GenericIECTechnicalConstraintExtractor,
)
from iec_parser.generic_iec_document_parser import GenericIECDocumentParser
from iec_parser.generic_iec_definition_parser import GenericIECDefinitionParser
from iec_parser.generic_iec_feature_registry import (
    CanonicalProductFeatureRegistry,
)
from iec_parser.generic_iec_kb_models import (
    Annex,
    ApplicabilityRule,
    ApplicabilityStatus,
    Clause,
    ClauseType,
    DocumentType,
    KnowledgeBase,
    ParentRelationship,
    RelationshipType,
    SourceReference,
    StandardDocument,
    StandardTable,
)
from iec_parser.generic_iec_relationship_parser import (
    GenericIECRelationshipParser,
)
from iec_parser.generic_iec_requirement_parser import (
    GenericIECRequirementParser,
)
from iec_parser.generic_iec_structural_parser import (
    GenericIECStructuralParser,
    StructuralBlock,
)


PathLike = Union[str, Path]


class GenericIECKnowledgeBaseBuilder:
    """Run Steps 2–10 and assemble a stable BASE or DELTA artifact."""

    def __init__(
        self,
        *,
        document_parser_cls: Type[Any] = GenericIECDocumentParser,
        structural_parser_cls: Type[Any] = GenericIECStructuralParser,
        clause_builder_cls: Type[Any] = GenericIECClauseBuilder,
        requirement_parser_cls: Type[Any] = GenericIECRequirementParser,
        relationship_parser_cls: Type[Any] = GenericIECRelationshipParser,
        applicability_extractor_cls: Type[Any] = GenericIECApplicabilityExtractor,
        applicability_normalizer_cls: Type[Any] = GenericIECApplicabilityNormalizer,
        constraint_extractor_cls: Type[Any] = GenericIECTechnicalConstraintExtractor,
        definition_parser_cls: Type[Any] = GenericIECDefinitionParser,
        registry: Optional[CanonicalProductFeatureRegistry] = None,
    ) -> None:
        """Configure existing pipeline components, allowing dependency-light tests."""

        self.document_parser_cls = document_parser_cls
        self.structural_parser_cls = structural_parser_cls
        self.clause_builder_cls = clause_builder_cls
        self.requirement_parser_cls = requirement_parser_cls
        self.relationship_parser_cls = relationship_parser_cls
        self.applicability_extractor_cls = applicability_extractor_cls
        self.applicability_normalizer_cls = applicability_normalizer_cls
        self.constraint_extractor_cls = constraint_extractor_cls
        self.definition_parser_cls = definition_parser_cls
        self.registry = registry or CanonicalProductFeatureRegistry()

    def build(self, pdf_path: PathLike) -> KnowledgeBase:
        """Build the appropriate independent KB based on document metadata."""

        path = self._require_pdf(pdf_path)
        document = self.document_parser_cls(path).parse()
        if document.document_type is DocumentType.BASE:
            return self._build_pipeline(path, document, apply_relationships=False)
        if document.document_type is DocumentType.PART_2:
            return self._build_pipeline(path, document, apply_relationships=True)
        raise ValueError(
            f"Unsupported IEC knowledge-base document type: {document.document_type.value}"
        )

    def build_base_kb(self, pdf_path: PathLike) -> KnowledgeBase:
        """Build a BASE KB, rejecting any non-BASE document."""

        path = self._require_pdf(pdf_path)
        document = self.document_parser_cls(path).parse()
        if document.document_type is not DocumentType.BASE:
            raise ValueError("build_base_kb requires a BASE standard document")
        return self._build_pipeline(path, document, apply_relationships=False)

    def build_primary_kb(self, pdf_path: PathLike) -> KnowledgeBase:
        """Build a standalone primary KB without imposing Part-1 semantics."""

        path = self._require_pdf(pdf_path)
        document = self.document_parser_cls(path).parse()
        if document.document_type in {DocumentType.PART_2, DocumentType.UNKNOWN}:
            raise ValueError(
                "build_primary_kb requires an identified non-companion standard document"
            )
        return self._build_pipeline(path, document, apply_relationships=False)

    def build_delta_kb(self, pdf_path: PathLike) -> KnowledgeBase:
        """Build a PART_2 delta KB without applying it to its parent."""

        path = self._require_pdf(pdf_path)
        document = self.document_parser_cls(path).parse()
        if document.document_type is not DocumentType.PART_2:
            raise ValueError("build_delta_kb requires a PART_2 standard document")
        return self._build_pipeline(path, document, apply_relationships=True)

    def _build_pipeline(
        self, path: Path, document: StandardDocument, *, apply_relationships: bool
    ) -> KnowledgeBase:
        structural_parser = self.structural_parser_cls(path)
        blocks: List[StructuralBlock] = structural_parser.parse()
        main_blocks = [
            block for block in blocks
            if block.semantic_context == "MAIN_CLAUSE"
            and block.block_type in {"CLAUSE", "SUBCLAUSE"}
        ]

        clauses = self._build_enriched_clauses(
            document, main_blocks, apply_relationships=apply_relationships
        )
        clauses = self._merge_definition_containers(clauses, blocks)

        kb = KnowledgeBase(
            schema_version="1.0",
            document=document,
            clauses=clauses,
            annexes=self._build_annexes(
                blocks, document, apply_relationships=apply_relationships
            ),
            tables=self._build_tables(blocks),
            definitions=self.definition_parser_cls().parse(document, blocks),
            references=[],
        )
        self._validate_assembly(kb)
        return kb

    def _build_enriched_clauses(
        self,
        document: StandardDocument,
        blocks: Sequence[StructuralBlock],
        *,
        apply_relationships: bool,
    ) -> List[Clause]:
        clauses = self.clause_builder_cls().build(blocks)
        clauses = self.requirement_parser_cls().parse(clauses, blocks)
        if apply_relationships:
            clauses = self.relationship_parser_cls().parse(document, clauses, blocks)
        clauses = self.applicability_extractor_cls().parse(clauses)
        clauses = self.applicability_normalizer_cls(self.registry).parse(clauses)
        return self.constraint_extractor_cls().parse(clauses)

    @staticmethod
    def _merge_definition_containers(
        clauses: List[Clause], blocks: Sequence[StructuralBlock]
    ) -> List[Clause]:
        """Materialize source-backed definition parents without parsing requirements."""

        existing = {clause.clause_id for clause in clauses}
        containers = [
            block for block in blocks
            if block.block_type == "DEFINITION_SECTION"
            and block.parent_id is None
            and block.block_id not in existing
        ]
        if not containers:
            return clauses
        order = {
            block.block_id: block.source_order for block in blocks
            if block.block_type in {"CLAUSE", "DEFINITION_SECTION"}
            and block.parent_id is None
        }
        materialized = list(clauses)
        for block in containers:
            materialized.append(Clause(
                clause_id=block.block_id,
                title=block.title,
                clause_type=ClauseType.NORMATIVE,
                source=SourceReference(
                    page_start=block.page_start,
                    page_end=block.page_end,
                    raw_text=block.raw_text,
                ),
                relationship_to_parent=ParentRelationship(
                    type=RelationshipType.NONE,
                    parent_clause_id=None,
                    notes=(
                        "Structural definition container; no normative requirement "
                        "was inferred from ownership."
                    ),
                ),
            ))
        return sorted(materialized, key=lambda clause: (
            order.get(clause.clause_id, 10**9), clause.clause_id
        ))

    def _build_annexes(
        self,
        blocks: Sequence[StructuralBlock],
        document: StandardDocument,
        *,
        apply_relationships: bool,
    ) -> List[Annex]:
        annexes: List[Annex] = []
        annex_positions = [index for index, block in enumerate(blocks) if block.block_type == "ANNEX"]
        for position_index, start in enumerate(annex_positions):
            heading = blocks[start]
            stop = annex_positions[position_index + 1] if position_index + 1 < len(annex_positions) else len(blocks)
            members = [
                block for block in blocks[start:stop]
                if block.semantic_context == "ANNEX" or block is heading
            ]
            annex_clause_blocks = [
                block for block in members if block.block_type in {"CLAUSE", "SUBCLAUSE"}
            ]
            annex_clause_tree = self._build_enriched_clauses(
                document,
                annex_clause_blocks,
                apply_relationships=apply_relationships,
            ) if annex_clause_blocks else []
            annex_requirements = [
                requirement
                for clause in self._walk_clauses(annex_clause_tree)
                for requirement in clause.requirements
            ]
            raw_text = "\n".join(block.raw_text for block in members if block.raw_text).strip()
            status_text = f"{heading.title or ''}\n{heading.raw_text[:300]}"
            informative = bool(re.search(r"\binformative\b", status_text, re.IGNORECASE))
            normative = bool(re.search(r"\bnormative\b", status_text, re.IGNORECASE)) and not informative
            annexes.append(Annex(
                annex_id=heading.block_id,
                title=heading.title,
                normative=normative,
                source=SourceReference(
                    page_start=min((block.page_start for block in members), default=heading.page_start),
                    page_end=max((block.page_end for block in members), default=heading.page_end),
                    raw_text=raw_text or heading.raw_text,
                ),
                requirements=annex_requirements,
                clauses=annex_clause_tree,
                applicability=ApplicabilityRule(status=ApplicabilityStatus.ALWAYS),
            ))
        return annexes

    @staticmethod
    def _build_tables(blocks: Sequence[StructuralBlock]) -> List[StandardTable]:
        return [
            StandardTable(
                table_id=block.block_id,
                title=block.title,
                source=SourceReference(
                    page_start=block.page_start,
                    page_end=block.page_end,
                    raw_text=block.raw_text,
                ),
                raw_text=block.raw_text,
                structured_data=None,
            )
            for block in blocks
            if block.block_type == "TABLE"
        ]

    def to_dict(self, kb: KnowledgeBase) -> Dict[str, Any]:
        """Return the stable recursive representation of a KB."""

        if not isinstance(kb, KnowledgeBase):
            raise TypeError("kb must be a KnowledgeBase")
        return kb.to_dict()

    def to_json(self, kb: KnowledgeBase, indent: Optional[int] = 2) -> str:
        """Serialize a KB deterministically while preserving Unicode."""

        return json.dumps(
            self.to_dict(kb), ensure_ascii=False, indent=indent, sort_keys=False
        )

    def save_json(self, kb: KnowledgeBase, output_path: PathLike) -> Path:
        """Save deterministic JSON, creating only the requested parent directory."""

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(kb, indent=2) + "\n", encoding="utf-8")
        return path

    def generate_output_filename(self, kb: KnowledgeBase) -> str:
        """Generate a stable filename from standard identity and KB role."""

        if not isinstance(kb, KnowledgeBase):
            raise TypeError("kb must be a KnowledgeBase")
        identity = kb.document.standard_id or kb.document.standard_number
        if not identity:
            raise ValueError("Cannot generate a filename without a standard identity")
        stem = re.sub(r"[^A-Za-z0-9]+", "_", identity).strip("_")
        if kb.document.document_type is DocumentType.BASE:
            suffix = "base_kb"
        elif kb.document.document_type is DocumentType.PART_2:
            suffix = "delta_kb"
        else:
            raise ValueError("Output filename is supported only for BASE and PART_2 KBs")
        return f"{stem}_{suffix}.json"

    def get_summary(self, kb: KnowledgeBase) -> Dict[str, Any]:
        """Return recursive counts without changing the KB."""

        clauses = list(self._walk_clauses(kb.clauses))
        requirements = [item for clause in clauses for item in clause.requirements]
        requirements.extend(
            requirement for annex in kb.annexes for requirement in annex.requirements
        )
        constraints = [item for req in requirements for item in req.technical_constraints]
        applicability = Counter(req.applicability.status.value for req in requirements)
        relationships = Counter(clause.relationship_to_parent.type.value for clause in clauses)
        return {
            "top_level_clauses": len(kb.clauses),
            "clauses": len(clauses),
            "requirements": len(requirements),
            "technical_constraints": len(constraints),
            "applicability": dict(applicability),
            "relationships": dict(relationships),
            "annexes": len(kb.annexes),
            "tables": len(kb.tables),
            "definitions": len(kb.definitions),
            "references": len(kb.references),
        }

    def _validate_assembly(self, kb: KnowledgeBase) -> None:
        if not isinstance(kb.document, StandardDocument):
            raise ValueError("KnowledgeBase document metadata is required")
        if not kb.document.standard_number:
            raise ValueError("KnowledgeBase document standard_number is required")
        if kb.document.document_type not in {
            DocumentType.BASE, DocumentType.PART_2, DocumentType.OTHER
        }:
            raise ValueError("KnowledgeBase must be an identified normative standard")
        seen_clause_ids = set()
        seen_objects = set()
        for clause in self._walk_clauses(kb.clauses):
            if not clause.clause_id or clause.clause_id in seen_clause_ids:
                raise ValueError(f"Duplicate or empty clause ID: {clause.clause_id!r}")
            seen_clause_ids.add(clause.clause_id)
            if id(clause) in seen_objects:
                raise ValueError(f"Malformed cyclic/reused clause hierarchy: {clause.clause_id}")
            seen_objects.add(id(clause))
            requirement_ids = set()
            for requirement in clause.requirements:
                if not requirement.requirement_id:
                    raise ValueError(f"Empty requirement ID in clause {clause.clause_id}")
                if requirement.requirement_id in requirement_ids:
                    raise ValueError(
                        f"Duplicate requirement ID in clause {clause.clause_id}: "
                        f"{requirement.requirement_id}"
                    )
                requirement_ids.add(requirement.requirement_id)
                for constraint in requirement.technical_constraints:
                    if constraint.source_requirement_id != requirement.requirement_id:
                        raise ValueError(
                            f"Constraint {constraint.constraint_id} source requirement mismatch"
                        )
        for annex in kb.annexes:
            requirement_ids = set()
            for requirement in annex.requirements:
                if not requirement.requirement_id:
                    raise ValueError(f"Empty requirement ID in annex {annex.annex_id}")
                if requirement.requirement_id in requirement_ids:
                    raise ValueError(
                        f"Duplicate requirement ID in annex {annex.annex_id}: "
                        f"{requirement.requirement_id}"
                    )
                requirement_ids.add(requirement.requirement_id)
                for constraint in requirement.technical_constraints:
                    if constraint.source_requirement_id != requirement.requirement_id:
                        raise ValueError(
                            f"Constraint {constraint.constraint_id} source requirement mismatch"
                        )

    @classmethod
    def _walk_clauses(cls, clauses: Sequence[Clause], ancestors=None):
        ancestor_ids = set() if ancestors is None else set(ancestors)
        for clause in clauses:
            if id(clause) in ancestor_ids:
                raise ValueError(f"Malformed cyclic clause hierarchy: {clause.clause_id}")
            yield clause
            yield from cls._walk_clauses(clause.children, ancestor_ids | {id(clause)})

    @staticmethod
    def _require_pdf(pdf_path: PathLike) -> Path:
        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(f"IEC standard PDF not found: {path}")
        return path


__all__ = ["GenericIECKnowledgeBaseBuilder"]
