"""Read-only tracing utilities for cross-family evaluation audits."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


class AuditClassification(str, Enum):
    """Permitted source-audit conclusions."""

    TRUE_POSITIVE = "TRUE_POSITIVE"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    FALSE_NEGATIVE = "FALSE_NEGATIVE"
    CORRECT_BUT_TOO_GENERIC = "CORRECT_BUT_TOO_GENERIC"
    UNRESOLVED_AUDIT = "UNRESOLVED_AUDIT"


@dataclass(frozen=True)
class EvaluationTrace:
    """Immutable snapshot of one identifier's path through the pipeline."""

    selectors: Dict[str, Optional[str]]
    standard_requirements: List[Dict[str, Any]] = field(default_factory=list)
    effective_requirements: List[Dict[str, Any]] = field(default_factory=list)
    report_evidence: List[Dict[str, Any]] = field(default_factory=list)
    applicability: List[Dict[str, Any]] = field(default_factory=list)
    evidence_matches: List[Dict[str, Any]] = field(default_factory=list)
    final_decisions: List[Dict[str, Any]] = field(default_factory=list)
    final_issues: List[Dict[str, Any]] = field(default_factory=list)
    source_references: List[Dict[str, Any]] = field(default_factory=list)


class GenericCrossFamilyEvaluationAudit:
    """Load run-local artifacts and trace identifiers without reevaluation."""

    PATHS = {
        "base": "standards/base_kb.json",
        "effective": "standards/effective_kb.json",
        "evidence": "report/report_evidence.json",
        "applicability": "report/applicability_result.json",
        "matches": "report/evidence_match_result.json",
        "decisions": "decisions/final_requirement_decision.json",
        "issues": "decisions/final_compliance_issues.json",
    }

    def __init__(self, run_directory: Any):
        self.run_directory = Path(run_directory).resolve()
        if not self.run_directory.is_dir():
            raise FileNotFoundError(self.run_directory)
        self.artifacts = {key: self._load(path) for key, path in self.PATHS.items()}

    def trace(
        self, *, clause_id=None, requirement_id=None,
        requirement_group_id=None, evidence_id=None, final_issue_id=None
    ) -> EvaluationTrace:
        selectors={"clause_id":self._s(clause_id),"requirement_id":self._s(requirement_id),"requirement_group_id":self._s(requirement_group_id),"evidence_id":self._s(evidence_id),"final_issue_id":self._s(final_issue_id)}
        base=self._requirements(self.artifacts["base"]);effective=self._requirements(self.artifacts["effective"])
        evidence=self._evidence(self.artifacts["evidence"]);apps=list(self.artifacts["applicability"].get("results",[]) or []);matches=list(self.artifacts["matches"].get("matches",[]) or []);decisions=list(self.artifacts["decisions"].get("results",[]) or []);issues=list(self.artifacts["issues"].get("issues",[]) or [])
        issues=[x for x in issues if self._matches(x,selectors)]
        inferred_requirements={str(v) for x in issues for v in x.get("requirement_ids",[]) or []}
        inferred_evidence={str(v) for x in issues for v in x.get("evidence_refs",[]) or []}
        if requirement_id:inferred_requirements.add(str(requirement_id))
        if evidence_id:inferred_evidence.add(str(evidence_id))
        predicate=lambda x:self._matches(x,selectors) or str(x.get("effective_requirement_id",x.get("requirement_id",""))) in inferred_requirements
        standard=[x for x in base if predicate(x)];eff=[x for x in effective if predicate(x)]
        apps=[x for x in apps if predicate(x)];matches=[x for x in matches if predicate(x)];decisions=[x for x in decisions if predicate(x)]
        for x in matches:
            inferred_evidence.update(str(v.get("evidence_id")) for v in x.get("evidence_refs",[]) or [] if v.get("evidence_id"))
        ev=[x for x in evidence if self._matches(x,selectors) or str(x.get("evidence_id")) in inferred_evidence]
        refs=[copy.deepcopy(v) for x in eff for key in ("base_sources","delta_sources") for v in x.get(key,[]) or []]
        return EvaluationTrace(selectors,standard,eff,ev,apps,matches,decisions,issues,refs)
    @staticmethod
    def classify(value: Any) -> AuditClassification:
        return AuditClassification(str(value.value if isinstance(value, Enum) else value))

    @staticmethod
    def first_incorrect_stage(stage_results: Mapping[str, bool]) -> Optional[str]:
        return next((name for name, correct in stage_results.items() if not correct), None)

    def artifact_hashes(self) -> Dict[str, str]:
        return {
            key: hashlib.sha256((self.run_directory / path).read_bytes()).hexdigest()
            for key, path in self.PATHS.items()
        }

    def _load(self, path):
        target = self.run_directory / path
        if not target.is_file():
            raise FileNotFoundError(target)
        return json.loads(target.read_text(encoding="utf-8"))
    @classmethod
    def _requirements(cls,artifact):
        out=[]
        def walk(items):
            for clause in items or []:
                cid=clause.get("clause_id",clause.get("annex_id"))
                for requirement in clause.get("requirements",[]) or []:out.append({"clause_id":cid,**copy.deepcopy(requirement)})
                walk(clause.get("children",[]))
        walk(artifact.get("clauses",[]));walk(artifact.get("annexes",[]));return out
    @classmethod
    def _evidence(cls,artifact):
        out=[]
        def walk(items):
            for clause in items or []:
                for item in clause.get("evidence_items",[]) or []:out.append({"owner_clause_id":clause.get("clause_id"),**copy.deepcopy(item)})
                walk(clause.get("children",[]))
        walk(artifact.get("clauses",[]));out.extend(copy.deepcopy(artifact.get("unmapped_sections",[]) or []));return out
    @staticmethod
    def _matches(value,selectors):
        pairs=(("clause_id",("clause_id","owner_clause_id")),("requirement_id",("requirement_id","effective_requirement_id")),("requirement_group_id",("requirement_group_id","group_id")),("evidence_id",("evidence_id",)),("final_issue_id",("issue_id",)))
        active=False
        for selector,fields in pairs:
            wanted=selectors.get(selector)
            if wanted is None:continue
            active=True
            if any(str(value.get(field,""))==wanted for field in fields):return True
            if selector=="requirement_id" and wanted in [str(x) for x in value.get("requirement_ids",[]) or []]:return True
            if selector=="evidence_id" and wanted in [str(x) for x in value.get("evidence_refs",[]) or []]:return True
        return not active
    @staticmethod
    def _s(value):return None if value is None else str(value)
    @staticmethod
    def to_dict(trace):return asdict(trace)
    @classmethod
    def to_json(cls,trace,indent=2):return json.dumps(cls.to_dict(trace),ensure_ascii=False,sort_keys=True,indent=indent)


__all__=["AuditClassification","EvaluationTrace","GenericCrossFamilyEvaluationAudit"]
