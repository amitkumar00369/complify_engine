"""Conservative normalization of raw IEC applicability conditions."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from iec_parser.generic_iec_feature_registry import (
    CanonicalProductFeatureRegistry,
    FeatureDataType,
)
from iec_parser.generic_iec_kb_models import (
    ApplicabilityStatus,
    Clause,
    Requirement,
)


Logic = Dict[str, Any]


@dataclass(frozen=True)
class ApplicabilityNormalizationDiagnostic:
    """Trace why one raw condition was or was not normalized."""

    clause_id: str
    requirement_id: str
    condition_text: str
    status: ApplicabilityStatus
    candidate_features: List[str]
    unmatched_fragments: List[str]
    reason: str


class GenericIECApplicabilityNormalizer:
    """Populate executable logic only for fully recognized product conditions."""

    SUPPORTED_OPERATORS = {
        "equals", "not_equals", "greater_than", "greater_than_or_equal",
        "less_than", "less_than_or_equal", "in", "not_in", "exists",
    }
    _LOGIC_KEYS = {"field", "operator", "value", "all", "any", "not"}
    _CLASS_VALUES = {
        "0": "CLASS_0", "0i": "CLASS_0I", "i": "CLASS_I",
        "ii": "CLASS_II", "iii": "CLASS_III",
    }
    _ATTACHMENT_VALUES = {"x": "TYPE_X", "y": "TYPE_Y", "z": "TYPE_Z"}
    _BLOCKED_STATE_RE = re.compile(
        r"(?:short[ -]circuited|open[ -]circuited|\bgwfi\b|\bgwit\b|"
        r"glow wire (?:flammability index|ignition temperature)|"
        r"depends upon the operation|rubber part|parts are of steel|"
        r"soldered connections|type 2 protection|mass not exceeding|"
        r"obviously unnecessary|overturns in one or more positions)",
    )

    def __init__(self, registry: CanonicalProductFeatureRegistry) -> None:
        """Configure the canonical registry used as the only field authority."""

        if not isinstance(registry, CanonicalProductFeatureRegistry):
            raise TypeError("registry must be a CanonicalProductFeatureRegistry")
        self.registry = registry
        self._diagnostics: List[ApplicabilityNormalizationDiagnostic] = []

    def parse(self, clauses: Sequence[Clause]) -> List[Clause]:
        """Return a normalized deep copy of a clause hierarchy."""

        if clauses is None or isinstance(clauses, (str, bytes)):
            raise TypeError("clauses must be a sequence of Clause objects")
        if any(not isinstance(clause, Clause) for clause in clauses):
            raise TypeError("Every input item must be a Clause")
        copied = copy.deepcopy(list(clauses))
        self._diagnostics = []
        for clause in copied:
            self._process_clause_recursive(clause)
        return copied

    def get_diagnostics(self) -> List[ApplicabilityNormalizationDiagnostic]:
        """Return diagnostics from the most recent parse call."""

        return list(self._diagnostics)

    def validate_logic(self, logic: Any) -> bool:
        """Return whether logic is complete and registry-valid."""

        return self._validate_logic(logic)

    def _process_clause_recursive(self, clause: Clause) -> None:
        implicit_feature = self._implicit_clause_feature(clause)
        for requirement in clause.requirements:
            self._process_requirement(clause.clause_id, requirement, implicit_feature)
        for child in clause.children:
            self._process_clause_recursive(child)

    def _process_requirement(self, clause_id: str, requirement: Requirement,
                             implicit_feature: Optional[str] = None) -> None:
        condition = requirement.applicability.condition_text
        if condition is None:
            condition = requirement.condition_text
        if not condition or not condition.strip():
            if implicit_feature:
                requirement.applicability.status = ApplicabilityStatus.RESOLVED
                requirement.applicability.logic = self._bool(implicit_feature)
                requirement.applicability.condition_text = (
                    f"Source-scoped feature {implicit_feature} is present"
                )
                return
            requirement.applicability.status = ApplicabilityStatus.ALWAYS
            requirement.applicability.logic = None
            return

        condition = self._recover_complete_condition(condition, requirement.text)
        requirement.condition_text = condition
        requirement.applicability.condition_text = condition

        normalized = self._normalize_condition(condition)
        candidates = self._find_feature_candidates(condition)
        logic, reason = self._parse_complete_condition(normalized)
        logic = self._promote_product_scope_operand(
            logic, requirement.applicability.scope
        )
        logic = self._split_composite_classification_operands(logic)
        if logic is not None and self._uses_classification_operand(logic):
            reason = "Source-backed product subject represented as a canonical classification predicate"
        if logic is None and requirement.applicability.scope:
            logic = self._parse_recovered_scope(requirement.applicability.scope)
            if logic is not None:
                reason = "Source-backed standard subject represented as a canonical predicate"
        if logic is not None and self._validate_logic(logic):
            requirement.applicability.status = ApplicabilityStatus.RESOLVED
            requirement.applicability.logic = logic
            unmatched: List[str] = []
        else:
            requirement.applicability.logic = None
            if candidates or logic is not None:
                requirement.applicability.status = ApplicabilityStatus.NEEDS_REVIEW
            else:
                requirement.applicability.status = ApplicabilityStatus.UNRESOLVED
            unmatched = [condition]
            if logic is not None:
                reason = "Generated logic failed registry or structural validation"
        self._diagnostics.append(
            ApplicabilityNormalizationDiagnostic(
                clause_id=clause_id,
                requirement_id=requirement.requirement_id,
                condition_text=condition,
                status=requirement.applicability.status,
                candidate_features=candidates,
                unmatched_fragments=unmatched,
                reason=reason,
            )
        )

    def _parse_recovered_scope(self, scope: Any) -> Optional[Logic]:
        """Represent an extractor-owned subject without a product-name dictionary."""

        if not isinstance(scope, dict):
            return None
        subject = scope.get("subject")
        if not isinstance(subject, dict):
            return None
        normalized = self._normalize_condition(str(subject.get("normalized_term") or ""))
        if not normalized:
            return None
        if str(subject.get("kind") or "") not in {
            "PRODUCT_TYPE", "COMPONENT", "ELECTRICAL_CLASS"
        }:
            # Construction/feature/environment subjects remain explicitly
            # unresolved unless the existing registry-backed parsers above
            # recognized every operand.  Unknown scope is never unconditional.
            return None
        alternatives = [
            self._normalize_condition(str(value))
            for value in (subject.get("alternatives") or []) if str(value).strip()
        ]
        if alternatives and str(subject.get("kind") or "") == "PRODUCT_TYPE":
            return self._any(*[
                self._leaf("canonical_product_classification", "equals", value)
                for value in alternatives
            ])
        if str(subject.get("kind") or "") == "PRODUCT_TYPE":
            composite = self._product_class_and_feature_scope(normalized)
            if composite is not None:
                return composite
            return self._leaf(
                "canonical_product_classification", "equals", normalized
            )
        return self._leaf(
            "product_type", "equals", self._product_type_value(normalized)
        )

    def _product_class_and_feature_scope(self, normalized: str) -> Optional[Logic]:
        """Split explicit class + Boolean construction text into two predicates."""

        matches: List[Tuple[int, int, str, str]] = []
        for feature in self.registry.get_all():
            if feature.data_type is not FeatureDataType.BOOLEAN:
                continue
            for alias in sorted(feature.aliases, key=len, reverse=True):
                token = self._normalize_condition(alias)
                found = re.search(rf"\b{re.escape(token)}s?\b", normalized)
                prefix = normalized[:found.start()] if found else ""
                if found and re.search(
                    r"(?:\bthat\b|\bwhich\b)?\s*(?:(?:does\s+not\s+)?(?:include|includes|"
                    r"including|incorporate|incorporates|incorporating|have|has|having)|"
                    r"with|without|no)\s+(?:an?\s+)?$", prefix
                ):
                    matches.append((found.start(), found.end(), feature.key, token))
                    break
        unique = {(start, end, key, token) for start, end, key, token in matches}
        if len(unique) != 1:
            return None
        start, end, feature_id, token = next(iter(unique))
        prefix = normalized[:start]
        negative = bool(re.search(r"(?:\bwithout\b|\bno\b|\bnot\s+(?:having|including|incorporating)\b)\s*(?:an?\s+)?$", prefix))
        connector = re.compile(
            rf"\s*(?:that|which)?\s*(?:(?:does\s+not\s+)?(?:include|includes|including|"
            rf"incorporate|incorporates|incorporating|have|has|having)|with|without|no)"
            rf"\s+(?:an?\s+)?{re.escape(token)}s?\b"
        )
        class_term = connector.sub("", normalized, count=1).strip(" ,-")
        if class_term == normalized or not class_term:
            return None
        return self._all(
            self._leaf("canonical_product_classification", "equals", class_term),
            self._leaf(feature_id, "equals", not negative),
        )

    def _promote_product_scope_operand(
        self, logic: Optional[Logic], scope: Any
    ) -> Optional[Logic]:
        """Promote only extractor-owned product-type leaves to classification operands."""

        if logic is None or not isinstance(scope, dict):
            return logic
        subject = scope.get("subject")
        if not isinstance(subject, dict) or str(subject.get("kind") or "") != "PRODUCT_TYPE":
            return logic

        def promote(node: Any) -> Any:
            if not isinstance(node, dict):
                return node
            copied = copy.deepcopy(node)
            if copied.get("field") == "product_type":
                copied["field"] = "canonical_product_classification"
                return copied
            for key in ("all", "any"):
                if isinstance(copied.get(key), list):
                    copied[key] = [promote(child) for child in copied[key]]
            if isinstance(copied.get("not"), dict):
                copied["not"] = promote(copied["not"])
            return copied

        return promote(logic)

    def _split_composite_classification_operands(
        self, logic: Optional[Logic]
    ) -> Optional[Logic]:
        """Refine composite classification strings after parser promotion."""

        if not isinstance(logic, dict):
            return logic
        copied = copy.deepcopy(logic)
        if (copied.get("field") == "canonical_product_classification"
                and copied.get("operator") == "equals"):
            split = self._product_class_and_feature_scope(
                self._normalize_condition(str(copied.get("value") or ""))
            )
            return split or copied
        for key in ("all", "any"):
            if isinstance(copied.get(key), list):
                copied[key] = [self._split_composite_classification_operands(child)
                               for child in copied[key]]
        if isinstance(copied.get("not"), dict):
            copied["not"] = self._split_composite_classification_operands(
                copied["not"]
            )
        return copied

    @staticmethod
    def _uses_classification_operand(logic: Any) -> bool:
        if not isinstance(logic, dict):
            return False
        if logic.get("field") == "canonical_product_classification":
            return True
        return any(
            GenericIECApplicabilityNormalizer._uses_classification_operand(child)
            for key in ("all", "any")
            for child in (logic.get(key) or [])
        ) or GenericIECApplicabilityNormalizer._uses_classification_operand(logic.get("not"))

    def _implicit_clause_feature(self, clause: Clause) -> Optional[str]:
        """Resolve a feature-scoped clause only from explicit normative syntax."""

        if not clause.requirements:
            return None
        opening = self._normalize_condition(clause.requirements[0].text)
        for feature in self.registry.get_all():
            if feature.data_type is not FeatureDataType.BOOLEAN:
                continue
            for alias in sorted({*feature.aliases, feature.key.replace("_", " ")}, key=len, reverse=True):
                normalized = self._normalize_condition(alias)
                if re.match(rf"^{re.escape(normalized)}s?\s+(?:shall|must)\b", opening):
                    return feature.key
        return None

    @staticmethod
    def _normalize_condition(condition: str) -> str:
        text = condition.translate(str.maketrans({"–": "-", "—": "-", "−": "-"}))
        text = re.sub(r"\s+", " ", text).strip().rstrip(" .,:;").casefold()
        return text

    def _find_feature_candidates(self, condition: str) -> List[str]:
        normalized = self._alias_text(condition)
        padded = f" {normalized} "
        candidates: Set[str] = set()
        for feature in self.registry.get_all():
            for alias in [feature.key.replace("_", " "), *feature.aliases]:
                candidate = self._alias_text(alias)
                if candidate and f" {candidate} " in padded:
                    candidates.add(feature.key)
        return sorted(candidates)

    @staticmethod
    def _alias_text(value: str) -> str:
        return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())

    def _parse_complete_condition(self, text: str) -> Tuple[Optional[Logic], str]:
        if self._BLOCKED_STATE_RE.search(text):
            return None, "Condition describes test, requirement, material, or exception state"

        logic = self._parse_canonical_examples(text)
        if logic is not None:
            return logic, "Complete condition matched a deterministic canonical pattern"

        logic = self._parse_class_condition(text)
        if logic is not None:
            return logic, "Complete protection-class condition represented"

        logic = self._parse_attachment_condition(text)
        if logic is not None:
            return logic, "Complete attachment-type condition represented"

        logic = self._parse_simple_product_condition(text)
        if logic is not None:
            return logic, "Complete product-feature condition represented"

        logic = self._parse_presence_usage_condition(text)
        if logic is not None:
            return logic, "Registry-backed component presence or usage condition represented"

        logic = self._parse_real_compound_condition(text)
        if logic is not None:
            return logic, "Complete compound condition represented"

        return None, "No safe complete deterministic mapping"

    @classmethod
    def _recover_complete_condition(cls, condition: str, requirement_text: str) -> str:
        """Recover a leading condition only when parser output is a strict prefix."""
        raw = re.sub(r"\s+", " ", str(requirement_text or "")).strip()
        current = re.sub(r"\s+", " ", str(condition or "")).strip()
        if not raw.casefold().startswith(current.casefold()):
            return current
        ordinary = re.match(r"^(if .+?),\s+it\s+(?:shall|must)\b", raw, re.I)
        if ordinary:
            return ordinary.group(1)
        inverted = re.match(r"^(when .+?),\s+(an?\s+.+?)\s+(?:shall|must)\b", raw, re.I)
        if inverted:
            return f"{inverted.group(2)} {inverted.group(1)}"
        return current

    def _parse_presence_usage_condition(self, text: str) -> Optional[Logic]:
        container_with_feature = re.fullmatch(
            r"if (?:an? )?(?:product|appliance|equipment|machine|tool|device) "
            r"(?:is|are) (?:provided|fitted|equipped) with (?:an? )?(.+)",
            text,
        )
        direct_container = re.fullmatch(
            r"if (?:an? )?(?:product|appliance|equipment|machine|tool|device) "
            r"(?:has|uses|contains|incorporates) (?:an? )?(.+)",
            text,
        )
        positive = (
            container_with_feature,
            direct_container,
            re.fullmatch(
                r"if (.+?) (?:is|are) (?:used|provided|fitted|incorporated|included)"
                r"(?:\s+.+)?",
                text,
            ),
            re.fullmatch(r"(?:an? )?(.+?) when used as .+", text),
            re.fullmatch(
                r"(?:for |where )?(?:products?|appliances?|equipment)?\s*"
                r"(?:having|using|containing|incorporating) (?:an? )?(.+)",
                text,
            ),
        )
        for match in positive:
            if match:
                feature = self._boolean_alias(match.group(1))
                if feature:
                    return self._bool(feature)
        negative = re.fullmatch(
            r"(?:for |where )?(?:products?|appliances?|equipment)?\s*"
            r"(?:without|not fitted with|not provided with) (?:an? )?(.+)",
            text,
        )
        if negative:
            feature = self._boolean_alias(negative.group(1))
            if feature:
                return self._bool(feature, False)
        return None

    def _parse_canonical_examples(self, text: str) -> Optional[Logic]:
        if re.fullmatch(r"(?:for )?stationary class i appliances?", text):
            return self._all(self._bool("is_stationary"), self._enum("protection_class", "CLASS_I"))
        if re.fullmatch(r"appliances incorporating (?:a )?programmer or (?:a )?timer", text):
            return self._any(self._bool("has_programmer"), self._bool("has_timer"))
        if re.fullmatch(
            r"appliances not intended for connection to the hot water supply and not provided with heating elements?",
            text,
        ):
            return self._all(
                self._bool("has_hot_water_connection", False),
                self._bool("has_heating_element", False),
            )
        subject_feature = re.fullmatch(r"for (.+?) having (.+)", text)
        if subject_feature:
            subject = self._boolean_alias(subject_feature.group(1))
            feature = self._boolean_alias(subject_feature.group(2))
            if subject and feature:
                return self._all(self._bool(subject), self._bool(feature))
        category_loading = re.fullmatch(
            r"for (.+?) of the (.+?) type that are loaded from the (.+?) or from the (.+)", text,
        )
        if category_loading:
            subject = self._boolean_alias(category_loading.group(1))
            construction = self._boolean_alias(category_loading.group(2) + " type")
            loading = self._enum_alias("loading type", category_loading.group(3), category_loading.group(4))
            if subject and construction and loading:
                return self._all(self._bool(subject), self._bool(construction), loading)
        if re.fullmatch(r"if the filter compartment can be opened", text):
            return self._bool("has_openable_filter_compartment")
        return None

    def _parse_class_condition(self, text: str) -> Optional[Logic]:
        exclusion = re.fullmatch(
            r"(?:except for|for (?:appliances|constructions) other than those of) class (0i|0|i|ii|iii)"
            r"(?: appliances?| constructions?)?",
            text,
        )
        if exclusion:
            return self._enum("protection_class", self._CLASS_VALUES[exclusion.group(1)], "not_equals")
        negative = re.fullmatch(
            r"this requirement does not apply to class (0i|0|i|ii|iii) appliances?",
            text,
        )
        if negative:
            return self._enum("protection_class", self._CLASS_VALUES[negative.group(1)], "not_equals")
        positive = re.fullmatch(
            r"(?:for )?class (0i|0|i|ii|iii) (?:appliances?|constructions?)",
            text,
        )
        if positive:
            return self._enum("protection_class", self._CLASS_VALUES[positive.group(1)])
        construction = re.fullmatch(
            r"appliances having parts of class (0i|0|i|ii|iii) construction", text
        )
        if construction:
            return self._enum("protection_class", self._CLASS_VALUES[construction.group(1)])
        combined = re.fullmatch(r"class ii appliances and class ii constructions", text)
        if combined:
            return self._enum("protection_class", "CLASS_II")
        multi = re.fullmatch(r"class 0 appliances, class ii appliances and class iii appliances", text)
        if multi:
            return self._any(
                self._enum("protection_class", "CLASS_0"),
                self._enum("protection_class", "CLASS_II"),
                self._enum("protection_class", "CLASS_III"),
            )
        return None

    def _parse_attachment_condition(self, text: str) -> Optional[Logic]:
        excluded = re.fullmatch(r"except for type ([xyz]) attachment", text)
        if excluded:
            return self._enum("attachment_type", self._ATTACHMENT_VALUES[excluded.group(1)], "not_equals")
        single = re.fullmatch(r"for appliances with type ([xyz]) attachment", text)
        if not single:
            single = re.fullmatch(r"for type ([xyz]) attachment", text)
        if single:
            return self._enum("attachment_type", self._ATTACHMENT_VALUES[single.group(1)])
        alternatives = re.fullmatch(r"for type ([xyz]) attachment and type ([xyz]) attachment", text)
        if alternatives:
            return self._any(
                self._enum("attachment_type", self._ATTACHMENT_VALUES[alternatives.group(1)]),
                self._enum("attachment_type", self._ATTACHMENT_VALUES[alternatives.group(2)]),
            )
        return None

    def _parse_simple_product_condition(self, text: str) -> Optional[Logic]:
        exact: Dict[str, Logic] = {
            "appliances having a range of rated values and which can be operated without adjustment throughout the range": self._enum("rated_value_configuration", "CONTINUOUS_RANGE"),
            "appliances having different rated values and which have to be adjusted for use at a particular value by the user or installer": self._enum("rated_value_configuration", "SELECTABLE_VALUES"),
            "if the appliance can be adjusted for different rated voltages": self._enum("rated_value_configuration", "SELECTABLE_VALUES"),
            "when symbols are used": self._bool("uses_standard_symbols"),
            "if figures are used for indicating the different positions": self._bool("uses_numeric_control_position_markings"),
            "if it is necessary to take precautions during user maintenance": self._bool("requires_user_maintenance_precautions"),
            "if it is necessary to take precautions during installation of the appliance": self._bool("requires_installation_precautions"),
            "if protective impedance is used": self._bool("has_protective_impedance"),
            "appliances incorporating heating elements": self._bool("has_heating_element"),
            "appliances incorporating motors": self._bool("has_motor"),
            "appliances incorporating a protective electronic circuit": self._bool("has_protective_electronic_circuit"),
            "if the appliance is marked with the first numeral of the ip system": self._exists("ip_rating"),
            "appliances intended to be connected to the supply mains by means of a plug": self._bool("has_plug"),
            "appliances intended to be connected to the water mains": self._bool("is_connected_to_water_mains"),
            "for remote operation": self._bool("has_remote_control"),
            "portable appliances": self._bool("is_portable"),
            "for portable appliances": self._bool("is_portable"),
            "for stationary appliances": self._bool("is_stationary"),
            "for appliances with supply cords": self._bool("has_supply_cord"),
            "for the base material of printed circuit boards": self._bool("has_pcb"),
            "for appliances that are operated while attended": self._bool("requires_attended_operation"),
            "appliances without automatic water level control": self._bool("automatic_water_level_control", False),
        }
        if text in exact:
            return exact[text]
        compound = self._parse_generic_product_scope(text)
        if compound:
            return compound
        # Generic product-category subjects are represented through the
        # registry's free-text product_type field.  The report profile uses
        # the same case-folded singular representation.
        subject = re.fullmatch(r"(?:for\s+)?(?:products?|appliances?|equipment)\s+of\s+type\s+(.+)", text)
        if subject:
            return self._leaf("product_type", "equals", self._product_type_value(subject.group(1)))
        alternatives = re.fullmatch(
            r"([a-z][a-z0-9 -]*\s+(?:products?|appliances?|machines?|equipment|tools?|devices?))"
            r"\s+(?:or|and)\s+"
            r"([a-z][a-z0-9 -]*\s+(?:products?|appliances?|machines?|equipment|tools?|devices?))",
            text,
        )
        if alternatives:
            return self._any(*[
                self._leaf("product_type", "equals", self._product_type_value(value))
                for value in alternatives.groups()
            ])
        named = re.fullmatch(r"(?:for\s+)?([a-z][a-z0-9 -]*\s+(?:products?|appliances?|machines?|equipment|tools?|devices?))", text)
        if named and not re.match(r"^(?:stationary|portable|built-in)\s+appliance$",
                                  named.group(1)):
            return self._leaf("product_type", "equals", self._product_type_value(named.group(1)))
        current = re.fullmatch(r"for appliances having a rated current (not exceeding|exceeding) 16 a", text)
        if current:
            operator = "less_than_or_equal" if current.group(1) == "not exceeding" else "greater_than"
            return self._leaf("rated_current", operator, 16)
        pollution = re.fullmatch(r"except for pollution degree ([1-4])", text)
        if pollution:
            return self._enum(
                "pollution_degree", f"POLLUTION_DEGREE_{pollution.group(1)}", "not_equals"
            )
        return None

    def _parse_generic_product_scope(self, text: str) -> Optional[Logic]:
        """Decompose a product class from independent use/construction scope.

        This parser is deliberately vocabulary-neutral: the base class remains
        canonical-classification evidence, while additional construction terms
        must resolve through the feature registry.  Free-text intended use is
        retained as its own fact and therefore remains UNKNOWN when the report
        does not explicitly establish it.
        """

        product_noun = r"(?:products?|appliances?|machines?|equipment|tools?|devices?|pumps?)"
        use_scope = re.fullmatch(
            rf"(?:for\s+)?(.+?\s+{product_noun})\s+(?:intended\s+)?for\s+use\s+in\s+(.+)",
            text,
        )
        if use_scope:
            return self._all(
                self._leaf(
                    "canonical_product_classification", "equals",
                    self._product_type_value(use_scope.group(1)),
                ),
                self._leaf("intended_use", "equals", use_scope.group(2).strip()),
            )
        construction = re.fullmatch(
            rf"(?:for\s+)?(.+?\s+{product_noun})\s+"
            r"(?:having|incorporating|with)\s+(?:an?\s+)?(.+)",
            text,
        )
        if construction:
            feature = self._boolean_alias(construction.group(2))
            if feature:
                return self._all(
                    self._leaf(
                        "canonical_product_classification", "equals",
                        self._product_type_value(construction.group(1)),
                    ),
                    self._bool(feature),
                )
        return None

    @staticmethod
    def _product_type_value(value: str) -> str:
        words = value.strip().casefold().split()
        if words and words[-1].endswith("s") and words[-1] not in {"class"}:
            words[-1] = words[-1][:-1]
        return " ".join(words)

    def _parse_real_compound_condition(self, text: str) -> Optional[Logic]:
        if re.fullmatch(r"appliances incorporating contactors or relays", text):
            return self._any(self._bool("has_contactor"), self._bool("has_relay"))
        if re.fullmatch(r"appliances incorporating voltage selector switches", text):
            return self._all(self._bool("has_voltage_selector"), self._bool("has_switch"))
        if re.fullmatch(r"if an appliance has more than one motor", text):
            return self._leaf("motor_count", "greater_than", 1)
        if re.fullmatch(r"class ii appliances intended to be permanently connected to fixed wiring", text):
            return self._all(
                self._enum("protection_class", "CLASS_II"),
                self._bool("is_permanently_connected"),
                self._bool("has_fixed_wiring_connection"),
            )
        if re.fullmatch(r"appliances intended to be permanently connected to the water mains", text):
            return self._all(
                self._bool("is_permanently_connected"),
                self._bool("is_connected_to_water_mains"),
            )
        if re.fullmatch(r"appliances intended to be permanently connected to fixed wiring", text):
            return self._all(
                self._bool("is_permanently_connected"),
                self._bool("has_fixed_wiring_connection"),
            )
        current_fixed = re.fullmatch(
            r"for appliances intended to be permanently connected to the fixed wiring and having a rated current not exceeding 16 a",
            text,
        )
        if current_fixed:
            return self._all(
                self._bool("is_permanently_connected"),
                self._bool("has_fixed_wiring_connection"),
                self._leaf("rated_current", "less_than_or_equal", 16),
            )
        if re.fullmatch(
            r"for multi-phase appliances that are supplied with a supply cord and that are intended to be permanently connected to the fixed wiring",
            text,
        ):
            return self._all(
                self._leaf("number_of_phases", "greater_than", 1),
                self._bool("has_supply_cord"),
                self._bool("is_permanently_connected"),
                self._bool("has_fixed_wiring_connection"),
            )
        if re.fullmatch(
            r"if an appliance is intended to be permanently connected to the water mains and not connected by a hose-set",
            text,
        ):
            return self._all(
                self._bool("is_permanently_connected"),
                self._bool("is_connected_to_water_mains"),
                self._bool("has_external_water_hose", False),
            )
        if re.fullmatch(r"if a stationary appliance is not fitted with a supply cord and a plug", text):
            return self._all(
                self._bool("is_stationary"),
                self._bool("has_supply_cord", False),
                self._bool("has_plug", False),
            )
        category_opening = re.fullmatch(
            r"(.+?) of the (.+?) type that are loaded from the (.+?) through an opening with a (.+)",
            text,
        )
        if category_opening:
            subject = self._boolean_alias(category_opening.group(1))
            construction = self._boolean_alias(category_opening.group(2) + " type")
            loading = self._enum_alias("loading type", category_opening.group(3))
            opening = self._boolean_alias(category_opening.group(4))
            if subject and construction and loading and opening:
                return self._all(self._bool(subject), self._bool(construction), loading, self._bool(opening))
        if re.fullmatch(r"if a removable or sliding lid is provided", text):
            return self._any(self._bool("has_removable_lid"), self._bool("has_sliding_lid"))
        if re.fullmatch(r"for lid or door interlocks", text):
            return self._any(self._bool("has_lid_interlock"), self._bool("has_door_interlock"))
        return None

    def _bool(self, field: str, value: bool = True) -> Logic:
        return self._leaf(field, "equals", value)

    def _boolean_alias(self, phrase: str) -> Optional[str]:
        """Resolve a source-defined category/feature through registry aliases only."""

        candidates = [phrase.strip()]
        words = phrase.strip().split()
        if words and words[-1].endswith("s"):
            candidates.append(" ".join([*words[:-1], words[-1][:-1]]))
        for candidate in candidates:
            matches = [feature for feature in self.registry.search_alias(candidate)
                       if feature.data_type is FeatureDataType.BOOLEAN]
            if len(matches) == 1:
                return matches[0].key
        return None

    def _enum_alias(self, feature_phrase: str, *values: str) -> Optional[Logic]:
        """Resolve source enum vocabulary without a product/category branch."""

        features = [feature for feature in self.registry.search_alias(feature_phrase)
                    if feature.data_type is FeatureDataType.ENUM]
        if len(features) != 1:
            return None
        feature = features[0]
        normalized = []
        for value in values:
            candidate = self._alias_text(value).replace(" loaded", "").upper()
            if candidate not in feature.allowed_values:
                return None
            normalized.append(self._enum(feature.key, candidate))
        return normalized[0] if len(normalized) == 1 else self._any(*normalized)

    def _enum(self, field: str, value: str, operator: str = "equals") -> Logic:
        return self._leaf(field, operator, value)

    def _exists(self, field: str) -> Logic:
        return {"field": field, "operator": "exists"}

    @staticmethod
    def _leaf(field: str, operator: str, value: Any) -> Logic:
        return {"field": field, "operator": operator, "value": value}

    @staticmethod
    def _all(*rules: Logic) -> Logic:
        return {"all": list(rules)}

    @staticmethod
    def _any(*rules: Logic) -> Logic:
        return {"any": list(rules)}

    def _validate_logic(self, logic: Any) -> bool:
        if not isinstance(logic, dict) or not logic or not set(logic).issubset(self._LOGIC_KEYS):
            return False
        if "all" in logic or "any" in logic:
            if set(logic) not in ({"all"}, {"any"}):
                return False
            key = "all" if "all" in logic else "any"
            children = logic[key]
            return isinstance(children, list) and bool(children) and all(
                self._validate_logic(child) for child in children
            )
        if "not" in logic:
            return set(logic) == {"not"} and self._validate_logic(logic["not"])
        keys = set(logic)
        if not {"field", "operator"}.issubset(keys):
            return False
        if keys not in ({"field", "operator"}, {"field", "operator", "value"}):
            return False
        field = logic["field"]
        operator = logic["operator"]
        if not isinstance(field, str):
            return False
        if operator not in self.SUPPORTED_OPERATORS:
            return False
        if field == "canonical_product_classification":
            if operator == "exists":
                return keys == {"field", "operator"}
            value = logic.get("value")
            if operator in {"in", "not_in"}:
                return isinstance(value, list) and bool(value) and all(
                    isinstance(item, str) and bool(item.strip()) for item in value
                )
            return operator in {"equals", "not_equals"} and isinstance(value, str) and bool(value.strip())
        if not self.registry.exists(field):
            return False
        if operator == "exists":
            return keys == {"field", "operator"}
        if "value" not in logic:
            return False
        value = logic["value"]
        feature = self.registry.get(field)
        if operator in {"in", "not_in"}:
            return isinstance(value, list) and bool(value) and all(
                self.registry.validate_feature_value(field, item) for item in value
            )
        if operator in {"greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"}:
            return feature.data_type in {
                FeatureDataType.INTEGER, FeatureDataType.NUMBER, FeatureDataType.MEASUREMENT
            } and self.registry.validate_feature_value(field, value)
        return self.registry.validate_feature_value(field, value)

    def _collect_fields(self, logic: Any) -> Set[str]:
        """Collect canonical fields from already validated or diagnostic logic."""

        if not isinstance(logic, dict):
            return set()
        if isinstance(logic.get("field"), str):
            return {logic["field"]}
        fields: Set[str] = set()
        for key in ("all", "any"):
            for child in logic.get(key, []) if isinstance(logic.get(key), list) else []:
                fields.update(self._collect_fields(child))
        if "not" in logic:
            fields.update(self._collect_fields(logic["not"]))
        return fields


__all__ = [
    "ApplicabilityNormalizationDiagnostic",
    "GenericIECApplicabilityNormalizer",
]
