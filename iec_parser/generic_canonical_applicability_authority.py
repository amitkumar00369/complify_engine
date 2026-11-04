"""Step 48-D canonical deterministic applicability authority."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "CANONICAL_APPLICABILITY_RESULT_V3"
POLICY_VERSION = "STEP55C_CONDITIONAL_ATOMIC_APPLICABILITY_V1"
SCOPE_POLICY_VERSION = "STEP52_APPLICABILITY_TAXONOMY_V1"
INTEGRITY_VERSION = "CANONICAL_APPLICABILITY_INTEGRITY_V1"

PRODUCT_SPECIFIC_BRANCHES_ADDED = 0
MODEL_SPECIFIC_BRANCHES_ADDED = 0
REPORT_SPECIFIC_BRANCHES_ADDED = 0
STANDARD_SPECIFIC_BRANCHES_ADDED = 0
CLAUSE_SPECIFIC_BRANCHES_ADDED = 0
GOLDEN_SPECIFIC_BRANCHES_ADDED = 0


class ApplicabilityStatus(str, Enum):
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class AuthorityTier(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class RequirementScope(str, Enum):
    GENERAL_STANDARD_SCOPE = "GENERAL_STANDARD_SCOPE"
    DIRECT_PRODUCT = "DIRECT_PRODUCT"
    SUBTYPE_SPECIFIC = "SUBTYPE_SPECIFIC"
    FEATURE_SPECIFIC = "FEATURE_SPECIFIC"
    CONSTRUCTION_SPECIFIC = "CONSTRUCTION_SPECIFIC"
    COMPONENT_SPECIFIC = "COMPONENT_SPECIFIC"
    ANNEX_METHOD = "ANNEX_METHOD"
    SUPPORTING = "SUPPORTING"
    UNKNOWN_SCOPE = "UNKNOWN_SCOPE"


CANONICAL_SCOPE_TYPES = (
    "STANDARD_SCOPE", "PRODUCT_SUBTYPE", "FEATURE", "CONSTRUCTION",
    "INSTALLATION", "COMPONENT", "OPERATING_CONDITION", "EXCLUSION",
    "SPECIAL_CASE",
)
EVALUATION_STAGE_ORDER = (
    "STANDARD_AUTHORITY", "STANDARD_SCOPE", "PRODUCT_SUBTYPE",
    "CONSTRUCTION", "INSTALLATION", "COMPONENT", "FEATURE",
    "OPERATING_CONDITION", "SPECIAL_CASE", "EXCLUSION",
    "FINAL_APPLICABILITY",
)
BLOCKED_STANDARD_AUTHORITY = {"BLOCKED_STANDARD_MISMATCH", "BLOCKED_EDITION_MISMATCH"}


class GenericCanonicalApplicabilityAuthority:
    """Resolve active requirements from KB scope, classification and facts."""

    SUFFICIENT = {"HIGH", "MEDIUM"}
    TRUE_VALUES = {True, "TRUE", "YES", "Y", "PRESENT", "1"}
    FALSE_VALUES = {False, "FALSE", "NO", "N", "ABSENT", "0"}

    def build(self, effective_kb: Any, legacy_applicability: Any,
              classification: Any, fact_ledger: Any,
              standard_authority: Any = None) -> dict[str, Any]:
        kb = self._plain(effective_kb or {})
        legacy = self._plain(legacy_applicability or {})
        classes = self._class_index(classification)
        facts = self._fact_index(fact_ledger)
        standard_authority = self._plain(standard_authority or {})
        standard_authority_status = str(standard_authority.get("standard_authority_status") or "NOT_DETERMINABLE")
        old = {str(x.get("effective_requirement_id")): x
               for x in legacy.get("results", [])}
        results = []
        inactive = 0
        for requirement, effective_clause_id in self._requirements(kb):
            rid = str(requirement.get("effective_requirement_id") or "")
            if str(requirement.get("effective_status")) == "INACTIVE":
                inactive += 1
                continue
            prior = old.get(rid, {})
            results.append(self._resolve(requirement, effective_clause_id, prior,
                                         classes, facts, kb, standard_authority_status))
        summary = Counter(x["final_applicability"] for x in results)
        scopes = Counter(x["scope_type"] for x in results)
        transitions = Counter(
            f'{x["legacy_decision"]} -> {x["status"]}' for x in results
            if x.get("legacy_decision") and x["legacy_decision"] != x["status"])
        artifact = {
            "schema_version": SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "scope_policy_version": SCOPE_POLICY_VERSION,
            "effective_kb_id": kb.get("effective_kb_id"),
            "profile_id": legacy.get("profile_id"),
            "authoritative": standard_authority_status.startswith("AUTHORITATIVE"),
            "standard_authority_status": standard_authority_status,
            "evaluation_stage_order": list(EVALUATION_STAGE_ORDER),
            "canonical_scope_types": list(CANONICAL_SCOPE_TYPES),
            "legacy_artifact_role": "COMPATIBILITY_INPUT_ONLY",
            "results": results,
            "summary": {
                "active_requirements": len(results),
                "inactive_requirements_excluded": inactive,
                "status_counts": dict(sorted(summary.items())),
                "scope_counts": dict(sorted(scopes.items())),
                "transition_count": sum(transitions.values()),
                "transitions": dict(sorted(transitions.items())),
            },
        }
        artifact["applicability_sha256"] = self._hash(artifact)
        return artifact

    def _resolve(self, req: dict[str, Any], effective_clause_id: str | None,
                 prior: dict[str, Any], classes: dict[str, dict[str, Any]],
                 facts: dict[str, list[dict[str, Any]]], kb: dict[str, Any],
                 standard_authority_status: str) -> dict[str, Any]:
        rid = str(req.get("effective_requirement_id"))
        scope, required_class, required_features = self._scope(req, prior)
        standard = classes.get("STANDARD_SCOPE", {})
        subtype = classes.get("PRODUCT_SUBTYPE", {})
        app = req.get("applicability") or {}
        app_status = self._enum(app.get("status"))
        effect = self._enum(app.get("effect")) or "APPLIES"
        exclusion = effect == "DOES_NOT_APPLY"
        conditionality = self._conditionality(req, app)
        logic_state, atomic_predicates = self._evaluate_atomic_logic(
            app.get("logic"), facts, req
        )
        feature_evaluations = [self._feature(feature, facts) for feature in required_features]
        canonical_scope, legacy_mapping_reason = self._canonical_scope(req, prior, scope, required_class, required_features, exclusion)
        predicates = self._predicate_inputs(req, prior, required_class, required_features, exclusion)
        predicate_evaluations = self._evaluate_structured_predicates(canonical_scope, predicates, facts)
        if conditionality["is_conditional"]:
            if atomic_predicates:
                families = {x["predicate_family"] for x in atomic_predicates}
                canonical_scope = next(iter(families)) if len(families) == 1 else "SPECIAL_CASE"
                legacy_mapping_reason = "ATOMIC_PREDICATE_CONTRACT"
            elif canonical_scope in {"STANDARD_SCOPE", "PRODUCT_SUBTYPE"}:
                canonical_scope = self._conditional_family(req, app)
                legacy_mapping_reason = "BROAD_SCOPE_REQUIRES_ATOMIC_PREDICATE"
        if predicate_evaluations:
            atomic_predicates.extend(
                self._predicate_contract_from_evaluation(req, item)
                for item in predicate_evaluations
            )
            logic_state = self._combine_predicate_states(
                [logic_state] + [self._predicate_logic_state(x) for x in predicate_evaluations]
            )
        atomic_exclusion = exclusion or canonical_scope == "EXCLUSION"
        status, authority, reason = self._decision(
            scope, required_class, required_features, feature_evaluations,
            standard, subtype, app_status, exclusion, prior)
        atomic_applicability_authoritative = False
        unconditional_applicability_authoritative = False
        if conditionality["is_conditional"]:
            status, authority, reason, atomic_applicability_authoritative = self._conditional_decision(
                logic_state, atomic_predicates, standard, subtype,
                required_class, atomic_exclusion,
            )
        elif canonical_scope in {"CONSTRUCTION", "INSTALLATION", "COMPONENT", "OPERATING_CONDITION", "SPECIAL_CASE", "EXCLUSION"} and predicate_evaluations:
            status, authority, reason = self._predicate_decision(canonical_scope, predicate_evaluations, status, authority, reason)
        elif status == "APPLICABLE" and authority in self.SUFFICIENT:
            # Standard-scope authority can establish an unconditional
            # applicability decision, but it is not atomic predicate authority
            # and must never authorize CONFIRMED_INVALID_NA on that basis.
            unconditional_applicability_authoritative = True
        if legacy_mapping_reason == "AMBIGUOUS_LEGACY_SCOPE_REQUIRES_REVIEW":
            status, authority, reason = "NEEDS_REVIEW", "LOW", "AMBIGUOUS_LEGACY_SCOPE"
        blocked = standard_authority_status in BLOCKED_STANDARD_AUTHORITY
        final_applicability = "AUTHORITY_BLOCKED" if blocked else (
            "UNKNOWN_APPLICABILITY" if status == "UNKNOWN" else status)
        authority_status = "BLOCKED" if blocked else (
            "AUTHORITATIVE" if standard_authority_status.startswith("AUTHORITATIVE") and authority in self.SUFFICIENT else "LIMITED")
        if blocked:
            status, authority, reason = "UNKNOWN", "NONE", "STANDARD_AUTHORITY_BLOCKED"
            atomic_applicability_authoritative = False
            unconditional_applicability_authoritative = False
        atomic_feature_evaluations = [self._feature_evaluation_projection(x)
                                      for x in atomic_predicates]
        source_ids = self._source_ids(req, standard, subtype,
                                      atomic_feature_evaluations or feature_evaluations)
        classification_evidence = {
            "standard_scope_classification_id": standard.get("classification_id"),
            "standard_scope_status": standard.get("status"),
            "standard_scope_authority": standard.get("authority_tier"),
            "product_subtype_classification_id": subtype.get("classification_id"),
            "product_subtype_status": subtype.get("status"),
            "product_subtype_authority": subtype.get("authority_tier"),
            "relationship": "MATCH" if self._class_matches(required_class, subtype) else None,
        }
        dependency_ids = sorted(set(
            [rid] + source_ids +
            [x for x in (standard.get("classification_id"), subtype.get("classification_id")) if x] +
            [x.get("fact_id") for x in atomic_predicates if x.get("fact_id")]
        ))
        return {
            "evaluation_id": "CANONICAL-APP-" + self._hash(rid)[:20].upper(),
            "effective_requirement_id": rid,
            "requirement_id": rid,
            "effective_clause_id": effective_clause_id,
            "clause_id": req.get("clause_id"),
            "requirement_scope": scope,
            "scope_type": canonical_scope,
            "standard_authority_status": standard_authority_status,
            "standard_scope_result": self._stage("STANDARD_SCOPE", standard.get("status"), standard.get("authority_tier")),
            "product_subtype_result": self._stage("PRODUCT_SUBTYPE", subtype.get("status"), subtype.get("authority_tier")),
            "construction_result": self._predicate_stage("CONSTRUCTION", predicates["construction_conditions"]),
            "installation_result": self._predicate_stage("INSTALLATION", predicates["installation_conditions"]),
            "component_result": self._predicate_stage("COMPONENT", predicates["component_conditions"]),
            "feature_result": self._stage("FEATURE", self._combined_feature_status(atomic_feature_evaluations), authority),
            "operating_condition_result": self._predicate_stage("OPERATING_CONDITION", predicates["operating_conditions"]),
            "special_case_result": self._predicate_stage("SPECIAL_CASE", predicates["special_case_conditions"]),
            "exclusion_result": self._predicate_stage("EXCLUSION", predicates["exclusions"]),
            "final_applicability": final_applicability,
            "authority_status": authority_status,
            "decision_reason": "STANDARD_AUTHORITY_BLOCKED" if blocked else reason,
            "conditionality": conditionality,
            "atomic_predicate_contract": self._primary_predicate_contract(
                req, conditionality, atomic_predicates
            ),
            "atomic_predicates": atomic_predicates,
            "atomic_predicate_state": logic_state,
            "atomic_applicability_authoritative": atomic_applicability_authoritative,
            "unconditional_applicability_authoritative": unconditional_applicability_authoritative,
            "broad_scope_relevance_only": bool(
                conditionality["is_conditional"] and not atomic_predicates
            ),
            "predicate_trace": {"stage_order": list(EVALUATION_STAGE_ORDER), "predicates": predicates, "predicate_evaluations": predicate_evaluations, "atomic_predicates": atomic_predicates, "legacy_mapping_reason": legacy_mapping_reason},
            "source_trace": {"effective_kb_id": kb.get("effective_kb_id"), "requirement_id": rid, "standard_authority_status": standard_authority_status},
            "decision": status,
            "status": status,
            "resolved_decision": status,
            "authority_tier": authority,
            "reason_code": reason,
            "reason": self._reason(reason),
            "required_standard_scope_class": standard.get("canonical_class"),
            "required_product_class": required_class,
            "required_scope_class": required_class or standard.get("canonical_class"),
            "classification_evidence": classification_evidence,
            "feature_predicates": sorted({x["canonical_fact_reference"] for x in atomic_predicates if x.get("canonical_fact_reference")}),
            "feature_evaluations": atomic_feature_evaluations,
            "feature_predicates_required": bool(atomic_predicates),
            "explicit_exclusions": ([{"effect": effect, "status": app_status}]
                                    if exclusion else []),
            "dependency_ids": dependency_ids,
            "source_ids": source_ids,
            "kb_ids": [x for x in (kb.get("effective_kb_id"), rid) if x],
            "traceability": {
                "effective_kb_id": kb.get("effective_kb_id"),
                "source_ids": source_ids,
                "legacy_evaluation_id": prior.get("evaluation_id"),
                "policy_version": POLICY_VERSION,
            },
            "legacy_decision": self._enum(prior.get("decision")),
            "legacy_reason_code": prior.get("reason_code"),
            "original_applicability_status": app_status,
            "applicability_status_from_kb": app_status,
            "condition_text": req.get("condition_text"),
            "rule": copy.deepcopy(app.get("logic")) if isinstance(app.get("logic"), dict) else None,
            "required_features": sorted({x["canonical_fact_reference"] for x in atomic_predicates if x.get("canonical_fact_reference")}),
            "facts_used": [self._predicate_fact_snapshot(x) for x in atomic_predicates if x.get("fact_id")],
            "missing_features": sorted({str(x.get("canonical_fact_reference") or x.get("predicate_id")) for x in atomic_predicates if x.get("predicate_status") in {"UNKNOWN", "MISSING"}}),
            "conflicting_features": sorted({str(x.get("canonical_fact_reference")) for x in atomic_predicates if x.get("predicate_status") == "CONFLICTING"}),
            "review_features": sorted({str(x.get("canonical_fact_reference") or x.get("predicate_id")) for x in atomic_predicates if x.get("predicate_status") == "NEEDS_REVIEW"}),
            "scope_evaluation": copy.deepcopy(prior.get("scope_evaluation")),
            "effective_source_type": req.get("effective_source_type"),
            "base_sources": copy.deepcopy(req.get("base_sources") or []),
            "delta_sources": copy.deepcopy(req.get("delta_sources") or []),
            "policy_version": POLICY_VERSION,
        }

    @classmethod
    def _conditionality(cls, req: dict[str, Any], app: dict[str, Any]) -> dict[str, Any]:
        condition = str(req.get("condition_text") or app.get("condition_text") or "").strip()
        scope = app.get("scope") or {}
        grammar = str(scope.get("grammar") or "").upper()
        subject_kind = str((scope.get("subject") or {}).get("kind") or "").upper()
        structured = any(app.get(key) or req.get(key) for key in (
            "construction_conditions", "installation_conditions",
            "component_conditions", "operating_conditions",
            "special_case_conditions", "exclusions",
        ))
        atomic_logic = cls._logic_has_atomic_predicate(app.get("logic"))
        leading = bool(re.match(
            r"^(if|when|where|for|unless|only if|except where|except when|except for|"
            r"provided that|during|under the condition that)\b",
            condition, re.I,
        ))
        qualified_subject = bool(re.search(
            r"\b(?:appliances?|products?|equipment|parts?|components?)\s+"
            r"(?:provided\s+with|having|intended|fitted|incorporating|equipped)\b",
            condition, re.I,
        ))
        exclusion = (
            cls._enum(app.get("effect")) == "DOES_NOT_APPLY"
            and cls._enum(app.get("status")) != "ALWAYS"
        )
        is_conditional = bool(
            structured or atomic_logic or leading or qualified_subject or exclusion
            or grammar in {"LEADING_CONDITION", "NEGATIVE"}
            or subject_kind in {"FEATURE", "CONSTRUCTION", "COMPONENT", "ENVIRONMENT", "ELECTRICAL_CLASS"}
        )
        indicator = None
        if is_conditional and condition:
            match = re.match(
                r"^(if|when|where|for|unless|only if|except where|except when|"
                r"except for|provided that|during|under the condition that)\b",
                condition, re.I,
            )
            indicator = match.group(1).upper().replace(" ", "_") if match else "STRUCTURAL_SUBJECT"
        return {
            "is_conditional": is_conditional,
            "condition_type": indicator if is_conditional else "UNCONDITIONAL",
            "source_condition_text": condition or None,
            "detection_basis": (
                "PARSED_STANDARD_CONDITION" if condition else
                "STRUCTURED_APPLICABILITY_FIELDS" if structured else
                "UNCONDITIONAL_REQUIREMENT"
            ),
        }

    @classmethod
    def _logic_has_atomic_predicate(cls, node: Any) -> bool:
        if not isinstance(node, dict):
            return False
        field = node.get("field")
        if isinstance(field, str):
            return field not in {"canonical_product_classification", "product_type"}
        if isinstance(node.get("not"), dict) and cls._logic_has_atomic_predicate(node["not"]):
            return True
        return any(
            cls._logic_has_atomic_predicate(child)
            for key in ("all", "any")
            for child in (node.get(key) or [])
        )

    @classmethod
    def _conditional_family(cls, req: dict[str, Any], app: dict[str, Any]) -> str:
        if cls._enum(app.get("effect")) == "DOES_NOT_APPLY":
            return "EXCLUSION"
        scope = app.get("scope") or {}
        kind = str((scope.get("subject") or {}).get("kind") or "")
        mapped = {
            "FEATURE": "FEATURE",
            "CONSTRUCTION": "CONSTRUCTION",
            "COMPONENT": "COMPONENT",
            "ENVIRONMENT": "OPERATING_CONDITION",
            "ELECTRICAL_CLASS": "CONSTRUCTION",
        }.get(kind)
        if mapped:
            return mapped
        semantic = cls._condition_scope(
            req.get("condition_text") or app.get("condition_text"), req.get("text")
        )
        return semantic or "SPECIAL_CASE"

    def _evaluate_atomic_logic(self, node: Any, facts: dict[str, list[dict[str, Any]]],
                               req: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        """Evaluate only fact predicates; classification leaves are relevance-only."""

        if not isinstance(node, dict):
            return "MISSING", []
        if isinstance(node.get("field"), str):
            field = str(node["field"])
            if field in {"canonical_product_classification", "product_type"}:
                return "BROAD_RELEVANCE", []
            row = self._evaluate_atomic_leaf(node, facts, req)
            return self._predicate_logic_state(row), [row]
        if isinstance(node.get("not"), dict):
            state, rows = self._evaluate_atomic_logic(node["not"], facts, req)
            inverted = {"TRUE": "FALSE", "FALSE": "TRUE"}.get(state, state)
            return inverted, rows
        for key in ("all", "any"):
            children = node.get(key)
            if isinstance(children, list) and children:
                evaluated = [self._evaluate_atomic_logic(child, facts, req)
                             for child in children]
                rows = [row for _, items in evaluated for row in items]
                states = [state for state, _ in evaluated
                          if state != "BROAD_RELEVANCE"]
                if not states:
                    return "MISSING", rows
                return self._combine_predicate_states(states, key), rows
        return "MISSING", []

    def _evaluate_atomic_leaf(self, node: dict[str, Any],
                              facts: dict[str, list[dict[str, Any]]],
                              req: dict[str, Any]) -> dict[str, Any]:
        field = str(node.get("field") or "")
        operator = str(node.get("operator") or "equals")
        expected = copy.deepcopy(node.get("value"))
        candidates = facts.get(field, [])
        family = self._predicate_family(field, req)
        predicate_id = "CANONICAL-PREDICATE-" + self._hash({
            "requirement_id": req.get("effective_requirement_id"),
            "field": field, "operator": operator, "expected": expected,
        })[:20].upper()
        base = {
            "condition_type": family,
            "predicate_id": predicate_id,
            "predicate_family": family,
            "predicate_operator": operator.upper(),
            "expected_value": expected,
            "canonical_fact_reference": field or None,
            "source_requirement_reference": req.get("effective_requirement_id"),
        }
        if not candidates:
            return {**base, "predicate_authority": "NONE", "predicate_status": "UNKNOWN",
                    "observed_value": None, "fact_id": None,
                    "reason": "CANONICAL_FACT_UNAVAILABLE"}
        authoritative = [x for x in candidates if str(x.get("status")) == "CONFIRMED"
                         and x.get("canonical_value") is not None]
        conflicting = [x for x in candidates if str(x.get("status")) in {
            "CONFLICTING", "MULTI_STATE", "INVALID", "INFERRED"
        }]
        if conflicting:
            fact = conflicting[0]
            return {**base, "predicate_authority": "LIMITED",
                    "predicate_status": "NEEDS_REVIEW",
                    "observed_value": copy.deepcopy(fact.get("canonical_value")),
                    "fact_id": fact.get("fact_id"), "reason": "CANONICAL_FACT_REVIEW_REQUIRED"}
        values = {self._hash(x.get("canonical_value")) for x in authoritative}
        if len(values) > 1:
            fact = authoritative[0]
            return {**base, "predicate_authority": "LIMITED",
                    "predicate_status": "CONFLICTING",
                    "observed_value": copy.deepcopy(fact.get("canonical_value")),
                    "fact_id": fact.get("fact_id"), "reason": "CANONICAL_FACT_VALUE_CONFLICT"}
        if not authoritative:
            fact = candidates[0]
            return {**base, "predicate_authority": "NONE",
                    "predicate_status": "UNKNOWN",
                    "observed_value": copy.deepcopy(fact.get("canonical_value")),
                    "fact_id": fact.get("fact_id"), "reason": "CANONICAL_FACT_NOT_AUTHORITATIVE"}
        fact = authoritative[0]
        observed = fact.get("canonical_value")
        fact_source_ids = sorted(set(
            str(value) for value in (
                list(fact.get("source_evidence_ids") or [])
                + list(fact.get("source_observation_ids") or [])
            ) if value
        ))
        try:
            matched = self._compare_predicate(observed, operator, expected)
        except (TypeError, ValueError):
            return {**base, "predicate_authority": "LIMITED",
                    "predicate_status": "NEEDS_REVIEW",
                    "observed_value": copy.deepcopy(observed),
                    "fact_id": fact.get("fact_id"), "reason": "PREDICATE_VALUES_NOT_COMPARABLE"}
        return {**base, "predicate_authority": "AUTHORITATIVE",
                "predicate_status": "TRUE" if matched else "FALSE",
                "observed_value": copy.deepcopy(observed),
                "fact_id": fact.get("fact_id"),
                "source_fact_evidence_ids": fact_source_ids,
                "reason": "CANONICAL_FACT_PREDICATE"}

    @classmethod
    def _predicate_family(cls, field: str, req: dict[str, Any]) -> str:
        name = field.casefold()
        if re.search(r"(?:component|capacitor|relay|contactor|switch|motor|transformer|inlet)", name):
            return "COMPONENT"
        if re.search(r"(?:install|permanently_connected|fixed_wiring|portable|stationary|hand_held)", name):
            return "INSTALLATION"
        if re.search(r"(?:class|construction|insulation|attachment|enclosure|cord)", name):
            return "CONSTRUCTION"
        if re.search(r"(?:operat|temperature|humidity|environment|outdoor|indoor)", name):
            return "OPERATING_CONDITION"
        return cls._conditional_family(req, req.get("applicability") or {}) if not field else "FEATURE"

    @staticmethod
    def _normalize_predicate_value(value: Any) -> Any:
        if isinstance(value, str):
            return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
        return value

    @classmethod
    def _compare_predicate(cls, actual: Any, operator: str, expected: Any) -> bool:
        if operator == "exists":
            return actual is not None
        if isinstance(actual, dict) and "value" in actual:
            if isinstance(expected, dict):
                if actual.get("unit") != expected.get("unit"):
                    raise TypeError("measurement units differ")
                actual, expected = actual.get("value"), expected.get("value")
            else:
                actual = actual.get("value")
        left = cls._normalize_predicate_value(actual)
        right = cls._normalize_predicate_value(expected)
        if operator == "equals": return left == right
        if operator == "not_equals": return left != right
        if operator in {"in", "not_in"}:
            if not isinstance(expected, (list, tuple, set)):
                raise TypeError("collection required")
            values = [cls._normalize_predicate_value(x) for x in expected]
            return (left in values) if operator == "in" else (left not in values)
        if isinstance(left, bool) or isinstance(right, bool):
            raise TypeError("ordered Boolean comparison")
        if operator == "greater_than": return left > right
        if operator == "greater_than_or_equal": return left >= right
        if operator == "less_than": return left < right
        if operator == "less_than_or_equal": return left <= right
        raise ValueError("unsupported predicate operator")

    @staticmethod
    def _predicate_logic_state(row: dict[str, Any]) -> str:
        return str(row.get("predicate_status") or row.get("predicate_result") or "UNKNOWN")

    @staticmethod
    def _combine_predicate_states(states: list[str], operator: str = "all") -> str:
        values = [x for x in states if x not in {"BROAD_RELEVANCE", "MISSING"}]
        if not values:
            return "MISSING"
        if operator == "any":
            if "TRUE" in values: return "TRUE"
            if "NEEDS_REVIEW" in values or "CONFLICTING" in values: return "NEEDS_REVIEW"
            if "UNKNOWN" in values: return "UNKNOWN"
            return "FALSE"
        if "FALSE" in values: return "FALSE"
        if "NEEDS_REVIEW" in values or "CONFLICTING" in values: return "NEEDS_REVIEW"
        if "UNKNOWN" in values: return "UNKNOWN"
        return "TRUE"

    def _conditional_decision(self, state: str, predicates: list[dict[str, Any]],
                              standard: dict[str, Any], subtype: dict[str, Any],
                              required_class: str | None, exclusion: bool):
        if not predicates or state == "MISSING":
            return "NEEDS_REVIEW", "LOW", "ATOMIC_PREDICATE_NOT_IDENTIFIED", False
        if state == "NEEDS_REVIEW":
            return "NEEDS_REVIEW", "LOW", "ATOMIC_PREDICATE_REQUIRES_REVIEW", False
        if state == "UNKNOWN":
            return "UNKNOWN", "NONE", "ATOMIC_PREDICATE_FACT_UNKNOWN", False
        standard_ok = (standard.get("status") == "MATCH"
                       and standard.get("authority_tier") in self.SUFFICIENT)
        subtype_ok = (not required_class or (
            subtype.get("status") == "MATCH"
            and subtype.get("authority_tier") in self.SUFFICIENT
            and self._class_matches(required_class, subtype)
        ))
        authoritative = standard_ok and subtype_ok and all(
            x.get("predicate_authority") == "AUTHORITATIVE" for x in predicates
        )
        if not standard_ok:
            return "UNKNOWN", "NONE", "STANDARD_SCOPE_UNKNOWN", False
        if not subtype_ok:
            return "NEEDS_REVIEW", "LOW", "CLASSIFICATION_AUTHORITY_INSUFFICIENT", False
        if not authoritative:
            return "NEEDS_REVIEW", "LOW", "ATOMIC_PREDICATE_AUTHORITY_INSUFFICIENT", False
        if exclusion:
            return (("NOT_APPLICABLE", "HIGH", "AUTHORITATIVE_EXCLUSION_MATCH", True)
                    if state == "TRUE" else
                    ("APPLICABLE", "HIGH", "EXCLUSION_CONDITION_FALSE", True))
        return (("APPLICABLE", "HIGH", "ATOMIC_PREDICATE_CONFIRMED", True)
                if state == "TRUE" else
                ("NOT_APPLICABLE", "HIGH", "ATOMIC_PREDICATE_NOT_MATCHED", True))

    def _primary_predicate_contract(self, req, conditionality, predicates):
        if not conditionality["is_conditional"]:
            return None
        if len(predicates) == 1:
            return copy.deepcopy(predicates[0])
        if predicates:
            return {
                "condition_type": "COMPOSITE",
                "predicate_id": "CANONICAL-PREDICATE-" + self._hash({
                    "requirement_id": req.get("effective_requirement_id"),
                    "predicate_ids": [x.get("predicate_id") for x in predicates],
                })[:20].upper(),
                "predicate_family": "SPECIAL_CASE",
                "predicate_operator": "COMPOSITE",
                "expected_value": None,
                "canonical_fact_reference": None,
                "predicate_authority": "AUTHORITATIVE" if all(
                    x.get("predicate_authority") == "AUTHORITATIVE" for x in predicates
                ) else "LIMITED",
                "predicate_status": self._combine_predicate_states([
                    self._predicate_logic_state(x) for x in predicates
                ]),
                "source_requirement_reference": req.get("effective_requirement_id"),
            }
        return {
            "condition_type": conditionality["condition_type"],
            "predicate_id": "CANONICAL-PREDICATE-" + self._hash({
                "requirement_id": req.get("effective_requirement_id"),
                "condition": conditionality.get("source_condition_text"),
            })[:20].upper(),
            "predicate_family": self._conditional_family(
                req, req.get("applicability") or {}
            ),
            "predicate_operator": None,
            "expected_value": None,
            "canonical_fact_reference": None,
            "predicate_authority": "NONE",
            "predicate_status": "MISSING",
            "source_requirement_reference": req.get("effective_requirement_id"),
        }

    @staticmethod
    def _feature_evaluation_projection(predicate):
        return {
            "feature_id": predicate.get("canonical_fact_reference"),
            "predicate_status": predicate.get("predicate_status"),
            "value": copy.deepcopy(predicate.get("observed_value")),
            "fact_id": predicate.get("fact_id"),
            "fact_status": predicate.get("predicate_authority"),
            "source_ids": copy.deepcopy(predicate.get("source_fact_evidence_ids") or []),
        }

    @staticmethod
    def _predicate_fact_snapshot(predicate):
        return {
            "feature_id": predicate.get("canonical_fact_reference"),
            "value": copy.deepcopy(predicate.get("observed_value")),
            "status": predicate.get("predicate_authority"),
            "evidence_ids": copy.deepcopy(predicate.get("source_fact_evidence_ids") or []),
        }

    def _predicate_contract_from_evaluation(self, req, evaluation):
        field = evaluation.get("predicate")
        return {
            "condition_type": evaluation.get("scope_type"),
            "predicate_id": "CANONICAL-PREDICATE-" + self._hash({
                "requirement_id": req.get("effective_requirement_id"),
                "field": field, "expected": evaluation.get("expected_value"),
            })[:20].upper(),
            "predicate_family": evaluation.get("scope_type") or "SPECIAL_CASE",
            "predicate_operator": "EQUALS",
            "expected_value": copy.deepcopy(evaluation.get("expected_value")),
            "canonical_fact_reference": field,
            "predicate_authority": evaluation.get("authority_status"),
            "predicate_status": evaluation.get("predicate_result"),
            "source_requirement_reference": req.get("effective_requirement_id"),
            "observed_value": copy.deepcopy(evaluation.get("observed_value")),
            "fact_id": evaluation.get("fact_id"),
            "reason": evaluation.get("reason"),
        }

    def _decision(self, scope: str, required_class: str | None, features: list[str],
                  evaluations: list[dict[str, Any]], standard: dict[str, Any],
                  subtype: dict[str, Any], app_status: str | None, exclusion: bool,
                  prior: dict[str, Any]) -> tuple[str, str, str]:
        if exclusion and app_status == "ALWAYS":
            return "NOT_APPLICABLE", "HIGH", "EXPLICIT_SCOPE_EXCLUSION"
        if exclusion:
            old = self._enum(prior.get("decision"))
            if old in {"APPLICABLE", "NOT_APPLICABLE"}:
                return old, "MEDIUM", ("EXCLUSION_CONDITION_FALSE" if old == "APPLICABLE" else "EXPLICIT_SCOPE_EXCLUSION")
            return "NEEDS_REVIEW", "LOW", "KB_PREDICATE_INCOMPLETE"
        if scope == "GENERAL_STANDARD_SCOPE":
            if app_status in {"NEEDS_REVIEW", "UNRESOLVED"}:
                return "NEEDS_REVIEW", "LOW", "KB_PREDICATE_INCOMPLETE"
            if standard.get("status") == "MATCH" and standard.get("authority_tier") in self.SUFFICIENT:
                return "APPLICABLE", standard["authority_tier"], "STANDARD_SCOPE_MATCH"
            if standard.get("status") == "CONFLICTING":
                return "NEEDS_REVIEW", "LOW", "STANDARD_SCOPE_CONFLICT"
            return "UNKNOWN", "NONE", "STANDARD_SCOPE_UNKNOWN"
        if scope in {"DIRECT_PRODUCT", "SUBTYPE_SPECIFIC"} and not features:
            if subtype.get("status") == "MATCH" and subtype.get("authority_tier") in self.SUFFICIENT and self._class_matches(required_class, subtype):
                return "APPLICABLE", subtype["authority_tier"], "SUBTYPE_MATCH"
            if subtype.get("status") in {"NEEDS_REVIEW", "CONFLICTING"} or subtype.get("authority_tier") == "LOW":
                return "NEEDS_REVIEW", "LOW", "SUBTYPE_LOW_AUTHORITY"
            if subtype.get("status") == "NO_MATCH":
                return "NOT_APPLICABLE", subtype.get("authority_tier", "LOW"), "SUBTYPE_NO_MATCH"
            old = self._enum(prior.get("decision"))
            if old in {"APPLICABLE", "NOT_APPLICABLE"}:
                return old, "MEDIUM", "LEGACY_RULE_CONFIRMED"
            return "UNKNOWN", "NONE", "SUBTYPE_UNKNOWN"
        if features:
            states = {x["predicate_status"] for x in evaluations}
            if "CONFLICTING" in states:
                return "NEEDS_REVIEW", "LOW", "FEATURE_CONFLICT"
            if "NEEDS_REVIEW" in states:
                return "NEEDS_REVIEW", "LOW", "FEATURE_UNKNOWN"
            if "UNKNOWN" in states:
                return "UNKNOWN", "NONE", "FEATURE_UNKNOWN"
            if "FALSE" in states:
                return "NOT_APPLICABLE", "HIGH", "FEATURE_ABSENT"
            if evaluations and states == {"TRUE"}:
                if required_class and not (subtype.get("status") == "MATCH" and subtype.get("authority_tier") in self.SUFFICIENT and self._class_matches(required_class, subtype)):
                    return "NEEDS_REVIEW", "LOW", "CLASSIFICATION_AUTHORITY_INSUFFICIENT"
                return "APPLICABLE", "HIGH", "FEATURE_CONFIRMED"
        if app_status == "ALWAYS":
            return "APPLICABLE", "HIGH", "STANDARD_SCOPE_MATCH"
        # Preserve explicit KB uncertainty; standard presence alone is insufficient.
        if app_status in {"NEEDS_REVIEW", "UNRESOLVED"}:
            return "NEEDS_REVIEW", "LOW", "KB_PREDICATE_INCOMPLETE"
        old = self._enum(prior.get("decision"))
        if old in {"APPLICABLE", "NOT_APPLICABLE"}:
            return old, "MEDIUM", "LEGACY_RULE_CONFIRMED"
        return "UNKNOWN", "NONE", "REQUIREMENT_SCOPE_UNKNOWN"

    def _scope(self, req: dict[str, Any], prior: dict[str, Any]) -> tuple[str, str | None, list[str]]:
        scope_eval = prior.get("scope_evaluation") or {}
        required_class = scope_eval.get("required_scope")
        features = sorted(set(prior.get("required_features") or []))
        features = [x for x in features if x != "canonical_product_classification"]
        if features:
            names = " ".join(features).lower()
            if any(x in names for x in ("motor", "cord", "inlet", "switch", "transformer", "thermal", "wiring", "insulation")):
                scope = "CONSTRUCTION_SPECIFIC"
            elif any(x in names for x in ("component", "capacitor", "relay", "contactor")):
                scope = "COMPONENT_SPECIFIC"
            else:
                scope = "FEATURE_SPECIFIC"
            return scope, required_class, features
        scope_type = str(scope_eval.get("scope_type") or "")
        relationship = str(scope_eval.get("relationship") or scope_eval.get("classification_relationship") or "")
        if (required_class or scope_type == "PRODUCT_CLASS") and relationship in {"MATCH", "EQUIVALENT", "WITHIN_SCOPE"}:
            return "DIRECT_PRODUCT", required_class, []
        source = str(req.get("effective_source_type") or "")
        text = str(req.get("text") or req.get("requirement_text") or "")
        if str(req.get("clause_id") or "").upper().startswith(tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")):
            return "ANNEX_METHOD", None, []
        if re.search(r"\bcompliance is checked\b", text, re.I):
            return "SUPPORTING", None, []
        app = req.get("applicability") or {}
        if self._enum(app.get("status")) == "ALWAYS" and self._enum(app.get("effect")) != "DOES_NOT_APPLY":
            return "GENERAL_STANDARD_SCOPE", None, []
        if source in {"BASE", "MODIFICATION", "REPLACEMENT", "PART_2_MODIFICATION", "PART_2_REPLACEMENT"}:
            return "GENERAL_STANDARD_SCOPE", None, []
        return "UNKNOWN_SCOPE", None, []

    def _canonical_scope(self, req, prior, legacy_scope, required_class, features, exclusion):
        app = req.get("applicability") or {}
        explicit = str(app.get("scope_type") or req.get("scope_type") or "").upper()
        if explicit in CANONICAL_SCOPE_TYPES:
            return explicit, "EXPLICIT_CANONICAL_SCOPE"
        if exclusion: return "EXCLUSION", "EXPLICIT_EXCLUSION_EFFECT"
        if app.get("installation_conditions") or req.get("installation_conditions"): return "INSTALLATION", "STRUCTURED_INSTALLATION_PREDICATE"
        if app.get("construction_conditions") or req.get("construction_conditions"): return "CONSTRUCTION", "STRUCTURED_CONSTRUCTION_PREDICATE"
        if app.get("component_conditions") or req.get("component_conditions"): return "COMPONENT", "STRUCTURED_COMPONENT_PREDICATE"
        if app.get("operating_conditions") or req.get("operating_conditions"): return "OPERATING_CONDITION", "STRUCTURED_OPERATING_PREDICATE"
        if app.get("special_case_conditions") or req.get("special_case_conditions"): return "SPECIAL_CASE", "STRUCTURED_SPECIAL_CASE_PREDICATE"
        if features: return "FEATURE", "STRUCTURED_FEATURE_PREDICATE"
        if required_class and legacy_scope in {"DIRECT_PRODUCT", "SUBTYPE_SPECIFIC"}:
            semantic = self._condition_scope(required_class, req.get("condition_text") or req.get("text") or req.get("requirement_text"))
            if semantic: return semantic, "GENERIC_CONDITION_SEMANTIC_CLASSIFICATION"
            return "PRODUCT_SUBTYPE", "STRUCTURED_REQUIRED_SUBTYPE"
        mapping = {"GENERAL_STANDARD_SCOPE":"STANDARD_SCOPE", "SUBTYPE_SPECIFIC":"PRODUCT_SUBTYPE",
                   "FEATURE_SPECIFIC":"FEATURE", "CONSTRUCTION_SPECIFIC":"CONSTRUCTION",
                   "COMPONENT_SPECIFIC":"COMPONENT", "ANNEX_METHOD":"SPECIAL_CASE"}
        if legacy_scope in mapping: return mapping[legacy_scope], "VALIDATED_LEGACY_ALIAS"
        return "SPECIAL_CASE", "AMBIGUOUS_LEGACY_SCOPE_REQUIRES_REVIEW"

    @staticmethod
    def _condition_scope(condition, text=None):
        value = " ".join(str(x or "") for x in (condition, text)).casefold()
        if re.search(r"\b(components?|capacitors?|relays?|contactors?|switch(?:es)?|motors?|transformers?)\b", value): return "COMPONENT"
        if re.search(r"\b(installed|installation|mounted|fixed|built[- ]?in|portable|hand[- ]?held)\b", value): return "INSTALLATION"
        if re.search(r"\b(class\s*(?:i|ii|iii|1|2|3)|construction|insulation|ptc|thermal)\b", value): return "CONSTRUCTION"
        if re.search(r"\b(provided with|equipped with|has\s+(?:an?|the)|incorporates?|feature)\b", value): return "FEATURE"
        if re.search(r"\b(abnormal operation|during operation|operating condition|under\s+[^.]+condition|when operating)\b", value): return "OPERATING_CONDITION"
        return None

    @staticmethod
    def _predicate_inputs(req, prior, required_class, features, exclusion):
        app = req.get("applicability") or {}
        get = lambda name, default=None: copy.deepcopy(app.get(name, req.get(name, default)))
        return {"required_scope": get("required_scope"), "required_subtype": get("required_subtype", required_class),
                "required_features": list(get("required_features", features) or []),
                "construction_conditions": list(get("construction_conditions", []) or []),
                "installation_conditions": list(get("installation_conditions", []) or []),
                "component_conditions": list(get("component_conditions", []) or []),
                "operating_conditions": list(get("operating_conditions", []) or []),
                "special_case_conditions": list(get("special_case_conditions", []) or []),
                "exclusions": list(get("exclusions", [{"effect":"DOES_NOT_APPLY"}] if exclusion else []) or [])}

    def _evaluate_structured_predicates(self, scope, predicates, facts):
        key = {"CONSTRUCTION":"construction_conditions", "INSTALLATION":"installation_conditions", "COMPONENT":"component_conditions", "OPERATING_CONDITION":"operating_conditions", "SPECIAL_CASE":"special_case_conditions", "EXCLUSION":"exclusions"}.get(scope)
        rows = predicates.get(key, []) if key else []
        result = []
        for item in rows:
            item = item if isinstance(item, dict) else {"predicate": str(item)}
            fact_name = item.get("fact_key") or item.get("feature") or item.get("predicate")
            if not fact_name:
                continue
            expected = item.get("expected_value", item.get("value", True))
            evaluated = self._feature(str(fact_name), facts) if fact_name else {"predicate_status":"UNKNOWN", "fact_id":None, "fact_status":"UNKNOWN", "value":None, "source_ids":[]}
            state = evaluated.get("predicate_status")
            observed = evaluated.get("value")
            if state in {"TRUE", "FALSE"} and expected is not True:
                state = "TRUE" if observed == expected else "FALSE"
            result.append({"scope_type":scope, "predicate":fact_name, "expected_value":copy.deepcopy(expected), "observed_value":copy.deepcopy(observed), "fact_id":evaluated.get("fact_id"), "fact_status":evaluated.get("fact_status") or "UNKNOWN", "classification_authority":None, "predicate_result":state, "authority_status":"AUTHORITATIVE" if state in {"TRUE", "FALSE"} else "UNRESOLVED", "reason":"CANONICAL_FACT_PREDICATE" if evaluated.get("fact_id") else "CANONICAL_FACT_UNAVAILABLE"})
        return result

    @staticmethod
    def _predicate_decision(scope, evaluations, prior_status, prior_authority, prior_reason):
        states = {x.get("predicate_result") for x in evaluations}
        if "CONFLICTING" in states or "NEEDS_REVIEW" in states: return "NEEDS_REVIEW", "LOW", "PREDICATE_AUTHORITY_REVIEW"
        if "UNKNOWN" in states: return "UNKNOWN", "NONE", "PREDICATE_FACT_UNKNOWN"
        matched = bool(states) and states == {"TRUE"}
        if scope == "EXCLUSION":
            return ("NOT_APPLICABLE", "HIGH", "AUTHORITATIVE_EXCLUSION_MATCH") if matched else (prior_status, prior_authority, "EXCLUSION_NOT_MATCHED")
        if "FALSE" in states: return "NOT_APPLICABLE", "HIGH", "PREDICATE_NOT_MATCHED"
        if matched: return "APPLICABLE", "HIGH", "PREDICATE_CONFIRMED"
        return prior_status, prior_authority, prior_reason

    @staticmethod
    def _stage(stage, result, authority=None):
        return {"stage": stage, "result": result or "NOT_EVALUATED", "authority": authority or "NONE"}

    @classmethod
    def _predicate_stage(cls, stage, predicates):
        return cls._stage(stage, "PRESENT_REQUIRES_EVALUATION" if predicates else "NOT_APPLICABLE")

    @staticmethod
    def _combined_feature_status(evaluations):
        states = {x.get("predicate_status") for x in evaluations}
        if not states: return "NOT_APPLICABLE"
        if "CONFLICTING" in states: return "CONFLICTING"
        if "NEEDS_REVIEW" in states: return "NEEDS_REVIEW"
        if "UNKNOWN" in states: return "UNKNOWN"
        if "FALSE" in states: return "NO_MATCH"
        return "MATCH"

    def validate(self, artifact: Any, effective_kb: Any,
                 classification: Any, fact_ledger: Any,
                 downstream_version: str | None = None) -> dict[str, Any]:
        data = self._plain(artifact or {})
        active = {str(r.get("effective_requirement_id")) for r, _ in self._requirements(self._plain(effective_kb or {}))
                  if str(r.get("effective_status")) != "INACTIVE"}
        rows = {str(x.get("requirement_id")): x for x in data.get("results", [])}
        diagnostics = []
        allowed_status = {x.value for x in ApplicabilityStatus}
        allowed_authority = {x.value for x in AuthorityTier}
        allowed_final = {"APPLICABLE", "NOT_APPLICABLE", "UNKNOWN_APPLICABILITY", "NEEDS_REVIEW", "AUTHORITY_BLOCKED"}
        for rid, row in rows.items():
            status = row.get("status"); authority = row.get("authority_tier")
            if status not in allowed_status: diagnostics.append(self._diag("INVALID_APPLICABILITY_STATUS", rid))
            if authority not in allowed_authority: diagnostics.append(self._diag("INVALID_APPLICABILITY_AUTHORITY", rid))
            if not row.get("traceability", {}).get("source_ids") or not row.get("dependency_ids"):
                diagnostics.append(self._diag("APPLICABILITY_TRACE_MISSING", rid))
            conditional = bool((row.get("conditionality") or {}).get("is_conditional"))
            if not conditional and row.get("requirement_scope") == "GENERAL_STANDARD_SCOPE" and status == "UNKNOWN" and row.get("classification_evidence", {}).get("standard_scope_status") == "MATCH" and row.get("classification_evidence", {}).get("standard_scope_authority") in self.SUFFICIENT:
                diagnostics.append(self._diag("GENERAL_SCOPE_BLOCKED_BY_MISSING_SUBTYPE", rid))
            if row.get("requirement_scope") in {"DIRECT_PRODUCT", "SUBTYPE_SPECIFIC"} and not row.get("feature_predicates_required") and row.get("classification_evidence", {}).get("relationship") == "MATCH" and row.get("classification_evidence", {}).get("product_subtype_status") == "MATCH" and row.get("classification_evidence", {}).get("product_subtype_authority") in self.SUFFICIENT and status == "UNKNOWN":
                diagnostics.append(self._diag("DIRECT_PRODUCT_MATCH_NOT_APPLIED", rid))
            if status == "APPLICABLE" and row.get("classification_evidence", {}).get("product_subtype_authority") == "LOW" and row.get("requirement_scope") in {"DIRECT_PRODUCT", "SUBTYPE_SPECIFIC"}:
                diagnostics.append(self._diag("LOW_AUTHORITY_PROMOTED", rid))
            if status == "APPLICABLE" and row.get("feature_predicates_required"):
                if conditional:
                    state = row.get("atomic_predicate_state")
                    valid_atomic_result = bool(row.get("atomic_applicability_authoritative")) and (
                        state == "TRUE" or
                        (state == "FALSE" and row.get("reason_code") == "EXCLUSION_CONDITION_FALSE")
                    )
                    if not valid_atomic_result:
                        diagnostics.append(self._diag("FEATURE_PREDICATE_BYPASSED", rid))
                elif any(x.get("predicate_status") != "TRUE" for x in row.get("feature_evaluations", [])):
                    diagnostics.append(self._diag("FEATURE_PREDICATE_BYPASSED", rid))
            if status == "NOT_APPLICABLE" and any(x.get("predicate_status") == "UNKNOWN" for x in row.get("feature_evaluations", [])):
                diagnostics.append(self._diag("MISSING_FEATURE_TREATED_AS_FALSE", rid))
            if status == "APPLICABLE" and row.get("reason_code") == "STANDARD_PRESENCE_USED_AS_APPLICABILITY":
                diagnostics.append(self._diag("STANDARD_PRESENCE_USED_AS_APPLICABILITY", rid))
            if status == "APPLICABLE" and row.get("reason_code") == "EXPLICIT_SCOPE_EXCLUSION":
                diagnostics.append(self._diag("EXPLICIT_EXCLUSION_IGNORED", rid))
            if row.get("scope_type") not in CANONICAL_SCOPE_TYPES:
                diagnostics.append(self._diag("MISSING_CANONICAL_SCOPE_TYPE", rid))
            if row.get("final_applicability") not in allowed_final:
                diagnostics.append(self._diag("UNSAFE_APPLICABILITY_DECISION", rid))
            if row.get("predicate_trace", {}).get("stage_order") != list(EVALUATION_STAGE_ORDER):
                diagnostics.append(self._diag("APPLICABILITY_ORDER_ERROR", rid))
            if row.get("standard_authority_status") in BLOCKED_STANDARD_AUTHORITY and row.get("final_applicability") != "AUTHORITY_BLOCKED":
                diagnostics.append(self._diag("STANDARD_AUTHORITY_BYPASS", rid))
            if row.get("scope_type") == "PRODUCT_SUBTYPE" and row.get("predicate_trace", {}).get("legacy_mapping_reason") == "AMBIGUOUS_LEGACY_SCOPE_REQUIRES_REVIEW":
                diagnostics.append(self._diag("GENERIC_CONDITIONAL_AS_PRODUCT_SCOPE", rid))
            if conditional and status == "APPLICABLE" and not row.get("atomic_applicability_authoritative"):
                diagnostics.append(self._diag("CONDITIONAL_ATOM_APPLICABLE_FROM_SCOPE_ONLY", rid))
            if conditional and status == "APPLICABLE" and row.get("atomic_predicate_state") in {"UNKNOWN", "MISSING"}:
                diagnostics.append(self._diag("UNKNOWN_PREDICATE_TREATED_AS_TRUE", rid))
            if conditional and status == "NOT_APPLICABLE" and row.get("atomic_predicate_state") in {"UNKNOWN", "MISSING"}:
                diagnostics.append(self._diag("UNKNOWN_PREDICATE_TREATED_AS_FALSE", rid))
            if conditional and status == "APPLICABLE" and not row.get("atomic_predicates") and row.get("scope_type") == "STANDARD_SCOPE":
                diagnostics.append(self._diag("BROAD_SCOPE_FEATURE_AUTHORITY_LEAK", rid))
            if conditional and status == "APPLICABLE" and not row.get("atomic_predicates") and row.get("scope_type") == "PRODUCT_SUBTYPE":
                diagnostics.append(self._diag("SUBTYPE_FEATURE_AUTHORITY_LEAK", rid))
            if conditional and status in {"APPLICABLE", "NOT_APPLICABLE"} and row.get("reason_code") == "LEGACY_RULE_CONFIRMED":
                diagnostics.append(self._diag("LEGACY_SCOPE_AUTHORITY_CONSUMER", rid))
        for rid in active - set(rows): diagnostics.append(self._diag("APPLICABILITY_TRACE_MISSING", rid))
        inactive_ids = {str(r.get("effective_requirement_id")) for r, _ in self._requirements(self._plain(effective_kb or {})) if str(r.get("effective_status")) == "INACTIVE"}
        for rid in inactive_ids & set(rows): diagnostics.append(self._diag("INACTIVE_REQUIREMENT_EVALUATED", rid))
        if data.get("legacy_override"): diagnostics.append(self._diag("LEGACY_APPLICABILITY_OVERRIDE", None))
        if data.get("schema_version") != SCHEMA_VERSION or downstream_version and downstream_version != POLICY_VERSION:
            diagnostics.append(self._diag("STALE_APPLICABILITY_VERSION", None))
        counts = Counter(x["code"] for x in diagnostics)
        required = ["GENERAL_SCOPE_BLOCKED_BY_MISSING_SUBTYPE", "DIRECT_PRODUCT_MATCH_NOT_APPLIED", "LOW_AUTHORITY_PROMOTED", "FEATURE_PREDICATE_BYPASSED", "MISSING_FEATURE_TREATED_AS_FALSE", "STANDARD_PRESENCE_USED_AS_APPLICABILITY", "INACTIVE_REQUIREMENT_EVALUATED", "EXPLICIT_EXCLUSION_IGNORED", "APPLICABILITY_TRACE_MISSING", "INVALID_APPLICABILITY_STATUS", "INVALID_APPLICABILITY_AUTHORITY", "LEGACY_APPLICABILITY_OVERRIDE", "STALE_APPLICABILITY_VERSION", "MISSING_CANONICAL_SCOPE_TYPE", "UNSAFE_APPLICABILITY_DECISION", "APPLICABILITY_ORDER_ERROR", "STANDARD_AUTHORITY_BYPASS", "GENERIC_CONDITIONAL_AS_PRODUCT_SCOPE", "CONDITIONAL_ATOM_APPLICABLE_FROM_SCOPE_ONLY", "UNKNOWN_PREDICATE_TREATED_AS_TRUE", "UNKNOWN_PREDICATE_TREATED_AS_FALSE", "BROAD_SCOPE_FEATURE_AUTHORITY_LEAK", "SUBTYPE_FEATURE_AUTHORITY_LEAK", "LEGACY_SCOPE_AUTHORITY_CONSUMER"]
        return {"schema_version": INTEGRITY_VERSION, "applicability_schema_version": data.get("schema_version"), "applicability_policy_version": data.get("policy_version"), "valid": not diagnostics, "diagnostic_count": len(diagnostics), "diagnostic_counts": {x: counts[x] for x in required}, "diagnostics": diagnostics}

    @classmethod
    def compatibility_report(cls, canonical: Any) -> dict[str, Any]:
        data = cls._plain(canonical)
        rows = copy.deepcopy(data.get("results", []))
        return {"effective_kb_id": data.get("effective_kb_id"), "profile_id": data.get("profile_id"), "results": rows, "summary": copy.deepcopy(data.get("summary", {})), "canonical_source": "report/canonical_applicability_result.json", "canonical_policy_version": POLICY_VERSION}

    @staticmethod
    def _class_index(classification: Any) -> dict[str, dict[str, Any]]:
        data = GenericCanonicalApplicabilityAuthority._plain(classification or {})
        indexed = {str(x.get("classification_level")): x for x in data.get("classifications", [])}
        if data.get("standard_scope"):
            indexed["STANDARD_SCOPE"] = data["standard_scope"]
        if data.get("product_subtype"):
            indexed["PRODUCT_SUBTYPE"] = data["product_subtype"]
        return indexed

    @staticmethod
    def _fact_index(ledger: Any) -> dict[str, list[dict[str, Any]]]:
        data = GenericCanonicalApplicabilityAuthority._plain(ledger or {})
        result: dict[str, list[dict[str, Any]]] = {}
        for fact in data.get("facts", []): result.setdefault(str(fact.get("fact_name")), []).append(fact)
        return result

    def _feature(self, feature: str, facts: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        candidates = facts.get(feature, [])
        if not candidates: return {"feature_id": feature, "predicate_status": "UNKNOWN", "value": None, "fact_id": None, "source_ids": []}
        fact = candidates[0]; state = str(fact.get("status") or "UNKNOWN"); value = fact.get("canonical_value")
        token = value if isinstance(value, bool) else str(value).upper() if value is not None else None
        if state == "CONFLICTING": predicate = "CONFLICTING"
        elif state in {"INVALID", "INFERRED", "MULTI_STATE"}: predicate = "NEEDS_REVIEW"
        elif state != "CONFIRMED" or value is None: predicate = "UNKNOWN"
        elif token in self.TRUE_VALUES: predicate = "TRUE"
        elif token in self.FALSE_VALUES: predicate = "FALSE"
        else: predicate = "TRUE"
        return {"feature_id": feature, "predicate_status": predicate, "value": copy.deepcopy(value), "fact_id": fact.get("fact_id"), "fact_status": state, "source_ids": copy.deepcopy(fact.get("source_evidence_ids") or fact.get("source_observation_ids") or [])}

    @staticmethod
    def _fact_snapshot(item: dict[str, Any]) -> dict[str, Any]:
        return {"feature_id": item.get("feature_id"), "value": copy.deepcopy(item.get("value")), "status": item.get("fact_status"), "evidence_ids": copy.deepcopy(item.get("source_ids") or [])}

    @staticmethod
    def _class_matches(required: str | None, subtype: dict[str, Any]) -> bool:
        if not required: return True
        norm = lambda x: re.sub(r"[^a-z0-9]+", " ", str(x or "").casefold()).strip()
        a, b = norm(required), norm(subtype.get("canonical_class"))
        return bool(a and b and (a == b or a in b or b in a))

    @classmethod
    def _source_ids(cls, req: dict[str, Any], standard: dict[str, Any], subtype: dict[str, Any], evaluations: list[dict[str, Any]]) -> list[str]:
        values = [str(req.get("effective_requirement_id"))]
        for source in (req.get("base_sources") or []) + (req.get("delta_sources") or []):
            if isinstance(source, dict): values.extend(str(source[k]) for k in ("source_id", "requirement_id", "clause_id") if source.get(k))
        for item in (standard, subtype): values.extend(str(x) for x in item.get("source_ids", []) if x)
        for item in evaluations: values.extend(str(x) for x in item.get("source_ids", []) if x)
        return sorted(set(x for x in values if x and x != "None"))

    @staticmethod
    def _reason(code: str) -> str:
        return code.replace("_", " ").capitalize() + "."

    @classmethod
    def _requirements(cls, kb: dict[str, Any]):
        def walk(nodes):
            for node in nodes or []:
                yield node
                yield from walk(node.get("children") or [])
        for clause in walk(kb.get("clauses") or []):
            for req in clause.get("requirements") or []: yield req, clause.get("effective_clause_id")
        for annex in walk(kb.get("annexes") or []):
            for req in annex.get("requirements") or []: yield req, annex.get("effective_clause_id")

    @staticmethod
    def _enum(value: Any) -> str | None:
        if value is None: return None
        return str(value.value if isinstance(value, Enum) else value)

    @staticmethod
    def _diag(code: str, subject: str | None) -> dict[str, Any]:
        return {"code": code, "requirement_id": subject}

    @staticmethod
    def _hash(value: Any) -> str:
        raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def _plain(cls, value: Any) -> Any:
        if isinstance(value, Enum): return value.value
        if is_dataclass(value): return cls._plain(asdict(value))
        if isinstance(value, Mapping): return {str(k): cls._plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)): return [cls._plain(x) for x in value]
        return copy.deepcopy(value)

    @classmethod
    def save_json(cls, value: Any, path: Any) -> Path:
        target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(cls._plain(value), sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target


__all__ = ["ApplicabilityStatus", "AuthorityTier", "RequirementScope", "GenericCanonicalApplicabilityAuthority", "SCHEMA_VERSION", "POLICY_VERSION", "SCOPE_POLICY_VERSION"]
