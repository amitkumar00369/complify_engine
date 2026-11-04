"""Tests for generic direct-clause requirement extraction."""

from iec_par.generic_iec_kb_models import (
    ApplicabilityStatus,
    Clause,
    ClauseType,
    ParentRelationship,
    RelationshipType,
    RequirementType,
    SourceReference,
)
from iec_par.generic_iec_requirement_parser import GenericIECRequirementParser
from iec_par.generic_iec_structural_parser import StructuralBlock


def clause(clause_id="7.1", raw_text="", children=None):
    return Clause(
        clause_id=clause_id,
        title="Test clause",
        clause_type=ClauseType.NORMATIVE,
        source=SourceReference(page_start=1, page_end=1, raw_text=raw_text),
        relationship_to_parent=ParentRelationship(type=RelationshipType.NONE),
        children=list(children or []),
    )


def parse_one(raw_text):
    return GenericIECRequirementParser().parse([clause(raw_text=raw_text)])[0]


def test_single_normative_requirement() -> None:
    parsed = parse_one("7.1 Appliances shall comply with this requirement.")
    assert len(parsed.requirements) == 1
    assert parsed.requirements[0].normative is True


def test_multiple_independent_requirements() -> None:
    parsed = parse_one(
        "7.1 Appliances shall be marked with rated voltage. "
        "Class II appliances shall be marked with symbol X. "
        "Compliance is checked by inspection."
    )
    assert len(parsed.requirements) == 3


def test_multiline_requirement_remains_one() -> None:
    parsed = parse_one(
        "7.1 The instructions shall state:\n"
        "- maximum inlet water pressure;\n"
        "- minimum inlet water pressure if necessary."
    )
    assert len(parsed.requirements) == 1
    assert "maximum inlet water pressure" in parsed.requirements[0].text
    assert "minimum inlet water pressure" in parsed.requirements[0].text


def test_conditional_wording_is_preserved() -> None:
    requirement = parse_one(
        "7.1 If the appliance is intended for outdoor use, it shall be marked accordingly."
    ).requirements[0]
    assert requirement.condition_text == "If the appliance is intended for outdoor use"
    assert requirement.applicability.condition_text == requirement.condition_text


def test_unconditional_requirement_is_always_applicable() -> None:
    requirement = parse_one("7.1 Appliances shall comply with this requirement.").requirements[0]
    assert requirement.applicability.status is ApplicabilityStatus.ALWAYS


def test_conditional_requirement_is_unresolved() -> None:
    requirement = parse_one(
        "7.1 For class II appliances, the symbol shall be visible."
    ).requirements[0]
    assert requirement.applicability.status is ApplicabilityStatus.UNRESOLVED


def test_note_is_not_a_normative_requirement() -> None:
    parsed = parse_one("7.1 NOTE Appliances shall normally be installed indoors.")
    assert parsed.requirements == []


def test_nested_imperative_warning_items_are_requirements_and_notes_are_excluded() -> None:
    parsed = parse_one(
        "8.14.1.101 Drill safety warnings\n"
        "1) Safety instructions for all operations\n"
        "a) Wear hearing protection when impact drilling.\n"
        "NOTE Exposure to noise may cause hearing loss.\n"
        "b) Use auxiliary handles supplied with the tool.\n"
        "2) Safety instructions when using long drill bits\n"
        "a) Never operate at higher speed than the maximum rating."
    )
    texts = [item.text for item in parsed.requirements]
    assert any("Wear hearing protection" in item for item in texts)
    assert any("Use auxiliary handles" in item for item in texts)
    assert any("Never operate" in item for item in texts)
    assert all("Exposure to noise" not in item for item in texts)


def test_example_is_not_a_normative_requirement() -> None:
    parsed = parse_one("7.1 EXAMPLE The appliance shall resemble the illustrated product.")
    assert parsed.requirements == []


def test_compliance_sentence_is_test() -> None:
    requirement = parse_one("7.1 Compliance is checked by inspection.").requirements[0]
    assert requirement.requirement_type is RequirementType.TEST
    assert requirement.test_method["type"] == "RAW_TEST_METHOD"


def test_marking_requirement_is_marking() -> None:
    requirement = parse_one("7.1 Appliances shall be marked with rated voltage.").requirements[0]
    assert requirement.requirement_type is RequirementType.MARKING


def test_instruction_requirement_is_instruction() -> None:
    requirement = parse_one("7.1 The instructions shall state the rated input.").requirements[0]
    assert requirement.requirement_type is RequirementType.INSTRUCTION


def test_construction_requirement_is_construction() -> None:
    requirement = parse_one("7.1 The appliance shall be constructed to prevent access.").requirements[0]
    assert requirement.requirement_type is RequirementType.CONSTRUCTION


def test_threshold_requirement_is_limit_without_numeric_limits() -> None:
    requirement = parse_one("7.1 The force shall not exceed 50 N.").requirements[0]
    assert requirement.requirement_type is RequirementType.LIMIT
    assert requirement.limits == []


def test_requirement_ids_are_stable() -> None:
    parsed = parse_one("7.1 Appliances shall comply. The enclosure shall remain secure.")
    assert [item.requirement_id for item in parsed.requirements] == ["7.1-R1", "7.1-R2"]


def test_child_text_is_not_duplicated_in_parent() -> None:
    child = clause("7.1", "7.1 The child shall remain secure.")
    parent = clause("7", "7 The parent shall remain secure.", [child])
    parsed = GenericIECRequirementParser().parse([parent])[0]
    assert len(parsed.requirements) == 1
    assert "child" not in parsed.requirements[0].text.lower()
    assert len(parsed.children[0].requirements) == 1


def test_requirement_source_order_is_preserved() -> None:
    parsed = parse_one("7.1 First item shall apply. Second item shall apply.")
    assert [item.text for item in parsed.requirements] == [
        "First item shall apply.",
        "Second item shall apply.",
    ]


def test_empty_clause_text_has_no_requirements() -> None:
    assert parse_one("").requirements == []


def test_no_applicability_logic_is_generated() -> None:
    parsed = parse_one("7.1 For class II appliances, the symbol shall be visible.")
    assert all(item.applicability.logic is None for item in parsed.requirements)


def test_no_numeric_limit_objects_are_generated() -> None:
    parsed = parse_one("7.1 The force shall not exceed 50 N.")
    assert all(item.limits == [] for item in parsed.requirements)


def test_input_hierarchy_is_preserved_without_mutation() -> None:
    original = clause(
        "7",
        "7 The parent shall remain secure.",
        [clause("7.1", "7.1 The child shall remain secure.")],
    )
    parsed = GenericIECRequirementParser().parse([original])[0]
    assert parsed is not original
    assert parsed.children[0].clause_id == "7.1"
    assert original.requirements == []
    assert original.children[0].requirements == []


def provenance_block(clause_id, context, raw_text):
    return StructuralBlock(
        block_type="SUBCLAUSE",
        block_id=clause_id,
        title="Replacement:",
        level=clause_id.count(".") + 1,
        parent_id=None,
        page_start=1,
        page_end=1,
        raw_text=raw_text,
        source_order=0,
        semantic_context=context,
    )


def test_definition_test_wording_creates_no_independent_test_requirement() -> None:
    raw_text = (
        "3.1.9 Replacement:\nnormal operation\noperation under the following conditions.\n"
        "In case of doubt, the test is carried out using the reduced load."
    )
    definition = clause("3.1.9", raw_text)
    parsed = GenericIECRequirementParser().parse(
        [definition], [provenance_block("3.1.9", "DEFINITION", raw_text)]
    )[0]
    assert parsed.requirements == []


def test_non_definition_test_wording_still_creates_test_requirement() -> None:
    raw_text = "8.1 Compliance is checked by the following test."
    normal = clause("8.1", raw_text)
    parsed = GenericIECRequirementParser().parse(
        [normal], [provenance_block("8.1", "MAIN_CLAUSE", raw_text)]
    )[0]
    assert len(parsed.requirements) == 1
    assert parsed.requirements[0].requirement_type is RequirementType.TEST


def test_annex_local_3x_normative_clause_is_not_suppressed() -> None:
    raw_text = "3.6.2 The battery terminal shall be marked with its polarity."
    annex_clause = clause("3.6.2", raw_text)
    parsed = GenericIECRequirementParser().parse(
        [annex_clause], [provenance_block("3.6.2", "ANNEX", raw_text)]
    )[0]
    assert len(parsed.requirements) == 1
    assert parsed.requirements[0].requirement_type is RequirementType.MARKING


def test_note_inside_definition_creates_no_requirement() -> None:
    raw_text = "3.1.9 NOTE The reduced load shall normally be used for this definition."
    definition = clause("3.1.9", raw_text)
    parsed = GenericIECRequirementParser().parse(
        [definition], [provenance_block("3.1.9", "DEFINITION", raw_text)]
    )[0]
    assert parsed.requirements == []


def test_definition_source_text_is_preserved() -> None:
    raw_text = "3.1.9 normal operation\nThe test is carried out using the reduced load."
    definition = clause("3.1.9", raw_text)
    parsed = GenericIECRequirementParser().parse(
        [definition], [provenance_block("3.1.9", "DEFINITION", raw_text)]
    )[0]
    assert parsed.source.raw_text == raw_text
