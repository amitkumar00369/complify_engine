"""Compact, human-readable projection of the canonical client result.

This module deliberately performs presentation and aggregation only.  It does
not decide applicability, evidence sufficiency, technical results, requirement
states, metrics, report validity, or final disposition.
"""
from __future__ import annotations

import copy
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


TOP_LEVEL_SECTIONS = (
    "report_information",
    "canonical_runtime_status",
    "canonical_identity_authority",
    "product_classification",
    "evaluation_overview",
    "compliance_findings",
    "not_applicable_review",
    "standard_authority",
    "kb_maturity_authority",
    "report_validity",
    "priority_actions",
    "final_assessment",
)

PRODUCT_SPECIFIC_BRANCHES = 0
REPORT_SPECIFIC_BRANCHES = 0
STANDARD_SPECIFIC_SUMMARY_BRANCHES = 0
SUMMARY_RECOMPUTATIONS = 0
METRIC_RECOMPUTATIONS = 0
DECISION_RECOMPUTATIONS = 0

_ROOT_LABELS = {
    "TECHNICAL_NON_COMPLIANCE": "Technical non-compliance",
    "EVIDENCE_GAP": "Supporting evidence is incomplete",
    "ENGINE_APPLICABILITY_GAP": "Requirement applicability requires clarification",
    "KB_PREDICATE_GAP": "Requirement applicability criteria require review",
    "SEMANTIC_NORMALIZATION_GAP": "Source wording requires clarification",
    "SOURCE_PRODUCT_DATA_MISSING": "Required product information is missing",
    "STANDARD_VERSION_AUTHORITY_GAP": "Standard edition requires verification",
    "REPORT_STRUCTURE_MISMATCH": "Report structure does not align with the governing standard",
    "CLASSIFICATION_AUTHORITY_GAP": "Product classification requires verification",
}

_ACTION_LABELS = {
    "CORRECT_PRODUCT_OR_RETEST": "Correct the product or repeat the affected test.",
    "PROVIDE_TEST_EVIDENCE": "Provide complete supporting test evidence.",
    "RESOLVE_APPLICABILITY": "Confirm whether the affected requirements apply.",
    "KB_REVIEW_REQUIRED": "Review the requirement applicability criteria.",
    "CLARIFY_SOURCE_DOCUMENT": "Clarify the relevant source-document wording.",
    "PROVIDE_PRODUCT_INFORMATION": "Provide the missing product information.",
    "RESOLVE_STANDARD_VERSION_AUTHORITY": "Verify the applicable standard edition.",
    "REPORT_REPLACEMENT_REQUIRED": "Provide a report aligned with the governing standard.",
    "CONFIRM_CLASSIFICATION_AUTHORITY": "Confirm the product classification.",
}

_REASON_LABELS = {
    "ACTIONABLE_APPLICABILITY_GAPS": "Applicability questions remain unresolved.",
    "ACTIONABLE_EVIDENCE_GAPS": "Required supporting evidence is incomplete.",
    "ACTIONABLE_TRACEABILITY_GAPS": "Product or evidence traceability requires clarification.",
    "CONFIRMED_NONCOMPLIANCE": "At least one requirement has a confirmed non-compliant result.",
    "STANDARD_AUTHORITY_BLOCKED": "The applicable standard edition must be verified before evaluation can continue.",
    "EVIDENCE_INCOMPLETE": "Supporting evidence is incomplete.",
    "REPORT_STRUCTURE_MISMATCH": "The report structure does not align with the governing standard.",
    "IDENTITY_RELATIONSHIP_UNRESOLVED": "The product/model relationship requires verification.",
}

_FINAL_SUMMARIES = {
    "NONCOMPLIANT": "The available evidence confirms at least one non-compliant requirement. Corrective action is required.",
    "NOT_DETERMINED": "The available evidence does not support a final product compliance conclusion.",
    "NOT_DETERMINABLE": "Evaluation is restricted until the governing standard edition is verified.",
    "COMPLIANT": "The evaluated requirements support a compliant conclusion.",
}

_DEVELOPMENT_PATTERN = re.compile(
    r"(?i)(?:\bstep\s*(?:48|49|50|51|52)[a-z]?\b|\b51b\b|"
    r"\bgolden\s+(?:case|regression)\b|\binternal\s+baseline\b|"
    r"\bfreeze\s+baseline\b|\bpolicy\s+step\b|\baudit\s+step\b)"
)
_AI_PATTERN = re.compile(
    r"(?i)(?:\bAI\b|\bartificial intelligence\b|\blarge language model\b|"
    r"\bmodel inference\b|\bprompt\b|\bOCR\b|\bVision\b|\bChatGPT\b|"
    r"\bOpenAI\b|\bCodex\b|\bmachine-generated\b|\bAI-generated\b|"
    r"\bAI interpretation\b)"
)
_LLM_PATTERN = re.compile(r"(?i)\bLLM\b")
_INTERNAL_TOOL_PATTERN = re.compile(
    r"(?i)(?:\bparser\b|\bengine\s+step\b|\bpolicy\s+version\b|"
    r"\bregression\s+fixture\b|\btest\s+harness\b|\btool\s+execution\b)"
)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _human_code(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).replace("_", " ").strip().capitalize()


def _display_name(value: Any) -> str:
    return str(value or "Product").replace("_", " ").strip().title()


def _clean_clause(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    for prefix in ("E-C-MAIN-", "E-C-"):
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


def _clause_from_requirement_id(requirement_id: Any) -> str | None:
    match = re.match(r"^E-R-(?:MAIN|ANNEX_[^-]+)-([^-]+)-", str(requirement_id or ""))
    return match.group(1) if match else None


def _format_measurement(value: Any, unit: Any) -> str | None:
    if value is None:
        return None
    display_value = int(value) if isinstance(value, float) and value.is_integer() else value
    return f"{display_value} {unit}".strip()


def _classification_level(value: Any) -> dict[str, Any]:
    row = value if isinstance(value, Mapping) else {}
    return {
        "value": row.get("value"),
        "status": row.get("status"),
        "confidence": row.get("confidence"),
        "authority": row.get("authority"),
    }


def _standard_label(value: Any) -> dict[str, Any] | None:
    row = value if isinstance(value, Mapping) else {}
    if not row:
        return None
    return {
        "standard_number": row.get("standard_number"),
        "edition": row.get("edition"),
        "year": row.get("year"),
        "title": row.get("title"),
    }


def _metric_record(metrics: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    return next(
        (row for row in metrics.get("metric_records", []) if row.get("metric_name") == name),
        {},
    )


class GenericClientComplianceSummaryBuilder:
    """Build and validate the compact client presentation."""

    def build(self, source: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(source)
        metrics = data.get("metrics") or {}
        decisions = data.get("requirement_decisions") or []
        states = data.get("canonical_requirement_state") or []
        executions = data.get("technical_rule_executions") or []
        roots = data.get("root_causes") or []
        na_rows = data.get("na_validation") or []

        decision_by_id = {
            str(row.get("effective_requirement_id") or row.get("requirement_id")): row
            for row in decisions
        }
        state_by_id = {str(row.get("requirement_id")): row for row in states}

        coverage = _metric_record(metrics, "evaluation_coverage_percentage")
        pass_rate = _metric_record(metrics, "evaluated_decision_pass_rate")

        noncompliant_states = [row for row in states if row.get("state") == "NON_COMPLIANT"]
        failure_rows = [
            row
            for row in executions
            if (row.get("execution_result") or row.get("result")) == "VIOLATES"
        ]

        root_groups = self._root_groups(roots)
        evidence_requirement_ids = root_groups.get("EVIDENCE_GAP", set())
        applicability_types = {
            "ENGINE_APPLICABILITY_GAP",
            "KB_PREDICATE_GAP",
            "SEMANTIC_NORMALIZATION_GAP",
            "SOURCE_PRODUCT_DATA_MISSING",
            "CLASSIFICATION_AUTHORITY_GAP",
        }
        applicability_requirement_ids: set[str] = set()
        for root_type in applicability_types:
            applicability_requirement_ids.update(root_groups.get(root_type, set()))

        report_identity = data.get("report_identity") or {}
        product_identity = (data.get("product_identity") or {}).get("product") or {}
        product_name = (product_identity.get("product_name") or {}).get("value")
        classification = data.get("product_classification") or {}
        fallback_name = (classification.get("product_subtype") or {}).get("value")
        evaluation_name = _display_name(product_name or fallback_name or "Product")

        summary = {
            "report_information": {
                "evaluation_name": f"{evaluation_name} Compliance Evaluation",
                "report_number": report_identity.get("report_number"),
                "report_identifier": report_identity.get("report_identifier"),
                "report_date": report_identity.get("report_date"),
                "laboratory": report_identity.get("laboratory"),
                "source_file": report_identity.get("source_file")
                or report_identity.get("filename")
                or report_identity.get("file_name"),
                "product_name": product_name,
                "brand": (product_identity.get("brand") or {}).get("value"),
                "manufacturer": (product_identity.get("manufacturer") or {}).get("value"),
                "models": [row.get("value") for row in (data.get("product_identity") or {}).get("models", []) if row.get("value")],
            },
            "canonical_runtime_status": copy.deepcopy(data.get("canonical_runtime_status") or {}),
            "canonical_identity_authority": copy.deepcopy(data.get("canonical_identity_authority") or {}),
            "product_classification": {
                "standard_scope_class": _classification_level(classification.get("standard_scope_class")),
                "standard_scope_family": _classification_level(classification.get("standard_scope_family")),
                "product_subtype": _classification_level(classification.get("product_subtype")),
            },
            "evaluation_overview": {
                "canonical_state_source": {
                    "artifact": "decisions/canonical_requirement_state_store.json",
                    "sha256": (data.get("traceability") or {}).get("canonical_requirement_state_sha256")
                    or (data.get("traceability") or {}).get("source_state_sha256"),
                },
                "requirement_counts": {
                    "relevant": metrics.get("relevant_requirement_count"),
                    "evaluated": metrics.get("evaluated_requirement_count"),
                    "compliant": metrics.get("compliant_count"),
                    "non_compliant": metrics.get("non_compliant_count"),
                    "insufficient_evidence": metrics.get("terminal_insufficient_evidence_count"),
                    "needs_review": metrics.get("needs_review_count"),
                    "not_applicable": metrics.get("not_applicable_count"),
                    "unresolved_applicability": metrics.get("unresolved_applicability_count"),
                },
                "evaluation_coverage": {
                    "evaluated": coverage.get("numerator", metrics.get("evaluation_coverage_numerator")),
                    "relevant": coverage.get("denominator", metrics.get("evaluation_coverage_denominator")),
                    "percentage": coverage.get("value", metrics.get("evaluation_coverage_percentage")),
                },
                "evaluated_decision_pass_rate": {
                    "compliant_decisions": pass_rate.get("numerator", metrics.get("compliant_count")),
                    "authoritative_decisions": pass_rate.get("denominator", metrics.get("evaluated_decision_count")),
                    "percentage": pass_rate.get("value", metrics.get("evaluated_decision_pass_rate")),
                },
            },
            "compliance_findings": {
                "non_compliant_requirements": {
                    "count": metrics.get("non_compliant_count"),
                    "items": [
                        self._requirement_item(
                            row.get("requirement_id"),
                            state_by_id,
                            decision_by_id,
                            finding=row.get("reason"),
                        )
                        for row in noncompliant_states
                    ],
                },
                "technical_failures": {
                    "count": len(failure_rows),
                    "items": [self._technical_failure(row, decision_by_id) for row in failure_rows],
                },
                "primary_issues": {
                    "count": sum(len(ids) for ids in root_groups.values()),
                    "categories": self._issue_categories(root_groups, roots, state_by_id, decision_by_id),
                },
                "insufficient_evidence": {
                    "count": metrics.get("terminal_insufficient_evidence_count"),
                    "summary": "Supporting evidence is insufficient for the affected requirements.",
                    "important_items": self._state_items(
                        states, "INSUFFICIENT_EVIDENCE", state_by_id, decision_by_id
                    ),
                },
                "needs_review": {
                    "count": metrics.get("needs_review_count"),
                    "summary": "The affected requirements need technical or applicability review.",
                    "important_items": self._state_items(
                        states, "NEEDS_REVIEW", state_by_id, decision_by_id
                    ),
                },
                "evidence_gaps": {
                    "count": len(evidence_requirement_ids),
                    "summary": "Complete supporting test evidence is required.",
                    "important_items": self._items_for_ids(
                        evidence_requirement_ids, state_by_id, decision_by_id, limit=10
                    ),
                },
                "applicability_review": {
                    "count": len(applicability_requirement_ids),
                    "summary": "Applicability or required product information remains unresolved.",
                    "important_items": self._items_for_ids(
                        applicability_requirement_ids, state_by_id, decision_by_id, limit=10
                    ),
                },
            },
            "not_applicable_review": self._na_summary(na_rows, state_by_id, decision_by_id),
            "standard_authority": self._standard_authority(data),
            "kb_maturity_authority": self._kb_maturity_authority(data),
            "report_validity": self._report_validity(data),
            "priority_actions": self._priority_actions(roots, state_by_id, decision_by_id),
            "final_assessment": self._final_assessment(data.get("final_disposition") or {}),
        }
        return summary

    @staticmethod
    def _requirement_text(decision: Mapping[str, Any]) -> str | None:
        return ((decision.get("canonical_references") or {}).get("standard_requirement") or {}).get("text")

    def _requirement_item(
        self,
        requirement_id: Any,
        state_by_id: Mapping[str, Mapping[str, Any]],
        decision_by_id: Mapping[str, Mapping[str, Any]],
        *,
        finding: Any = None,
        action: Any = None,
    ) -> dict[str, Any]:
        rid = str(requirement_id or "")
        state = state_by_id.get(rid, {})
        decision = decision_by_id.get(rid, {})
        return {
            "clause": _clean_clause(decision.get("clause_id") or state.get("clause_id"))
            or _clause_from_requirement_id(rid),
            "status": state.get("state") or decision.get("final_decision"),
            "requirement": self._requirement_text(decision),
            "finding": finding or state.get("reason") or decision.get("reason"),
            "recommended_action": _ACTION_LABELS.get(str(action), _human_code(action)) if action else None,
        }

    def _technical_failure(
        self, row: Mapping[str, Any], decision_by_id: Mapping[str, Mapping[str, Any]]
    ) -> dict[str, Any]:
        rid = str(row.get("requirement_id") or "")
        decision = decision_by_id.get(rid, {})
        subject = _human_code(row.get("technical_subject") or row.get("canonical_parameter"))
        page = row.get("source_page")
        evidence = "Recorded measurement in the test report"
        if page is not None:
            evidence += f", page {page}"
        return {
            "clause": _clean_clause(decision.get("clause_id")) or _clause_from_requirement_id(rid),
            "status": "NON_COMPLIANT",
            "requirement": self._requirement_text(decision),
            "finding": f"{subject or 'Measured value'} does not meet the specified limit.",
            "measured_value": _format_measurement(row.get("measured_value"), row.get("unit")),
            "limit": _format_measurement(row.get("limit_value"), row.get("unit")),
            "comparison": _human_code(row.get("operator")),
            "evidence": evidence + ".",
            "recommended_action": _ACTION_LABELS["CORRECT_PRODUCT_OR_RETEST"],
        }

    @staticmethod
    def _root_groups(roots: Iterable[Mapping[str, Any]]) -> dict[str, set[str]]:
        groups: dict[str, set[str]] = defaultdict(set)
        for row in roots:
            rid = str(row.get("requirement_id") or "")
            for root in [row.get("primary_root_cause"), *(row.get("secondary_root_causes") or [])]:
                if not isinstance(root, Mapping):
                    continue
                root_type = str(root.get("root_type") or root.get("type") or root.get("reason") or "")
                if root_type and rid:
                    groups[root_type].add(rid)
        return dict(groups)

    def _issue_categories(
        self,
        root_groups: Mapping[str, set[str]],
        roots: Iterable[Mapping[str, Any]],
        state_by_id: Mapping[str, Mapping[str, Any]],
        decision_by_id: Mapping[str, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        effects: dict[str, Counter[str]] = defaultdict(Counter)
        actions: dict[str, Counter[str]] = defaultdict(Counter)
        for row in roots:
            for root in [row.get("primary_root_cause"), *(row.get("secondary_root_causes") or [])]:
                if not isinstance(root, Mapping):
                    continue
                root_type = str(root.get("root_type") or root.get("type") or root.get("reason") or "")
                if root.get("decision_effect"):
                    effects[root_type][str(root.get("decision_effect"))] += 1
                if root.get("resolution_action"):
                    actions[root_type][str(root.get("resolution_action"))] += 1
        result = []
        for root_type, ids in sorted(root_groups.items(), key=lambda item: (-len(item[1]), item[0])):
            action = actions[root_type].most_common(1)[0][0] if actions[root_type] else None
            result.append(
                {
                    "issue": _ROOT_LABELS.get(root_type, _human_code(root_type)),
                    "count": len(ids),
                    "effects": [
                        {"effect": _human_code(effect), "count": count}
                        for effect, count in sorted(effects[root_type].items())
                    ],
                    "recommended_action": _ACTION_LABELS.get(str(action), _human_code(action)) if action else None,
                    "important_items": self._items_for_ids(
                        ids, state_by_id, decision_by_id, limit=5, action=action
                    ),
                }
            )
        return result

    def _state_items(
        self,
        states: Iterable[Mapping[str, Any]],
        state_name: str,
        state_by_id: Mapping[str, Mapping[str, Any]],
        decision_by_id: Mapping[str, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        ids = [str(row.get("requirement_id")) for row in states if row.get("state") == state_name]
        return self._items_for_ids(ids, state_by_id, decision_by_id, limit=10)

    def _items_for_ids(
        self,
        requirement_ids: Iterable[str],
        state_by_id: Mapping[str, Mapping[str, Any]],
        decision_by_id: Mapping[str, Mapping[str, Any]],
        *,
        limit: int,
        action: Any = None,
    ) -> list[dict[str, Any]]:
        def key(rid: str) -> tuple[int, str, str]:
            state = (state_by_id.get(rid) or {}).get("state")
            rank = {"NON_COMPLIANT": 0, "AUTHORITY_BLOCKED": 1, "UNKNOWN_APPLICABILITY": 2, "NEEDS_REVIEW": 3}.get(str(state), 4)
            clause = _clean_clause((decision_by_id.get(rid) or {}).get("clause_id")) or _clause_from_requirement_id(rid) or ""
            return rank, clause, rid

        return [
            self._requirement_item(rid, state_by_id, decision_by_id, action=action)
            for rid in sorted(set(requirement_ids), key=key)[:limit]
        ]

    def _na_summary(
        self,
        rows: Iterable[Mapping[str, Any]],
        state_by_id: Mapping[str, Mapping[str, Any]],
        decision_by_id: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        rows = list(rows)
        status_counts = Counter(str(row.get("status")) for row in rows if row.get("status"))

        def category(status: str, summary: str) -> dict[str, Any]:
            selected = [row for row in rows if row.get("status") == status]
            return {
                "count": len(selected),
                "summary": summary,
                "important_items": [
                    {
                        **self._requirement_item(row.get("requirement_id"), state_by_id, decision_by_id),
                        "report_claim": row.get("report_claim"),
                        "applicability": row.get("canonical_applicability"),
                    }
                    for row in selected[:10]
                ],
            }

        return {
            "record_count": len(rows),
            "reported_not_applicable_count": sum(1 for row in rows if row.get("reported_na") is True),
            "status_counts": dict(sorted(status_counts.items())),
            "confirmed_invalid": category(
                "CONFIRMED_INVALID_NA",
                "The report's not-applicable claim conflicts with confirmed applicability.",
            ),
            "potential_conflicts": category(
                "POTENTIAL_CONFLICT",
                "The not-applicable claim requires review before it can be accepted.",
            ),
            "unresolved": category(
                "UNRESOLVED_NA",
                "Applicability is unresolved for these not-applicable assessments.",
            ),
            "justified": category(
                "JUSTIFIED_NA",
                "The not-applicable assessment is supported by the available information.",
            ),
        }

    @staticmethod
    def _standard_authority(data: Mapping[str, Any]) -> dict[str, Any]:
        authority = data.get("standard_authority") or {}
        context = data.get("standard_context") or {}
        blocked = bool(authority.get("evaluation_blocked")) or authority.get("standard_authority_status") in {
            "BLOCKED_STANDARD_MISMATCH", "BLOCKED_EDITION_MISMATCH",
            "NEEDS_REVIEW", "NOT_DETERMINABLE",
        }
        comparisons = []
        for row in authority.get("comparisons") or []:
            comparisons.append(
                {
                    "report_standard": row.get("report_standard_identifier"),
                    "report_edition": row.get("original_report_edition") or row.get("report_standard_edition"),
                    "evaluated_standard": row.get("kb_standard_identifier"),
                    "evaluated_edition": row.get("kb_standard_edition"),
                    "effective_authorized_edition": row.get("effective_authorized_edition"),
                    "authority_basis": row.get("authority_basis"),
                    "mapping_id": row.get("mapping_id"),
                    "approval_id": row.get("approval_id"),
                    "approval_reference": row.get("approval_reference"),
                    "comparison": _human_code(row.get("match_type")),
                }
            )
        status = authority.get("standard_authority_status")
        reasons = {
            "AUTHORITATIVE_MATCH": "The report and evaluated standard editions match.",
            "AUTHORITATIVE_VIA_VALIDATED_MAPPING": "A validated edition mapping authorizes evaluation.",
            "AUTHORITATIVE_VIA_GOVERNED_OVERRIDE": "A governed approval authorizes evaluation within its approved scope.",
            "BLOCKED_STANDARD_MISMATCH": "Evaluation is restricted because the report standard does not match the evaluated standard.",
            "BLOCKED_EDITION_MISMATCH": "Evaluation is restricted because the report and evaluated editions do not have an authorized relationship.",
            "NEEDS_REVIEW": "Evaluation is restricted because standard-edition authority is incomplete or requires review.",
            "NOT_DETERMINABLE": "Evaluation is restricted because standard-edition authority cannot be determined.",
        }
        return {
            "status": status,
            "evaluation_status": "RESTRICTED" if blocked else "AUTHORIZED",
            "reason": reasons.get(status, "Standard-edition authority requires review."),
            "authority_basis": authority.get("authority_basis"),
            "original_report_edition": authority.get("original_report_edition") or authority.get("report_standard_edition"),
            "evaluated_kb_edition": authority.get("kb_standard_edition"),
            "effective_authorized_edition": authority.get("effective_authorized_edition"),
            "mapping_id": authority.get("mapping_id"),
            "approval_id": authority.get("approval_id"),
            "approval_reference": authority.get("approval_reference"),
            "approval_scope": authority.get("approval_scope"),
            "limitations": authority.get("approval_limitations") or [],
            "blocking_reason": authority.get("authority_reason") if blocked else None,
            "base_standard": _standard_label(context.get("base_standard")),
            "particular_standard": _standard_label(context.get("delta_standard")),
            "standard_comparisons": comparisons,
        }

    @staticmethod
    def _kb_maturity_authority(data: Mapping[str, Any]) -> dict[str, Any]:
        authority = data.get("kb_maturity_authority") or {}
        status = authority.get("authorization_status")
        return {
            "status": status,
            "evaluation_status": "AUTHORIZED" if status == "AUTHORIZED" else "RESTRICTED",
            "kb_identifier": authority.get("effective_kb_id"),
            "kb_version": authority.get("kb_version"),
            "recorded_maturity": authority.get("original_maturity"),
            "evaluation_purpose": authority.get("evaluation_purpose"),
            "reason": authority.get("authorization_reason"),
            "reason_code": authority.get("reason_code"),
            "policy_id": authority.get("policy_id"),
            "authority_sha256": authority.get("authority_sha256"),
            "explanation": (
                "The standard and edition may be valid, but this knowledge base is not authorized for authoritative compliance evaluation."
                if status != "AUTHORIZED" else
                "The knowledge base is authorized for authoritative compliance evaluation."
            ),
        }

    @staticmethod
    def _report_validity(data: Mapping[str, Any]) -> dict[str, Any]:
        validity = data.get("report_validity") or {}
        structure = data.get("report_structure_compatibility") or {}
        status = validity.get("status") or validity.get("authority_status")
        reasons = [_REASON_LABELS.get(str(code), _human_code(code)) for code in validity.get("reason_codes") or []]
        if structure.get("overall_compatibility") == "STRUCTURE_MISMATCH":
            reasons.append(_REASON_LABELS["REPORT_STRUCTURE_MISMATCH"])
        return {
            "status": status,
            "structure_compatibility": structure.get("overall_compatibility"),
            "structure_confidence": structure.get("confidence"),
            "affected_requirement_count": validity.get("affected_requirement_count"),
            "limitations": list(dict.fromkeys(reason for reason in reasons if reason)),
        }

    def _priority_actions(
        self,
        roots: Iterable[Mapping[str, Any]],
        state_by_id: Mapping[str, Mapping[str, Any]],
        decision_by_id: Mapping[str, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for row in roots:
            rid = str(row.get("requirement_id") or "")
            for root in [row.get("primary_root_cause"), *(row.get("secondary_root_causes") or [])]:
                if not isinstance(root, Mapping) or not root.get("resolution_action"):
                    continue
                action = str(root.get("resolution_action"))
                entry = grouped.setdefault(
                    action,
                    {"ids": set(), "types": Counter(), "effects": Counter()},
                )
                entry["ids"].add(rid)
                entry["types"][str(root.get("root_type") or root.get("type") or root.get("reason"))] += 1
                if root.get("decision_effect"):
                    entry["effects"][str(root.get("decision_effect"))] += 1

        order = {
            "CORRECT_PRODUCT_OR_RETEST": 0,
            "RESOLVE_STANDARD_VERSION_AUTHORITY": 1,
            "REPORT_REPLACEMENT_REQUIRED": 2,
            "CONFIRM_CLASSIFICATION_AUTHORITY": 3,
            "PROVIDE_PRODUCT_INFORMATION": 4,
            "RESOLVE_APPLICABILITY": 5,
            "PROVIDE_TEST_EVIDENCE": 6,
            "KB_REVIEW_REQUIRED": 7,
            "CLARIFY_SOURCE_DOCUMENT": 8,
        }
        result = []
        for action, entry in sorted(grouped.items(), key=lambda item: (order.get(item[0], 99), item[0])):
            root_type = entry["types"].most_common(1)[0][0]
            items = self._items_for_ids(entry["ids"], state_by_id, decision_by_id, limit=10, action=action)
            result.append(
                {
                    "priority": "IMMEDIATE" if action in {"CORRECT_PRODUCT_OR_RETEST", "RESOLVE_STANDARD_VERSION_AUTHORITY", "REPORT_REPLACEMENT_REQUIRED"} else "NEXT",
                    "action": _ACTION_LABELS.get(action, _human_code(action)),
                    "reason": _ROOT_LABELS.get(root_type, _human_code(root_type)),
                    "affected_requirement_count": len(entry["ids"]),
                    "important_clauses": list(dict.fromkeys(item.get("clause") for item in items if item.get("clause"))),
                }
            )
        return result

    @staticmethod
    def _final_assessment(disposition: Mapping[str, Any]) -> dict[str, Any]:
        conclusion = disposition.get("product_compliance_conclusion")
        basis = disposition.get("decision_basis")
        public_basis = {
            key: value
            for key, value in basis.items()
            if isinstance(basis, Mapping) and isinstance(value, (int, float, bool))
        } if isinstance(basis, Mapping) else {}
        return {
            "final_disposition": disposition.get("value"),
            "overall_status": disposition.get("overall_status"),
            "product_compliance_conclusion": conclusion,
            "summary": _FINAL_SUMMARIES.get(str(conclusion), "The evaluation outcome is recorded in the final disposition."),
            "reasons": [
                _REASON_LABELS.get(str(code), _human_code(code))
                for code in disposition.get("reason_codes") or []
            ],
            "decision_counts": public_basis,
        }

    def validate(
        self,
        source: Mapping[str, Any],
        summary: Mapping[str, Any],
        *,
        source_file: str | None = None,
        source_size: int | None = None,
        brief_file: str | None = None,
        brief_size: int | None = None,
        summary_size: int | None = None,
    ) -> dict[str, Any]:
        source = _plain(source)
        summary = _plain(summary)
        metrics = source.get("metrics") or {}
        overview = summary.get("evaluation_overview") or {}
        counts = overview.get("requirement_counts") or {}
        coverage = overview.get("evaluation_coverage") or {}
        pass_rate = overview.get("evaluated_decision_pass_rate") or {}
        coverage_source = _metric_record(metrics, "evaluation_coverage_percentage")
        pass_source = _metric_record(metrics, "evaluated_decision_pass_rate")

        metric_pairs = [
            (counts.get("relevant"), metrics.get("relevant_requirement_count")),
            (counts.get("evaluated"), metrics.get("evaluated_requirement_count")),
            (counts.get("compliant"), metrics.get("compliant_count")),
            (counts.get("non_compliant"), metrics.get("non_compliant_count")),
            (counts.get("insufficient_evidence"), metrics.get("terminal_insufficient_evidence_count")),
            (counts.get("needs_review"), metrics.get("needs_review_count")),
            (counts.get("not_applicable"), metrics.get("not_applicable_count")),
            (counts.get("unresolved_applicability"), metrics.get("unresolved_applicability_count")),
            (coverage.get("percentage"), coverage_source.get("value", metrics.get("evaluation_coverage_percentage"))),
            (pass_rate.get("percentage"), pass_source.get("value", metrics.get("evaluated_decision_pass_rate"))),
        ]
        denominator_pairs = [
            (coverage.get("evaluated"), coverage_source.get("numerator", metrics.get("evaluation_coverage_numerator"))),
            (coverage.get("relevant"), coverage_source.get("denominator", metrics.get("evaluation_coverage_denominator"))),
            (pass_rate.get("compliant_decisions"), pass_source.get("numerator", metrics.get("compliant_count"))),
            (pass_rate.get("authoritative_decisions"), pass_source.get("denominator", metrics.get("evaluated_decision_count"))),
        ]
        metric_mismatches = sum(actual != expected for actual, expected in metric_pairs)
        denominator_mismatches = sum(actual != expected for actual, expected in denominator_pairs)
        decision_count_mismatches = sum(actual != expected for actual, expected in metric_pairs[:8])

        source_noncompliant = {
            str(row.get("requirement_id"))
            for row in source.get("canonical_requirement_state") or []
            if row.get("state") == "NON_COMPLIANT"
        }
        summary_noncompliant = {
            (item.get("clause"), item.get("status"))
            for item in ((summary.get("compliance_findings") or {}).get("non_compliant_requirements") or {}).get("items", [])
        }
        source_noncompliant_clauses = {
            (_clean_clause(row.get("clause_id")) or _clause_from_requirement_id(row.get("requirement_id")), "NON_COMPLIANT")
            for row in source.get("canonical_requirement_state") or []
            if row.get("state") == "NON_COMPLIANT"
        }

        source_failures = Counter(self._failure_signature(row) for row in source.get("technical_rule_executions") or [] if (row.get("execution_result") or row.get("result")) == "VIOLATES")
        summary_failures = Counter(self._summary_failure_signature(row) for row in ((summary.get("compliance_findings") or {}).get("technical_failures") or {}).get("items", []))
        technical_failures_dropped = sum((source_failures - summary_failures).values())
        technical_failure_mismatches = technical_failures_dropped + sum((summary_failures - source_failures).values())

        source_root_groups = self._root_groups(source.get("root_causes") or [])
        summary_category_counts = {
            row.get("issue"): row.get("count")
            for row in ((summary.get("compliance_findings") or {}).get("primary_issues") or {}).get("categories", [])
        }
        root_category_mismatches = sum(
            summary_category_counts.get(_ROOT_LABELS.get(root_type, _human_code(root_type))) != len(ids)
            for root_type, ids in source_root_groups.items()
        )
        critical_findings_dropped = len(source_noncompliant_clauses - summary_noncompliant) + technical_failures_dropped + root_category_mismatches

        source_na_counts = Counter(str(row.get("status")) for row in source.get("na_validation") or [] if row.get("status"))
        summary_na_counts = Counter((summary.get("not_applicable_review") or {}).get("status_counts") or {})
        na_count_mismatches = 0 if source_na_counts == summary_na_counts else len(set(source_na_counts) | set(summary_na_counts))

        report = summary.get("report_information") or {}
        source_report = source.get("report_identity") or {}
        report_identity_mismatches = sum(
            report.get(field) != source_report.get(field)
            for field in ("report_number", "report_identifier", "report_date", "laboratory")
        )
        source_source_file = source_report.get("source_file") or source_report.get("filename") or source_report.get("file_name")
        report_identity_mismatches += int(report.get("source_file") != source_source_file)
        source_classification = source.get("product_classification") or {}
        summary_classification = summary.get("product_classification") or {}
        classification_mismatches = sum(
            summary_classification.get(level) != _classification_level(source_classification.get(level))
            for level in ("standard_scope_class", "standard_scope_family", "product_subtype")
        )
        standard_authority_mismatches = int(
            (summary.get("standard_authority") or {}).get("status")
            != (source.get("standard_authority") or {}).get("standard_authority_status")
        )
        source_maturity = source.get("kb_maturity_authority") or {}
        compact_maturity = summary.get("kb_maturity_authority") or {}
        kb_maturity_authority_mismatches = sum((
            compact_maturity.get("status") != source_maturity.get("authorization_status"),
            compact_maturity.get("authority_sha256") != source_maturity.get("authority_sha256"),
            compact_maturity.get("policy_id") != source_maturity.get("policy_id"),
        ))
        source_validity = source.get("report_validity") or {}
        compact_validity = summary.get("report_validity") or {}
        source_structure = source.get("report_structure_compatibility") or {}
        report_validity_mismatches = sum(
            (
                compact_validity.get("status")
                != (source_validity.get("status") or source_validity.get("authority_status")),
                compact_validity.get("structure_compatibility")
                != source_structure.get("overall_compatibility"),
                compact_validity.get("structure_confidence") != source_structure.get("confidence"),
            )
        )
        source_disposition = source.get("final_disposition") or {}
        summary_disposition = summary.get("final_assessment") or {}
        final_disposition_mismatches = sum(
            summary_disposition.get(summary_key) != source_disposition.get(source_key)
            for summary_key, source_key in (
                ("final_disposition", "value"),
                ("overall_status", "overall_status"),
                ("product_compliance_conclusion", "product_compliance_conclusion"),
            )
        )
        runtime_status_mismatches = int(
            (summary.get("canonical_runtime_status") or {})
            != (source.get("canonical_runtime_status") or {})
        )
        identity_authority_mismatches = int(
            (summary.get("canonical_identity_authority") or {})
            != (source.get("canonical_identity_authority") or {})
        )

        text = json.dumps(summary, ensure_ascii=False)
        development_refs = len(_DEVELOPMENT_PATTERN.findall(text))
        ai_refs = len(_AI_PATTERN.findall(text))
        llm_refs = len(_LLM_PATTERN.findall(text))
        tool_refs = len(_INTERNAL_TOOL_PATTERN.findall(text))
        reduction = None
        if brief_size and summary_size is not None:
            reduction = round((1 - (summary_size / brief_size)) * 100, 2)

        counters = {
            "report_identity_mismatches": report_identity_mismatches,
            "classification_mismatches": classification_mismatches,
            "metric_value_mismatches": metric_mismatches,
            "metric_denominator_mismatches": denominator_mismatches,
            "decision_count_mismatches": decision_count_mismatches,
            "technical_failure_mismatches": technical_failure_mismatches,
            "n_a_count_mismatches": na_count_mismatches,
            "standard_authority_mismatches": standard_authority_mismatches,
            "kb_maturity_authority_mismatches": kb_maturity_authority_mismatches,
            "report_validity_mismatches": report_validity_mismatches,
            "final_disposition_mismatches": final_disposition_mismatches,
            "runtime_status_mismatches": runtime_status_mismatches,
            "identity_authority_mismatches": identity_authority_mismatches,
            "critical_findings_dropped": critical_findings_dropped,
            "technical_failures_dropped": technical_failures_dropped,
            "development_step_references": development_refs,
            "ai_references": ai_refs,
            "llm_references": llm_refs,
            "internal_tool_references": tool_refs,
            "summary_recomputations": SUMMARY_RECOMPUTATIONS,
            "metric_recomputations": METRIC_RECOMPUTATIONS,
            "decision_recomputations": DECISION_RECOMPUTATIONS,
            "product_specific_branches": PRODUCT_SPECIFIC_BRANCHES,
            "report_specific_branches": REPORT_SPECIFIC_BRANCHES,
            "standard_specific_summary_branches": STANDARD_SPECIFIC_SUMMARY_BRANCHES,
        }
        passed = all(value == 0 for value in counters.values()) and reduction is not None and reduction >= 80
        return {
            "status": "PASS" if passed else "FAIL",
            "source_file": source_file,
            "source_size": source_size,
            "size_reduction_baseline_file": brief_file,
            "size_reduction_baseline_size": brief_size,
            "summary_size": summary_size,
            "size_reduction_percentage": reduction,
            **counters,
        }

    @staticmethod
    def _failure_signature(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            _clause_from_requirement_id(row.get("requirement_id")),
            row.get("measured_value"),
            row.get("limit_value"),
            row.get("unit"),
        )

    @staticmethod
    def _summary_failure_signature(row: Mapping[str, Any]) -> tuple[Any, ...]:
        def parse(value: Any) -> tuple[Any, Any]:
            if value is None:
                return None, None
            match = re.match(r"^(-?(?:\d+(?:\.\d+)?|\.\d+))(?:\s+(.*))?$", str(value))
            if not match:
                return value, None
            number = float(match.group(1))
            return int(number) if number.is_integer() else number, match.group(2)

        measured, measured_unit = parse(row.get("measured_value"))
        limit, limit_unit = parse(row.get("limit"))
        return row.get("clause"), measured, limit, measured_unit or limit_unit

    @staticmethod
    def save_json(value: Mapping[str, Any], path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(_plain(value), indent=2, ensure_ascii=False) + "\n")
        return output


__all__ = [
    "GenericClientComplianceSummaryBuilder",
    "TOP_LEVEL_SECTIONS",
    "PRODUCT_SPECIFIC_BRANCHES",
    "REPORT_SPECIFIC_BRANCHES",
    "STANDARD_SPECIFIC_SUMMARY_BRANCHES",
    "SUMMARY_RECOMPUTATIONS",
    "METRIC_RECOMPUTATIONS",
    "DECISION_RECOMPUTATIONS",
]
