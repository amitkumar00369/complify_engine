"""Canonical purpose-scoped KB maturity authorization authority."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "CANONICAL_KB_MATURITY_AUTHORITY_V1"
POLICY_PATH = Path(__file__).with_name("kb_maturity_authorization_policy.json")
EVALUATION_PURPOSE = "AUTHORITATIVE_COMPLIANCE_EVALUATION"
AUTHORIZED_STANDARD_STATES = {
    "AUTHORITATIVE_MATCH",
    "AUTHORITATIVE_VIA_VALIDATED_MAPPING",
    "AUTHORITATIVE_VIA_GOVERNED_OVERRIDE",
}
BLOCKING_MATURITY_STATES = {"NOT_AUTHORIZED", "NEEDS_REVIEW", "NOT_DETERMINABLE"}


class GenericCanonicalKBMaturityAuthority:
    """Apply one persisted policy without inferring approval from a label."""

    def __init__(self, policy_path: Any = None):
        self.policy_path = Path(policy_path) if policy_path else POLICY_PATH

    def evaluate(
        self,
        effective_kb: Any,
        standard_authority: Any,
        *,
        purpose: str = EVALUATION_PURPOSE,
    ) -> dict[str, Any]:
        kb = self._plain(effective_kb or {})
        standard = self._plain(standard_authority or {})
        policy = json.loads(self.policy_path.read_text(encoding="utf-8"))
        purpose_policy = (policy.get("purposes") or {}).get(purpose)
        maturity = self._plain(kb.get("maturity") or {})
        original = maturity.get("state")
        standard_status = standard.get("standard_authority_status")

        missing_metadata: list[str] = []
        if standard_status not in AUTHORIZED_STANDARD_STATES:
            status = "NOT_DETERMINABLE"
            reason_code = "STANDARD_AUTHORITY_PRECEDENCE_BLOCK"
            reason = "KB maturity authorization was not evaluated because standard authority is not authoritative."
        elif not purpose_policy:
            status = "NOT_DETERMINABLE"
            reason_code = "EVALUATION_PURPOSE_NOT_GOVERNED"
            reason = "The requested evaluation purpose is not governed by the persisted maturity policy."
        elif not original:
            status = "NOT_DETERMINABLE"
            reason_code = "KB_MATURITY_MISSING"
            reason = "KB maturity is missing and cannot authorize compliance evaluation."
        elif original not in {"DRAFT", "REVIEWED", "PRODUCTION"}:
            status = "NOT_DETERMINABLE"
            reason_code = "KB_MATURITY_UNKNOWN"
            reason = "The recorded KB maturity is unknown to the authorization policy."
        elif original not in set(purpose_policy.get("authorized_maturity_states") or []):
            status = "NEEDS_REVIEW" if original == "REVIEWED" else "NOT_AUTHORIZED"
            reason_code = "KB_MATURITY_NOT_AUTHORIZED_FOR_PURPOSE"
            reason = f"KB maturity {original} is not authorized for {purpose}."
        else:
            for field in purpose_policy.get("required_metadata") or []:
                value = maturity.get(field)
                if value is None or value == "" or value == []:
                    missing_metadata.append(str(field))
            if missing_metadata:
                status = "NEEDS_REVIEW"
                reason_code = "KB_AUTHORIZATION_METADATA_INCOMPLETE"
                reason = "The KB maturity label is eligible, but required authorization metadata is incomplete."
            else:
                status = "AUTHORIZED"
                reason_code = "KB_AUTHORIZED_FOR_PURPOSE"
                reason = f"The persisted policy authorizes this KB for {purpose}."

        result = {
            "schema_version": SCHEMA_VERSION,
            "policy_id": policy.get("policy_id"),
            "policy_version": policy.get("policy_id"),
            "policy_schema_version": policy.get("schema_version"),
            "policy_artifact": "iec_parser/kb_maturity_authorization_policy.json",
            "evaluation_purpose": purpose,
            "effective_kb_id": kb.get("effective_kb_id"),
            "kb_version": maturity.get("version") or kb.get("version"),
            "kb_build_id": maturity.get("build_id"),
            "original_maturity": original,
            "maturity_metadata": maturity,
            "authorization_status": status,
            "authorized": status == "AUTHORIZED",
            "evaluation_blocked": status != "AUTHORIZED",
            "reason_code": reason_code,
            "authorization_reason": reason,
            "missing_authorization_metadata": missing_metadata,
            "standard_authority_status": standard_status,
            "standard_authority_sha256": standard.get("authority_sha256"),
            "authority_precedence": [
                "STANDARD_AUTHORITY",
                "KB_MATURITY_AUTHORITY",
                "APPLICABILITY_AND_REQUIREMENT_STATE",
                "TECHNICAL_EVALUATION",
                "COMPLIANCE_AGGREGATION",
            ],
            "source_artifacts": {
                "effective_kb": "standards/effective_kb.json",
                "standard_authority": "standards/canonical_standard_authority.json",
                "policy": "iec_parser/kb_maturity_authorization_policy.json",
            },
        }
        result["authority_sha256"] = self._hash(result)
        return result

    def validate(self, value: Any) -> dict[str, Any]:
        data = self._plain(value or {})
        diagnostics = []
        if data.get("authorization_status") not in {"AUTHORIZED", "NOT_AUTHORIZED", "NEEDS_REVIEW", "NOT_DETERMINABLE"}:
            diagnostics.append({"code": "INVALID_KB_MATURITY_AUTHORIZATION_STATUS"})
        if data.get("authorized") is not (data.get("authorization_status") == "AUTHORIZED"):
            diagnostics.append({"code": "AUTHORIZATION_BOOLEAN_MISMATCH"})
        if data.get("evaluation_blocked") is not (data.get("authorization_status") != "AUTHORIZED"):
            diagnostics.append({"code": "BLOCKING_BOOLEAN_MISMATCH"})
        if data.get("authority_sha256") != self._hash(data):
            diagnostics.append({"code": "INVALID_KB_MATURITY_AUTHORITY_HASH"})
        return {
            "schema_version": "CANONICAL_KB_MATURITY_AUTHORITY_INTEGRITY_V1",
            "valid": not diagnostics,
            "diagnostic_count": len(diagnostics),
            "diagnostics": diagnostics,
        }

    @classmethod
    def _hash(cls, value: Any) -> str:
        data = cls._plain(value or {})
        data.pop("authority_sha256", None)
        return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

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
    def save_json(cls, value: Any, path: Any) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(cls._plain(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return target


__all__ = [
    "GenericCanonicalKBMaturityAuthority",
    "SCHEMA_VERSION",
    "EVALUATION_PURPOSE",
    "BLOCKING_MATURITY_STATES",
]
