"""Evaluate normalized IEC applicability rules against a product profile."""

from __future__ import annotations

import copy
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

from iec_parser.generic_product_profile_models import (
    ProductFact, ProductFactStatus, ProductProfile,
)


PathLike = Union[str, Path]


class RequirementApplicabilityDecision(str, Enum):
    """Final applicability state, kept distinct from compliance outcomes."""

    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    INACTIVE = "INACTIVE"


@dataclass
class ProductFactSnapshot:
    """Concise immutable-in-result view of a product fact used by a rule."""

    feature_id: str
    value: Any
    status: str
    confidence: Optional[float] = None
    evidence_ids: List[str] = field(default_factory=list)


@dataclass
class ApplicabilityEvaluationResult:
    """Traceable applicability decision for one effective requirement."""

    evaluation_id: str
    effective_requirement_id: str
    effective_clause_id: Optional[str]
    clause_id: Optional[str]
    decision: RequirementApplicabilityDecision
    reason_code: str
    reason: str
    applicability_status_from_kb: Optional[str] = None
    condition_text: Optional[str] = None
    rule: Optional[Dict[str, Any]] = None
    required_features: List[str] = field(default_factory=list)
    facts_used: List[ProductFactSnapshot] = field(default_factory=list)
    missing_features: List[str] = field(default_factory=list)
    conflicting_features: List[str] = field(default_factory=list)
    review_features: List[str] = field(default_factory=list)
    scope_evaluation: Optional[Dict[str, Any]] = None
    effective_source_type: Optional[str] = None
    base_sources: List[Any] = field(default_factory=list)
    delta_sources: List[Any] = field(default_factory=list)
    notes: Optional[str] = None


@dataclass
class ApplicabilityEvaluationReport:
    """Complete deterministic evaluation report for one KB/profile pair."""

    effective_kb_id: str
    profile_id: str
    results: List[ApplicabilityEvaluationResult] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)


class _LogicState(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"
    REVIEW = "REVIEW"


@dataclass
class _Context:
    facts: Mapping[str, ProductFact]
    classifications: Sequence[Any] = field(default_factory=tuple)
    facts_used: Dict[str, ProductFactSnapshot] = field(default_factory=dict)
    missing: Set[str] = field(default_factory=set)
    conflicting: Set[str] = field(default_factory=set)
    review: Set[str] = field(default_factory=set)
    statuses_used: Set[str] = field(default_factory=set)
    issue_codes: List[str] = field(default_factory=list)
    scope_evaluation: Optional[Dict[str, Any]] = None


class GenericRequirementApplicabilityEvaluator:
    """Apply Step 9 executable rules without evaluating product compliance."""

    _OPERATORS = {
        "equals", "not_equals", "greater_than", "greater_than_or_equal",
        "less_than", "less_than_or_equal", "in", "not_in", "exists",
    }

    def evaluate(
        self, effective_kb: Any, product_profile: Union[ProductProfile, Mapping[str, Any]]
    ) -> ApplicabilityEvaluationReport:
        """Evaluate every effective requirement in clauses and annexes."""

        profile = self._coerce_profile(product_profile)
        results: List[ApplicabilityEvaluationResult] = []
        for requirement, effective_clause_id in self._iter_requirements(effective_kb):
            results.append(self.evaluate_requirement(requirement, profile, effective_clause_id))
        kb_id = str(self._get(effective_kb, "effective_kb_id", ""))
        report = ApplicabilityEvaluationReport(kb_id, profile.profile_id, results)
        report.summary = self.get_summary(report)
        return report

    def evaluate_requirement(
        self, requirement: Any, product_profile: Union[ProductProfile, Mapping[str, Any]],
        effective_clause_id: Optional[str] = None,
    ) -> ApplicabilityEvaluationResult:
        """Evaluate one requirement using strict effective/applicability priority."""

        profile = self._coerce_profile(product_profile)
        requirement_id = str(self._get(requirement, "effective_requirement_id", ""))
        if not requirement_id:
            raise ValueError("effective requirement has no effective_requirement_id")
        effective_status = self._enum_value(self._get(requirement, "effective_status"))
        applicability = self._get(requirement, "applicability", {}) or {}
        applicability_status = self._enum_value(self._get(applicability, "status"))
        raw_rule = self._get(applicability, "logic")
        effect = self._enum_value(self._get(applicability, "effect")) or "APPLIES"
        rule = copy.deepcopy(raw_rule) if isinstance(raw_rule, dict) else raw_rule
        context = _Context(profile.facts, tuple(profile.classifications))

        if effective_status == "INACTIVE":
            decision, code, reason = (
                RequirementApplicabilityDecision.INACTIVE,
                "EFFECTIVE_REQUIREMENT_INACTIVE",
                "The Effective KB marks this requirement inactive; its rule was not evaluated.",
            )
        elif effective_status == "NEEDS_REVIEW":
            decision, code, reason = (
                RequirementApplicabilityDecision.NEEDS_REVIEW,
                "EFFECTIVE_REQUIREMENT_NEEDS_REVIEW",
                "The Effective KB marks this requirement as needing review.",
            )
        elif applicability_status == "ALWAYS":
            if effect == "DOES_NOT_APPLY":
                decision, code, reason = (
                    RequirementApplicabilityDecision.NOT_APPLICABLE,
                    "KB_UNCONDITIONAL_EXCLUSION", "The active requirement is explicitly excluded.",
                )
            else:
                decision, code, reason = (
                    RequirementApplicabilityDecision.APPLICABLE,
                    "KB_APPLICABILITY_ALWAYS", "The active requirement always applies.",
                )
        elif applicability_status == "NEEDS_REVIEW":
            decision, code, reason = (
                RequirementApplicabilityDecision.NEEDS_REVIEW,
                "KB_APPLICABILITY_NEEDS_REVIEW",
                "The normalized applicability rule requires review.",
            )
        elif applicability_status == "UNRESOLVED":
            decision, code, reason = (
                RequirementApplicabilityDecision.NEEDS_REVIEW,
                "KB_APPLICABILITY_UNRESOLVED",
                "The applicability rule is unresolved and was not reconstructed.",
            )
        elif applicability_status == "RESOLVED":
            state = self._evaluate_node(rule, context)
            decision, code, reason = self._decision_for_state(state, context)
            if effect == "DOES_NOT_APPLY" and decision in {
                RequirementApplicabilityDecision.APPLICABLE,
                RequirementApplicabilityDecision.NOT_APPLICABLE,
            }:
                decision = (RequirementApplicabilityDecision.NOT_APPLICABLE
                            if decision is RequirementApplicabilityDecision.APPLICABLE
                            else RequirementApplicabilityDecision.APPLICABLE)
                code = ("EXCLUSION_CONDITION_TRUE" if decision is RequirementApplicabilityDecision.NOT_APPLICABLE
                        else "EXCLUSION_CONDITION_FALSE")
                reason = ("The exclusion condition evaluated true." if decision is RequirementApplicabilityDecision.NOT_APPLICABLE
                          else "The exclusion condition evaluated false; the requirement remains applicable.")
        else:
            context.issue_codes.append("INVALID_RULE")
            decision, code, reason = (
                RequirementApplicabilityDecision.NEEDS_REVIEW, "INVALID_RULE",
                "The requirement has an unsupported applicability status.",
            )

        required = sorted(self._collect_features(rule)) if applicability_status == "RESOLVED" else []
        scope_evaluation = self._composite_scope_evaluation(
            context.scope_evaluation, required, context, decision
        )
        return ApplicabilityEvaluationResult(
            evaluation_id=self._evaluation_id(requirement_id),
            effective_requirement_id=requirement_id,
            effective_clause_id=effective_clause_id,
            clause_id=self._get(requirement, "clause_id"),
            decision=decision, reason_code=code, reason=reason,
            applicability_status_from_kb=applicability_status,
            condition_text=self._get(requirement, "condition_text"),
            rule=copy.deepcopy(rule) if isinstance(rule, dict) else None,
            required_features=required,
            facts_used=[context.facts_used[key] for key in sorted(context.facts_used)],
            missing_features=sorted(context.missing),
            conflicting_features=sorted(context.conflicting),
            review_features=sorted(context.review),
            scope_evaluation=scope_evaluation,
            effective_source_type=self._enum_value(self._get(requirement, "effective_source_type")),
            base_sources=self._plain_list(self._get(requirement, "base_sources", [])),
            delta_sources=self._plain_list(self._get(requirement, "delta_sources", [])),
            notes=self._get(requirement, "review_reason"),
        )

    @staticmethod
    def _composite_scope_evaluation(
        scope: Optional[Dict[str, Any]], required: Sequence[str], context: _Context,
        decision: RequirementApplicabilityDecision,
    ) -> Optional[Dict[str, Any]]:
        """Expose class and feature predicates as independent authorities."""

        if not scope:
            return None
        result = copy.deepcopy(scope)
        feature_ids = [item for item in required
                       if item != "canonical_product_classification"]
        predicates = []
        for feature_id in feature_ids:
            snapshot = context.facts_used.get(feature_id)
            predicates.append({
                "feature_id": feature_id,
                "status": snapshot.status if snapshot else "MISSING",
                "value": copy.deepcopy(snapshot.value) if snapshot else None,
                "authority": "PRODUCT_FACT",
                "resolved": bool(snapshot and snapshot.status in {
                    "CONFIRMED", "INFERRED_STRONG"
                } and snapshot.value is not None),
            })
        result["classification_relationship"] = result.get("relationship")
        result["classification_authority"] = "CANONICAL_PRODUCT_CLASSIFICATION"
        result["feature_predicates"] = predicates
        result["feature_predicates_required"] = bool(feature_ids)
        result["composite_predicate_state"] = decision.value
        result["classification_match_proves_feature_predicates"] = False
        return result

    @classmethod
    def to_dict(cls, value: Union[ApplicabilityEvaluationReport, ApplicabilityEvaluationResult]) -> Dict[str, Any]:
        """Serialize evaluator models to JSON-safe dictionaries."""

        if not is_dataclass(value):
            raise TypeError("value must be an applicability evaluation model")
        return cls._json_safe(asdict(value))

    @classmethod
    def to_json(
        cls, value: Union[ApplicabilityEvaluationReport, ApplicabilityEvaluationResult],
        indent: Optional[int] = 2,
    ) -> str:
        """Serialize deterministically with plain enum values."""

        return json.dumps(cls.to_dict(value), ensure_ascii=False, sort_keys=True, indent=indent)

    @classmethod
    def save_json(cls, report: ApplicabilityEvaluationReport, output_path: PathLike) -> Path:
        """Write an evaluation artifact without volatile metadata."""

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cls.to_json(report, 2) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def get_summary(report: ApplicabilityEvaluationReport) -> Dict[str, Any]:
        """Return decision, rule, evidence-trust, and missing-feature counts."""

        counts = Counter(item.decision.value for item in report.results)
        dependencies = Counter(
            status for item in report.results
            for status in {snapshot.status for snapshot in item.facts_used}
        )
        evaluated_reason_codes = {
            "RULE_EVALUATED_TRUE", "RULE_EVALUATED_FALSE", "PRODUCT_FACT_MISSING",
            "PRODUCT_FACT_UNKNOWN", "PRODUCT_FACT_INFERRED_FROM_NA",
            "PRODUCT_FACT_CONFLICT", "PRODUCT_FACT_INFERRED", "INCOMPARABLE_VALUE",
            "PRODUCT_CLASSIFICATION_MISSING", "PRODUCT_CLASSIFICATION_UNKNOWN",
            "PRODUCT_CLASSIFICATION_INFERRED", "PRODUCT_CLASSIFICATION_INCOMPARABLE",
            "PRODUCT_SCOPE_QUALIFICATION_MISSING", "INVALID_RULE",
        }
        return {
            "total_effective_requirements_evaluated": len(report.results),
            **{decision.value: counts[decision.value]
               for decision in RequirementApplicabilityDecision},
            "rules_evaluated": sum(item.reason_code in evaluated_reason_codes
                                   for item in report.results),
            "always_requirements": sum(
                item.applicability_status_from_kb == "ALWAYS" for item in report.results
            ),
            "requirements_with_missing_product_features": sum(
                bool(item.missing_features) for item in report.results
            ),
            "requirements_dependent_on": {
                status.value: dependencies[status.value] for status in ProductFactStatus
            },
            "unique_product_facts_used": sorted({
                fact.feature_id for item in report.results for fact in item.facts_used
            }),
            "unique_missing_features": sorted({
                feature for item in report.results for feature in item.missing_features
            }),
        }

    def _evaluate_node(self, node: Any, context: _Context) -> _LogicState:
        if not isinstance(node, dict):
            context.issue_codes.append("INVALID_RULE")
            return _LogicState.REVIEW
        keys = [key for key in ("field", "all", "any", "not") if key in node]
        if len(keys) != 1:
            context.issue_codes.append("INVALID_RULE")
            return _LogicState.REVIEW
        kind = keys[0]
        if kind == "field":
            return self._evaluate_leaf(node, context)
        if kind in {"all", "any"}:
            children = node[kind]
            if not isinstance(children, list) or not children:
                context.issue_codes.append("INVALID_RULE")
                return _LogicState.REVIEW
            states = [self._evaluate_node(child, context) for child in children]
            return self._combine_all(states) if kind == "all" else self._combine_any(states)
        child = node["not"]
        state = self._evaluate_node(child, context)
        return {
            _LogicState.TRUE: _LogicState.FALSE,
            _LogicState.FALSE: _LogicState.TRUE,
            _LogicState.UNKNOWN: _LogicState.UNKNOWN,
            _LogicState.REVIEW: _LogicState.REVIEW,
        }[state]

    def _evaluate_leaf(self, node: Dict[str, Any], context: _Context) -> _LogicState:
        field_name = node.get("field")
        operator = node.get("operator")
        if not isinstance(field_name, str) or not field_name.strip() or operator not in self._OPERATORS:
            context.issue_codes.append("INVALID_RULE")
            return _LogicState.REVIEW
        field_name = field_name.strip()
        if field_name == "canonical_product_classification":
            return self._evaluate_classification_scope(node, context)
        if field_name not in context.facts:
            context.missing.add(field_name)
            context.issue_codes.append("PRODUCT_FACT_MISSING")
            return _LogicState.UNKNOWN
        fact = context.facts[field_name]
        snapshot = ProductFactSnapshot(
            feature_id=field_name, value=copy.deepcopy(fact.value), status=fact.status.value,
            confidence=fact.confidence,
            evidence_ids=[item.evidence_id for item in fact.evidence],
        )
        context.facts_used[field_name] = snapshot
        context.statuses_used.add(fact.status.value)
        if fact.status is ProductFactStatus.CONFLICT:
            context.conflicting.add(field_name); context.review.add(field_name)
            context.issue_codes.append("PRODUCT_FACT_CONFLICT")
            return _LogicState.REVIEW
        if fact.status is ProductFactStatus.INFERRED:
            context.review.add(field_name); context.issue_codes.append("PRODUCT_FACT_INFERRED")
            return _LogicState.REVIEW
        if fact.status is ProductFactStatus.INFERRED_FROM_NA:
            context.issue_codes.append("PRODUCT_FACT_INFERRED_FROM_NA")
            return _LogicState.UNKNOWN
        if fact.status is ProductFactStatus.UNKNOWN:
            context.issue_codes.append("PRODUCT_FACT_UNKNOWN")
            return _LogicState.UNKNOWN
        if fact.value is None and operator != "exists":
            context.issue_codes.append("PRODUCT_FACT_UNKNOWN")
            return _LogicState.UNKNOWN
        try:
            outcome = self._compare(fact.value, operator, node.get("value"))
        except (TypeError, ValueError):
            context.review.add(field_name); context.issue_codes.append("INCOMPARABLE_VALUE")
            return _LogicState.REVIEW
        return _LogicState.TRUE if outcome else _LogicState.FALSE

    def _evaluate_classification_scope(
        self, node: Dict[str, Any], context: _Context
    ) -> _LogicState:
        """Evaluate a recovered product scope against Step 35 classification."""

        candidates = [item for item in context.classifications
                      if self._get(item, "canonical_term")]
        expected = node.get("value")
        if not candidates:
            context.missing.add("canonical_product_classification")
            context.issue_codes.append("PRODUCT_CLASSIFICATION_MISSING")
            context.scope_evaluation = {
                "scope_type": "PRODUCT_CLASS", "required_scope": expected,
                "normalized_required_scope": self._normalize_scope(expected),
                "actual_classification": None, "normalized_actual_classification": None,
                "relationship": "UNKNOWN", "basis": "CANONICAL_PRODUCT_CLASSIFICATION",
                "classification_status": None, "classification_confidence": None,
                "classification_basis": [], "definition_reference": None,
                "scope_reference": None,
            }
            return _LogicState.UNKNOWN
        classification = candidates[0]
        actual = self._get(classification, "canonical_term")
        status = self._enum_value(self._get(classification, "status"))
        required_tokens = self._scope_tokens(expected)
        actual_tokens = self._scope_tokens(actual)
        if not required_tokens or not actual_tokens:
            relationship = "UNKNOWN"
        elif required_tokens == actual_tokens:
            relationship = "MATCH"
        elif actual_tokens <= required_tokens:
            # The family matches, but remaining words are construction scope
            # that classification alone cannot prove.
            relationship = "MATCH"
        elif required_tokens.isdisjoint(actual_tokens):
            relationship = "NON_MATCH"
        else:
            relationship = "UNKNOWN"
        context.scope_evaluation = {
            "scope_type": "PRODUCT_CLASS", "required_scope": expected,
            "normalized_required_scope": self._normalize_scope(expected),
            "actual_classification": actual,
            "normalized_actual_classification": self._normalize_scope(actual),
            "relationship": relationship, "basis": "CANONICAL_PRODUCT_CLASSIFICATION",
            "classification_status": status,
            "classification_confidence": self._get(classification, "confidence"),
            "classification_basis": copy.deepcopy(
                self._get(classification, "classification_basis", []) or []),
            "definition_reference": self._get(classification, "definition_reference"),
            "scope_reference": self._get(classification, "scope_reference"),
        }
        snapshot = ProductFactSnapshot(
            feature_id="canonical_product_classification", value=actual,
            status=status or "UNKNOWN",
            confidence=self._get(classification, "confidence"),
            evidence_ids=[self._get(item, "evidence_id") for item in
                          (self._get(classification, "evidence", []) or [])
                          if self._get(item, "evidence_id")],
        )
        context.facts_used[snapshot.feature_id] = snapshot
        context.statuses_used.add(snapshot.status)
        if status == "CONFLICT":
            context.review.add(snapshot.feature_id)
            context.issue_codes.append("PRODUCT_CLASSIFICATION_CONFLICT")
            return _LogicState.REVIEW
        if status in {"UNKNOWN", "INFERRED_FROM_NA", None}:
            context.missing.add(snapshot.feature_id)
            context.issue_codes.append("PRODUCT_CLASSIFICATION_UNKNOWN")
            return _LogicState.UNKNOWN
        if status == "INFERRED":
            context.review.add(snapshot.feature_id)
            context.issue_codes.append("PRODUCT_CLASSIFICATION_INFERRED")
            return _LogicState.REVIEW
        if relationship == "NON_MATCH":
            return _LogicState.FALSE
        if relationship == "UNKNOWN":
            context.review.add(snapshot.feature_id)
            context.issue_codes.append("PRODUCT_CLASSIFICATION_INCOMPARABLE")
            return _LogicState.REVIEW
        if actual_tokens < required_tokens:
            context.missing.add("product_scope_qualification")
            context.issue_codes.append("PRODUCT_SCOPE_QUALIFICATION_MISSING")
            return _LogicState.UNKNOWN
        if status in {"CONFIRMED", "INFERRED_STRONG"}:
            return _LogicState.TRUE
        context.issue_codes.append("PRODUCT_CLASSIFICATION_UNKNOWN")
        return _LogicState.UNKNOWN

    @staticmethod
    def _normalize_scope(value: Any) -> str:
        return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split())

    @classmethod
    def _scope_tokens(cls, value: Any) -> Set[str]:
        structural_words = {
            "the", "this", "that", "these", "those", "other", "general",
            "each", "any", "all", "for", "with", "without", "and", "or",
        }
        return {token[:-1] if len(token) > 4 and token.endswith("s") else token
                for token in cls._normalize_scope(value).split()
                if len(token) > 2 and token not in structural_words}

    @classmethod
    def _compare(cls, actual: Any, operator: str, expected: Any) -> bool:
        if operator == "exists":
            return actual is not None
        left, right = cls._comparable_values(actual, expected)
        if operator == "equals": return left == right
        if operator == "not_equals": return left != right
        if operator == "in":
            if not isinstance(right, (list, tuple, set)): raise TypeError("in requires a collection")
            return left in right
        if operator == "not_in":
            if not isinstance(right, (list, tuple, set)): raise TypeError("not_in requires a collection")
            return left not in right
        if isinstance(left, bool) or isinstance(right, bool) or not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            raise TypeError("ordered comparison requires numbers")
        if operator == "greater_than": return left > right
        if operator == "greater_than_or_equal": return left >= right
        if operator == "less_than": return left < right
        if operator == "less_than_or_equal": return left <= right
        raise ValueError("unsupported operator")

    @staticmethod
    def _comparable_values(actual: Any, expected: Any) -> Tuple[Any, Any]:
        if isinstance(actual, dict):
            if "value" not in actual: raise TypeError("measurement has no scalar value")
            if isinstance(expected, dict):
                if "value" not in expected or actual.get("unit") != expected.get("unit"):
                    raise TypeError("measurement units are incompatible")
                return actual["value"], expected["value"]
            return actual["value"], expected
        if isinstance(expected, dict):
            raise TypeError("expected measurement is incompatible with scalar fact")
        return actual, expected

    @staticmethod
    def _combine_all(states: Sequence[_LogicState]) -> _LogicState:
        if _LogicState.FALSE in states: return _LogicState.FALSE
        if _LogicState.REVIEW in states: return _LogicState.REVIEW
        if _LogicState.UNKNOWN in states: return _LogicState.UNKNOWN
        return _LogicState.TRUE

    @staticmethod
    def _combine_any(states: Sequence[_LogicState]) -> _LogicState:
        if _LogicState.TRUE in states: return _LogicState.TRUE
        if _LogicState.REVIEW in states: return _LogicState.REVIEW
        if _LogicState.UNKNOWN in states: return _LogicState.UNKNOWN
        return _LogicState.FALSE

    @staticmethod
    def _decision_for_state(
        state: _LogicState, context: _Context
    ) -> Tuple[RequirementApplicabilityDecision, str, str]:
        if state is _LogicState.TRUE:
            return RequirementApplicabilityDecision.APPLICABLE, "RULE_EVALUATED_TRUE", "The resolved rule evaluated true."
        if state is _LogicState.FALSE:
            return RequirementApplicabilityDecision.NOT_APPLICABLE, "RULE_EVALUATED_FALSE", "The resolved rule evaluated false."
        if state is _LogicState.UNKNOWN:
            for code in ("PRODUCT_SCOPE_QUALIFICATION_MISSING", "PRODUCT_CLASSIFICATION_UNKNOWN", "PRODUCT_CLASSIFICATION_MISSING", "PRODUCT_FACT_INFERRED_FROM_NA", "PRODUCT_FACT_UNKNOWN", "PRODUCT_FACT_MISSING"):
                if code in context.issue_codes:
                    return RequirementApplicabilityDecision.UNKNOWN, code, "Required product information is insufficient."
            return RequirementApplicabilityDecision.UNKNOWN, "PRODUCT_FACT_UNKNOWN", "Required product information is insufficient."
        for code in ("INVALID_RULE", "INCOMPARABLE_VALUE", "PRODUCT_CLASSIFICATION_INCOMPARABLE", "PRODUCT_CLASSIFICATION_INFERRED", "PRODUCT_FACT_CONFLICT", "PRODUCT_FACT_INFERRED"):
            if code in context.issue_codes:
                return RequirementApplicabilityDecision.NEEDS_REVIEW, code, "The rule or a material product fact requires review."
        return RequirementApplicabilityDecision.NEEDS_REVIEW, "INVALID_RULE", "The rule requires review."

    @classmethod
    def _collect_features(cls, node: Any) -> Set[str]:
        if not isinstance(node, dict): return set()
        output: Set[str] = set()
        if isinstance(node.get("field"), str): output.add(node["field"].strip())
        for key in ("all", "any"):
            if isinstance(node.get(key), list):
                for child in node[key]: output.update(cls._collect_features(child))
        if "not" in node: output.update(cls._collect_features(node["not"]))
        return output

    @classmethod
    def _iter_requirements(cls, kb: Any) -> Iterable[Tuple[Any, Optional[str]]]:
        def clauses(items: Sequence[Any]) -> Iterable[Tuple[Any, Optional[str]]]:
            for clause in items:
                clause_key = cls._get(clause, "effective_clause_id")
                for requirement in cls._get(clause, "requirements", []) or []:
                    yield requirement, clause_key
                yield from clauses(cls._get(clause, "children", []) or [])
        yield from clauses(cls._get(kb, "clauses", []) or [])
        for annex in cls._get(kb, "annexes", []) or []:
            annex_key = cls._get(annex, "effective_annex_id")
            for requirement in cls._get(annex, "requirements", []) or []:
                yield requirement, annex_key

    @staticmethod
    def _coerce_profile(value: Union[ProductProfile, Mapping[str, Any]]) -> ProductProfile:
        if isinstance(value, ProductProfile): return value
        if isinstance(value, Mapping): return ProductProfile.from_dict(dict(value))
        raise TypeError("product_profile must be ProductProfile or a mapping")

    @staticmethod
    def _get(value: Any, name: str, default: Any = None) -> Any:
        return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)

    @staticmethod
    def _enum_value(value: Any) -> Optional[str]:
        if value is None: return None
        return str(value.value if isinstance(value, Enum) else value)

    @classmethod
    def _plain_list(cls, value: Any) -> List[Any]:
        return [cls._json_safe(asdict(item) if is_dataclass(item) else copy.deepcopy(item))
                for item in (value or [])]

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if isinstance(value, Enum): return value.value
        if isinstance(value, dict): return {key: cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, list): return [cls._json_safe(item) for item in value]
        return value

    @staticmethod
    def _evaluation_id(requirement_id: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", requirement_id).strip("_")
        return f"APP-EVAL-{normalized}"


__all__ = [
    "ApplicabilityEvaluationReport", "ApplicabilityEvaluationResult",
    "GenericRequirementApplicabilityEvaluator", "ProductFactSnapshot",
    "RequirementApplicabilityDecision",
]
