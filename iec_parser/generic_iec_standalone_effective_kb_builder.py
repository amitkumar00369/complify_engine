"""Standalone primary-standard projection into the common Effective-KB contract."""
from __future__ import annotations

import copy

from .generic_iec_effective_kb_builder import GenericIECEffectiveKnowledgeBaseBuilder
from .generic_iec_effective_kb_models import EffectiveBuildStatus, EffectiveKnowledgeBase
from .generic_iec_kb_models import KnowledgeBase


class GenericIECStandaloneEffectiveKnowledgeBaseBuilder(GenericIECEffectiveKnowledgeBaseBuilder):
    """Project validated Base content without creating companion semantics."""

    def build(self, base_kb: KnowledgeBase) -> EffectiveKnowledgeBase:
        report = self.validator.validate(base_kb)
        if report.errors:
            codes = ", ".join(sorted({item.code for item in report.errors}))
            raise ValueError(f"Base validation failed; standalone projection stopped: {codes}")
        base = copy.deepcopy(base_kb)
        identity = "EFFECTIVE-STANDALONE-" + self._token(
            base.document.standard_id or base.document.standard_number or "STANDARD"
        )
        effective = EffectiveKnowledgeBase(
            schema_version="1.0", effective_kb_id=identity,
            base_standard=copy.deepcopy(base.document), delta_standard=None,
            build_status=EffectiveBuildStatus.VALID,
            clauses=[self._project_base_clause(item, base.document) for item in base.clauses],
            annexes=[self._project_base_annex(item, base.document) for item in base.annexes],
            tables=copy.deepcopy(base.tables),
            definitions=[self._project_base_definition(item, base.document) for item in base.definitions],
            references=copy.deepcopy(base.references),
            maturity=copy.deepcopy(base.document.maturity),
        )
        self._assert_effective_integrity(effective)
        return effective


__all__ = ["GenericIECStandaloneEffectiveKnowledgeBaseBuilder"]
