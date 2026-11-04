"""Generic deterministic standard and edition authority (Step 49-B)."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "CANONICAL_STANDARD_AUTHORITY_V2"
POLICY_VERSION = "CANONICAL_STANDARD_EDITION_AUTHORITY_POLICY_V2"
EDITION_OVERRIDE_POLICY_VERSION = "GOVERNED_STANDARD_EDITION_OVERRIDE_POLICY_V1"
MAPPING_SCHEMA_VERSION = "VALIDATED_STANDARD_MAPPING_REGISTRY_V1"
MAPPING_POLICY_VERSION = "STEP49B_VALIDATED_STANDARD_MAPPING_POLICY_V1"
APPROVAL_SCHEMA_VERSION = "GOVERNED_STANDARD_EDITION_OVERRIDE_REGISTRY_V1"
APPROVAL_POLICY_VERSION = "GOVERNED_STANDARD_EDITION_OVERRIDE_POLICY_V1"
INTEGRITY_SCHEMA_VERSION = "CANONICAL_STANDARD_AUTHORITY_INTEGRITY_V1"

AUTHORITY_STATES = {
    "AUTHORITATIVE_MATCH",
    "AUTHORITATIVE_VIA_VALIDATED_MAPPING",
    "AUTHORITATIVE_VIA_GOVERNED_OVERRIDE",
    "BLOCKED_STANDARD_MISMATCH",
    "BLOCKED_EDITION_MISMATCH",
    "NEEDS_REVIEW",
    "NOT_DETERMINABLE",
}
BLOCKING_STATES = {"BLOCKED_STANDARD_MISMATCH", "BLOCKED_EDITION_MISMATCH", "NEEDS_REVIEW", "NOT_DETERMINABLE"}

PRODUCT_SPECIFIC_BRANCHES = 0
REPORT_SPECIFIC_BRANCHES = 0
STANDARD_SPECIFIC_ENGINE_BRANCHES = 0
CLAUSE_SPECIFIC_ENGINE_BRANCHES = 0
GOLDEN_EXPECTATION_BRANCHES = 0


class GenericCanonicalStandardAuthority:
    """Compare report-declared standards with the effective KB using data mappings only."""

    def __init__(self, mapping_registry: Any = None, approval_registry: Any = None):
        self.mapping_registry = self._registry(mapping_registry)
        self.approval_registry = self._approval_registry(approval_registry)

    def evaluate(
        self,
        effective_kb: Any,
        report_evidence: Any,
        *,
        ignore_editions: bool = False,
        standard_validation: Any = None,
    ) -> dict[str, Any]:
        kb = self._plain(effective_kb or {})
        report = self._plain(report_evidence or {})
        kb_standards = self._kb_standards(kb)
        report_standards = self._report_standards(report.get("standard_numbers") or [], kb_standards)
        comparisons = []
        validation = self._plain(standard_validation or {})
        validation_status = validation.get("status")

        if not kb_standards or not report_standards:
            status = "NOT_DETERMINABLE" if not kb_standards else "NEEDS_REVIEW"
            reason = "KB_STANDARD_IDENTITY_MISSING" if not kb_standards else "REPORT_STANDARD_IDENTITY_MISSING"
        else:
            for declared in report_standards:
                candidates = [x for x in kb_standards if x["normalized_identifier"] == declared["normalized_identifier"]]
                if not candidates:
                    comparisons.append(self._comparison(declared, None, "IDENTIFIER_MISMATCH", None, None))
                    continue
                target = candidates[0]
                if declared.get("ambiguous_editions"):
                    comparisons.append(self._comparison(
                        declared, target, "EDITION_NOT_DETERMINABLE", None, None,
                    ))
                    continue
                report_edition = declared.get("edition")
                kb_edition = target.get("edition")
                if report_edition is None or kb_edition is None:
                    comparisons.append(self._comparison(
                        declared, target, "EDITION_NOT_DETERMINABLE", None, None,
                    ))
                elif str(report_edition) == str(kb_edition):
                    comparisons.append(self._comparison(declared, target, "EXACT_IDENTIFIER_AND_EDITION", None, None))
                else:
                    mapping = self._find_mapping(declared, target)
                    approval = None if mapping else self._find_approval(declared, target, report)
                    mapping_partial = mapping and mapping.get("scope", {}).get("type") != "FULL_STANDARD"
                    approval_partial = approval and not self.approval_authorizes(approval, report_context=report)
                    match_type = (
                        "VALIDATED_PARTIAL_MAPPING" if mapping_partial else
                        "VALIDATED_MAPPING" if mapping else
                        "GOVERNED_PARTIAL_OVERRIDE" if approval_partial else
                        "GOVERNED_OVERRIDE" if approval else
                        "EDITION_MISMATCH"
                    )
                    comparisons.append(self._comparison(declared, target, match_type, mapping, approval))

            compared_identifiers = {
                item.get("normalized_identifier") for item in report_standards
            }
            for target in kb_standards:
                if target.get("normalized_identifier") not in compared_identifiers:
                    comparisons.append(self._comparison(None, target, "REPORT_DECLARATION_MISSING", None, None))

            types = {x["match_type"] for x in comparisons}
            if validation_status == "STANDARD_SET_INCOMPLETE":
                status, reason = "NOT_DETERMINABLE", "SUPPLIED_STANDARD_SET_INCOMPLETE"
            elif validation_status == "STANDARD_MISMATCH":
                status, reason = "BLOCKED_STANDARD_MISMATCH", "STANDARD_SET_VALIDATION_MISMATCH"
            elif "IDENTIFIER_MISMATCH" in types:
                status, reason = "BLOCKED_STANDARD_MISMATCH", "REPORT_STANDARD_NOT_IN_EFFECTIVE_KB"
            elif "EDITION_MISMATCH" in types:
                status, reason = "BLOCKED_EDITION_MISMATCH", "UNMAPPED_REPORT_KB_EDITION_MISMATCH"
            elif types & {"EDITION_NOT_DETERMINABLE", "REPORT_DECLARATION_MISSING", "VALIDATED_PARTIAL_MAPPING", "GOVERNED_PARTIAL_OVERRIDE"}:
                status, reason = "NEEDS_REVIEW", "STANDARD_AUTHORITY_DATA_INCOMPLETE_OR_AMBIGUOUS"
            elif "GOVERNED_OVERRIDE" in types:
                status, reason = "AUTHORITATIVE_VIA_GOVERNED_OVERRIDE", "ALL_UNMATCHED_EDITIONS_HAVE_GOVERNED_APPROVALS"
            elif "VALIDATED_MAPPING" in types:
                status, reason = "AUTHORITATIVE_VIA_VALIDATED_MAPPING", "ALL_EDITION_DIFFERENCES_HAVE_VALIDATED_MAPPINGS"
            else:
                status, reason = "AUTHORITATIVE_MATCH", "REPORT_AND_EFFECTIVE_KB_STANDARD_EDITIONS_MATCH"

        primary_report = report_standards[-1] if report_standards else {}
        primary_kb = next((x for x in reversed(kb_standards)
                           if x.get("normalized_identifier") == primary_report.get("normalized_identifier")),
                          kb_standards[-1] if kb_standards else {})
        mapping_rows = [x.get("mapping") for x in comparisons if x.get("mapping")]
        approval_rows = [x.get("approval") for x in comparisons if x.get("approval")]
        authority_basis = {
            "AUTHORITATIVE_MATCH": "EXACT_MATCH",
            "AUTHORITATIVE_VIA_VALIDATED_MAPPING": "VALIDATED_MAPPING",
            "AUTHORITATIVE_VIA_GOVERNED_OVERRIDE": "GOVERNED_OVERRIDE",
            "BLOCKED_STANDARD_MISMATCH": "BLOCKED_STANDARD_MISMATCH",
            "BLOCKED_EDITION_MISMATCH": "BLOCKED_EDITION_MISMATCH",
            "NEEDS_REVIEW": "NEEDS_REVIEW",
            "NOT_DETERMINABLE": "NOT_DETERMINABLE",
        }[status]
        result = {
            "schema_version": SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "mapping_registry_schema_version": self.mapping_registry.get("schema_version"),
            "mapping_registry_version": self.mapping_registry.get("registry_version"),
            "approval_registry_schema_version": self.approval_registry.get("schema_version"),
            "approval_registry_version": self.approval_registry.get("registry_version"),
            "standard_authority_status": status,
            "authoritative": status.startswith("AUTHORITATIVE"),
            "evaluation_blocked": status in BLOCKING_STATES,
            "report_standard_identifier": primary_report.get("identifier"),
            "report_standard_edition": primary_report.get("edition"),
            "kb_standard_identifier": primary_kb.get("identifier"),
            "kb_standard_edition": primary_kb.get("edition"),
            "normalized_standard_identifier": primary_report.get("normalized_identifier") or primary_kb.get("normalized_identifier"),
            "normalized_report_edition": primary_report.get("edition"),
            "normalized_kb_edition": primary_kb.get("edition"),
            "original_report_edition": primary_report.get("edition"),
            "effective_authorized_edition": primary_kb.get("edition") if status.startswith("AUTHORITATIVE") else None,
            "authority_basis": authority_basis,
            "match_type": self._overall_match_type(status),
            "mapping_id": mapping_rows[0].get("mapping_id") if len(mapping_rows) == 1 else None,
            "mapping_status": "VALIDATED" if mapping_rows else "NOT_APPLICABLE",
            "mapping_scope": mapping_rows[0].get("scope") if len(mapping_rows) == 1 else None,
            "approval_id": approval_rows[0].get("approval_id") if len(approval_rows) == 1 else None,
            "approval_reference": approval_rows[0].get("approval_reference") if len(approval_rows) == 1 else None,
            "approval_scope": approval_rows[0].get("scope") if len(approval_rows) == 1 else None,
            "approval_limitations": approval_rows[0].get("limitations") if len(approval_rows) == 1 else [],
            "authority_reason": reason,
            "authority_provenance": {
                "report_source": "report/report_evidence.json:standard_numbers",
                "kb_source": "standards/effective_kb.json:base_standard/delta_standard",
                "mapping_registry_source": self.mapping_registry.get("registry_id"),
                "mapping_ids": sorted(x.get("mapping_id") for x in mapping_rows if x.get("mapping_id")),
                "approval_registry_source": self.approval_registry.get("registry_id"),
                "approval_ids": sorted(x.get("approval_id") for x in approval_rows if x.get("approval_id")),
                "automatic_edition_equivalence_allowed": False,
                "edition_override_requested": bool(ignore_editions),
                "configuration_flag_authority_allowed": False,
                "edition_override_applied": status == "AUTHORITATIVE_VIA_GOVERNED_OVERRIDE",
                "edition_override_scope": approval_rows[0].get("scope") if len(approval_rows) == 1 else None,
                "edition_override_basis": "GOVERNED_APPROVAL" if approval_rows else None,
                "edition_override_policy_version": EDITION_OVERRIDE_POLICY_VERSION if approval_rows else None,
                "standard_validation_status": validation_status,
            },
            "report_standards": report_standards,
            "kb_standards": kb_standards,
            "comparisons": comparisons,
            "standard_edition_decisions": comparisons,
            "downstream_authority": {
                "applicability": "BLOCKED" if status in BLOCKING_STATES else "AUTHORITATIVE" if status.startswith("AUTHORITATIVE") else "LIMITED",
                "evidence": "PRESERVED_NOT_EVALUATED" if status in BLOCKING_STATES else "AUTHORITATIVE" if status.startswith("AUTHORITATIVE") else "LIMITED",
                "technical": "BLOCKED" if status in BLOCKING_STATES else "AUTHORITATIVE" if status.startswith("AUTHORITATIVE") else "LIMITED",
                "requirement_decisions": "NO_AUTHORITATIVE_CONCLUSION" if status in BLOCKING_STATES else "AUTHORITATIVE" if status.startswith("AUTHORITATIVE") else "LIMITED",
                "report_validity": "INVALID_STANDARD_AUTHORITY" if status in BLOCKING_STATES else "VALID_STANDARD_AUTHORITY" if status.startswith("AUTHORITATIVE") else "VALID_WITH_AUTHORITY_LIMITATION",
                "final_disposition": "BLOCKED_STANDARD_AUTHORITY" if status in BLOCKING_STATES else "CONTINUE",
            },
        }
        result["authority_sha256"] = self._hash(result)
        return result

    def validate(self, result: Any) -> dict[str, Any]:
        data = self._plain(result or {})
        diagnostics = []
        status = data.get("standard_authority_status")
        if status not in AUTHORITY_STATES:
            diagnostics.append({"code": "INVALID_STANDARD_AUTHORITY_STATUS"})
        if status == "AUTHORITATIVE_VIA_VALIDATED_MAPPING":
            mappings = [x.get("mapping") for x in data.get("comparisons", []) if x.get("mapping")]
            if not mappings or any(not self._valid_mapping(x) for x in mappings):
                diagnostics.append({"code": "UNVALIDATED_EDITION_EQUIVALENCE"})
        if status == "AUTHORITATIVE_VIA_GOVERNED_OVERRIDE":
            approvals = [x.get("approval") for x in data.get("comparisons", []) if x.get("approval")]
            if not approvals or any(not self._valid_approval(x) for x in approvals):
                diagnostics.append({"code": "INVALID_GOVERNED_OVERRIDE"})
        if status == "AUTHORITATIVE_MATCH" and any(x.get("match_type") != "EXACT_IDENTIFIER_AND_EDITION" for x in data.get("comparisons", [])):
            diagnostics.append({"code": "UNSAFE_AUTHORITATIVE_MATCH"})
        provenance = data.get("authority_provenance") or {}
        if (
            status == "AUTHORITATIVE_IDENTIFIER_MATCH_WITH_EDITION_OVERRIDE"
            or data.get("authority_basis") == "FLAG_ONLY_OVERRIDE"
            or provenance.get("configuration_flag_authority_allowed") is True
        ):
            diagnostics.append({"code": "FLAG_ONLY_AUTHORITY_OVERRIDE"})
        for comparison in data.get("comparisons", []):
            if comparison.get("match_type") == "EXACT_IDENTIFIER_AND_EDITION" and (
                comparison.get("report_standard_edition") is None
                or comparison.get("kb_standard_edition") is None
                or str(comparison.get("report_standard_edition")) != str(comparison.get("kb_standard_edition"))
            ):
                diagnostics.append({"code": "UNSAFE_AUTHORITATIVE_MATCH"})
        if status in BLOCKING_STATES and not data.get("evaluation_blocked"):
            diagnostics.append({"code": "AUTHORITY_PROPAGATION_ERROR"})
        if not data.get("authority_provenance"):
            diagnostics.append({"code": "AUTHORITY_PROVENANCE_MISSING"})
        counts = Counter(x["code"] for x in diagnostics)
        codes = ["INVALID_STANDARD_AUTHORITY_STATUS", "UNVALIDATED_EDITION_EQUIVALENCE",
                 "INVALID_GOVERNED_OVERRIDE", "UNSAFE_AUTHORITATIVE_MATCH",
                 "FLAG_ONLY_AUTHORITY_OVERRIDE", "AUTHORITY_PROPAGATION_ERROR",
                 "AUTHORITY_PROVENANCE_MISSING"]
        return {
            "schema_version": INTEGRITY_SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "valid": not diagnostics,
            "total_errors": len(diagnostics),
            "diagnostic_counts": {x: counts[x] for x in codes},
            "diagnostics": diagnostics,
        }

    def _find_mapping(self, source: Mapping[str, Any], target: Mapping[str, Any]):
        for mapping in self.mapping_registry.get("mappings", []):
            if not self._valid_mapping(mapping):
                continue
            if self._identifier(mapping.get("source_standard_identifier")) != source.get("normalized_identifier"):
                continue
            if self._identifier(mapping.get("target_standard_identifier")) != target.get("normalized_identifier"):
                continue
            if str(mapping.get("source_edition")) != str(source.get("edition")):
                continue
            if str(mapping.get("target_edition")) != str(target.get("edition")):
                continue
            if not (mapping.get("authority_basis") or mapping.get("validation_authority")) or not (mapping.get("source_reference") or mapping.get("validation_reference")):
                continue
            relationship=mapping.get("relationship");scope=mapping.get("scope")
            if relationship not in {"IDENTICAL","SUPERSEDES_WITHOUT_RELEVANT_CHANGE","CLAUSE_EQUIVALENT","REQUIREMENT_EQUIVALENT","PARTIAL_MAPPING"} or not isinstance(scope,Mapping) or scope.get("type") not in {"FULL_STANDARD","CLAUSES","REQUIREMENTS"}:continue
            if relationship=="PARTIAL_MAPPING" and scope.get("type")=="FULL_STANDARD":continue
            return self._plain(mapping)
        return None

    def _find_approval(self, source: Mapping[str, Any], target: Mapping[str, Any], report: Mapping[str, Any]):
        for approval in self.approval_registry.get("approvals", []):
            if not self._valid_approval(approval):
                continue
            if self._identifier(approval.get("report_standard_identifier")) != source.get("normalized_identifier"):
                continue
            if self._identifier(approval.get("kb_standard_identifier")) != target.get("normalized_identifier"):
                continue
            if str(approval.get("report_edition")) != str(source.get("edition")):
                continue
            if str(approval.get("kb_edition")) != str(target.get("edition")):
                continue
            return self._plain(approval)
        return None

    @classmethod
    def _valid_mapping(cls, mapping: Mapping[str, Any]) -> bool:
        validation_status = mapping.get("validation_status") or mapping.get("mapping_status")
        mapping_status = mapping.get("mapping_status")
        expected_hash = mapping.get("mapping_payload_sha256")
        relationship = mapping.get("relationship")
        scope = mapping.get("scope")
        return bool(
            validation_status == "VALIDATED"
            and mapping_status in {"ACTIVE", "VALID", "VALIDATED"}
            and mapping.get("mapping_id")
            and mapping.get("source_standard_identifier")
            and mapping.get("source_edition") is not None
            and mapping.get("target_standard_identifier")
            and mapping.get("target_edition") is not None
            and (mapping.get("authority_basis") or mapping.get("validation_authority"))
            and (mapping.get("source_reference") or mapping.get("validation_reference"))
            and relationship in {"IDENTICAL", "SUPERSEDES_WITHOUT_RELEVANT_CHANGE", "CLAUSE_EQUIVALENT", "REQUIREMENT_EQUIVALENT", "PARTIAL_MAPPING"}
            and isinstance(scope, Mapping)
            and scope.get("type") in {"FULL_STANDARD", "CLAUSES", "REQUIREMENTS"}
            and not (relationship == "PARTIAL_MAPPING" and scope.get("type") == "FULL_STANDARD")
            and expected_hash
            and expected_hash == cls.mapping_payload_hash(mapping)
        )

    @classmethod
    def _valid_approval(cls, approval: Mapping[str, Any]) -> bool:
        required = (
            "approval_id", "approval_status", "approver", "approval_reference",
            "approval_date", "report_standard_identifier", "report_edition",
            "kb_standard_identifier", "kb_edition", "mapping_type", "scope",
            "limitations", "assumptions", "justification", "effective_from",
            "source_document_reference", "created_by", "policy_version",
            "approval_payload_sha256",
        )
        return bool(
            all(key in approval and approval.get(key) is not None for key in required)
            and approval.get("approval_status") in {"ACTIVE", "APPROVED"}
            and isinstance(approval.get("scope"), Mapping)
            and approval.get("scope", {}).get("type") in {
                "FULL_STANDARD", "STANDARD_PAIR", "REPORT", "PRODUCT_FAMILY",
                "CLAUSES", "REQUIREMENTS", "PART", "AMENDMENT",
            }
            and approval.get("approval_payload_sha256") == cls.approval_payload_hash(approval)
        )

    @classmethod
    def mapping_payload_hash(cls, mapping: Mapping[str, Any]) -> str:
        payload = {str(k): cls._plain(v) for k, v in mapping.items()
                   if k not in {"mapping_payload_sha256", "mapping_sha256"}}
        return cls._hash(payload)

    @classmethod
    def approval_payload_hash(cls, approval: Mapping[str, Any]) -> str:
        payload = {str(k): cls._plain(v) for k, v in approval.items()
                   if k not in {"approval_payload_sha256", "created_at", "evaluated_at", "runtime_path", "temporary_directory", "process_id"}}
        return cls._hash(payload)

    @staticmethod
    def approval_authorizes(approval: Mapping[str, Any], *, requirement_id=None,
                            clause_id=None, report_context=None, product_family=None) -> bool:
        scope = (approval or {}).get("scope") or {}
        kind = scope.get("type")
        if kind in {"FULL_STANDARD", "STANDARD_PAIR"}:
            return True
        if kind == "REQUIREMENTS":
            return requirement_id is not None and str(requirement_id) in {str(x) for x in scope.get("requirement_ids", [])}
        if kind == "CLAUSES":
            return clause_id is not None and str(clause_id) in {str(x) for x in scope.get("clause_ids", [])}
        if kind == "REPORT":
            report = report_context or {}
            report_id = report.get("document_id") or report.get("report_number")
            allowed = scope.get("report_identifiers") or ([scope.get("report_identifier")] if scope.get("report_identifier") else [])
            return report_id is not None and str(report_id) in {str(x) for x in allowed}
        if kind == "PRODUCT_FAMILY":
            allowed = scope.get("product_families") or ([scope.get("product_family")] if scope.get("product_family") else [])
            return product_family is not None and str(product_family) in {str(x) for x in allowed}
        return False

    def _registry(self, value: Any) -> dict[str, Any]:
        if value is None:
            path = Path(__file__).with_name("validated_standard_mapping_registry.json")
            value = json.loads(path.read_text())
        elif isinstance(value, (str, Path)):
            value = json.loads(Path(value).read_text())
        data = self._plain(value)
        if data.get("schema_version") != MAPPING_SCHEMA_VERSION:
            raise ValueError("Unsupported validated standard mapping registry schema")
        return data

    def _approval_registry(self, value: Any) -> dict[str, Any]:
        if value is None:
            path = Path(__file__).with_name("governed_standard_edition_override_registry.json")
            value = json.loads(path.read_text())
        elif isinstance(value, (str, Path)):
            value = json.loads(Path(value).read_text())
        data = self._plain(value)
        if data.get("schema_version") != APPROVAL_SCHEMA_VERSION:
            raise ValueError("Unsupported governed standard-edition override registry schema")
        return data

    def _kb_standards(self, kb: Mapping[str, Any]):
        rows = []
        for role in ("base_standard", "delta_standard"):
            item = self._plain(kb.get(role) or {})
            identifier = item.get("standard_number") or item.get("standard_id")
            if not identifier:
                continue
            edition = item.get("year")
            identity=self._standard_identity(identifier)
            rows.append({"role": role.upper(), "identifier": identifier,
                         "normalized_identifier": self._identifier(identifier),
                         "edition": str(edition) if edition is not None else None,
                         "edition_label": item.get("edition"), "publication_year":str(edition) if edition is not None else None,"amendments":item.get("amendments") or [],"standard_id": item.get("standard_id"),**identity})
        return rows

    def _report_standards(self, refs: Sequence[Any], kb_standards: Sequence[Mapping[str, Any]] = ()):
        grouped = {}
        for raw in refs:
            text = str(raw).strip()
            normalized_text = re.sub(r"\s+", " ", text.upper().replace("_", " ")).strip()
            known = [x.get("normalized_identifier") for x in kb_standards
                     if x.get("normalized_identifier") and
                     re.search(r"(?<![A-Z0-9])" + re.escape(str(x["normalized_identifier"])) + r"(?!\d)", normalized_text)]
            identifier = max(known, key=len) if known else self._identifier(text)
            if not identifier:
                continue
            edition = self._edition(text)
            current = grouped.get(identifier)
            if current is None or (current.get("edition") is None and edition is not None):
                identity=self._standard_identity(text)
                grouped[identifier] = {"identifier": identifier,
                                       "normalized_identifier": identifier,
                                       "edition": edition,"publication_year":edition,"amendments":re.findall(r"(?:AMD|A)\s*\d+\s*:\s*(?:19|20)\d{2}",text.upper()),"raw_declarations": [text],**identity}
            else:
                current["raw_declarations"].append(text)
                if edition is not None and current.get("edition") not in {None, edition}:
                    current["ambiguous_editions"] = sorted({current["edition"], edition})
        identifiers = set(grouped)
        # A bare umbrella declaration is descriptive when a specific member of
        # the same family is also declared. It is not a missing KB document.
        retained = [x for x in sorted(identifiers)
                    if not any(other != x and other.startswith(x + "-") for other in identifiers)]
        return [grouped[x] for x in retained]

    @staticmethod
    def _comparison(report, kb, match_type, mapping, approval):
        report = report or {}
        kb = kb or {}
        basis = {
            "EXACT_IDENTIFIER_AND_EDITION": "EXACT_MATCH",
            "VALIDATED_MAPPING": "VALIDATED_MAPPING",
            "VALIDATED_PARTIAL_MAPPING": "VALIDATED_MAPPING_PARTIAL_SCOPE",
            "GOVERNED_OVERRIDE": "GOVERNED_OVERRIDE",
            "GOVERNED_PARTIAL_OVERRIDE": "GOVERNED_OVERRIDE_PARTIAL_SCOPE",
            "EDITION_MISMATCH": "BLOCKED_EDITION_MISMATCH",
            "IDENTIFIER_MISMATCH": "BLOCKED_STANDARD_MISMATCH",
            "EDITION_NOT_DETERMINABLE": "EDITION_UNKNOWN",
            "REPORT_DECLARATION_MISSING": "EDITION_UNKNOWN",
        }.get(match_type, "NEEDS_REVIEW")
        return {"standard_decision_id": "STANDARD-EDITION-" + GenericCanonicalStandardAuthority._hash({
                    "report": report.get("normalized_identifier"), "report_edition": report.get("edition"),
                    "kb": kb.get("normalized_identifier"), "kb_edition": kb.get("edition"),
                })[:20].upper(),
                "standard_id": kb.get("standard_id"),
                "report_standard_identifier": report.get("identifier"),
                "report_standard_edition": report.get("edition"),
                "kb_standard_identifier": kb.get("identifier"),
                "kb_standard_edition": kb.get("edition"),
                "normalized_standard_identifier": report.get("normalized_identifier") or kb.get("normalized_identifier"),
                "normalized_report_edition": report.get("edition"),
                "normalized_kb_edition": kb.get("edition"),
                "original_report_edition": report.get("edition"),
                "effective_authorized_edition": kb.get("edition") if match_type in {"EXACT_IDENTIFIER_AND_EDITION", "VALIDATED_MAPPING", "GOVERNED_OVERRIDE"} else None,
                "authority_status": basis,
                "authority_basis": basis,
                "match_type": match_type,
                "mapping_id": mapping.get("mapping_id") if mapping else None,
                "mapping_status": mapping.get("mapping_status") if mapping else "NOT_FOUND",
                "mapping": mapping,
                "approval_id": approval.get("approval_id") if approval else None,
                "approval_status": approval.get("approval_status") if approval else "NOT_FOUND",
                "approval_reference": approval.get("approval_reference") if approval else None,
                "approval": approval}

    @staticmethod
    def _overall_match_type(status):
        return {"AUTHORITATIVE_MATCH": "EXACT_IDENTIFIER_AND_EDITION",
                "AUTHORITATIVE_VIA_VALIDATED_MAPPING": "VALIDATED_MAPPING",
                "AUTHORITATIVE_VIA_GOVERNED_OVERRIDE": "GOVERNED_OVERRIDE",
                "BLOCKED_STANDARD_MISMATCH": "IDENTIFIER_MISMATCH",
                "BLOCKED_EDITION_MISMATCH": "EDITION_MISMATCH",
                "NEEDS_REVIEW": "INCOMPLETE_OR_AMBIGUOUS",
                "NOT_DETERMINABLE": "NOT_DETERMINABLE"}[status]

    @staticmethod
    def _identifier(value: Any):
        text = str(value or "").upper().replace("_", " ")
        match = re.search(r"\b([A-Z]{2,})\s*[- ]?\s*(\d{3,6}(?:-\d{1,4})*)\b", text)
        if not match:
            # Synthetic identifiers are supported by tests and non-IEC families.
            match = re.search(r"\b(\d{2,6}(?:-\d{1,4})*)\b", text)
            return match.group(1) if match else None
        prefix = re.sub(r"\s+", " ", match.group(1)).strip()
        return f"{prefix} {match.group(2)}"

    @classmethod
    def _display_identifier(cls, value: Any):
        return cls._identifier(value)

    @classmethod
    def _standard_identity(cls,value:Any):
        raw=str(value or "");normalized=cls._identifier(raw);organization=(normalized or "").split(" ",1)[0] if normalized and " " in normalized else None;number=(normalized or "").split(" ",1)[1] if normalized and " " in normalized else normalized;parts=(number or "").split("-")
        national=None
        prefix=re.match(r"\s*([A-Z]{2,}(?:\s+[A-Z]{2,})*)",raw.upper())
        if prefix and organization and prefix.group(1).split()[-1]!=organization:national=prefix.group(1)
        return {"organization":organization,"standard_number":number,"part_number":"-".join(parts[1:]) if len(parts)>1 else None,"national_adoption_prefix":national}

    @staticmethod
    def mapping_authorizes(mapping:Mapping[str,Any],requirement_id=None,clause_id=None):
        scope=(mapping or {}).get("scope") or {};kind=scope.get("type")
        if kind=="FULL_STANDARD":return True
        if kind=="REQUIREMENTS":return str(requirement_id) in {str(x) for x in scope.get("requirement_ids",[])}
        if kind=="CLAUSES":return str(clause_id) in {str(x) for x in scope.get("clause_ids",[])}
        return False

    @staticmethod
    def _edition(value: Any):
        text = str(value or "")
        years = re.findall(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", text)
        # The first year belongs to the standard declaration. Later years may
        # identify amendments/corrigenda and are not replacement editions.
        return years[0] if years else None

    @staticmethod
    def _plain(value: Any):
        if isinstance(value, Mapping):
            return {str(k): GenericCanonicalStandardAuthority._plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [GenericCanonicalStandardAuthority._plain(x) for x in value]
        if hasattr(value, "value"):
            return value.value
        if hasattr(value, "__dict__"):
            return GenericCanonicalStandardAuthority._plain(vars(value))
        return value

    @staticmethod
    def _hash(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

    @staticmethod
    def save_json(value: Any, path: Any):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        return target


__all__ = ["GenericCanonicalStandardAuthority", "SCHEMA_VERSION", "POLICY_VERSION",
           "EDITION_OVERRIDE_POLICY_VERSION", "MAPPING_SCHEMA_VERSION", "MAPPING_POLICY_VERSION",
           "APPROVAL_SCHEMA_VERSION", "APPROVAL_POLICY_VERSION",
           "AUTHORITY_STATES", "BLOCKING_STATES"]
