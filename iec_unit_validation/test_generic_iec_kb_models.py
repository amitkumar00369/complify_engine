"""Tests for the independent generic IEC knowledge-base models."""

import json

from iec_par.generic_iec_kb_models import (
    ApplicabilityRule,
    ApplicabilityStatus,
    Clause,
    ClauseType,
    ConstraintStatus,
    ConstraintType,
    DocumentType,
    KnowledgeBase,
    NumericLimit,
    ParentRelationship,
    RelationshipType,
    Requirement,
    RequirementType,
    SourceReference,
    StandardDocument,
    TechnicalConstraint,
)


def make_requirement(requirement_id: str, text: str) -> Requirement:
    return Requirement(
        requirement_id=requirement_id,
        text=text,
        requirement_type=RequirementType.SAFETY,
        normative=True,
        applicability=ApplicabilityRule(status=ApplicabilityStatus.ALWAYS),
    )


def test_create_base_standard() -> None:
    document = StandardDocument(
        standard_number="IEC 12345", document_type=DocumentType.BASE
    )
    assert document.document_type is DocumentType.BASE
    assert document.parent_standard is None


def test_create_part_2_standard_with_parent() -> None:
    document = StandardDocument(
        standard_number="IEC 12345-2-7",
        part_number="2-7",
        document_type=DocumentType.PART_2,
        parent_standard="IEC 12345-1",
    )
    assert document.document_type is DocumentType.PART_2
    assert document.parent_standard == "IEC 12345-1"


def test_clause_with_multiple_requirements() -> None:
    clause = Clause(
        clause_id="7",
        clause_type=ClauseType.NORMATIVE,
        source=SourceReference(page_start=10),
        relationship_to_parent=ParentRelationship(type=RelationshipType.NONE),
        requirements=[
            make_requirement("7.1", "The equipment shall be guarded."),
            make_requirement("7.2", "The guard shall remain secure."),
        ],
    )
    assert len(clause.requirements) == 2
    assert [item.requirement_id for item in clause.requirements] == ["7.1", "7.2"]


def test_store_replacement_relationship() -> None:
    relationship = ParentRelationship(
        type=RelationshipType.REPLACEMENT, parent_clause_id="7"
    )
    assert relationship.type is RelationshipType.REPLACEMENT
    assert relationship.parent_clause_id == "7"


def test_store_addition_relationship() -> None:
    relationship = ParentRelationship(
        type=RelationshipType.ADDITION, parent_clause_id="8.1"
    )
    assert relationship.type is RelationshipType.ADDITION


def test_store_nested_applicability_logic() -> None:
    logic = {
        "all": [
            {"feature": "rated_voltage", "operator": ">", "value": 50},
            {"any": [{"feature": "indoor"}, {"feature": "supervised"}]},
        ]
    }
    rule = ApplicabilityRule(
        status=ApplicabilityStatus.RESOLVED,
        condition_text="Applies when all stated conditions are met.",
        logic=logic,
    )
    assert rule.logic == logic
    assert rule.logic["all"][1]["any"][0]["feature"] == "indoor"


def test_serialize_complete_knowledge_base() -> None:
    requirement = make_requirement("5.1", "The value shall not exceed the limit.")
    requirement.limits.append(NumericLimit(parameter="value", max_value=10, unit="A"))
    kb = KnowledgeBase(
        document=StandardDocument(
            standard_id="example-1",
            standard_number="IEC 12345-1",
            document_type=DocumentType.BASE,
        ),
        clauses=[
            Clause(
                clause_id="5",
                clause_type=ClauseType.NORMATIVE,
                source=SourceReference(page_start=4, page_end=5),
                relationship_to_parent=ParentRelationship(type=RelationshipType.NONE),
                requirements=[requirement],
            )
        ],
    )
    data = kb.to_dict()
    encoded = kb.to_json()
    assert data["schema_version"] == "1.0"
    assert data["document"]["document_type"] == "BASE"
    assert json.loads(encoded) == data


def test_mutable_defaults_are_not_shared() -> None:
    first = KnowledgeBase(
        document=StandardDocument(document_type=DocumentType.UNKNOWN)
    )
    second = KnowledgeBase(
        document=StandardDocument(document_type=DocumentType.UNKNOWN)
    )
    first.clauses.append(
        Clause(
            clause_id="1",
            clause_type=ClauseType.UNKNOWN,
            source=SourceReference(),
            relationship_to_parent=ParentRelationship(type=RelationshipType.NONE),
        )
    )
    first_rule = ApplicabilityRule(status=ApplicabilityStatus.UNRESOLVED)
    second_rule = ApplicabilityRule(status=ApplicabilityStatus.UNRESOLVED)
    first_rule.unresolved_features.append("feature_a")

    assert second.clauses == []
    assert second_rule.unresolved_features == []


def test_requirement_can_be_created_without_technical_constraints() -> None:
    requirement = make_requirement("1-R1", "The appliance shall comply.")
    assert isinstance(requirement, Requirement)


def test_technical_constraints_default_to_empty_list() -> None:
    assert make_requirement("1-R1", "The appliance shall comply.").technical_constraints == []


def test_technical_constraint_mutable_default_isolation() -> None:
    first = make_requirement("1-R1", "First requirement.")
    second = make_requirement("1-R2", "Second requirement.")
    first.technical_constraints.append(TechnicalConstraint(constraint_id="1-R1-C1"))
    assert second.technical_constraints == []


def test_simple_limit_serialization() -> None:
    constraint = TechnicalConstraint(
        constraint_id="1-R1-C1",
        parameter="leakage_current",
        operator="less_than_or_equal",
        value=3.5,
        unit="mA",
        unit_normalized="mA",
        constraint_type=ConstraintType.SIMPLE_LIMIT,
        status=ConstraintStatus.RESOLVED,
    )
    data = constraint.to_dict()
    assert data["value"] == 3.5
    assert data["constraint_type"] == "SIMPLE_LIMIT"
    assert json.loads(constraint.to_json())["status"] == "RESOLVED"


def test_range_with_primary_and_secondary_values() -> None:
    constraint = TechnicalConstraint(
        constraint_id="1-R1-C1",
        operator="between",
        value=220,
        value_secondary=240,
        unit="V",
        constraint_type=ConstraintType.RANGE,
    )
    assert constraint.value == 220
    assert constraint.value_secondary == 240


def test_tolerance_object_serialization() -> None:
    constraint = TechnicalConstraint(
        constraint_id="1-R1-C1",
        value=5,
        unit="%",
        tolerance={"type": "PLUS_MINUS", "value": 5},
        constraint_type=ConstraintType.TOLERANCE,
    )
    assert constraint.to_dict()["tolerance"] == {"type": "PLUS_MINUS", "value": 5}


def test_formula_with_nested_expression_serialization() -> None:
    expression = {
        "selection": "MAX",
        "operands": [
            {"type": "CONSTANT", "value": 3.5, "unit": "mA"},
            {
                "type": "FORMULA",
                "formula": "1 mA/kW * rated_power_input",
                "cap": {"operator": "less_than_or_equal", "value": 5, "unit": "mA"},
            },
        ],
    }
    constraint = TechnicalConstraint(
        constraint_id="13.2-R1-C1",
        expression=expression,
        constraint_type=ConstraintType.FORMULA,
        status=ConstraintStatus.RESOLVED,
    )
    assert json.loads(constraint.to_json())["expression"] == expression


def test_compound_expression_with_any_and_all_semantics() -> None:
    expression = {
        "any": [
            {"parameter": "aperture_diameter", "operator": "greater_than_or_equal", "value": 5},
            {
                "all": [
                    {"parameter": "aperture_area", "operator": "greater_than_or_equal", "value": 20},
                    {"parameter": "aperture_width", "operator": "greater_than_or_equal", "value": 3},
                ]
            },
        ]
    }
    constraint = TechnicalConstraint(
        constraint_id="22.201-R1-C1",
        expression=expression,
        constraint_type=ConstraintType.COMPOUND,
    )
    assert constraint.to_dict()["expression"]["any"][1]["all"][1]["value"] == 3


def test_test_parameter_representation() -> None:
    constraint = TechnicalConstraint(
        constraint_id="1-R1-C1",
        parameter="applied_force",
        operator="equals",
        value=30,
        unit="N",
        constraint_type=ConstraintType.TEST_PARAMETER,
        status=ConstraintStatus.RESOLVED,
    )
    assert constraint.constraint_type is ConstraintType.TEST_PARAMETER
    assert constraint.operator == "equals"


def test_constraint_status_serialization() -> None:
    constraint = TechnicalConstraint(
        constraint_id="1-R1-C1", status=ConstraintStatus.NEEDS_REVIEW
    )
    assert json.loads(constraint.to_json())["status"] == "NEEDS_REVIEW"


def test_source_requirement_id_is_preserved() -> None:
    constraint = TechnicalConstraint(
        constraint_id="7-R1-C1", source_requirement_id="7-R1"
    )
    assert constraint.source_requirement_id == "7-R1"


def test_existing_numeric_limit_still_works_unchanged() -> None:
    limit = NumericLimit(parameter="current", max_value=10, unit="A")
    requirement = make_requirement("1-R1", "Current shall be limited.")
    requirement.limits.append(limit)
    assert requirement.limits == [limit]
    assert requirement.limits[0].max_value == 10


def test_existing_requirement_serialization_is_backward_compatible() -> None:
    requirement = make_requirement("1-R1", "The appliance shall comply.")
    data = requirement.to_dict()
    assert data["requirement_id"] == "1-R1"
    assert data["limits"] == []
    assert data["references"] == []
    assert data["technical_constraints"] == []
    assert data["applicability"]["status"] == "ALWAYS"


def test_complete_knowledge_base_serializes_technical_constraints() -> None:
    requirement = make_requirement("5.1-R1", "The opening shall not exceed 50 mm.")
    requirement.technical_constraints.append(
        TechnicalConstraint(
            constraint_id="5.1-R1-C1",
            parameter="opening_distance",
            operator="less_than_or_equal",
            value=50,
            unit="mm",
            constraint_type=ConstraintType.DISTANCE_LIMIT,
            status=ConstraintStatus.RESOLVED,
            source_requirement_id="5.1-R1",
        )
    )
    kb = KnowledgeBase(
        document=StandardDocument(document_type=DocumentType.BASE),
        clauses=[
            Clause(
                clause_id="5.1",
                clause_type=ClauseType.NORMATIVE,
                source=SourceReference(),
                relationship_to_parent=ParentRelationship(type=RelationshipType.NONE),
                requirements=[requirement],
            )
        ],
    )
    serialized = json.loads(kb.to_json())
    constraint = serialized["clauses"][0]["requirements"][0]["technical_constraints"][0]
    assert constraint["constraint_id"] == "5.1-R1-C1"
    assert constraint["constraint_type"] == "DISTANCE_LIMIT"
