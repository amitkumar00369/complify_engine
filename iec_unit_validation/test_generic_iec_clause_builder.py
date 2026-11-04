"""Tests for building Clause trees from generic structural blocks."""

from pathlib import Path

from iec_par.generic_iec_clause_builder import GenericIECClauseBuilder
from iec_par.generic_iec_kb_models import (
    Clause,
    ClauseType,
    RelationshipType,
)
from iec_par.generic_iec_structural_parser import (
    GenericIECStructuralParser,
    StructuralBlock,
)


def block(
    block_id: str,
    *,
    block_type: str = "CLAUSE",
    parent_id=None,
    level: int = 1,
    order: int = 0,
    title: str = "Heading",
    page_start: int = 1,
    page_end: int = 1,
    raw_text: str = "Raw structural text",
) -> StructuralBlock:
    return StructuralBlock(
        block_type=block_type,
        block_id=block_id,
        title=title,
        level=level,
        parent_id=parent_id,
        page_start=page_start,
        page_end=page_end,
        raw_text=raw_text,
        source_order=order,
    )


def flatten(clauses):
    result = []
    for clause in clauses:
        result.append(clause)
        result.extend(flatten(clause.children))
    return result


def test_convert_one_top_level_clause() -> None:
    clauses = GenericIECClauseBuilder().build(
        [block("1", title="Scope", raw_text="1 Scope\nDocument scope.")]
    )
    assert len(clauses) == 1
    assert isinstance(clauses[0], Clause)
    assert clauses[0].clause_id == "1"
    assert clauses[0].title == "Scope"
    assert clauses[0].clause_type is ClauseType.NORMATIVE


def test_convert_nested_hierarchy() -> None:
    clauses = GenericIECClauseBuilder().build(
        [
            block("7", order=0),
            block("7.12", block_type="SUBCLAUSE", parent_id="7", level=2, order=1),
            block("7.12.1", block_type="SUBCLAUSE", parent_id="7.12", level=3, order=2),
        ]
    )
    assert clauses[0].children[0].clause_id == "7.12"
    assert clauses[0].children[0].children[0].clause_id == "7.12.1"
    assert len(flatten(clauses)) == 3


def test_convert_deep_hierarchy() -> None:
    blocks = [
        block("19", order=0),
        block("19.11", block_type="SUBCLAUSE", parent_id="19", level=2, order=1),
        block("19.11.4", block_type="SUBCLAUSE", parent_id="19.11", level=3, order=2),
        block("19.11.4.8", block_type="SUBCLAUSE", parent_id="19.11.4", level=4, order=3),
    ]
    clauses = GenericIECClauseBuilder.build_from_blocks(blocks)
    assert clauses[0].children[0].children[0].children[0].clause_id == "19.11.4.8"


def test_nearest_real_ancestor_without_synthetic_clause() -> None:
    clauses = GenericIECClauseBuilder().build(
        [
            block("3", order=0),
            block("3.1.9", block_type="SUBCLAUSE", parent_id="3", level=3, order=1),
        ]
    )
    assert clauses[0].children[0].clause_id == "3.1.9"
    assert [clause.clause_id for clause in flatten(clauses)] == ["3", "3.1.9"]


def test_preserve_page_references() -> None:
    clause = GenericIECClauseBuilder().build(
        [block("7", page_start=10, page_end=12)]
    )[0]
    assert clause.source.page_start == 10
    assert clause.source.page_end == 12


def test_preserve_raw_text_exactly() -> None:
    raw_text = "7 Heading\n  Original spacing is retained.\n"
    clause = GenericIECClauseBuilder().build(
        [block("7", raw_text=raw_text)]
    )[0]
    assert clause.source.raw_text == raw_text


def test_preserve_source_order() -> None:
    clauses = GenericIECClauseBuilder().build(
        [
            block("2", order=20),
            block("1", order=10),
            block("1.2", block_type="SUBCLAUSE", parent_id="1", level=2, order=12),
            block("1.1", block_type="SUBCLAUSE", parent_id="1", level=2, order=11),
        ]
    )
    assert [clause.clause_id for clause in clauses] == ["1", "2"]
    assert [clause.clause_id for clause in clauses[0].children] == ["1.1", "1.2"]


def test_ignore_annex_blocks() -> None:
    clauses = GenericIECClauseBuilder().build(
        [block("1", order=0), block("A", block_type="ANNEX", order=1)]
    )
    assert [clause.clause_id for clause in flatten(clauses)] == ["1"]


def test_ignore_table_blocks() -> None:
    clauses = GenericIECClauseBuilder().build(
        [block("1", order=0), block("101", block_type="TABLE", order=1)]
    )
    assert [clause.clause_id for clause in flatten(clauses)] == ["1"]


def test_ignore_bibliography_blocks() -> None:
    clauses = GenericIECClauseBuilder().build(
        [block("1", order=0), block("BIBLIOGRAPHY", block_type="BIBLIOGRAPHY", order=1)]
    )
    assert [clause.clause_id for clause in flatten(clauses)] == ["1"]


def test_duplicate_clause_ids_raise_value_error() -> None:
    try:
        GenericIECClauseBuilder().build([block("7", order=0), block("7", order=1)])
    except ValueError as exc:
        assert "Duplicate clause ID" in str(exc)
    else:
        raise AssertionError("Duplicate clause IDs must raise ValueError")


def test_missing_invalid_parent_does_not_lose_clause() -> None:
    clauses = GenericIECClauseBuilder().build(
        [block("7.12", block_type="SUBCLAUSE", parent_id="7", level=2)]
    )
    assert [clause.clause_id for clause in clauses] == ["7.12"]
    assert clauses[0].relationship_to_parent.parent_clause_id is None


def make_parent_and_child_clauses():
    return GenericIECClauseBuilder().build(
        [
            block("7", order=0),
            block("7.1", block_type="SUBCLAUSE", parent_id="7", level=2, order=1),
        ]
    )


def test_every_clause_has_empty_requirements() -> None:
    created = flatten(make_parent_and_child_clauses())
    assert all(clause.requirements == [] for clause in created)


def test_every_clause_relationship_type_is_none() -> None:
    created = flatten(make_parent_and_child_clauses())
    assert all(
        clause.relationship_to_parent.type is RelationshipType.NONE for clause in created
    )


def test_child_parent_clause_id_is_populated_structurally() -> None:
    clauses = GenericIECClauseBuilder().build(
        [
            block("7", order=0),
            block("7.1", block_type="SUBCLAUSE", parent_id="7", level=2, order=1),
        ]
    )
    created = flatten(clauses)
    assert created[1].relationship_to_parent.parent_clause_id == "7"


def test_void_title_creates_void_clause_type() -> None:
    clause = GenericIECClauseBuilder().build([block("12", title="Void")])[0]
    assert clause.clause_type is ClauseType.VOID


def test_none_input_raises_type_error_and_empty_list_returns_empty() -> None:
    try:
        GenericIECClauseBuilder().build(None)  # type: ignore[arg-type]
    except TypeError:
        pass
    else:
        raise AssertionError("None input must raise TypeError")
    assert GenericIECClauseBuilder().build([]) == []


def test_malformed_empty_clause_id_raises_value_error() -> None:
    malformed = block("")
    try:
        GenericIECClauseBuilder().build([malformed])
    except ValueError as exc:
        assert "non-empty block_id" in str(exc)
    else:
        raise AssertionError("An empty clause ID must raise ValueError")


def test_current_rawdata_pdfs_preserve_all_clause_blocks_once() -> None:
    for pdf_path in sorted(Path("RawData").glob("*.pdf")):
        structural = GenericIECStructuralParser(pdf_path).parse()
        expected = [
            item.block_id
            for item in structural
            if item.block_type in {"CLAUSE", "SUBCLAUSE"}
        ]
        clauses = GenericIECClauseBuilder().build(structural)
        actual = [clause.clause_id for clause in flatten(clauses)]
        assert len(actual) == len(set(actual))
        assert set(actual) == set(expected)
        assert len(actual) == len(expected)
        assert all(clause.source.raw_text for clause in flatten(clauses))
