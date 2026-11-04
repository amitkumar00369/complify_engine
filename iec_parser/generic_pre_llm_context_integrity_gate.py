"""Deterministic pre-LLM provenance and eligibility gate (Step 32-B.1)."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, Mapping

from .generic_pre_llm_integrity_models import ContextIntegrityEligibility, PreLLMIntegrityResult


class GenericPreLLMContextIntegrityGate:
    """Permit only complete, unambiguous, provenance-backed LLM candidates."""
    SCHEMA_VERSION = "1.0"

    def audit_run(self, run_directory: str | Path, output_path: str | Path | None = None):
        root = Path(run_directory)
        contexts = self._load(root / "llm/resolved_compliance_context.json")
        routes = self._load(root / "llm/llm_routing_result.json")
        evidence = self._load(root / "report/report_evidence.json")
        result = self.audit_bundle(contexts, routes, evidence)
        self.save_json(result, output_path or root / "llm/pre_llm_integrity_result.json")
        return result

    def audit_bundle(self, context_bundle: Any, routing_result: Any, report_evidence: Any):
        bundle, routing, source = map(self._plain, (context_bundle, routing_result, report_evidence))
        source_index = defaultdict(list)
        for record, path in self._records(source):
            if record.get("evidence_id") is not None: source_index[str(record["evidence_id"])].append((record, path))
        routes = {str(x.get("context_id")): x for x in routing.get("routes") or []}
        decisions = []
        for context in bundle.get("contexts") or []:
            cid = str(context.get("context_id") or ""); route = routes.get(cid, {})
            integrity = context.get("resolution_integrity") or {}; blockers = []; findings = []
            if route.get("route") != "LLM_CANDIDATE": blockers.append("ROUTE_NOT_LLM_CANDIDATE")
            if integrity.get("status") != "COMPLETE": blockers.append("CONTEXT_NOT_COMPLETE")
            if integrity.get("duplicate_ids"): blockers.append("UNRESOLVED_DUPLICATE_REFERENCE")
            if integrity.get("ambiguous_references"): blockers.append("UNRESOLVED_AMBIGUOUS_REFERENCE")
            if integrity.get("missing_references"): blockers.append("UNRESOLVED_MANDATORY_REFERENCE")
            if integrity.get("cross_scope_conflicts"): blockers.append("CROSS_SCOPE_INTEGRITY_CONFLICT")
            if route.get("source_gap_locked"): blockers.append("SOURCE_GAP_INTEGRITY_VIOLATION")
            for pos, item in enumerate(context.get("report_evidence") or []):
                eid = str(item.get("evidence_id") or ""); matches = source_index.get(eid, [])
                if not any(item == source_record for source_record, _ in matches):
                    findings.append({"classification": "DERIVED_ARTIFACT_CONTAMINATION", "field": f"report_evidence[{pos}]", "evidence_id": eid, "source_paths": [p for _, p in matches]})
            if findings: blockers.append("CONTAMINATION_DETECTED")
            decisions.append(ContextIntegrityEligibility(cid, str(context.get("final_issue_id") or ""), not blockers, sorted(set(blockers)), findings))
        counts = Counter(reason for x in decisions for reason in x.blocking_reason_codes)
        accounting = {"total_contexts": len(decisions), "eligible_for_step_32c": sum(x.eligible_for_step_32c for x in decisions),
            "blocked_total": sum(not x.eligible_for_step_32c for x in decisions), "blocked_by_integrity": sum(any(r in x.blocking_reason_codes for r in ("CONTEXT_NOT_COMPLETE", "UNRESOLVED_DUPLICATE_REFERENCE", "UNRESOLVED_AMBIGUOUS_REFERENCE", "UNRESOLVED_MANDATORY_REFERENCE", "CROSS_SCOPE_INTEGRITY_CONFLICT")) for x in decisions),
            "blocked_by_source_gap": counts["SOURCE_GAP_INTEGRITY_VIOLATION"], "blocked_by_contamination": counts["CONTAMINATION_DETECTED"], "by_blocking_reason": dict(sorted(counts.items()))}
        return PreLLMIntegrityResult(self.SCHEMA_VERSION, bundle.get("run_id"), accounting, decisions,
            {"report_evidence_records_checked": sum(len(x.get("report_evidence") or []) for x in bundle.get("contexts") or []), "allowed_source": "report/report_evidence.json", "status": "VALID" if not counts["CONTAMINATION_DETECTED"] else "INVALID"})

    @staticmethod
    def _records(value, path="$"):
        if isinstance(value, Mapping):
            yield dict(value), path
            for key, child in value.items(): yield from GenericPreLLMContextIntegrityGate._records(child, f"{path}.{key}")
        elif isinstance(value, list):
            for pos, child in enumerate(value): yield from GenericPreLLMContextIntegrityGate._records(child, f"{path}[{pos}]")

    @staticmethod
    def _load(path):
        try: return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc: raise ValueError(f"invalid required integrity artifact {path}: {exc}") from exc
    @classmethod
    def _plain(cls, value):
        if is_dataclass(value): return cls._plain(asdict(value))
        if isinstance(value, Mapping): return {str(k): cls._plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)): return [cls._plain(x) for x in value]
        return value.value if hasattr(value, "value") else value
    @classmethod
    def to_json(cls, value, indent=2): return json.dumps(cls._plain(value), ensure_ascii=False, sort_keys=True, indent=indent)
    @classmethod
    def save_json(cls, value, path):
        target=Path(path); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(cls.to_json(value)+"\n",encoding="utf-8"); return target


__all__ = ["GenericPreLLMContextIntegrityGate"]
