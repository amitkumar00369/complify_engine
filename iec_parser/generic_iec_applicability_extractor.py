"""Raw, non-canonical applicability extraction for generic IEC requirements."""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from iec_parser.generic_iec_kb_models import (
    ApplicabilityRule,
    ApplicabilityEffect,
    ApplicabilityStatus,
    Clause,
    Requirement,
    RequirementSemanticType,
)


class GenericIECApplicabilityExtractor:
    """Enrich requirement copies with raw applicability condition wording."""

    _EXCLUDED_PREFIX_RE = re.compile(r"^(?:NOTE|EXAMPLE)(?:\s+\d+)?\b", re.IGNORECASE)
    _NEGATIVE_RE = re.compile(
        r"^((?:(?:This|The)\s+(?:requirement|subclause)\s+does\s+not\s+apply\s+to"
        r"\b[^.;]*|(?:This|The)\s+(?:requirement|subclause)\s+does\s+not\s+apply\s+if"
        r"\b[^.]*|Except\s+for\b[^,.;]*))",
        re.IGNORECASE,
    )
    _LEADING_RE = re.compile(
        r"^((?:For|If|Unless|When|Where|Only\s+for|In\s+appliances\s+where|"
        r"In\s+the\s+case\s+of|Except\s+when)\b[^,;]*)(?:,|;)",
        re.IGNORECASE,
    )
    _MODAL_BOUNDARY_RE = re.compile(
        r"\s+(?:shall|must|is\s+required\s+to|are\s+required\s+to|is\s+to\s+be|"
        r"are\s+to\s+be|is\s+subjected\s+to|are\s+subjected\s+to|"
        r"(?:is|are)\s+(?:(?:also|then|subsequently)\s+)?(?:operated|placed|"
        r"positioned|held|supplied|considered)|"
        r"(?:is|are)\s+not\s+allowed|"
        r"(?:is|are)\s+applicable|"
        r"may\s+(?:be\s+)?(?:used|operated|provided|installed|allowed))\b",
        re.IGNORECASE,
    )
    _GENERIC_BARE_SUBJECTS = {
        "the appliance", "the appliances", "an appliance", "appliances",
        "the product", "the products", "products", "equipment", "the equipment",
        "the part", "the parts", "parts", "the component", "the components",
        "components", "the circuit", "the circuits", "circuits", "the value",
        "the current", "the voltage", "the temperature", "the force", "the test",
    }
    _QUALIFIER_RE = re.compile(
        r"\b(?:class\s+[0-9a-z]+|hand[- ]held|stationary|portable|built[- ]in|"
        r"incorporating|having|provided\s+with|intended\s+(?:to|for)|without|"
        r"fitted\s+with|designed\s+for|operating\s+at|for\s+(?:indoor|outdoor)|"
        r"of\s+the\s+.+?\s+type|other\s+than)\b", re.IGNORECASE,
    )
    _TEST_STATE_RE = re.compile(
        r"^(?:(?:When|If)\s+(?:measured|tested|testing|(?:the\s+)?[^,;]*\btest\s+is\s+carried\s+out|"
        r"the\s+current\s+is\s+measured|the\s+current\s+measured|"
        r"the\s+appliance\s+has\s+cooled|the\s+specimen\s+does\s+not\s+withstand\s+the\s+test|"
        r"there\s+is\s+doubt\s+as\s+to\s+whether\s+a\s+defect\s+has\s+occurred|"
        r"steady\s+conditions\s+are\s+established|the\s+appliance\s+is\s+supplied\s+at|"
        r"the\s+appliance\s+is\s+operated|the\s+temperature\s+is)|"
        r"For\s+(?:the|this)\s+(?:test|measurement)|For\s+testing)\b",
        re.IGNORECASE,
    )
    _PRODUCT_SIGNAL_RE = re.compile(
        r"\b(?:product|products|appliance|appliances|part|parts|circuit|circuits|class\s+[0-9A-Za-z]+|"
        r"stationary|portable|built-in|equipment|"
        r"incorporat(?:e|es|ing)|having|provided\s+with|fitted\s+with|intended|"
        r"installation|outdoor|indoor|component|interlocks?|symbols?|remote\s+operation|"
        r"attachment|insulation|sleeving)\b",
        re.IGNORECASE,
    )
    _PURPOSE_CONTEXT_RE = re.compile(
        r"^For\s+(?:optimum|optimal|improved|better|correct|safe|safer|"
        r"reliable|continued|long(?:er)?|maximum|minimum)?\s*"
        r"(?:service\s+life|safety|operation|performance|information|"
        r"guidance|reliability|protection|convenience)\b",
        re.IGNORECASE,
    )

    def parse(self, clauses: Sequence[Clause]) -> List[Clause]:
        """Return a deep-copied hierarchy with raw applicability metadata refined."""

        if clauses is None or isinstance(clauses, (str, bytes)):
            raise TypeError("clauses must be a sequence of Clause objects")
        if any(not isinstance(clause, Clause) for clause in clauses):
            raise TypeError("Every input item must be a Clause")
        copied = copy.deepcopy(list(clauses))
        for clause in copied:
            self._process_clause_recursive(clause)
        return copied

    def _process_clause_recursive(self, clause: Clause) -> None:
        inherited: Optional[Dict[str, Any]] = None
        inherited_from: Optional[str] = None
        for requirement in clause.requirements:
            condition, status, scope = self.discover_scope(requirement.text)
            if scope is None and inherited is not None and self._inherits_preceding_scope(
                    requirement.text):
                scope = copy.deepcopy(inherited)
                scope["inherited"] = True
                scope["inheritance_reason"] = "STRUCTURALLY_DEPENDENT_FOLLOWING_REQUIREMENT"
                scope["inherited_from_requirement_id"] = inherited_from
                condition = str(scope["subject"]["source_text"])
                status = ApplicabilityStatus.UNRESOLVED
            self._process_requirement(clause.clause_id, requirement, condition, status, scope)
            if scope is not None:
                inherited = copy.deepcopy(scope)
                inherited_from = requirement.requirement_id
            elif not self._inherits_preceding_scope(requirement.text):
                inherited = None
                inherited_from = None
        for child in clause.children:
            self._process_clause_recursive(child)

    def _process_requirement(
        self, clause_id: str, requirement: Requirement, condition: Optional[str],
        status: ApplicabilityStatus, scope: Optional[Dict[str, Any]],
    ) -> None:
        if condition is None and requirement.condition_text:
            condition = requirement.condition_text
            status = ApplicabilityStatus.UNRESOLVED
        exclusion = requirement.semantic_type in {
            RequirementSemanticType.EXCLUSION,
            RequirementSemanticType.CONDITIONAL_EXCLUSION,
        } and self._exclusion_applies_to_discovered_scope(requirement.text, scope)
        requirement.condition_text = condition
        if scope is not None:
            scope = copy.deepcopy(scope)
            scope["provenance"] = {
                "clause_id": clause_id,
                "requirement_id": requirement.requirement_id,
                "source_text": requirement.text,
                "parser_stage": "APPLICABILITY_EXTRACTION",
            }
        requirement.applicability = ApplicabilityRule(
            status=status,
            condition_text=condition,
            logic=None,
            effect=(ApplicabilityEffect.DOES_NOT_APPLY if exclusion
                    else ApplicabilityEffect.APPLIES),
            scope=scope,
        )

    @staticmethod
    def _exclusion_applies_to_discovered_scope(
        text: str, scope: Optional[Dict[str, Any]],
    ) -> bool:
        """Associate an exclusion only with the condition it actually governs.

        A requirement may start with a positive condition and contain a later,
        independent ``does not apply`` sentence.  That trailing exclusion must
        not invert the leading condition.  Negative grammar, or a negative
        applicability phrase before the first normative modal, does govern the
        discovered condition.
        """

        grammar = str((scope or {}).get("grammar") or "").upper()
        if grammar == "NEGATIVE":
            return True
        if not scope:
            return True
        # This disambiguation is intentionally limited to an explicit leading
        # condition.  Normative-subject and inherited scopes may themselves be
        # the target of an exclusion; treating every later negative phrase as
        # independent would silently turn those conditional requirements into
        # unconditional ones.
        if grammar != "LEADING_CONDITION":
            return True
        negative = re.search(
            r"\b(?:does\s+not\s+apply|do\s+not\s+apply|except\s+(?:for|when|where))\b",
            text or "", re.I,
        )
        if not negative:
            return False
        modal = re.search(r"\b(?:shall|must)\b", text or "", re.I)
        return modal is None or negative.start() < modal.start()

    @classmethod
    def discover_scope(
        cls, text: str
    ) -> Tuple[Optional[str], ApplicabilityStatus, Optional[Dict[str, Any]]]:
        """Recover one source-backed applicability subject without product vocabulary."""

        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized or cls._EXCLUDED_PREFIX_RE.match(normalized):
            return None, ApplicabilityStatus.ALWAYS, None
        analysis_text = re.sub(
            r"^(?:Addition|Modification|Replacement)\s*:\s*",
            "",
            normalized,
            count=1,
            flags=re.IGNORECASE,
        )

        negative = cls._NEGATIVE_RE.match(analysis_text)
        if negative:
            condition = cls._clean_condition(negative.group(1))
            subject = re.sub(
                r"^(?:(?:This|The)\s+(?:requirement|subclause)(?:\s+also)?\s+does\s+not\s+apply\s+to|"
                r"Except\s+for)\s+", "", condition, flags=re.I,
            )
            return condition, ApplicabilityStatus.UNRESOLVED, cls._scope(subject, condition, "NEGATIVE")

        if cls._PURPOSE_CONTEXT_RE.match(analysis_text):
            return None, ApplicabilityStatus.ALWAYS, None

        leading = cls._LEADING_RE.match(analysis_text)
        if leading:
            condition = cls._clean_condition(leading.group(1))
            if cls._is_test_state_condition(condition):
                return None, ApplicabilityStatus.ALWAYS, None
            subject = re.sub(
                r"^(?:For|If|Unless|When|Where|Only\s+for|In\s+the\s+case\s+of|"
                r"In\s+appliances\s+where|Except\s+when)\s+", "", condition,
                flags=re.I,
            )
            ambiguous_where = condition.casefold().startswith("where ") and not cls._is_applicability_condition(condition)
            status = (ApplicabilityStatus.NEEDS_REVIEW if ambiguous_where
                      else ApplicabilityStatus.UNRESOLVED)
            return condition, status, cls._scope(subject, condition, "LEADING_CONDITION")

        instruction = re.match(
            r"^(?:The\s+)?instructions?\s+for\s+(.+?)\s+(?:shall|must)\b",
            analysis_text, re.I,
        )
        if instruction:
            subject = cls._clean_condition(instruction.group(1))
            return subject, ApplicabilityStatus.UNRESOLVED, cls._scope(
                subject, subject, "OWNED_DOCUMENT_SUBJECT"
            )

        boundary = cls._MODAL_BOUNDARY_RE.search(analysis_text)
        if boundary:
            subject = cls._clean_condition(analysis_text[:boundary.start()])
            if cls._is_scoped_subject(subject):
                return subject, ApplicabilityStatus.UNRESOLVED, cls._scope(
                    subject, subject, "NORMATIVE_SUBJECT"
                )

        return None, ApplicabilityStatus.ALWAYS, None

    def _detect_condition(self, text: str) -> Tuple[Optional[str], ApplicabilityStatus]:
        condition, status, _ = self.discover_scope(text)
        return condition, status

    @classmethod
    def _scope(cls, subject: str, source_text: str, grammar: str) -> Dict[str, Any]:
        normalized = cls._normalized_subject(subject)
        alternatives = [cls._normalized_subject(x) for x in re.split(r"\s+(?:or|and/or)\s+", subject, flags=re.I)]
        alternatives = [x for x in alternatives if x]
        kind = cls._subject_kind(subject)
        return {
            "mode": "CONDITIONAL",
            "subject": {
                "kind": kind,
                "source_text": subject,
                "normalized_term": normalized,
                "alternatives": alternatives if len(alternatives) > 1 else [],
                "source": "STANDARD_TEXT",
            },
            "predicate_hint": {
                "fact_key": "product_type" if kind in {"PRODUCT_TYPE", "COMPONENT"} else None,
                "operator": "IN" if len(alternatives) > 1 else "IS",
            },
            "grammar": grammar,
            "inherited": False,
        }

    @classmethod
    def _is_scoped_subject(cls, subject: str) -> bool:
        value = cls._clean_condition(subject)
        folded = value.casefold()
        if folded in cls._GENERIC_BARE_SUBJECTS or not value:
            return False
        if cls._QUALIFIER_RE.search(value):
            return True
        if re.search(r"\bthat\b", value, re.I) or re.match(r"^Each\s+\w+", value, re.I):
            return True
        if re.match(r"^(?:the\s+)?(?:instructions?|parts?|components?|fittings?)\s+(?:for|of)\s+", value, re.I):
            return True
        # A multi-word plural noun phrase before a normative modal is a
        # standard-defined subject.  Its vocabulary comes from the supplied
        # standard, not a production product list.
        words = re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)?", value)
        return len(words) >= 2 and bool(re.search(r"s(?:\s+and\s+.+s)?$", folded))

    @classmethod
    def _subject_kind(cls, subject: str) -> str:
        value = subject.casefold()
        if re.search(r"\bclass\s+[0-9a-z]+\b", value):
            return "ELECTRICAL_CLASS"
        if re.search(r"\b(?:having|provided\s+with|incorporating|fitted\s+with|without)\b", value):
            return "FEATURE"
        if re.search(r"\b(?:stationary|portable|built[- ]in|hand[- ]held|installed|installation)\b", value):
            return "CONSTRUCTION"
        if re.search(r"\b(?:outdoor|indoor|environment|atmosphere)\b", value):
            return "ENVIRONMENT"
        if re.match(r"^(?:the\s+)?(?:parts?|components?|fittings?)\b", value):
            return "COMPONENT"
        return "PRODUCT_TYPE"

    @staticmethod
    def _normalized_subject(subject: str) -> str:
        value = re.sub(r"^(?:the\s+)?(?:instructions?\s+for\s+)", "", subject, flags=re.I)
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

    @staticmethod
    def _inherits_preceding_scope(text: str) -> bool:
        value = re.sub(r"^(?:Addition|Modification|Replacement)\s*:\s*", "", text,
                       flags=re.I).strip()
        return bool(re.match(
            r"^(?:Compliance\s+is\s+checked|The\s+(?:appliance|appliances|tool|tools|"
            r"part|parts|component|components|fitting|fittings|voltage|current)\b|"
            r"The\s+\w+\b|Each\s+\w+\b|Repetition\s+of\b)", value, re.I,
        ))

    @classmethod
    def _is_test_state_condition(cls, condition: str) -> bool:
        return bool(cls._TEST_STATE_RE.match(condition))

    @classmethod
    def _is_applicability_condition(cls, condition: str) -> bool:
        if condition.lower().startswith(("if ", "unless ", "except ")):
            return True
        return bool(cls._PRODUCT_SIGNAL_RE.search(condition))

    @staticmethod
    def _clean_condition(condition: str) -> str:
        return re.sub(r"\s+", " ", condition).strip().rstrip(" .;")
