"""Canonical evidence sufficiency and identity-usability authority (Step 48-E)."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "CANONICAL_EVIDENCE_SUFFICIENCY_V1"
POLICY_VERSION = "STEP48E_EVIDENCE_SUFFICIENCY_POLICY_V1"
IDENTITY_POLICY_VERSION = "STEP48E_IDENTITY_USABILITY_POLICY_V1"
INTEGRITY_VERSION = "CANONICAL_EVIDENCE_SUFFICIENCY_INTEGRITY_V1"
PASS_AUTHORITY_POLICY_VERSION = "STEP50B_PASS_EVIDENCE_AUTHORITY_V1"
VALID_EVALUATION_BASES = {"DETERMINISTIC_RULE", "REPORTED_VERDICT", "INSPECTION", "DOCUMENT_REVIEW"}

PRODUCT_SPECIFIC_BRANCHES_ADDED = 0
MODEL_SPECIFIC_BRANCHES_ADDED = 0
REPORT_SPECIFIC_BRANCHES_ADDED = 0
STANDARD_SPECIFIC_BRANCHES_ADDED = 0
CLAUSE_SPECIFIC_BRANCHES_ADDED = 0
GOLDEN_SPECIFIC_BRANCHES_ADDED = 0

SUFFICIENCY_STATUSES = {"SUFFICIENT", "INSUFFICIENT", "NEEDS_REVIEW", "NOT_COMPARABLE"}
USABILITY_STATUSES = {"USABLE", "RESTRICTED", "NOT_USABLE", "NEEDS_REVIEW"}
INDEPENDENT_MATCH_TYPES = {
    "REQUIREMENT_ROW", "REQUIREMENT_SUBROW", "EXACT_SHARED_ROW_SEMANTIC",
    "EXACT_REQUIREMENT", "SEMANTIC_REQUIREMENT",
}
AMBIGUOUS_MATCH_TYPES = {"GROUP_VERDICT", "CLAUSE_PRESENCE_ONLY"}
TECHNICAL_COMPLETE = {"SATISFIES", "VIOLATES"}
TECHNICAL_REVIEW = {"NEEDS_REVIEW", "UNKNOWN", "INCOMPARABLE", "NO_MEASUREMENT"}


class GenericCanonicalEvidenceSufficiency:
    """Evaluate candidate evidence independently from compliance outcomes."""

    def build(self, canonical_applicability: Any, evidence_match: Any,
              identity_store: Any, identity_relationships: Any,
              structure_compatibility: Any, technical_constraints: Any = None,
              effective_kb: Any = None) -> dict[str, Any]:
        app = self._plain(canonical_applicability or {})
        matches = {str(self._get(x, "effective_requirement_id")): self._plain(x)
                   for x in self._get(evidence_match, "matches", []) or []}
        technical = self._technical_index(technical_constraints)
        requirements = self._requirement_index(effective_kb)
        identity = self._identity_usability(identity_store, identity_relationships)
        structure = self._structure_index(structure_compatibility)
        results = []
        for applicability in self._get(app, "results", []) or []:
            if self._enum(self._get(applicability, "status")) != "APPLICABLE":
                continue
            rid = str(self._get(applicability, "effective_requirement_id") or
                      self._get(applicability, "requirement_id") or "")
            results.append(self._evaluate(
                rid, self._plain(applicability), matches.get(rid, {}),
                identity, structure, technical.get(rid, []), requirements.get(rid, {})))
        suff = Counter(x["sufficiency"]["status"] for x in results)
        usable = Counter(x["identity_usability"]["status"] for x in results)
        artifact = {
            "schema_version": SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "identity_usability_policy_version": IDENTITY_POLICY_VERSION,
            "effective_kb_id": self._get(app, "effective_kb_id"),
            "profile_id": self._get(app, "profile_id"),
            "authoritative": True,
            "legacy_artifact_role": "CANDIDATE_INPUT_ONLY",
            "results": results,
            "summary": {
                "applicable_requirements": len(results),
                "evidence_matched": sum(bool(x["evidence_match"]["evidence_ids"]) for x in results),
                "sufficiency_counts": dict(sorted(suff.items())),
                "identity_usability_counts": dict(sorted(usable.items())),
            },
        }
        artifact["evidence_sufficiency_sha256"] = self._hash(artifact)
        return artifact

    def _evaluate(self, rid: str, applicability: dict[str, Any], match: dict[str, Any],
                  identity: dict[str, Any], structure: dict[str, Any],
                  technical: list[dict[str, Any]], requirement: dict[str, Any]) -> dict[str, Any]:
        refs = [self._plain(x) for x in self._get(match, "evidence_refs", []) or []]
        evidence_ids = sorted({str(self._get(x, "evidence_id")) for x in refs
                               if self._get(x, "evidence_id")})
        measurement_ids = sorted({str(mid) for x in refs
                                  for mid in self._get(x, "measurement_ids", []) or []})
        match_status = self._enum(self._get(match, "match_status")) or "NO_MATCH"
        match_type = self._enum(self._get(match, "match_type"))
        clause = str(self._get(applicability, "clause_id") or "")
        compatibility = structure.get(clause, structure.get("__overall__", "UNKNOWN"))
        semantic = self._semantic(match_status, match_type, refs)
        tstates = {self._enum(self._get(x, "decision")) for x in technical}
        tstates.discard(None)
        missing = []
        conflicts = []
        reasons = []

        if compatibility in {"STRUCTURE_MISMATCH", "NOT_COMPARABLE"}:
            status = "NOT_COMPARABLE"; reasons.append("STRUCTURE_MISMATCH_EVIDENCE_BLOCKED")
        elif semantic == "MISMATCH":
            status = "NOT_COMPARABLE"; reasons.append("SEMANTIC_SUBJECT_NOT_COMPARABLE")
        elif identity["status"] == "NOT_USABLE":
            status = "NOT_COMPARABLE"; reasons.append("IDENTITY_NOT_USABLE")
        elif identity["status"] in {"RESTRICTED", "NEEDS_REVIEW"} and evidence_ids:
            status = "NEEDS_REVIEW"; reasons.append("IDENTITY_USABILITY_RESTRICTED")
        elif not evidence_ids:
            status = "INSUFFICIENT"; missing.append("EVIDENCE"); reasons.append("NO_OWNED_EVIDENCE")
        elif match_type in AMBIGUOUS_MATCH_TYPES or match_status in {"MULTIPLE_CANDIDATES", "NEEDS_REVIEW"}:
            status = "NEEDS_REVIEW"; reasons.append("EVIDENCE_OWNERSHIP_AMBIGUOUS")
        elif tstates & TECHNICAL_REVIEW:
            status = "INSUFFICIENT" if "NO_MEASUREMENT" in tstates else "NEEDS_REVIEW"
            missing.extend(["REQUIRED_MEASUREMENT"] if "NO_MEASUREMENT" in tstates else [])
            reasons.append("TECHNICAL_EVIDENCE_INCOMPLETE" if status == "INSUFFICIENT" else "TECHNICAL_EVIDENCE_REQUIRES_REVIEW")
        elif tstates & TECHNICAL_COMPLETE:
            status = "SUFFICIENT"; reasons.append("COMPLETE_TECHNICAL_EVIDENCE")
        elif semantic == "ALIGNED" and match_type in INDEPENDENT_MATCH_TYPES and self._has_material_verdict(refs):
            status = "SUFFICIENT"; reasons.append("INDEPENDENT_DESCRIPTIVE_EVIDENCE")
        else:
            status = "INSUFFICIENT"; reasons.append("MATCH_WITHOUT_SUFFICIENCY_BASIS")
            if self._requires_parameter(requirement) and not measurement_ids:
                missing.append("REQUIRED_PARAMETER")
            if self._requires_condition(requirement) and not self._condition_present(refs):
                missing.append("REQUIRED_TEST_CONDITION")

        source_ids = sorted(set(evidence_ids + measurement_ids + identity["relationship_ids"]))
        evaluation_basis = None
        evaluation_authority = "NOT_ESTABLISHED"
        authority_reason = "EVIDENCE_SUFFICIENCY_NOT_ACCEPTED"
        technical_execution_ids = sorted({str(self._get(x, "technical_evaluation_id") or
                                              self._get(x, "evaluation_id") or
                                              self._get(x, "rule_id"))
                                          for x in technical
                                          if self._get(x, "technical_evaluation_id") or
                                             self._get(x, "evaluation_id") or self._get(x, "rule_id")})
        if status == "SUFFICIENT" and identity["status"] == "USABLE":
            if tstates & TECHNICAL_COMPLETE:
                evaluation_basis = "DETERMINISTIC_RULE"
                evaluation_authority = "AUTHORITATIVE"
                authority_reason = "EXECUTED_DETERMINISTIC_RULE_" + ("VIOLATES" if "VIOLATES" in tstates else "SATISFIES")
            elif self._has_material_verdict(refs):
                evaluation_basis = "REPORTED_VERDICT"
                evaluation_authority = "AUTHORITATIVE"
                authority_reason = "EXPLICIT_ATOMIC_REPORTED_VERDICT_ACCEPTED"
            else:
                authority_reason = "SUFFICIENT_EVIDENCE_WITHOUT_POSITIVE_EVALUATION_BASIS"
        return {
            "evaluation_id": "CANONICAL-EVIDENCE-" + self._hash(rid)[:20].upper(),
            "requirement_id": rid,
            "effective_requirement_id": rid,
            "applicability_status": "APPLICABLE",
            "evidence_match": {
                "match_status": match_status,
                "match_type": match_type,
                "match_score": self._get(match, "match_score"),
                "evidence_ids": evidence_ids,
                "measurement_ids": measurement_ids,
            },
            "identity_usability": copy.deepcopy(identity),
            "sufficiency": {
                "status": status,
                "reason_codes": reasons,
                "missing_elements": sorted(set(missing)),
                "conflicts": conflicts,
            },
            "semantic_alignment": semantic,
            "structure_compatibility": compatibility,
            "technical_evidence_states": sorted(tstates),
            "evaluation_basis": evaluation_basis,
            "evaluation_authority": evaluation_authority,
            "authority_reason": authority_reason,
            "supporting_evidence_ids": evidence_ids,
            "technical_execution_ids": technical_execution_ids,
            "pass_authority_policy_version": PASS_AUTHORITY_POLICY_VERSION,
            "source_trace": {"evidence_ids": evidence_ids,
                             "measurement_ids": measurement_ids,
                             "identity_relationship_ids": identity["relationship_ids"]},
            "dependency_ids": sorted(set([rid] + source_ids)),
            "policy_version": POLICY_VERSION,
        }

    def _identity_usability(self, store: Any, relationships: Any) -> dict[str, Any]:
        models = [self._plain(x) for x in self._get(store, "models", []) or []]
        declared = [x for x in models if self._enum(x.get("role")) == "DECLARED_MODEL"]
        tested = [x for x in models if self._enum(x.get("role")) == "TESTED_MODEL"]
        representative = [x for x in models if self._enum(x.get("role")) == "REPRESENTATIVE_MODEL"]
        rels = [self._plain(x) for x in self._get(relationships, "relationships", []) or []]
        states = {self._enum(x.get("relationship")) for x in rels}
        ids = sorted(str(x.get("relationship_id")) for x in rels if x.get("relationship_id"))
        if "CONFLICTING" in states:
            status, reason = "NEEDS_REVIEW", "IDENTITY_RELATIONSHIP_CONFLICTING"
        elif "MISMATCH" in states:
            status, reason = "NOT_USABLE", "DECLARED_TESTED_MODEL_MISMATCH"
        elif declared and tested and states and states <= {"UNKNOWN"}:
            status, reason = "RESTRICTED", "DECLARED_TESTED_RELATIONSHIP_UNKNOWN"
        elif states & {"MATCH", "REPRESENTATIVE_OF"}:
            status, reason = "USABLE", "AUTHORITATIVE_IDENTITY_RELATIONSHIP"
        elif states & {"RELATED", "VARIANT_OF", "FAMILY_MEMBER"}:
            # Transfer is qualified: it is not universally valid for every test.
            status, reason = "RESTRICTED", "QUALIFIED_FAMILY_OR_VARIANT_RELATIONSHIP"
        elif declared and tested and {str(x.get("value")) for x in declared} == {str(x.get("value")) for x in tested}:
            status, reason = "USABLE", "SAME_AUTHORITATIVE_MODEL"
        elif declared and not tested:
            status, reason = "USABLE", "DECLARED_MODEL_REPORT_SCOPE"
        elif tested and not declared:
            status, reason = "USABLE", "TESTED_MODEL_ONLY_REPORT_SCOPE"
        elif representative:
            status, reason = "NEEDS_REVIEW", "REPRESENTATIVE_RELATIONSHIP_MISSING"
        else:
            status, reason = "USABLE", "REPORT_LEVEL_IDENTITY_SCOPE"
        return {
            "status": status,
            "declared_identity_ids": sorted(x.get("identity_id") for x in declared if x.get("identity_id")),
            "tested_identity_ids": sorted(x.get("identity_id") for x in tested if x.get("identity_id")),
            "representative_identity_ids": sorted(x.get("identity_id") for x in representative if x.get("identity_id")),
            "relationship_ids": ids,
            "reason_code": reason,
            "policy_version": IDENTITY_POLICY_VERSION,
        }

    def validate(self, artifact: Any, final_decision: Any = None) -> dict[str, Any]:
        data = self._plain(artifact or {})
        final = {str(self._get(x, "effective_requirement_id")): self._enum(self._get(x, "final_decision"))
                 for x in self._get(final_decision, "results", []) or []}
        diagnostics = []
        for row in data.get("results", []):
            rid = str(row.get("requirement_id")); suff = row.get("sufficiency", {}).get("status")
            usable = row.get("identity_usability", {}).get("status"); match = row.get("evidence_match", {})
            reasons = set(row.get("sufficiency", {}).get("reason_codes", []))
            def add(code: str): diagnostics.append({"code": code, "requirement_id": rid})
            if suff not in SUFFICIENCY_STATUSES: add("INVALID_SUFFICIENCY_STATUS")
            if usable not in USABILITY_STATUSES: add("INVALID_IDENTITY_USABILITY_STATUS")
            if suff == "SUFFICIENT" and not reasons: add("MATCH_TREATED_AS_SUFFICIENT_WITHOUT_BASIS")
            if suff == "SUFFICIENT" and match.get("match_status") == "PARENT_CLAUSE" and not set(row.get("technical_evidence_states", [])) & TECHNICAL_COMPLETE: add("PARENT_MATCH_AUTO_PASS")
            if suff == "SUFFICIENT" and match.get("match_status") == "EXACT_SUBCLAUSE" and match.get("match_type") not in INDEPENDENT_MATCH_TYPES and not set(row.get("technical_evidence_states", [])) & TECHNICAL_COMPLETE: add("EXACT_MATCH_AUTO_PASS")
            if usable == "USABLE" and row.get("identity_usability", {}).get("reason_code") == "DECLARED_TESTED_RELATIONSHIP_UNKNOWN": add("IDENTITY_RELATIONSHIP_UNKNOWN_BUT_USABLE")
            if usable == "USABLE" and row.get("identity_usability", {}).get("reason_code") == "DECLARED_TESTED_MODEL_MISMATCH": add("IDENTITY_MISMATCH_BUT_USABLE")
            if suff == "SUFFICIENT" and row.get("structure_compatibility") in {"STRUCTURE_MISMATCH", "NOT_COMPARABLE"}: add("STRUCTURE_MISMATCH_EVIDENCE_USED")
            if suff == "SUFFICIENT" and row.get("semantic_alignment") == "MISMATCH": add("SEMANTIC_MISMATCH_EVIDENCE_USED")
            missing = set(row.get("sufficiency", {}).get("missing_elements", []))
            if suff == "SUFFICIENT" and "REQUIRED_PARAMETER" in missing: add("MISSING_REQUIRED_PARAMETER_MARKED_SUFFICIENT")
            if suff == "SUFFICIENT" and "REQUIRED_TEST_CONDITION" in missing: add("MISSING_REQUIRED_TEST_CONDITION_MARKED_SUFFICIENT")
            if final.get(rid) == "COMPLIANT" and suff == "NOT_COMPARABLE": add("NOT_COMPARABLE_MARKED_COMPLIANT")
            if final.get(rid) == "COMPLIANT" and suff == "INSUFFICIENT": add("INSUFFICIENT_MARKED_COMPLIANT")
            if final.get(rid) == "COMPLIANT" and row.get("evaluation_basis") not in VALID_EVALUATION_BASES: add("COMPLIANT_WITH_INVALID_EVALUATION_BASIS")
            if final.get(rid) == "COMPLIANT" and row.get("evaluation_authority") != "AUTHORITATIVE": add("COMPLIANT_WITHOUT_EVALUATION_AUTHORITY")
            if usable == "USABLE" and row.get("identity_usability", {}).get("reason_code", "").startswith("QUALIFIED_"): add("RESTRICTED_IDENTITY_MARKED_FULLY_USABLE")
            if row.get("evidence_match", {}).get("evidence_ids") and not row.get("source_trace", {}).get("evidence_ids"): add("EVIDENCE_SOURCE_TRACE_MISSING")
            if row.get("policy_version") != POLICY_VERSION: add("STALE_EVIDENCE_VERSION")
        counts = Counter(x["code"] for x in diagnostics)
        all_codes = ["MATCH_TREATED_AS_SUFFICIENT_WITHOUT_BASIS","PARENT_MATCH_AUTO_PASS","EXACT_MATCH_AUTO_PASS","IDENTITY_RELATIONSHIP_UNKNOWN_BUT_USABLE","IDENTITY_MISMATCH_BUT_USABLE","STRUCTURE_MISMATCH_EVIDENCE_USED","SEMANTIC_MISMATCH_EVIDENCE_USED","MISSING_REQUIRED_PARAMETER_MARKED_SUFFICIENT","MISSING_REQUIRED_TEST_CONDITION_MARKED_SUFFICIENT","NOT_COMPARABLE_MARKED_COMPLIANT","INSUFFICIENT_MARKED_COMPLIANT","COMPLIANT_WITH_INVALID_EVALUATION_BASIS","COMPLIANT_WITHOUT_EVALUATION_AUTHORITY","RESTRICTED_IDENTITY_MARKED_FULLY_USABLE","EVIDENCE_SOURCE_TRACE_MISSING","INVALID_SUFFICIENCY_STATUS","INVALID_IDENTITY_USABILITY_STATUS","LEGACY_EVIDENCE_OVERRIDE","STALE_EVIDENCE_VERSION"]
        return {"schema_version": INTEGRITY_VERSION, "policy_version": POLICY_VERSION,
                "valid": not diagnostics, "total_errors": len(diagnostics),
                "diagnostic_counts": {x: counts[x] for x in all_codes},
                "diagnostics": diagnostics}

    @classmethod
    def _technical_index(cls, value: Any) -> dict[str, list[dict[str, Any]]]:
        out = defaultdict(list)
        for x in cls._get(value, "results", []) or []:
            out[str(cls._get(x, "effective_requirement_id"))].append(cls._plain(x))
        for x in cls._get(value, "rule_results", []) or []:
            out[str(cls._get(x, "source_requirement_id"))].append(cls._plain(x))
        return out

    @classmethod
    def _requirement_index(cls, kb: Any) -> dict[str, dict[str, Any]]:
        out = {}
        def walk(items: Any) -> None:
            for clause in items or []:
                for req in cls._get(clause, "requirements", []) or []:
                    out[str(cls._get(req, "effective_requirement_id"))] = cls._plain(req)
                walk(cls._get(clause, "children", []) or [])
        walk(cls._get(kb, "clauses", []) or [])
        for annex in cls._get(kb, "annexes", []) or []:
            for req in cls._get(annex, "requirements", []) or []:
                out[str(cls._get(req, "effective_requirement_id"))] = cls._plain(req)
        return out

    @classmethod
    def _structure_index(cls, value: Any) -> dict[str, str]:
        overall = cls._enum(cls._get(value, "overall_compatibility")) or "UNKNOWN"
        out = {"__overall__": overall}
        for x in cls._get(value, "findings", []) or []:
            clause = cls._get(x, "standard_clause")
            if clause: out[str(clause)] = cls._enum(cls._get(x, "compatibility")) or overall
        return out

    @staticmethod
    def _semantic(match_status: str, match_type: str | None, refs: list[dict[str, Any]]) -> str:
        if match_status == "NO_MATCH": return "UNKNOWN"
        if match_type == "CLAUSE_PRESENCE_ONLY": return "MISMATCH"
        if match_type == "GROUP_VERDICT" or match_status in {"MULTIPLE_CANDIDATES", "NEEDS_REVIEW"}: return "AMBIGUOUS"
        if refs: return "ALIGNED"
        return "UNKNOWN"

    @staticmethod
    def _has_material_verdict(refs: list[dict[str, Any]]) -> bool:
        return any(str(x.get("reported_verdict") or "") in {"PASS", "FAIL"} for x in refs)

    @staticmethod
    def _requires_parameter(req: dict[str, Any]) -> bool:
        return bool(req.get("acceptance_criteria") or req.get("parameter") or req.get("parameters"))

    @staticmethod
    def _requires_condition(req: dict[str, Any]) -> bool:
        text = str(req.get("text") or req.get("requirement_text") or "").lower()
        return any(x in text for x in ("under the following conditions", "operated for", "test condition"))

    @staticmethod
    def _condition_present(refs: list[dict[str, Any]]) -> bool:
        return any(len(str(x.get("raw_text_excerpt") or "")) >= 20 for x in refs)

    @classmethod
    def _plain(cls, value: Any) -> Any:
        if is_dataclass(value): return cls._plain(asdict(value))
        if isinstance(value, Enum): return value.value
        if isinstance(value, Mapping): return {str(k): cls._plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)): return [cls._plain(x) for x in value]
        return value

    @staticmethod
    def _get(value: Any, name: str, default: Any = None) -> Any:
        return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default) if value is not None else default

    @staticmethod
    def _enum(value: Any) -> str | None:
        return None if value is None else str(value.value if isinstance(value, Enum) else value)

    @classmethod
    def _hash(cls, value: Any) -> str:
        raw = value if isinstance(value, str) else json.dumps(cls._plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def save_json(cls, value: Any, path: str | Path) -> Path:
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cls._plain(value), sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return p


__all__ = ["GenericCanonicalEvidenceSufficiency", "SCHEMA_VERSION", "POLICY_VERSION",
           "IDENTITY_POLICY_VERSION", "INTEGRITY_VERSION", "PASS_AUTHORITY_POLICY_VERSION",
           "VALID_EVALUATION_BASES"]
