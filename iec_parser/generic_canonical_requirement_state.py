"""Canonical, versioned requirement-state store and deterministic integrity checks."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Mapping


class CanonicalRequirementState(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN_APPLICABILITY = "UNKNOWN_APPLICABILITY"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    AUTHORITY_BLOCKED = "AUTHORITY_BLOCKED"
    INACTIVE = "INACTIVE"


SCHEMA_VERSION = "CANONICAL_REQUIREMENT_STATE_STORE_V1"
STATE_POLICY_VERSION = "STEP48A_REQUIREMENT_STATE_V1"
PROJECTION_POLICY_VERSION = "STEP48A_REQUIREMENT_STATE_PROJECTION_V1"
AUTHORITY_BLOCKED_POLICY_VERSION = "STEP55B_AUTHORITY_BLOCKED_STATE_V1"


class GenericCanonicalRequirementStateStore:
    """Materialize, project and validate the authoritative final-decision state."""

    AUTHORITY = "FINAL_REQUIREMENT_DECISION_ENGINE"

    def build(
        self,
        final_decision: Any,
        effective_kb: Any,
        run_id: Any = None,
        standard_authority: Any = None,
        kb_maturity_authority: Any = None,
    ) -> Dict[str, Any]:
        final = self._plain(final_decision or {})
        kb = self._plain(effective_kb or {})
        authority = self._plain(standard_authority or {})
        maturity_authority = self._plain(kb_maturity_authority or {})
        effective = {rid: req for rid, req in self._requirements(kb)}
        records = []
        for item in final.get("results", []) or []:
            rid = str(item.get("effective_requirement_id") or "")
            req = effective.get(rid, {})
            state = str(item.get("final_decision") or "")
            population = state not in {"NOT_APPLICABLE", "INACTIVE"} and str(item.get("decision_effect") or req.get("decision_effect") or "") != "INFORMATIONAL"
            records.append({
                "requirement_id": rid,
                "requirement_version": str(req.get("version_id") or req.get("effective_version") or kb.get("effective_kb_id") or "CURRENT"),
                "clause_id": item.get("effective_clause_id") or item.get("clause_id") or req.get("clause_id"),
                "current": True,
                "state": state,
                "reason_code": item.get("reason_code"),
                "reason": item.get("reason"),
                "state_reason": item.get("reason") or item.get("reason_code"),
                "state_authority": self.AUTHORITY,
                "standard_authority_status": authority.get("standard_authority_status"),
                "standard_authority_reason": authority.get("authority_reason"),
                "kb_maturity_authorization_status": maturity_authority.get("authorization_status"),
                "kb_maturity_authorization_reason": maturity_authority.get("authorization_reason"),
                "run_id": run_id,
                "source_decision_ids": [item.get("decision_id")] if item.get("decision_id") else [],
                "evaluation_population_member": population,
                "effective_status": item.get("effective_status") or req.get("effective_status"),
                "decision_effect": item.get("decision_effect") or req.get("decision_effect"),
                "criticality": copy.deepcopy(item.get("criticality") or req.get("criticality")),
                "traceability": {
                    "effective_requirement_id": rid,
                    "final_decision_id": item.get("decision_id"),
                    "applicability_decision": item.get("applicability_decision"),
                    "supporting_evidence_ids": copy.deepcopy(item.get("supporting_evidence_ids") or []),
                    "supporting_measurement_ids": copy.deepcopy(item.get("supporting_measurement_ids") or []),
                    "standard_authority_reference": self._authority_reference(authority),
                    "kb_maturity_authority_reference": self._kb_authority_reference(maturity_authority),
                },
            })
        return self._store(records, kb, final.get("report_document_id"), run_id, authority, maturity_authority)

    def build_authority_blocked(
        self,
        effective_kb: Any,
        standard_authority: Any,
        run_id: Any,
        report_evidence: Any = None,
        kb_maturity_authority: Any = None,
    ) -> Dict[str, Any]:
        """Persist one blocked state for every active governed requirement.

        Standard authority is an evaluation boundary, not an applicability or
        report-N/A decision.  Report N/A evidence is retained as traceability
        only; it is deliberately not promoted into a canonical N/A lifecycle
        result while standard authority is blocked.
        """
        kb = self._plain(effective_kb or {})
        authority = self._plain(standard_authority or {})
        maturity_authority = self._plain(kb_maturity_authority or {})
        report = self._plain(report_evidence or {})
        report_na_by_clause = self._report_na_evidence_by_clause(report)
        status = authority.get("standard_authority_status")
        reason = authority.get("authority_reason") or status or "STANDARD_AUTHORITY_BLOCKED"
        authority_ref = self._authority_reference(authority)
        standard_blocked = status not in {
            "AUTHORITATIVE_MATCH", "AUTHORITATIVE_VIA_VALIDATED_MAPPING",
            "AUTHORITATIVE_VIA_GOVERNED_OVERRIDE",
        }
        block_code = "STANDARD_AUTHORITY_BLOCKED" if standard_blocked else "KB_MATURITY_BLOCKED"
        if not standard_blocked:
            reason = maturity_authority.get("authorization_reason") or maturity_authority.get("authorization_status") or "KB_MATURITY_BLOCKED"
        records = []
        for rid, req in self._requirements(kb):
            if str(req.get("effective_status") or "").upper() == "INACTIVE":
                continue
            clause_id = req.get("clause_id") or req.get("effective_clause_id")
            records.append({
                "requirement_id": rid,
                "requirement_version": str(req.get("version_id") or req.get("effective_version") or kb.get("effective_kb_id") or "CURRENT"),
                "clause_id": clause_id,
                "current": True,
                "state": CanonicalRequirementState.AUTHORITY_BLOCKED.value,
                "canonical_state": CanonicalRequirementState.AUTHORITY_BLOCKED.value,
                "reason_code": block_code,
                "reason": reason,
                "state_reason": reason,
                "state_authority": self.AUTHORITY,
                "standard_authority_status": status,
                "standard_authority_reason": authority.get("authority_reason"),
                "kb_maturity_authorization_status": maturity_authority.get("authorization_status"),
                "kb_maturity_authorization_reason": maturity_authority.get("authorization_reason"),
                "run_id": run_id,
                "source_decision_ids": [],
                "evaluation_population_member": False,
                "effective_status": req.get("effective_status"),
                "decision_effect": req.get("decision_effect"),
                "criticality": copy.deepcopy(req.get("criticality")),
                "requirement_identity": {
                    "requirement_id": rid,
                    "clause_id": clause_id,
                    "text": req.get("text") or req.get("requirement_text"),
                    "requirement_type": req.get("requirement_type"),
                    "effective_source": req.get("effective_source") or req.get("source_standard"),
                    "applicability_predicate": copy.deepcopy(req.get("applicability") or {}),
                },
                "traceability": {
                    "effective_requirement_id": rid,
                    "final_decision_id": None,
                    "applicability_decision": None,
                    "supporting_evidence_ids": [],
                    "supporting_measurement_ids": [],
                    "report_na_evidence_ids": copy.deepcopy(report_na_by_clause.get(str(clause_id), [])),
                    "standard_authority_reference": copy.deepcopy(authority_ref),
                    "kb_maturity_authority_reference": self._kb_authority_reference(maturity_authority),
                    "source_requirement_population_ref": "standards/effective_kb.json",
                },
            })
        return self._store(records, kb, report.get("document_id") or report.get("report_number"), run_id, authority, maturity_authority)

    def _store(self, records, kb, report_document_id, run_id, authority, maturity_authority=None):
        records.sort(key=lambda x: (x["requirement_id"], x["requirement_version"]))
        counts = self.state_counts({"records": records})
        population_counts = self.state_counts({"records": records}, population_only=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "state_schema_version": SCHEMA_VERSION,
            "state_policy_version": STATE_POLICY_VERSION,
            "projection_policy_version": PROJECTION_POLICY_VERSION,
            "authority_blocked_policy_version": AUTHORITY_BLOCKED_POLICY_VERSION,
            "producer": "GenericCanonicalRequirementStateStore",
            "run_id": run_id,
            "effective_kb_id": kb.get("effective_kb_id"),
            "source_report_document_id": report_document_id,
            "state_authority": self.AUTHORITY,
            "allowed_states": [x.value for x in CanonicalRequirementState],
            "source_standard_authority_ref": self._authority_reference(authority),
            "source_kb_maturity_authority_ref": self._kb_authority_reference(maturity_authority or {}),
            "source_requirement_population_ref": "standards/effective_kb.json",
            "records": records,
            "summary": {"record_count": len(records), "state_counts": counts, "evaluation_population_count": sum(population_counts.values()), "evaluation_population_state_counts": population_counts},
        }
        digest = self.semantic_hash(payload)
        payload["store_sha256"] = digest
        payload["source_state_sha256"] = digest
        return payload

    def validate(self, store: Any, effective_kb: Any = None, requirement_summary: Any = None, step40: Any = None) -> Dict[str, Any]:
        data = self._plain(store or {})
        records = list(data.get("records", []) or [])
        diagnostics = []
        current = [x for x in records if x.get("current") is not False]
        ids = Counter(str(x.get("requirement_id") or "") for x in current)
        for rid, count in sorted(ids.items()):
            if count > 1:
                diagnostics.append(self._diagnostic("DUPLICATE_CURRENT_STATE", rid, count))
        if effective_kb is not None:
            requirements = list(self._requirements(self._plain(effective_kb)))
            blocked_store = any(x.get("state") == CanonicalRequirementState.AUTHORITY_BLOCKED.value for x in current)
            expected = {
                rid for rid, req in requirements
                if not blocked_store or str(req.get("effective_status") or "").upper() != "INACTIVE"
            }
            for rid in sorted(expected - set(ids)):
                diagnostics.append(self._diagnostic("MISSING_CURRENT_STATE", rid))
            for row in current:
                rid = str(row.get("requirement_id") or "")
                if rid in expected and not row.get("requirement_version"):
                    diagnostics.append(self._diagnostic("STALE_STATE_VERSION", rid))
        allowed = {x.value for x in CanonicalRequirementState}
        for row in current:
            if str(row.get("state")) not in allowed:
                diagnostics.append(self._diagnostic("INVALID_STATE", row.get("requirement_id"), row.get("state")))
        counts = self.state_counts(data)
        population = self.state_counts(data, population_only=True)
        declared = ((data.get("summary") or {}).get("state_counts") or {})
        if dict(declared) != counts:
            diagnostics.append(self._diagnostic("POPULATION_MISMATCH", None, {"declared": declared, "actual": counts}))
        if requirement_summary:
            reported = (self._plain(requirement_summary).get("canonical_state_counts") or {})
            if reported and dict(reported) != counts:
                diagnostics.append(self._diagnostic("SUMMARY_STATE_MISMATCH", None, {"reported": reported, "actual": counts}))
        if step40:
            metrics = self._plain(step40).get("metrics") or self._plain(step40)
            reported = ((metrics.get("compliance_score") or {}).get("reason_breakdown") or {})
            if reported and dict(reported) != population:
                diagnostics.append(self._diagnostic("STEP40_STATE_MISMATCH", None, {"reported": reported, "actual": population}))
        if data.get("projection_policy_version") != PROJECTION_POLICY_VERSION:
            diagnostics.append(self._diagnostic("UNKNOWN_STATE_PROJECTION", None, data.get("projection_policy_version")))
        declared_hash = data.get("store_sha256")
        if not declared_hash or declared_hash != data.get("source_state_sha256") or declared_hash != self.semantic_hash(data):
            diagnostics.append(self._diagnostic("INVALID_STATE_HASH", None, declared_hash))
        codes = Counter(x["code"] for x in diagnostics)
        return {"schema_version": "CANONICAL_REQUIREMENT_STATE_INTEGRITY_V1", "state_store_schema_version": data.get("schema_version"), "state_policy_version": data.get("state_policy_version"), "projection_policy_version": data.get("projection_policy_version"), "valid": not diagnostics, "diagnostic_count": len(diagnostics), "diagnostic_counts": dict(sorted(codes.items())), "diagnostics": diagnostics, "record_count": len(records), "state_counts": counts, "evaluation_population_state_counts": population}

    @staticmethod
    def state_counts(store: Mapping[str, Any], population_only: bool = False) -> Dict[str, int]:
        rows = [x for x in store.get("records", []) or [] if x.get("current") is not False and (not population_only or x.get("evaluation_population_member") is True)]
        counts = Counter(str(x.get("state")) for x in rows)
        return {state.value: counts[state.value] for state in CanonicalRequirementState if counts[state.value]}

    @classmethod
    def decision_view(cls, store: Any) -> Dict[str, Any]:
        data = cls._plain(store or {})
        return {"results": [{"effective_requirement_id": x.get("requirement_id"), "final_decision": x.get("state"), "reason_code": x.get("reason_code"), "reason": x.get("reason"), "decision_effect": x.get("decision_effect"), "criticality": x.get("criticality"), "decision_id": next(iter(x.get("source_decision_ids") or []), None)} for x in data.get("records", []) or [] if x.get("current") is not False]}

    @classmethod
    def blocked_disposition(cls, store: Any, standard_authority: Any, kb_maturity_authority: Any = None) -> Dict[str, Any]:
        state = cls._plain(store or {})
        authority = cls._plain(standard_authority or {})
        maturity = cls._plain(kb_maturity_authority or {})
        standard_blocked = authority.get("standard_authority_status") not in {
            "AUTHORITATIVE_MATCH", "AUTHORITATIVE_VIA_VALIDATED_MAPPING",
            "AUTHORITATIVE_VIA_GOVERNED_OVERRIDE",
        }
        reason_code = "STANDARD_AUTHORITY_BLOCKED" if standard_blocked else "KB_MATURITY_AUTHORIZATION_BLOCKED"
        disposition = "BLOCKED_STANDARD_AUTHORITY" if standard_blocked else "BLOCKED_KB_MATURITY_AUTHORITY"
        blocked = sum(
            row.get("state") == CanonicalRequirementState.AUTHORITY_BLOCKED.value
            for row in state.get("records", []) or []
        )
        return {
            "schema_version": "CANONICAL_BLOCKED_DISPOSITION_V1",
            "deterministic_disposition": disposition,
            "overall_status": "BLOCKED",
            "product_compliance_conclusion": "NOT_DETERMINABLE",
            "reason_codes": [reason_code],
            "decision_basis": {
                "authority_blocked_requirements": blocked,
                "canonical_state_sha256": state.get("store_sha256"),
                "standard_authority_status": authority.get("standard_authority_status"),
                "kb_maturity_authorization_status": maturity.get("authorization_status"),
                "kb_maturity_authority_sha256": maturity.get("authority_sha256"),
            },
            "source_state_sha256": state.get("store_sha256"),
            "standard_authority_reason": authority.get("authority_reason"),
            "kb_maturity_authorization_reason": maturity.get("authorization_reason"),
        }

    @classmethod
    def semantic_hash(cls, value: Any) -> str:
        unstable = {
            "store_sha256", "source_state_sha256", "run_id", "started_at",
            "completed_at", "timestamp", "generation_timestamp", "output_directory",
            "temp_path", "process_id", "pid",
        }
        def semantic(item):
            if isinstance(item, Mapping):
                return {
                    str(key): semantic(child)
                    for key, child in sorted(item.items(), key=lambda pair: str(pair[0]))
                    if str(key).lower() not in unstable and not str(key).lower().endswith("_timestamp")
                }
            if isinstance(item, (list, tuple)):
                return [semantic(child) for child in item]
            return cls._plain(item)
        source = json.dumps(semantic(cls._plain(value or {})), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    @staticmethod
    def _authority_reference(authority: Mapping[str, Any]) -> Dict[str, Any]:
        provenance = authority.get("authority_provenance") or {}
        return {
            "artifact_path": "standards/canonical_standard_authority.json",
            "authority_sha256": authority.get("authority_sha256"),
            "standard_authority_status": authority.get("standard_authority_status"),
            "standard_authority_reason": authority.get("authority_reason"),
            "report_standards": copy.deepcopy(authority.get("report_standards") or []),
            "kb_standards": copy.deepcopy(authority.get("kb_standards") or []),
            "comparisons": copy.deepcopy(authority.get("comparisons") or []),
            "mapping_id": authority.get("mapping_id"),
            "mapping_status": authority.get("mapping_status"),
            "edition_override_requested": provenance.get("edition_override_requested"),
            "edition_override_applied": provenance.get("edition_override_applied"),
        }

    @staticmethod
    def _kb_authority_reference(authority: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "artifact_path": "standards/canonical_kb_maturity_authority.json",
            "authority_sha256": authority.get("authority_sha256"),
            "effective_kb_id": authority.get("effective_kb_id"),
            "kb_version": authority.get("kb_version"),
            "original_maturity": authority.get("original_maturity"),
            "authorization_status": authority.get("authorization_status"),
            "policy_id": authority.get("policy_id"),
            "evaluation_purpose": authority.get("evaluation_purpose"),
            "authorization_reason": authority.get("authorization_reason"),
        }

    @classmethod
    def _report_na_evidence_by_clause(cls, report: Mapping[str, Any]) -> Dict[str, list]:
        result: Dict[str, set] = {}
        def walk(item):
            if isinstance(item, Mapping):
                verdict = str(item.get("reported_verdict") or item.get("raw_verdict_text") or "").strip().upper().replace(" ", "_")
                evidence_id = item.get("evidence_id")
                clause_id = item.get("clause_id") or item.get("subclause_id")
                if evidence_id and clause_id and verdict in {"NA", "N/A", "NOT_APPLICABLE"}:
                    result.setdefault(str(clause_id), set()).add(str(evidence_id))
                for child in item.values():
                    walk(child)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    walk(child)
        walk(report)
        return {key: sorted(values) for key, values in result.items()}

    @staticmethod
    def _diagnostic(code: str, requirement_id: Any, details: Any = None) -> Dict[str, Any]:
        return {"code": code, "requirement_id": requirement_id, "details": details}

    @classmethod
    def _requirements(cls, kb: Mapping[str, Any]):
        def walk(items):
            for clause in items or []:
                yield clause
                yield from walk(clause.get("children") or [])
        for clause in walk(kb.get("clauses") or []):
            for req in clause.get("requirements") or []:
                rid = str(req.get("effective_requirement_id") or req.get("requirement_id") or "")
                if rid:
                    yield rid, req
        for annex in kb.get("annexes") or []:
            for req in annex.get("requirements") or []:
                rid = str(req.get("effective_requirement_id") or req.get("requirement_id") or "")
                if rid:
                    yield rid, req
            for clause in walk(annex.get("clauses") or []):
                for req in clause.get("requirements") or []:
                    rid = str(req.get("effective_requirement_id") or req.get("requirement_id") or "")
                    if rid:
                        yield rid, req

    @classmethod
    def _plain(cls, value: Any):
        if isinstance(value, Enum):
            return value.value
        if is_dataclass(value):
            return cls._plain(asdict(value))
        if isinstance(value, Mapping):
            return {str(k): cls._plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._plain(v) for v in value]
        return copy.deepcopy(value)

    @classmethod
    def save_json(cls, value: Any, path: Any) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(cls._plain(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return target


__all__ = ["CanonicalRequirementState", "GenericCanonicalRequirementStateStore", "SCHEMA_VERSION", "STATE_POLICY_VERSION", "PROJECTION_POLICY_VERSION", "AUTHORITY_BLOCKED_POLICY_VERSION"]
