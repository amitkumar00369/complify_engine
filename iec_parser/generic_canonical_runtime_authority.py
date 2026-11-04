"""Canonical terminal runtime authority for compliance pipeline runs.

This authority describes lifecycle completion only.  It deliberately does not
derive or modify compliance, applicability, N/A, technical, metric, root, or
final-disposition semantics.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "CANONICAL_RUNTIME_STATUS_V1"
POLICY_VERSION = "STEP55F_TERMINAL_RUNTIME_AUTHORITY_V1"

TERMINAL_STATUSES = {
    "SUCCESS",
    "SUCCESS_WITH_REVIEW",
    "BLOCKED",
    "FAILED",
    "REVIEW_REQUIRED",
}
NON_TERMINAL_STATUSES = {
    "RUNNING",
    "PROCESSING",
    "PENDING",
    "STARTED",
    "IN_PROGRESS",
    "INITIALIZED",
}

OUTCOME_CLASSES = {
    "SUCCESS": "SUCCESSFULLY_EVALUATED",
    "SUCCESS_WITH_REVIEW": "SUCCESSFULLY_EVALUATED_WITH_REVIEW",
    "BLOCKED": "AUTHORITY_BLOCKED",
    "FAILED": "EXECUTION_FAILED",
    "REVIEW_REQUIRED": "TERMINAL_REVIEW_INDETERMINATE",
}


class GenericCanonicalRuntimeAuthority:
    """Build and validate one deterministic terminal lifecycle record."""

    def build(
        self,
        *,
        source_run_id: str,
        status: str,
        standard_authority: Mapping[str, Any] | None = None,
        kb_maturity_authority: Mapping[str, Any] | None = None,
        requirement_state: Mapping[str, Any] | None = None,
        roots: Mapping[str, Any] | None = None,
        metrics: Mapping[str, Any] | None = None,
        final_disposition: Mapping[str, Any] | None = None,
        blocking_gate: str | None = None,
        failed_stage: str | None = None,
        reason_code: str | None = None,
    ) -> dict[str, Any]:
        normalized_status = str(status or "").upper()
        if normalized_status not in TERMINAL_STATUSES:
            raise ValueError(f"Canonical runtime status must be terminal: {normalized_status or '<empty>'}")
        if normalized_status == "FAILED" and not failed_stage:
            raise ValueError("FAILED canonical runtime status requires failed_stage")
        if normalized_status != "FAILED" and failed_stage:
            raise ValueError("failed_stage is valid only for FAILED canonical runtime status")
        if normalized_status == "BLOCKED" and not blocking_gate:
            raise ValueError("BLOCKED canonical runtime status requires blocking_gate")

        standard = self._plain(standard_authority or {})
        maturity = self._plain(kb_maturity_authority or {})
        state = self._plain(requirement_state or {})
        root = self._plain(roots or {})
        metric = self._plain(metrics or {})
        disposition = self._plain(final_disposition or {})

        outcome_class = OUTCOME_CLASSES[normalized_status]
        if normalized_status == "BLOCKED" and blocking_gate not in {
            "STANDARD_AUTHORITY",
            "KB_MATURITY_AUTHORITY",
        }:
            outcome_class = "TERMINAL_REVIEW_INDETERMINATE"

        authority_references = {
            "standard_authority": {
                "artifact": "standards/canonical_standard_authority.json",
                "status": standard.get("standard_authority_status"),
                "sha256": standard.get("authority_sha256"),
            },
            "kb_maturity_authority": {
                "artifact": "standards/canonical_kb_maturity_authority.json",
                "status": maturity.get("authorization_status"),
                "sha256": maturity.get("authority_sha256"),
            },
            "canonical_requirement_state": {
                "artifact": "decisions/canonical_requirement_state_store.json",
                "sha256": state.get("store_sha256"),
            },
            "canonical_root_authority": {
                "artifact": "report/canonical_root_cause_authority.json",
                "sha256": root.get("artifact_sha256"),
            },
            "canonical_metrics_authority": {
                "artifact": "report/canonical_compliance_metrics.json",
                "sha256": metric.get("metrics_sha256"),
            },
            "final_disposition": {
                "artifact": "decisions/overall_report_status.json",
                "sha256": self._hash(disposition) if disposition else None,
                "value": disposition.get("deterministic_disposition"),
            },
        }
        record = {
            "schema_version": SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "authority": "CANONICAL_RUNTIME_STATUS",
            "status": normalized_status,
            "terminal": True,
            "outcome_class": outcome_class,
            "reason_code": reason_code or self._default_reason(normalized_status, blocking_gate),
            "blocking_gate": blocking_gate,
            "failed_stage": failed_stage,
            "source_run_id": str(source_run_id),
            "authority_references": authority_references,
        }
        record["runtime_state_sha256"] = self._hash(record)
        return record

    def validate(self, record: Mapping[str, Any]) -> dict[str, Any]:
        value = self._plain(record or {})
        diagnostics: list[dict[str, Any]] = []
        status = value.get("status")
        if status not in TERMINAL_STATUSES:
            diagnostics.append({"code": "NON_TERMINAL_OR_UNKNOWN_RUNTIME_STATUS", "status": status})
        if not value.get("terminal"):
            diagnostics.append({"code": "RUNTIME_STATUS_NOT_TERMINAL"})
        if status == "FAILED" and not value.get("failed_stage"):
            diagnostics.append({"code": "FAILED_WITHOUT_FAILED_STAGE"})
        if status != "FAILED" and value.get("failed_stage"):
            diagnostics.append({"code": "FAILED_STAGE_ON_NON_FAILURE"})
        if status == "BLOCKED" and not value.get("blocking_gate"):
            diagnostics.append({"code": "BLOCKED_WITHOUT_BLOCKING_GATE"})
        if status == "BLOCKED" and value.get("outcome_class") == "EXECUTION_FAILED":
            diagnostics.append({"code": "BLOCKED_RUNTIME_FALSE_FAILURE"})
        if status == "BLOCKED" and value.get("outcome_class") in {
            "SUCCESSFULLY_EVALUATED",
            "SUCCESSFULLY_EVALUATED_WITH_REVIEW",
        }:
            diagnostics.append({"code": "BLOCKED_RUNTIME_FALSE_SUCCESS"})
        expected_hash = self._hash({k: v for k, v in value.items() if k != "runtime_state_sha256"})
        if value.get("runtime_state_sha256") != expected_hash:
            diagnostics.append({"code": "INVALID_RUNTIME_STATE_HASH"})
        if value.get("schema_version") != SCHEMA_VERSION:
            diagnostics.append({"code": "INVALID_RUNTIME_SCHEMA_VERSION"})
        if value.get("policy_version") != POLICY_VERSION:
            diagnostics.append({"code": "INVALID_RUNTIME_POLICY_VERSION"})
        return {
            "schema_version": "CANONICAL_RUNTIME_STATUS_INTEGRITY_V1",
            "valid": not diagnostics,
            "diagnostic_count": len(diagnostics),
            "diagnostics": diagnostics,
            "runtime_state_sha256": value.get("runtime_state_sha256"),
        }

    @staticmethod
    def _default_reason(status: str, blocking_gate: str | None) -> str:
        if status == "BLOCKED":
            return f"{blocking_gate or 'RUNTIME'}_BLOCKED"
        return {
            "SUCCESS": "PIPELINE_COMPLETED",
            "SUCCESS_WITH_REVIEW": "PIPELINE_COMPLETED_WITH_REVIEW",
            "FAILED": "PIPELINE_EXECUTION_FAILED",
            "REVIEW_REQUIRED": "PIPELINE_TERMINATED_FOR_REVIEW",
        }[status]

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
    def _hash(cls, value: Any) -> str:
        payload = json.dumps(
            cls._plain(value), sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @classmethod
    def save_json(cls, value: Mapping[str, Any], path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(cls._plain(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return target


__all__ = [
    "GenericCanonicalRuntimeAuthority",
    "NON_TERMINAL_STATUSES",
    "OUTCOME_CLASSES",
    "POLICY_VERSION",
    "SCHEMA_VERSION",
    "TERMINAL_STATUSES",
]
