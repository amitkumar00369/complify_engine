"""Tests for raw IEC applicability condition extraction."""

from iec_par.generic_iec_applicability_extractor import (
    GenericIECApplicabilityExtractor,
)
from iec_par.generic_iec_kb_models import (
    ApplicabilityRule,
    ApplicabilityStatus,
    Clause,
    ClauseType,
    ParentRelationship,
    RelationshipType,
    Requirement,
    RequirementType,
    SourceReference,
)


def requirement(text, requirement_id="7.1-R1", requirement_type=RequirementType.GENERAL):
    return Requirement(
        requirement_id=requirement_id,
        text=text,
        requirement_type=requirement_type,
        normative=True,
        applicability=ApplicabilityRule(status=ApplicabilityStatus.ALWAYS),
    )


def clause(requirements=None, children=None, clause_id="7.1"):
    return Clause(
        clause_id=clause_id,
        title="Heading",
        clause_type=ClauseType.NORMATIVE,
        source=SourceReference(raw_text="source"),
        relationship_to_parent=ParentRelationship(type=RelationshipType.NONE),
        requirements=list(requirements or []),
        children=list(children or []),
    )


def extract(text, requirement_type=RequirementType.GENERAL):
    parsed = GenericIECApplicabilityExtractor().parse(
        [clause([requirement(text, requirement_type=requirement_type)])]
    )
    return parsed[0].requirements[0]


def test_for_class_condition() -> None:
    item = extract("For class II appliances, the symbol shall be marked.")
    assert item.condition_text == "For class II appliances"


def test_incorporating_subject_condition() -> None:
    item = extract("Appliances incorporating a programmer or timer shall switch off.")
    assert item.condition_text == "Appliances incorporating a programmer or timer"


def test_if_condition() -> None:
    item = extract("If the appliance is intended for outdoor use, the enclosure shall comply.")
    assert item.condition_text == "If the appliance is intended for outdoor use"


def test_negative_condition() -> None:
    item = extract("This requirement does not apply to class III appliances.")
    assert item.condition_text == "This requirement does not apply to class III appliances"


def test_unless_condition() -> None:
    item = extract("Unless the appliance is permanently installed, it shall have a plug.")
    assert item.condition_text == "Unless the appliance is permanently installed"


def test_unconditional_is_always() -> None:
    item = extract("Appliances shall be constructed so that access is prevented.")
    assert item.condition_text is None
    assert item.applicability.status is ApplicabilityStatus.ALWAYS


def test_conditional_is_unresolved() -> None:
    item = extract("For stationary appliances, the switch shall be accessible.")
    assert item.applicability.status is ApplicabilityStatus.UNRESOLVED


def test_no_logic_is_generated() -> None:
    assert extract("For class II appliances, the symbol shall be marked.").applicability.logic is None


def test_requirement_text_is_unchanged() -> None:
    text = "If the appliance is outdoors,  the enclosure shall comply."
    assert extract(text).text == text


def test_child_hierarchy_is_unchanged() -> None:
    child = clause([requirement("For class II appliances, it shall apply.")], clause_id="7.1")
    parent = clause(children=[child], clause_id="7")
    parsed = GenericIECApplicabilityExtractor().parse([parent])
    assert parsed[0].children[0].clause_id == "7.1"


def test_requirement_id_is_unchanged() -> None:
    assert extract("For class II appliances, it shall apply.").requirement_id == "7.1-R1"


def test_conditional_test_requirement() -> None:
    item = extract(
        "For class II appliances, compliance is checked by inspection.",
        RequirementType.TEST,
    )
    assert item.condition_text == "For class II appliances"
    assert item.applicability.status is ApplicabilityStatus.UNRESOLVED


def test_measured_state_is_not_applicability() -> None:
    item = extract("When measured at rated voltage, the current shall not exceed 2 A.")
    assert item.condition_text is None
    assert item.applicability.status is ApplicabilityStatus.ALWAYS


def test_when_component_present_is_applicability() -> None:
    item = extract("When the appliance incorporates a thermal control, it shall switch off.")
    assert item.condition_text == "When the appliance incorporates a thermal control"


def test_steady_test_state_is_not_applicability() -> None:
    item = extract("When steady conditions are established, the value shall be measured.")
    assert item.condition_text is None


def test_permanently_connected_condition() -> None:
    item = extract("For appliances intended to be permanently connected, a switch shall be provided.")
    assert item.condition_text == "For appliances intended to be permanently connected"


def test_parts_at_selv_condition() -> None:
    item = extract("For parts operating at SELV, the insulation shall comply.")
    assert item.condition_text == "For parts operating at SELV"


def test_except_condition() -> None:
    item = extract("Except for class III appliances, the terminal shall be earthed.")
    assert item.condition_text == "Except for class III appliances"


def test_ambiguous_condition_needs_review() -> None:
    item = extract("Where appropriate, the warning shall be provided.")
    assert item.condition_text == "Where appropriate"
    assert item.applicability.status is ApplicabilityStatus.NEEDS_REVIEW


def test_notes_and_examples_do_not_create_conditions() -> None:
    notes = [
        clause([requirement("NOTE For class II appliances, the symbol shall be used.")]),
        clause([requirement("EXAMPLE If outdoors, the enclosure shall comply.")], clause_id="8"),
    ]
    parsed = GenericIECApplicabilityExtractor().parse(notes)
    assert all(
        item.condition_text is None
        for parsed_clause in parsed
        for item in parsed_clause.requirements
    )


def test_named_test_carried_out_is_test_state() -> None:
    item = extract(
        "When the glow-wire test is carried out, the part shall be positioned normally."
    )
    assert item.condition_text is None
    assert item.applicability.status is ApplicabilityStatus.ALWAYS


def test_does_not_apply_if_is_negative_condition() -> None:
    item = extract(
        "This requirement does not apply if parts are fixed by independent fasteners."
    )
    assert item.condition_text == (
        "This requirement does not apply if parts are fixed by independent fasteners"
    )
    assert item.applicability.status is ApplicabilityStatus.UNRESOLVED


def test_relationship_prefix_does_not_hide_condition() -> None:
    item = extract(
        "Addition: Appliances without automatic control shall be marked."
    )
    assert item.condition_text == "Appliances without automatic control"
    assert item.applicability.status is ApplicabilityStatus.UNRESOLVED


def test_washing_machines_are_clear_product_context() -> None:
    item = extract(
        "For washing machines loaded from the top, the lid shall be interlocked."
    )
    assert item.condition_text == "For washing machines loaded from the top"
    assert item.applicability.status is ApplicabilityStatus.UNRESOLVED
