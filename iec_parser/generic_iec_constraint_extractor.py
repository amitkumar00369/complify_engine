"""Deterministic extraction of technical constraints from IEC requirements."""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from iec_parser.generic_iec_kb_models import (
    Clause,
    ConstraintStatus,
    ConstraintType,
    Requirement,
    RequirementType,
    TechnicalConstraint,
)


class GenericIECTechnicalConstraintExtractor:
    """Populate technical constraints without evaluating product compliance."""

    _NUMBER = r"[+-]?\d+(?:[\s\u00a0]\d{3})*(?:[.,]\d+)?"
    _UNIT = (
        r"mA/kW|mL/min|ml/min|L/min|l/min|r/min|N·m|Nm|mm²|mm2|"
        r"MΩ|kΩ|Ω|µC|uC|mJ|mA|mV|kV|kW|m/s|Hz|°C|mm|cm|cycles|min|[AVWJKkmsNh%]"
    )
    _COMPARATORS: Tuple[Tuple[str, str], ...] = (
        # Longest semantic forms must precede their shorter constituents.
        (r"up\s+to\s+and\s+including", "less_than_or_equal"),
        (r"equal\s+to\s+or\s+greater\s+than", "greater_than_or_equal"),
        (r"shall\s+not\s+exceed", "less_than_or_equal"),
        (r"shall\s+not\s+be\s+less\s+than", "greater_than_or_equal"),
        (r"does\s+not\s+exceed", "less_than_or_equal"),
        (r"shall\s+be\s+not\s+greater\s+than", "less_than_or_equal"),
        (r"shall\s+be\s+no\s+greater\s+than", "less_than_or_equal"),
        (r"shall\s+be\s+no\s+higher\s+than", "less_than_or_equal"),
        (r"shall\s+be\s+less\s+than", "less_than"),
        (r"shall\s+be\s+not\s+less\s+than", "greater_than_or_equal"),
        (r"shall\s+be\s+at\s+least", "greater_than_or_equal"),
        (r"shall\s+be\s+greater\s+than", "greater_than"),
        (r"shall\s+be\s+more\s+than", "greater_than"),
        (r"shall\s+be\s+equal\s+to", "equals"),
        (r"no\s+higher\s+than", "less_than_or_equal"),
        (r"no\s+lower\s+than", "greater_than_or_equal"),
        (r"not\s+greater\s+than", "less_than_or_equal"),
        (r"not\s+exceeding", "less_than_or_equal"),
        (r"not\s+more\s+than", "less_than_or_equal"),
        (r"no\s+more\s+than", "less_than_or_equal"),
        (r"no\s+less\s+than", "greater_than_or_equal"),
        (r"not\s+less\s+than", "greater_than_or_equal"),
        (r"greater\s+than", "greater_than"),
        (r"more\s+than", "greater_than"),
        (r"exceeding", "greater_than"),
        (r"exceeds", "greater_than"),
        (r"at\s+least", "greater_than_or_equal"),
        (r"less\s+than", "less_than"),
        (r"below", "less_than"),
        (r"at\s+most", "less_than_or_equal"),
        (r"up\s+to", "less_than_or_equal"),
        (r"not\s+equal\s+to", "not_equals"),
        (r"equal\s+to", "equals"),
        (r"maximum(?:\s+of)?", "less_than_or_equal"),
        (r"minimum(?:\s+of)?", "greater_than_or_equal"),
        (r">=|≥", "greater_than_or_equal"),
        (r"<=|≤", "less_than_or_equal"),
        (r"!=|≠", "not_equals"),
        (r">", "greater_than"),
        (r"<", "less_than"),
        (r"=", "equals"),
    )
    _UNIT_NORMALIZATION = {
        "l/min": "L/min", "ml/min": "mL/min", "mm2": "mm²", "Nm": "N·m"
    }
    _PARAMETERS: Tuple[Tuple[str, str], ...] = (
        ("temperature rise", "temperature_rise"),
        ("leakage current", "leakage_current"),
        ("rated power input", "rated_power_input"),
        ("power input", "power_input"),
        ("rated current", "rated_current"),
        ("rated voltage", "rated_voltage"),
        ("creepage distance", "creepage_distance"),
        ("distance", "distance"),
        ("thickness", "thickness"),
        ("humidity", "humidity"),
        ("electric charge", "charge"),
        ("charge", "charge"),
        ("torque", "torque"),
        ("number of cycles", "operation_cycles"),
        ("cycle count", "operation_cycles"),
        ("operations", "operation_cycles"),
        ("cycles", "operation_cycles"),
        ("drum speed", "drum_speed"),
        ("peripheral speed", "speed"),
        ("kinetic energy", "energy"),
        ("flow of water", "water_flow_rate"),
        ("water flow", "water_flow_rate"),
        ("opening", "opening_distance"),
        ("clearance", "clearance"),
        ("temperature", "temperature"),
        ("diameter", "aperture_diameter"),
        ("area", "aperture_area"),
        ("width", "aperture_width"),
        ("force", "applied_force"),
        ("duration", "test_duration"),
        ("time", "test_duration"),
        ("frequency", "frequency"),
        ("resistance", "resistance"),
        ("capacity", "capacity"),
        ("percentage", "percentage"),
        ("power", "power"),
        ("energy", "energy"),
        ("speed", "speed"),
        ("current", "current"),
        ("voltage", "voltage"),
    )
    _REFERENCE_ONLY_RE = re.compile(
        r"^(?:\s*(?:clause|subclause|table|figure|note|page)\s+[A-Z]?\d+(?:\.\d+)*"
        r"|\s*(?:IEC|ISO)\s+\d+(?:-\d+)*(?:\s.*)?\s*)$",
        re.IGNORECASE,
    )

    def parse(self, clauses: Sequence[Clause]) -> List[Clause]:
        """Return a deep copy with safely extracted technical constraints."""

        if clauses is None or isinstance(clauses, (str, bytes)):
            raise TypeError("clauses must be a sequence of Clause objects")
        if any(not isinstance(clause, Clause) for clause in clauses):
            raise TypeError("Every input item must be a Clause")
        copied = copy.deepcopy(list(clauses))
        for clause in copied:
            self._process_clause_recursive(clause)
        return copied

    def _process_clause_recursive(self, clause: Clause) -> None:
        from iec_parser.generic_technical_rule_families import GenericTechnicalRuleCompiler
        for requirement in clause.requirements:
            requirement.technical_constraints = self._extract_requirement_constraints(requirement)
            requirement.executable_rules = GenericTechnicalRuleCompiler().compile_requirement(
                requirement, clause.clause_id
            )
        for child in clause.children:
            self._process_clause_recursive(child)

    def _extract_requirement_constraints(
        self, requirement: Requirement
    ) -> List[TechnicalConstraint]:
        text = requirement.text
        if not text or self._is_cross_reference(text):
            return []

        # Complex structures take precedence so their operands are never duplicated.
        constraints = self._extract_leakage_formula(text, requirement.requirement_id)
        if constraints:
            return constraints
        constraints = self._extract_selection_formula(text, requirement.requirement_id)
        if constraints:
            return constraints
        constraints = self._extract_electrolyser_compound(text, requirement.requirement_id)
        if constraints:
            return constraints
        constraints = self._extract_roller_separation_compound(text, requirement.requirement_id)
        if constraints:
            return constraints
        constraints = self._extract_time_dependent_constraint(text, requirement.requirement_id)
        if constraints:
            return constraints

        constraints = self._extract_range(text, requirement.requirement_id)
        if constraints:
            return constraints
        constraints = self._extract_tolerance(text, requirement.requirement_id)
        if constraints:
            return constraints
        constraints = self._extract_operation_cycles(text, requirement.requirement_id)
        if constraints:
            return constraints

        if requirement.requirement_type is RequirementType.TEST:
            constraints = self._extract_test_parameters(text, requirement.requirement_id)
            if constraints:
                return self._assign_ids(constraints, requirement.requirement_id)

        constraints = self._extract_simple_limits(text, requirement.requirement_id)
        if constraints:
            return self._assign_ids(constraints, requirement.requirement_id)

        # Recognize technical numeric prose conservatively, but never turn it into a limit.
        unresolved = self._extract_unresolved_numeric(text, requirement.requirement_id)
        return unresolved

    def _extract_leakage_formula(
        self, text: str, requirement_id: str
    ) -> List[TechnicalConstraint]:
        pattern = re.compile(
            rf"leakage\s+current\s+shall\s+not\s+exceed\s+"
            rf"(?P<const>{self._NUMBER})\s*(?P<unit>mA)\s*,?\s*or\s+"
            rf"(?P<coefficient>{self._NUMBER})\s*(?P<coefficient_unit>mA/kW)\s+"
            rf"of\s+rated\s+power\s+input\s+with\s+a\s+limit\s+of\s+"
            rf"(?P<cap>{self._NUMBER})\s*(?P<cap_unit>mA)\s*,?\s*"
            rf"whichever\s+is\s+(?P<selection>greater|less|smaller)",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return []
        selection = "MAX" if match.group("selection").lower() == "greater" else "MIN"
        raw = match.group(0)
        expression = {
            "selection": selection,
            "operands": [
                {
                    "type": "CONSTANT",
                    "value": self._normalize_decimal(match.group("const")),
                    "unit": self._normalize_unit(match.group("unit")),
                },
                {
                    "type": "FORMULA",
                    "coefficient": self._normalize_decimal(match.group("coefficient")),
                    "coefficient_unit": match.group("coefficient_unit"),
                    "variable": "rated_power_input",
                    "cap": {
                        "operator": "less_than_or_equal",
                        "value": self._normalize_decimal(match.group("cap")),
                        "unit": self._normalize_unit(match.group("cap_unit")),
                    },
                },
            ],
        }
        return [TechnicalConstraint(
            constraint_id=f"{requirement_id}-C1",
            parameter="leakage_current",
            parameter_text="leakage current",
            operator="less_than_or_equal",
            unit="mA",
            unit_normalized="mA",
            expression=expression,
            raw_text=raw,
            constraint_type=ConstraintType.FORMULA,
            status=ConstraintStatus.RESOLVED,
            source_requirement_id=requirement_id,
            notes="Dependent limit preserved without numerical evaluation.",
        )]

    def _extract_selection_formula(
        self, text: str, requirement_id: str
    ) -> List[TechnicalConstraint]:
        pattern = re.compile(
            rf"(?P<subject>[A-Za-z][A-Za-z ]{{1,60}}?)\s+shall\s+not\s+exceed\s+"
            rf"(?P<a>{self._NUMBER})\s*(?P<unit_a>{self._UNIT})\s*,?\s*or\s+"
            rf"(?P<b>{self._NUMBER})\s*(?P<unit_b>{self._UNIT})\s*,?\s*"
            rf"(?:whichever\s+is\s+|the\s+)(?P<selection>greater|higher|less|lesser|smaller|lower)",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return []
        selection = "MAX" if match.group("selection").lower() in {"greater", "higher"} else "MIN"
        parameter, parameter_text = self._identify_parameter(match.group("subject"))
        unit_a = self._normalize_unit(match.group("unit_a"))
        unit_b = self._normalize_unit(match.group("unit_b"))
        status = ConstraintStatus.RESOLVED if unit_a == unit_b else ConstraintStatus.NEEDS_REVIEW
        return [TechnicalConstraint(
            constraint_id=f"{requirement_id}-C1",
            parameter=parameter,
            parameter_text=parameter_text,
            operator="less_than_or_equal",
            unit=match.group("unit_a"),
            unit_normalized=unit_a,
            expression={
                "selection": selection,
                "operands": [
                    {"type": "CONSTANT", "value": self._normalize_decimal(match.group("a")), "unit": unit_a},
                    {"type": "CONSTANT", "value": self._normalize_decimal(match.group("b")), "unit": unit_b},
                ],
            },
            raw_text=match.group(0),
            constraint_type=ConstraintType.FORMULA,
            status=status,
            source_requirement_id=requirement_id,
        )]

    def _extract_electrolyser_compound(
        self, text: str, requirement_id: str
    ) -> List[TechnicalConstraint]:
        pattern = re.compile(
            rf"aperture\s+of\s+at\s+least\s+(?P<diameter>{self._NUMBER})\s*(?P<du>mm)\s+"
            rf"in\s+diameter\s*,?\s*or\s+(?P<area>{self._NUMBER})\s*(?P<au>mm(?:²|2))\s+"
            rf"in\s+area\s+with\s+a\s+width\s+of\s+at\s+least\s+"
            rf"(?P<width>{self._NUMBER})\s*(?P<wu>mm)",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return []
        expression = {
            "any": [
                {
                    "field": "aperture_diameter", "operator": "greater_than_or_equal",
                    "value": self._normalize_decimal(match.group("diameter")),
                    "unit": self._normalize_unit(match.group("du")),
                },
                {"all": [
                    {
                        "field": "aperture_area", "operator": "greater_than_or_equal",
                        "value": self._normalize_decimal(match.group("area")),
                        "unit": self._normalize_unit(match.group("au")),
                    },
                    {
                        "field": "aperture_width", "operator": "greater_than_or_equal",
                        "value": self._normalize_decimal(match.group("width")),
                        "unit": self._normalize_unit(match.group("wu")),
                    },
                ]},
            ]
        }
        return [TechnicalConstraint(
            constraint_id=f"{requirement_id}-C1",
            parameter="aperture",
            parameter_text="aperture",
            expression=expression,
            raw_text=match.group(0),
            constraint_type=ConstraintType.COMPOUND,
            status=ConstraintStatus.RESOLVED,
            source_requirement_id=requirement_id,
        )]

    def _extract_time_dependent_constraint(
        self, text: str, requirement_id: str
    ) -> List[TechnicalConstraint]:
        pattern = re.compile(
            rf"drum\s+speed\s+shall\s+be\s+no\s+higher\s+than\s+"
            rf"(?P<speed>{self._NUMBER})\s*(?P<speed_unit>r/min)\s+within\s+"
            rf"(?P<time>{self._NUMBER})\s*(?P<time_unit>s)\s+of\s+opening\s+"
            rf"the\s+lid\s+or\s+door\s+by\s+(?P<distance>{self._NUMBER})\s*(?P<distance_unit>mm)",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return []
        context = re.search(r"within\s+.*$", match.group(0), re.IGNORECASE).group(0)
        return [TechnicalConstraint(
            constraint_id=f"{requirement_id}-C1",
            parameter="drum_speed",
            parameter_text="drum speed",
            operator="less_than_or_equal",
            value=self._normalize_decimal(match.group("speed")),
            unit=match.group("speed_unit"),
            unit_normalized=self._normalize_unit(match.group("speed_unit")),
            condition_text=context,
            expression={
                "time_window": {
                    "operator": "less_than_or_equal",
                    "value": self._normalize_decimal(match.group("time")),
                    "unit": self._normalize_unit(match.group("time_unit")),
                },
                "trigger": {
                    "parameter": "opening_distance", "operator": "equals",
                    "value": self._normalize_decimal(match.group("distance")),
                    "unit": self._normalize_unit(match.group("distance_unit")),
                },
            },
            raw_text=match.group(0),
            constraint_type=ConstraintType.COMPOUND,
            status=ConstraintStatus.RESOLVED,
            source_requirement_id=requirement_id,
        )]

    def _extract_roller_separation_compound(
        self, text: str, requirement_id: str
    ) -> List[TechnicalConstraint]:
        pattern = re.compile(
            rf"rollers\s+shall\s+separate\s+either\s+by\s+at\s+least\s+"
            rf"(?P<both>{self._NUMBER})\s*mm\s+at\s+both\s+ends\s+or\s+by\s+"
            rf"at\s+least\s+(?P<one>{self._NUMBER})\s*mm\s+at\s+one\s+end\s+and\s+"
            rf"(?P<other>{self._NUMBER})\s*mm\s+at\s+the\s+other",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return []
        return [TechnicalConstraint(
            constraint_id=f"{requirement_id}-C1",
            parameter="roller_separation",
            parameter_text="rollers separate",
            expression={"any": [
                {
                    "field": "separation_both_ends", "operator": "greater_than_or_equal",
                    "value": self._normalize_decimal(match.group("both")), "unit": "mm",
                },
                {"all": [
                    {
                        "field": "separation_one_end", "operator": "greater_than_or_equal",
                        "value": self._normalize_decimal(match.group("one")), "unit": "mm",
                    },
                    {
                        "field": "separation_other_end", "operator": "equals",
                        "value": self._normalize_decimal(match.group("other")), "unit": "mm",
                    },
                ]},
            ]},
            raw_text=match.group(0), constraint_type=ConstraintType.COMPOUND,
            status=ConstraintStatus.RESOLVED, source_requirement_id=requirement_id,
        )]

    def _extract_operation_cycles(
        self, text: str, requirement_id: str
    ) -> List[TechnicalConstraint]:
        pattern = re.compile(
            rf"number\s+of\s+cycles(?:\s+of\s+operation)?\b.*?"
            rf"shall\s+not\s+be\s+less\s+than\s+(?P<value>{self._NUMBER})",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return []
        return [TechnicalConstraint(
            constraint_id=f"{requirement_id}-C1", parameter="operation_cycles",
            parameter_text="number of cycles", operator="greater_than_or_equal",
            value=self._normalize_decimal(match.group("value")), unit="cycles",
            unit_normalized="cycles", raw_text=match.group(0),
            constraint_type=ConstraintType.COUNT_LIMIT, status=ConstraintStatus.RESOLVED,
            source_requirement_id=requirement_id,
        )]

    def _extract_range(self, text: str, requirement_id: str) -> List[TechnicalConstraint]:
        pattern = re.compile(
            rf"(?P<subject>[A-Za-z][^.;,:]{{0,100}}?)\s+(?:shall\s+be\s+)?between\s+"
            rf"(?P<low>{self._NUMBER})\s*(?P<unit1>{self._UNIT})\s+and\s+"
            rf"(?P<high>{self._NUMBER})\s*(?P<unit2>{self._UNIT})",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return []
        unit1 = self._normalize_unit(match.group("unit1"))
        unit2 = self._normalize_unit(match.group("unit2"))
        parameter, parameter_text = self._identify_parameter(match.group("subject"))
        return [TechnicalConstraint(
            constraint_id=f"{requirement_id}-C1", parameter=parameter,
            parameter_text=parameter_text, operator="between",
            value=self._normalize_decimal(match.group("low")),
            value_secondary=self._normalize_decimal(match.group("high")),
            unit=match.group("unit1"), unit_normalized=unit1,
            raw_text=match.group(0), constraint_type=ConstraintType.RANGE,
            status=ConstraintStatus.RESOLVED if unit1 == unit2 else ConstraintStatus.NEEDS_REVIEW,
            source_requirement_id=requirement_id,
        )]

    def _extract_tolerance(self, text: str, requirement_id: str) -> List[TechnicalConstraint]:
        pattern = re.compile(
            rf"within\s*(?:±|\+\s*/\s*-)\s*(?P<value>{self._NUMBER})\s*(?P<unit>{self._UNIT})",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return []
        value = self._normalize_decimal(match.group("value"))
        parameter, parameter_text = self._identify_parameter(text[:match.start()])
        unit = self._normalize_unit(match.group("unit"))
        return [TechnicalConstraint(
            constraint_id=f"{requirement_id}-C1", parameter=parameter,
            parameter_text=parameter_text, value=value, unit=match.group("unit"),
            unit_normalized=unit,
            tolerance={"type": "PLUS_MINUS", "value": value},
            raw_text=match.group(0), constraint_type=ConstraintType.TOLERANCE,
            status=ConstraintStatus.RESOLVED, source_requirement_id=requirement_id,
        )]

    def _extract_simple_limits(
        self, text: str, requirement_id: str
    ) -> List[TechnicalConstraint]:
        constraints: List[TechnicalConstraint] = []
        comparator_pattern = "|".join(f"(?:{pattern})" for pattern, _ in self._COMPARATORS)
        pattern = re.compile(
            rf"(?P<subject>[A-Za-z][^.;:]{{0,140}}?)\s+(?P<phrase>{comparator_pattern})\s*"
            rf"(?P<value>{self._NUMBER})(?:\s*(?P<unit>{self._UNIT})(?![A-Za-z]))?",
            re.IGNORECASE,
        )
        inherited_parameter: Optional[str] = None
        inherited_parameter_text: Optional[str] = None
        for match in pattern.finditer(text):
            # A numeric predicate in an explicit if/when antecedent controls
            # whether the following obligation is triggered; it is not itself
            # an acceptance limit to compare as product compliance.
            antecedent = text[:match.start("phrase")]
            condition_start = list(re.finditer(r"\b(?:if|when)\b", antecedent, re.IGNORECASE))
            # A comparator inside an if/when prefix is a trigger.  Commas,
            # semicolons and "then" all commonly terminate that prefix.
            condition_tail = antecedent[condition_start[-1].start():] if condition_start else ""
            if condition_start and not re.search(r"[.;:]", condition_tail):
                continue
            phrase = " ".join(match.group("phrase").lower().split())
            operator = self._operator_for_phrase(phrase)
            if operator is None:
                continue
            subject = self._clean_subject(match.group("subject"))
            parameter, parameter_text = self._identify_parameter(subject)
            if parameter is None and inherited_parameter is not None:
                parameter, parameter_text = inherited_parameter, inherited_parameter_text
            unit_source = match.group("unit")
            if unit_source is None and parameter == "operation_cycles":
                unit_source = "cycles"
            if unit_source is None:
                # A unitless known quantity is safe only when its parameter is explicit.
                if parameter is None:
                    continue
            constraint_type = self._constraint_type(parameter, unit_source, operator)
            constraints.append(TechnicalConstraint(
                constraint_id="", parameter=parameter, parameter_text=parameter_text,
                operator=operator, value=self._normalize_decimal(match.group("value")),
                unit=unit_source,
                unit_normalized=self._normalize_unit(unit_source) if unit_source else None,
                raw_text=match.group(0), constraint_type=constraint_type,
                status=ConstraintStatus.RESOLVED if parameter else ConstraintStatus.NEEDS_REVIEW,
                source_requirement_id=requirement_id,
            ))
            if parameter is not None:
                inherited_parameter, inherited_parameter_text = parameter, parameter_text

        # A following symbolic bound may omit the already established subject, for
        # example a lower symbolic bound followed by an upper symbolic bound.
        if constraints:
            tail_pattern = re.compile(
                rf"(?:\band\b|,)\s*(?P<phrase>>=|≥|<=|≤|!=|≠|>|<|=)\s*"
                rf"(?P<value>{self._NUMBER})(?:\s*(?P<unit>{self._UNIT})(?![A-Za-z]))?",
                re.IGNORECASE,
            )
            occupied = {(item.operator, item.value, item.unit_normalized) for item in constraints}
            for match in tail_pattern.finditer(text):
                operator = self._operator_for_phrase(match.group("phrase"))
                unit_source = match.group("unit")
                key = (operator, self._normalize_decimal(match.group("value")),
                       self._normalize_unit(unit_source) if unit_source else None)
                if key in occupied:
                    continue
                constraints.append(TechnicalConstraint(
                    constraint_id="", parameter=inherited_parameter,
                    parameter_text=inherited_parameter_text, operator=operator,
                    value=key[1], unit=unit_source, unit_normalized=key[2],
                    raw_text=match.group(0),
                    constraint_type=self._constraint_type(inherited_parameter, unit_source, operator or ""),
                    status=ConstraintStatus.RESOLVED if inherited_parameter else ConstraintStatus.NEEDS_REVIEW,
                    source_requirement_id=requirement_id,
                ))
                occupied.add(key)

        # Interlock requirements express the opening threshold through "before ... exceeds".
        opening = re.search(
            rf"before\s+(?:the\s+)?(?:lid\s+)?opening\s+exceeds\s+"
            rf"(?P<value>{self._NUMBER})\s*(?P<unit>mm)", text, re.IGNORECASE
        )
        if opening:
            constraints.append(TechnicalConstraint(
                constraint_id="", parameter="opening_distance", parameter_text="opening",
                operator="less_than_or_equal", value=self._normalize_decimal(opening.group("value")),
                unit=opening.group("unit"), unit_normalized="mm", raw_text=opening.group(0),
                constraint_type=ConstraintType.DISTANCE_LIMIT, status=ConstraintStatus.RESOLVED,
                source_requirement_id=requirement_id,
            ))
        force_threshold = re.search(
            rf"before\s+(?:the\s+)?force\s+exceeds\s+"
            rf"(?P<value>{self._NUMBER})\s*(?P<unit>N)", text, re.IGNORECASE
        )
        if force_threshold:
            constraints.append(TechnicalConstraint(
                constraint_id="", parameter="applied_force", parameter_text="force",
                operator="less_than_or_equal",
                value=self._normalize_decimal(force_threshold.group("value")),
                unit=force_threshold.group("unit"), unit_normalized="N",
                raw_text=force_threshold.group(0), constraint_type=ConstraintType.FORCE_LIMIT,
                status=ConstraintStatus.RESOLVED, source_requirement_id=requirement_id,
            ))
        return constraints

    def _extract_test_parameters(
        self, text: str, requirement_id: str
    ) -> List[TechnicalConstraint]:
        constraints: List[TechnicalConstraint] = []
        force = re.search(
            rf"(?:(?:apply|applied|with)\s+(?:a\s+)?force\s+(?:of\s+)?|"
            rf"(?:a\s+)?force\s+of\s+)"
            rf"(?P<value>{self._NUMBER})\s*(?P<unit>N)", text, re.IGNORECASE
        )
        if force:
            constraints.append(self._test_parameter(
                "applied_force", "force", force.group("value"), force.group("unit"),
                force.group(0), requirement_id,
            ))
        duration = re.search(
            rf"(?:for|during)\s+(?P<value>{self._NUMBER})\s*(?P<unit>s|min|h)\b",
            text, re.IGNORECASE,
        )
        if duration:
            constraints.append(self._test_parameter(
                "test_duration", "duration", duration.group("value"), duration.group("unit"),
                duration.group(0), requirement_id,
            ))
        return constraints

    def _test_parameter(
        self, parameter: str, parameter_text: str, value: str, unit: str,
        raw_text: str, requirement_id: str,
    ) -> TechnicalConstraint:
        return TechnicalConstraint(
            constraint_id="", parameter=parameter, parameter_text=parameter_text,
            operator="equals", value=self._normalize_decimal(value), unit=unit,
            unit_normalized=self._normalize_unit(unit), raw_text=raw_text,
            constraint_type=ConstraintType.TEST_PARAMETER, status=ConstraintStatus.RESOLVED,
            source_requirement_id=requirement_id,
            notes="Test setup parameter; not an acceptance limit.",
        )

    def _extract_unresolved_numeric(
        self, text: str, requirement_id: str
    ) -> List[TechnicalConstraint]:
        sanitized = re.sub(
            r"\b(?:IEC|ISO)(?::|\s+)\s*\d+(?:\s*-\s*\d+)*(?:\.\d+)*", " ", text,
            flags=re.IGNORECASE,
        )
        sanitized = re.sub(
            r"\b(?:Clause|Subclause|Table|Figure|NOTE|Page)\s+[A-Z]?\d+(?:\.\d+)*",
            " ", sanitized, flags=re.IGNORECASE,
        )
        # Structural headings embedded by PDF extraction (for example ``21.101.1 A``)
        # are identifiers followed by prose, not ampere measurements.
        sanitized = re.sub(r"\b\d+(?:\.\d+){1,}\s+(?=[A-Z]\b)", " ", sanitized)
        numeric = re.search(rf"(?P<value>{self._NUMBER})\s+(?P<unit>{self._UNIT})\b", sanitized)
        if not numeric or not re.search(r"\b(?:shall|must|test|apply|within|limit)\b", text, re.IGNORECASE):
            return []
        if self._is_cross_reference(numeric.group(0)):
            return []
        parameter, parameter_text = self._identify_parameter(sanitized[:numeric.start()])
        return [TechnicalConstraint(
            constraint_id=f"{requirement_id}-C1", parameter=parameter,
            parameter_text=parameter_text, value=self._normalize_decimal(numeric.group("value")),
            unit=numeric.group("unit"), unit_normalized=self._normalize_unit(numeric.group("unit")),
            raw_text=numeric.group(0), constraint_type=ConstraintType.OTHER,
            status=ConstraintStatus.UNRESOLVED, source_requirement_id=requirement_id,
            notes="Numeric technical wording recognized without a safe comparison interpretation.",
        )]

    @classmethod
    def _normalize_decimal(cls, value: str) -> float | int:
        normalized = re.sub(r"[\s\u00a0]", "", value).replace(",", ".")
        number = float(normalized)
        return int(number) if number.is_integer() else number

    @classmethod
    def _normalize_unit(cls, unit: Optional[str]) -> Optional[str]:
        if unit is None:
            return None
        return cls._UNIT_NORMALIZATION.get(unit, unit)

    @classmethod
    def _identify_parameter(cls, text: str) -> Tuple[Optional[str], Optional[str]]:
        normalized = " ".join(text.lower().split())
        best: Optional[Tuple[int, str, str]] = None
        for phrase, parameter in cls._PARAMETERS:
            index = normalized.rfind(phrase)
            if index >= 0 and (best is None or index > best[0]):
                best = (index, parameter, phrase)
        if best:
            return best[1], best[2]
        cleaned = cls._clean_subject(text)
        return None, cleaned or None

    @staticmethod
    def _clean_subject(text: str) -> str:
        cleaned = re.split(r"\b(?:and|or)\b", text, flags=re.IGNORECASE)[-1]
        cleaned = re.sub(r"^(?:addition|modification|replacement)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        return " ".join(cleaned.strip(" ,:-").split())

    @classmethod
    def _operator_for_phrase(cls, phrase: str) -> Optional[str]:
        for pattern, operator in cls._COMPARATORS:
            if re.fullmatch(pattern, phrase, re.IGNORECASE):
                return operator
        return None

    @staticmethod
    def _constraint_type(
        parameter: Optional[str], unit: Optional[str], operator: str
    ) -> ConstraintType:
        normalized_unit = GenericIECTechnicalConstraintExtractor._normalize_unit(unit)
        if parameter == "leakage_current" or normalized_unit in {"mA", "A"}:
            return ConstraintType.CURRENT_LIMIT
        if parameter in {"opening_distance", "clearance", "creepage_distance", "aperture_diameter", "aperture_width"} or normalized_unit in {"mm", "cm", "m", "mm²"}:
            return ConstraintType.DISTANCE_LIMIT
        if parameter == "drum_speed" or normalized_unit == "r/min":
            return ConstraintType.SPEED_LIMIT
        if parameter == "water_flow_rate" or normalized_unit in {"L/min", "mL/min"}:
            return ConstraintType.FLOW_LIMIT
        if parameter in {"temperature", "temperature_rise"} or normalized_unit in {"°C", "K"}:
            return ConstraintType.TEMPERATURE_LIMIT
        if normalized_unit in {"V", "mV", "kV"}:
            return ConstraintType.VOLTAGE_LIMIT
        if normalized_unit in {"W", "kW"}:
            return ConstraintType.POWER_LIMIT
        if normalized_unit in {"N", "N·m"}:
            return ConstraintType.FORCE_LIMIT
        if normalized_unit == "cycles" or parameter == "operation_cycles":
            return ConstraintType.COUNT_LIMIT
        if normalized_unit == "%":
            return ConstraintType.PERCENTAGE_LIMIT
        if normalized_unit in {"s", "min", "h"}:
            return ConstraintType.TIME_LIMIT
        if operator == "equals":
            return ConstraintType.EXACT
        return ConstraintType.SIMPLE_LIMIT

    @classmethod
    def _is_cross_reference(cls, text: str) -> bool:
        stripped = text.strip().rstrip(".")
        if cls._REFERENCE_ONLY_RE.fullmatch(stripped):
            return True
        return bool(re.fullmatch(r"\d+(?:\.\d+)+", stripped))

    @staticmethod
    def _assign_ids(
        constraints: List[TechnicalConstraint], requirement_id: str
    ) -> List[TechnicalConstraint]:
        for index, constraint in enumerate(constraints, start=1):
            constraint.constraint_id = f"{requirement_id}-C{index}"
        return constraints


__all__ = ["GenericIECTechnicalConstraintExtractor"]
