"""Deterministic requirement extraction from direct IEC clause text."""

from __future__ import annotations

import copy
import re
from typing import Dict, List, Optional, Sequence

from iec_parser.generic_iec_kb_models import (
    ApplicabilityRule,
    ApplicabilityEffect,
    ApplicabilityStatus,
    Clause,
    Requirement,
    RequirementSemanticType,
    RequirementType,
)
from iec_parser.generic_iec_structural_parser import StructuralBlock


class GenericIECRequirementParser:
    """Populate requirements in a deep copy of an existing Clause tree."""

    _NORMATIVE_RE = re.compile(
        r"\b(?:shall(?:\s+not)?|must|is\s+required\s+to|are\s+required\s+to|"
        r"is\s+to\s+be|are\s+to\s+be|is\s+subjected\s+to|are\s+subjected\s+to|"
        r"compliance\s+is\s+checked\s+by|(?:the\s+)?test\s+is\s+carried\s+out|"
        r"does\s+not\s+apply|(?:is|are)\s+not\s+applicable|"
        r"(?:is|are|need)\s+not\s+(?:be\s+)?subjected\s+to|"
        r"(?:is|are)\s+not\s+allowed|applies\s+only\s+when|"
        r"(?:is|are)\s+applicable|"
        r"(?:is|are)\s+(?:(?:also|then|subsequently)\s+)?(?:operated|placed|positioned|held|maintained|supplied|"
        r"connected|disconnected|reduced|decreased|increased|measured|checked|"
        r"considered|tested|marked|constructed|installed|used|allowed|prevented)|"
        r"may\s+(?:be\s+)?(?:used|operated|provided|connected|installed|allowed))\b",
        re.IGNORECASE,
    )
    _TEST_RE = re.compile(
        r"\b(?:compliance\s+is\s+checked|checked\s+by|test\s+is\s+carried\s+out|"
        r"is\s+tested|are\s+tested|is\s+subjected\s+to|are\s+subjected\s+to|"
        r"measurement\s+is\s+made)\b",
        re.IGNORECASE,
    )
    _EXCLUDED_PREFIX_RE = re.compile(
        r"^(?:NOTE(?:\s+\d+)?\b|EXAMPLE(?:\s+\d+)?\b|Table\s+[A-Z0-9.]+\b|"
        r"Figure\s+[A-Z0-9.]+\b|Key\b|Legend\b)",
        re.IGNORECASE,
    )
    _IMPERATIVE_RE = re.compile(
        r"^(?:(?:\d+|[a-z])\)\s*)?(?:always\s+|never\s+)?"
        r"(?:wear|use|brace|hold|keep|ensure|disconnect|apply|start|operate|"
        r"discharge|recharge|charge|cool|stabilize|maintain|measure|determine|do\s+not)\b",
        re.IGNORECASE,
    )

    def parse(
        self,
        clauses: Sequence[Clause],
        structural_blocks: Optional[Sequence[StructuralBlock]] = None,
    ) -> List[Clause]:
        """Return a populated deep copy, optionally using structural provenance."""

        if clauses is None:
            raise TypeError("clauses must be a sequence of Clause objects")
        if isinstance(clauses, (str, bytes)):
            raise TypeError("clauses must be a sequence of Clause objects")
        if any(not isinstance(clause, Clause) for clause in clauses):
            raise TypeError("Every input item must be a Clause")
        contexts = self._build_context_map(structural_blocks)

        copied = copy.deepcopy(list(clauses))
        for clause in copied:
            self._populate_clause_tree(clause, contexts)
        return copied

    @staticmethod
    def _build_context_map(
        structural_blocks: Optional[Sequence[StructuralBlock]],
    ) -> Dict[str, str]:
        if structural_blocks is None:
            return {}
        if isinstance(structural_blocks, (str, bytes)) or any(
            not isinstance(block, StructuralBlock) for block in structural_blocks
        ):
            raise TypeError("structural_blocks must contain StructuralBlock objects")
        return {
            block.block_id: block.semantic_context
            for block in structural_blocks
            if block.block_type in {"CLAUSE", "SUBCLAUSE"}
        }

    def _populate_clause_tree(
        self, clause: Clause, contexts: Dict[str, str]
    ) -> None:
        raw_text = clause.source.raw_text or ""
        if contexts.get(clause.clause_id) == "DEFINITION":
            candidates: List[str] = []
        else:
            candidates = self._split_requirement_candidates(
                self._remove_heading(raw_text, clause.clause_id)
            )
        clause.requirements = [
            self._build_requirement(clause.clause_id, index, text)
            for index, text in enumerate(candidates, start=1)
        ]
        for child in clause.children:
            self._populate_clause_tree(child, contexts)

    @classmethod
    def _remove_heading(cls, raw_text: str, clause_id: str) -> str:
        normalized_lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        # Multi-column extraction can place a short heading title immediately
        # before its isolated clause number. Remove both structural lines while
        # preserving the following clause body.
        if (len(normalized_lines) > 1
                and normalized_lines[1].strip() == clause_id
                and cls._looks_like_non_normative_title(normalized_lines[0])):
            return "\n".join(normalized_lines[2:])
        if normalized_lines:
            normalized_lines[0] = re.sub(
                r"^\s*" + re.escape(clause_id) + r"(?:\s+|$)",
                "",
                normalized_lines[0],
                count=1,
            )
        return "\n".join(normalized_lines)

    @classmethod
    def _looks_like_non_normative_title(cls, text: str) -> bool:
        value = re.sub(r"\s+", " ", text).strip()
        return bool(value and len(value.split()) <= 18
                    and not cls._is_normative_statement(value)
                    and not cls._IMPERATIVE_RE.match(value))

    @classmethod
    def _split_requirement_candidates(cls, text: str) -> List[str]:
        if not text.strip():
            return []
        text = cls._truncate_at_embedded_heading(text)
        text = cls._remove_layout_chrome(text)
        text = cls._remove_note_example_blocks(text)
        list_items = cls._normative_list_items(text)
        merged = cls._merge_continuation_lines(text)
        sentences = re.split(
            r"(?<=[.!?])\s+(?=(?:[A-Z(]|For\b|If\b|When\b|Where\b))",
            merged,
        )
        requirements: List[str] = []
        for sentence in sentences:
            candidate = re.sub(r"\s+", " ", sentence).strip()
            if not candidate or cls._is_excluded_material(candidate):
                continue
            if cls._is_normative_statement(candidate) or cls._IMPERATIVE_RE.match(candidate):
                requirements.append(candidate)
        for item in list_items:
            if item not in requirements:
                requirements.append(item)
        return cls._remove_composite_duplicates(requirements)

    @staticmethod
    def _remove_layout_chrome(text: str) -> str:
        """Remove generic repeated publication chrome from requirement text."""

        patterns = (
            r"\blicen[cs]ed\s+by\b", r"\bsingle[- ]user\s+licen[cs]e\b",
            r"\bcopying\s+and\s+networking\s+prohibited\b", r"\bdownloaded\s*:",
            r"^\s*[–—-]?\s*\d+\s*[–—-]?\s*$", r"\bpage\s+\d+\s+of\s+\d+\b",
            r"\bhttps?://|\bwww\.|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
        )
        return "\n".join(line for line in text.splitlines()
                         if not any(re.search(pattern, line, re.I) for pattern in patterns))

    @classmethod
    def _remove_composite_duplicates(cls, requirements: List[str]) -> List[str]:
        """Remove overlap while retaining any independent normative prefix."""

        normalized = [re.sub(r"\W+", " ", item.casefold()).strip() for item in requirements]
        output: List[str] = []
        for index, item in enumerate(requirements):
            contained = [other for other_index, other in enumerate(normalized)
                         if other_index != index and len(other) >= 24 and other in normalized[index]]
            if len(contained) >= 2:
                continue
            if len(contained) == 1:
                marker = normalized[index].find(contained[0])
                prefix_words = normalized[index][:marker].strip()
                if marker > 0 and len(prefix_words) >= 24:
                    other_index = normalized.index(contained[0])
                    raw_marker = item.casefold().find(requirements[other_index].casefold())
                    prefix = item[:raw_marker].strip(" \t\r\n;:,.—–-") if raw_marker > 0 else ""
                    if prefix and (cls._is_normative_statement(prefix)
                                   or cls._IMPERATIVE_RE.match(prefix)):
                        output.append(prefix)
                continue
            output.append(item)
        return output

    @classmethod
    def _normative_list_items(cls, text: str) -> List[str]:
        """Retain independently normative numbered/lettered list items."""

        items: List[str] = []
        current: List[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if re.match(r"^(?:\d+|[a-z])\)\s+", stripped, re.IGNORECASE):
                if current:
                    candidate = re.sub(r"\s+", " ", " ".join(current)).strip()
                    if cls._is_normative_statement(candidate) or cls._IMPERATIVE_RE.match(candidate):
                        items.append(candidate)
                current = [stripped]
            elif current and stripped:
                current.append(stripped)
        if current:
            candidate = re.sub(r"\s+", " ", " ".join(current)).strip()
            if cls._is_normative_statement(candidate) or cls._IMPERATIVE_RE.match(candidate):
                items.append(candidate)
        return items

    @staticmethod
    def _truncate_at_embedded_heading(text: str) -> str:
        lines=text.splitlines()
        for index, line in enumerate(lines[:-1]):
            if (GenericIECRequirementParser._looks_like_non_normative_title(line)
                    and re.fullmatch(r"\s*\d+(?:\.\d+)+\s*", lines[index + 1])):
                return "\n".join(lines[:index])
        for index,line in enumerate(lines[1:],1):
            if re.match(r"^\s*\d+(?:\.\d+)+\s+(?:[A-Z(]|[a-z]\))",line):
                return "\n".join(lines[:index])
        return text

    @staticmethod
    def _remove_note_example_blocks(text: str) -> str:
        output=[]; skipping=False
        for line in text.splitlines():
            if re.match(r"^\s*(?:NOTE|EXAMPLE)(?:\s+\d+)?\b",line,re.I):
                skipping=True;continue
            if skipping and not re.match(r"^\s*(?:(?:\d+|[a-z])\)\s+|\d+(?:\.\d+)+\s+)",line,re.I):
                # A NOTE often has no blank-line boundary in extracted PDF
                # text.  Resume at the first independently normative line;
                # otherwise valid requirements following a note disappear.
                if not (GenericIECRequirementParser._is_normative_statement(line)
                        or GenericIECRequirementParser._IMPERATIVE_RE.match(line)):
                    continue
            skipping=False;output.append(line)
        return "\n".join(output)

    @staticmethod
    def _merge_continuation_lines(text: str) -> str:
        lines = [line.strip() for line in text.split("\n")]
        merged: List[str] = []
        for line in lines:
            if not line:
                if merged and merged[-1] != "":
                    merged.append("")
                continue
            if re.match(r"^(?:[-–—•]|[a-z]\)|\d+\))\s+", line):
                merged.append(line)
            else:
                merged.append(line)
        return re.sub(r"\s*\n\s*", " ", "\n".join(merged)).strip()

    @classmethod
    def _is_excluded_material(cls, text: str) -> bool:
        return bool(cls._EXCLUDED_PREFIX_RE.match(text.lstrip()))

    @classmethod
    def _is_normative_statement(cls, text: str) -> bool:
        return bool(cls._NORMATIVE_RE.search(text))

    def _build_requirement(
        self, clause_id: str, sequence: int, text: str
    ) -> Requirement:
        semantic_type = self._semantic_type(text)
        condition_text = self._extract_condition_text(text)
        if semantic_type is RequirementSemanticType.EXCLUSION and condition_text:
            semantic_type = RequirementSemanticType.CONDITIONAL_EXCLUSION
        status = (
            ApplicabilityStatus.UNRESOLVED
            if condition_text
            else ApplicabilityStatus.ALWAYS
        )
        requirement_type = self._classify_requirement_type(text, condition_text)
        test_method = None
        if requirement_type is RequirementType.TEST:
            test_method = {"type": "RAW_TEST_METHOD", "text": text}
        return Requirement(
            requirement_id=f"{clause_id}-R{sequence}",
            text=text,
            requirement_type=requirement_type,
            normative=True,
            condition_text=condition_text,
            applicability=ApplicabilityRule(
                status=status,
                condition_text=condition_text,
                logic=None,
                effect=(ApplicabilityEffect.DOES_NOT_APPLY
                        if semantic_type in {RequirementSemanticType.EXCLUSION,
                                             RequirementSemanticType.CONDITIONAL_EXCLUSION}
                        else ApplicabilityEffect.APPLIES),
            ),
            test_method=test_method,
            semantic_type=semantic_type,
        )

    @staticmethod
    def _semantic_type(text: str) -> RequirementSemanticType:
        value = re.sub(r"^(?:Addition|Modification|Replacement)\s*:\s*", "", text,
                       flags=re.IGNORECASE)
        excluded = re.search(
            r"\b(?:(?:is|are)\s+not\s+applicable|does\s+not\s+apply|"
            r"(?:is|are|need)\s+not\s+(?:be\s+)?subjected\s+to\s+(?:(?:the|this)\s+)?test)\b",
            value, re.IGNORECASE)
        if excluded:
            conditional = bool(re.search(r"\b(?:if|when|unless|for)\b", value, re.IGNORECASE))
            return (RequirementSemanticType.CONDITIONAL_EXCLUSION if conditional
                    else RequirementSemanticType.EXCLUSION)
        if re.search(r"\b(?:shall|must)\s+not\b|\b(?:is|are)\s+not\s+allowed\b",
                     value, re.IGNORECASE):
            return RequirementSemanticType.PROHIBITION
        return RequirementSemanticType.REQUIREMENT

    @staticmethod
    def _extract_condition_text(text: str) -> Optional[str]:
        text = re.sub(r"^(?:Addition|Modification|Replacement)\s*:\s*", "", text,
                      flags=re.IGNORECASE)
        when_exclusion = re.search(
            r"\b(?:is|are)\s+not\s+applicable\s+(when|if)\s+(.+?)(?:[.;]|$)",
            text, re.IGNORECASE)
        if when_exclusion:
            return f"{when_exclusion.group(1)} {when_exclusion.group(2)}".strip()
        if re.fullmatch(r"(?:This|The)\s+(?:requirement|test|subclause)\s+"
                        r"(?:is|are)\s+not\s+applicable\.?", text, re.IGNORECASE):
            return None
        # Leading ``for`` phrases that name a purpose or desired outcome do
        # not restrict the products to which the requirement applies.
        purpose = re.match(
            r"^For\s+(?:optimum|optimal|improved|better|correct|safe|safer|"
            r"reliable|continued|long(?:er)?|maximum|minimum)?\s*"
            r"(?:service\s+life|safety|operation|performance|information|"
            r"guidance|reliability|protection|convenience)\s*[,;]",
            text, re.IGNORECASE,
        )
        if purpose:
            return None
        leading = re.match(
            r"^((?:If|When|Where|For|Unless|Except\s+when)\b[^,.;]*)(?:,|;)",
            text,
            re.IGNORECASE,
        )
        if leading:
            return leading.group(1).strip()

        exclusion = re.match(
            r"^((?:This|The) requirement(?:\s+also)? does not apply to\b[^.;]*)", text, re.IGNORECASE
        )
        if exclusion:
            return exclusion.group(1).strip()

        trailing_exclusion = re.match(
            r"^(.+?)\s+(?:is|are|need)\s+not\s+(?:be\s+)?subjected\s+to\s+(?:(?:the|this)\s+)?test\b",
            text, re.IGNORECASE)
        if trailing_exclusion:
            return trailing_exclusion.group(1).strip()
        trailing_not_applicable = re.match(
            r"^(.+?)\s+(?:is|are)\s+not\s+applicable\b", text, re.IGNORECASE)
        if trailing_not_applicable:
            return trailing_not_applicable.group(1).strip()
        applies_only = re.search(r"\bapplies\s+only\s+when\s+(.+?)(?:[.;]|$)", text,
                                 re.IGNORECASE)
        if applies_only:
            return f"when {applies_only.group(1)}".strip()

        # Product vocabulary is intentionally absent here.  The extractor's
        # generic modal-subject grammar performs the authoritative recovery;
        # using it here prevents an explicit scope from being initialized as
        # ALWAYS before that enrichment stage.
        from iec_parser.generic_iec_applicability_extractor import (
            GenericIECApplicabilityExtractor,
        )
        condition, status, _ = GenericIECApplicabilityExtractor.discover_scope(text)
        return condition if status is not ApplicabilityStatus.ALWAYS else None

    @classmethod
    def _classify_requirement_type(
        cls, text: str, condition_text: Optional[str]
    ) -> RequirementType:
        lowered = text.lower()
        if cls._TEST_RE.search(text):
            return RequirementType.TEST
        if re.search(r"\b(?:marked|marking|label(?:led)?|symbol|identification)\b", lowered):
            return RequirementType.MARKING
        if re.search(
            r"\b(?:instructions?|instruction\s+sheet|user\s+manual|installation\s+manual)\b",
            lowered,
        ):
            return RequirementType.INSTRUCTION
        if re.search(
            r"\b(?:shall\s+be\s+constructed|construction|enclosure|fixing|"
            r"wiring\s+arrangement|mechanically\s+secured)\b",
            lowered,
        ):
            return RequirementType.CONSTRUCTION
        has_number = bool(re.search(r"\d", text))
        has_limit = bool(
            re.search(
                r"\b(?:not\s+exceed|at\s+least|not\s+less\s+than|not\s+more\s+than|"
                r"maximum|minimum|between|within)\b|[<>≤≥±]",
                lowered,
            )
        )
        if has_number and has_limit:
            return RequirementType.LIMIT
        if re.search(r"\b(?:safety|safe|protect(?:ion|ed)?|hazard|injury)\b", lowered):
            return RequirementType.SAFETY
        if condition_text:
            return RequirementType.CONDITIONAL
        return RequirementType.GENERAL
