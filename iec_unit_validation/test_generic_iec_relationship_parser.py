"""Tests for semantic IEC Part 2 relationship classification."""

import copy

from iec_par.generic_iec_kb_models import (
    ApplicabilityRule,
    ApplicabilityStatus,
    Clause,
    ClauseType,
    DocumentType,
    ParentRelationship,
    RelationshipType,
    Requirement,
    RequirementType,
    SourceReference,
    StandardDocument,
)
from iec_par.generic_iec_relationship_parser import (
    GenericIECRelationshipParser,
)


def document(document_type=DocumentType.PART_2):
    return StandardDocument(document_type=document_type)


def clause(clause_id, raw_text, children=None, structural_parent=None):
    return Clause(
        clause_id=clause_id,
        title="Heading",
        clause_type=ClauseType.NORMATIVE,
        source=SourceReference(page_start=1, page_end=1, raw_text=raw_text),
        relationship_to_parent=ParentRelationship(
            type=RelationshipType.NONE, parent_clause_id=structural_parent
        ),
        children=list(children or []),
    )


def parse_one(raw_text, clause_id="7.1"):
    return GenericIECRelationshipParser().parse(
        document(), [clause(clause_id, raw_text)]
    )[0]


def flatten(clauses):
    result = []
    for item in clauses:
        result.append(item)
        result.extend(flatten(item.children))
    return result


def test_base_standard_remains_none() -> None:
    result = GenericIECRelationshipParser().parse(
        document(DocumentType.BASE), [clause("7", "7 Addition:")]
    )[0]
    assert result.relationship_to_parent.type is RelationshipType.NONE


def test_detect_applicable() -> None:
    result = parse_one("7.1 This clause of Part 1 is applicable.")
    assert result.relationship_to_parent.type is RelationshipType.APPLICABLE


def test_detect_applicable_except() -> None:
    result = parse_one("7.1 This clause of Part 1 is applicable except as follows.")
    assert result.relationship_to_parent.type is RelationshipType.APPLICABLE_EXCEPT


def test_detect_addition() -> None:
    assert parse_one("7.1 Addition:\nText.").relationship_to_parent.type is RelationshipType.ADDITION


def test_detect_modification() -> None:
    result = parse_one("7.1 Modification:\nReplace wording.")
    assert result.relationship_to_parent.type is RelationshipType.MODIFICATION


def test_detect_replacement_marker() -> None:
    result = parse_one("7.1 Replacement:\nThe appliance shall comply.")
    assert result.relationship_to_parent.type is RelationshipType.REPLACEMENT


def test_detect_replaced_by_phrase() -> None:
    result = parse_one("7.1 This clause of Part 1 is replaced by the following.")
    assert result.relationship_to_parent.type is RelationshipType.REPLACEMENT


def test_detect_not_applicable() -> None:
    result = parse_one("7.1 This clause of Part 1 is not applicable.")
    assert result.relationship_to_parent.type is RelationshipType.NOT_APPLICABLE


def test_requirement_level_exclusion_is_not_clause_not_applicable() -> None:
    result = parse_one(
        "22.101 The appliance shall comply. This requirement is not applicable to sealed appliances.",
        "22.101",
    )
    assert result.relationship_to_parent.type is RelationshipType.NONE


def test_ambiguous_wording_is_unresolved() -> None:
    result = parse_one("7.1 The relationship with Part 1 is altered as described below.")
    assert result.relationship_to_parent.type is RelationshipType.UNRESOLVED
    assert "review" in (result.relationship_to_parent.notes or "").lower()


def test_applicable_except_is_not_simple_applicable() -> None:
    result = parse_one(
        "7 This clause of Part 1 is applicable except as follows.\nAddition:\nText.", "7"
    )
    assert result.relationship_to_parent.type is RelationshipType.APPLICABLE_EXCEPT


def test_child_relationship_does_not_overwrite_sibling() -> None:
    root = clause(
        "7",
        "7 This clause of Part 1 is applicable except as follows.",
        [clause("7.1", "7.1 Addition:"), clause("7.2", "7.2 Replacement:")],
    )
    parsed = GenericIECRelationshipParser().parse(document(), [root])[0]
    assert parsed.children[0].relationship_to_parent.type is RelationshipType.ADDITION
    assert parsed.children[1].relationship_to_parent.type is RelationshipType.REPLACEMENT


def test_parent_relationship_does_not_propagate() -> None:
    root = clause("7", "7 Addition:", [clause("7.1", "7.1 Ordinary text.")])
    parsed = GenericIECRelationshipParser().parse(document(), [root])[0]
    assert parsed.relationship_to_parent.type is RelationshipType.ADDITION
    assert parsed.children[0].relationship_to_parent.type is RelationshipType.NONE


def test_explicit_new_101_clause_is_new_requirement() -> None:
    result = parse_one("19.101 Add the following additional subclause.", "19.101")
    assert result.relationship_to_parent.type is RelationshipType.NEW_REQUIREMENT
    assert result.relationship_to_parent.parent_clause_id == "19"


def test_101_numbering_alone_does_not_imply_new_requirement() -> None:
    result = parse_one("19.101 The appliance shall comply.", "19.101")
    assert result.relationship_to_parent.type is RelationshipType.NONE


def test_structural_hierarchy_remains_intact() -> None:
    root = clause("7", "7 Applicable text.", [clause("7.1", "7.1 Addition:")])
    parsed = GenericIECRelationshipParser().parse(document(), [root])
    assert parsed[0].children[0].clause_id == "7.1"


def test_requirements_remain_unchanged() -> None:
    item = clause("7.1", "7.1 Addition:")
    item.requirements.append(
        Requirement(
            requirement_id="7.1-R1",
            text="The appliance shall comply.",
            requirement_type=RequirementType.GENERAL,
            normative=True,
            applicability=ApplicabilityRule(status=ApplicabilityStatus.ALWAYS),
        )
    )
    before = copy.deepcopy(item.requirements)
    parsed = GenericIECRelationshipParser().parse(document(), [item])[0]
    assert parsed.requirements == before


def test_raw_source_text_remains_unchanged() -> None:
    raw = "7.1 Addition:\n  Original source text."
    assert parse_one(raw).source.raw_text == raw


def test_clause_order_remains_unchanged() -> None:
    items = [clause("7", "7 Addition:"), clause("8", "8 Replacement:")]
    parsed = GenericIECRelationshipParser().parse(document(), items)
    assert [item.clause_id for item in parsed] == ["7", "8"]


def test_no_clause_is_deleted() -> None:
    root = clause("7", "7 Addition:", [clause("7.1", "7.1 Not applicable.")])
    parsed = GenericIECRelationshipParser().parse(document(), [root])
    assert len(flatten(parsed)) == 2


def test_parser_returns_deep_copy() -> None:
    original = clause("7", "7 Addition:")
    parsed = GenericIECRelationshipParser().parse(document(), [original])[0]
    assert parsed is not original
    assert original.relationship_to_parent.type is RelationshipType.NONE
