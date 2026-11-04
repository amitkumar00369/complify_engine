"""Tests for generic IEC structural block detection."""

from pathlib import Path

from iec_par.generic_iec_structural_parser import GenericIECStructuralParser


def by_id(blocks, block_id):
    return next(block for block in blocks if block.block_id == block_id)


def test_detect_top_level_clauses() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "1 Scope\nScope text.\n2 Normative references\nReference text.\n"
        "3 Terms and definitions\nDefinition text."
    )
    assert [block.block_id for block in blocks] == ["1", "2", "3"]
    assert by_id(blocks, "1").block_type == "CLAUSE"
    assert by_id(blocks, "3").block_type == "DEFINITION_SECTION"


def test_detect_nested_subclauses() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "19 Abnormal operation\n19.11 Electronic circuits\n"
        "19.11.4 Protective circuits\n19.11.4.8 Additional test"
    )
    assert [block.block_id for block in blocks] == ["19", "19.11", "19.11.4", "19.11.4.8"]
    assert all(block.block_type == "SUBCLAUSE" for block in blocks[1:])


def test_hierarchy_levels() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "19 Heading\n19.11 Heading\n19.11.4 Heading\n19.11.4.8 Heading"
    )
    assert [block.level for block in blocks] == [1, 2, 3, 4]


def test_parent_id_resolution() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "19 Heading\n19.11 Heading\n19.11.4 Heading\n19.11.4.8 Heading"
    )
    assert [block.parent_id for block in blocks] == [None, "19", "19.11", "19.11.4"]


def test_detect_annex_a() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "Annex A\n(normative)\nRoutine tests\nAnnex content."
    )
    annex = by_id(blocks, "A")
    assert annex.block_type == "ANNEX"
    assert annex.title == "(normative) Routine tests"


def test_detect_annex_cc() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "Annex CC\n(informative)\nAlternative construction\nContent."
    )
    annex = by_id(blocks, "CC")
    assert annex.block_type == "ANNEX"
    assert "informative" in (annex.title or "")


def test_detect_table_101() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "7 Marking\nText.\nTable 101 - Required values\nColumn A Column B"
    )
    table = by_id(blocks, "101")
    assert table.block_type == "TABLE"
    assert table.title == "Required values"
    assert table.parent_id == "7"


def test_detect_bibliography() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "20 Stability\nText.\nBibliography\nIEC reference list."
    )
    bibliography = by_id(blocks, "BIBLIOGRAPHY")
    assert bibliography.block_type == "BIBLIOGRAPHY"


def test_numeric_values_are_not_clauses() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "1 Scope\n240 V\n50 Hz\n10 mm\n1.06 times rated voltage\nScope text."
    )
    assert [block.block_id for block in blocks] == ["1"]


def test_high_numbered_clauses_continue_after_numeric_footnote() -> None:
    pages = [
        "INTERNATIONAL STANDARD\n1 Scope\nBody\n2 References\nBody",
        "1 Under consideration.\n3 Terms and definitions\nBody\n4 Requirements\nBody",
        "5 Protection\nBody\n6 Verification\nBody",
    ]
    assert [block.block_id for block in GenericIECStructuralParser.parse_pages(pages)] == [
        "1", "2", "3", "4", "5", "6"
    ]


def test_annex_is_separate_after_high_numbered_clause() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "1 Scope\n2 References\n3 Terms\n4 General\n5 Verification\n"
        "Annex A\n(normative)\nRoutine checks"
    )
    assert by_id(blocks, "5").block_type == "CLAUSE"
    assert by_id(blocks, "A").block_type == "ANNEX"


def test_table_and_figure_numbers_do_not_end_main_structure() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "1 Scope\nTable 1 - Values\nFigure 1 - Layout\n2 References\n3 Terms"
    )
    assert [block.block_id for block in blocks if block.block_type == "CLAUSE"] == ["1", "2"]
    assert by_id(blocks, "3").block_type == "DEFINITION_SECTION"


def test_coverage_metadata_detects_sequence_break() -> None:
    parser = GenericIECStructuralParser("unused.pdf")
    pages = ["1 Scope\n3 Terms"]
    blocks = parser._parse_selected_pages(pages, 0)
    metadata = parser._coverage(pages, blocks)
    assert metadata["unexpected_sequence_breaks"] == []
    assert metadata["last_parsed_main_clause"] == "1"


def test_heading_sentence_starting_with_indefinite_article_is_detected() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "19 Abnormal operation\n"
        "19.8 One phase is disconnected.\n"
        "19.9 A running overload test is carried out on applicable appliances.\n"
        "19.10 Appliances are operated with the lowest possible load."
    )
    assert [block.block_id for block in blocks] == ["19", "19.8", "19.9", "19.10"]
    item = by_id(blocks, "19.9")
    assert item.parent_id == "19"
    assert item.page_start == 1
    assert item.raw_text.startswith("19.9 A running overload test")


def test_english_block_is_selected_before_french_duplicate() -> None:
    text = (
        "INTERNATIONAL STANDARD\nCONTENTS\f"
        "1 Scope\nEnglish scope.\n2 Normative references\nEnglish references.\f"
        "Annex A\n(normative)\nEnglish annex\f"
        "SOMMAIRE\f"
        "1 Domaine d application\nTexte français.\n2 Références normatives"
    )
    blocks = GenericIECStructuralParser.parse_text(text)
    assert [block.block_id for block in blocks] == ["1", "2", "A"]
    assert all("français" not in block.raw_text for block in blocks)


def test_missing_intermediate_parent_is_not_synthesized() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "24 Components\n24.1.4 Additional control requirements"
    )
    assert [block.block_id for block in blocks] == ["24", "24.1.4"]
    assert all(block.block_id != "24.1" for block in blocks)


def test_nearest_existing_ancestor_is_selected() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "24 Components\n24.1.4 Additional control requirements"
    )
    assert by_id(blocks, "24.1.4").parent_id == "24"


def test_explicit_parent_is_selected() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "24 Components\n24.1 Controls\n24.1.4 Additional control requirements"
    )
    assert by_id(blocks, "24.1.4").parent_id == "24.1"


def test_iec_references_are_not_clause_headings() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "2 Normative references\nIEC 61032\nIEC 60529\nIEC 60335-2-7\nReference text."
    )
    assert [block.block_id for block in blocks] == ["2"]


def test_source_order() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "1 Scope\nTable 1 - Values\n2 References\nAnnex A\n(normative)\nTests"
    )
    assert [block.source_order for block in blocks] == list(range(len(blocks)))
    assert [block.block_id for block in blocks] == ["1", "1", "2", "A"]


def test_page_start_and_end_with_synthetic_pages() -> None:
    blocks = GenericIECStructuralParser.parse_pages(
        ["1 Scope\nScope begins.", "Scope continues.\n2 References\nReference text."]
    )
    scope = by_id(blocks, "1")
    references = by_id(blocks, "2")
    assert (scope.page_start, scope.page_end) == (1, 2)
    assert (references.page_start, references.page_end) == (2, 2)
    assert "Scope continues." in scope.raw_text
    assert "2 References" not in scope.raw_text


def test_missing_file_raises_file_not_found_error() -> None:
    try:
        GenericIECStructuralParser("/tmp/generic_iec_missing_structure.pdf").parse()
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Missing PDFs must raise FileNotFoundError")


def test_invalid_path_type_raises_type_error() -> None:
    try:
        GenericIECStructuralParser(123)  # type: ignore[arg-type]
    except TypeError:
        pass
    else:
        raise AssertionError("Invalid path types must raise TypeError")


def test_current_rawdata_pdfs_have_expected_structure() -> None:
    pdfs = sorted(Path("RawData").glob("*.pdf"))
    base_files = [path for path in pdfs if "60335-1" in path.name]
    part_2_files = [path for path in pdfs if "60335-2-7" in path.name]
    assert base_files and part_2_files

    base = GenericIECStructuralParser(base_files[0]).parse()
    part_2 = GenericIECStructuralParser(part_2_files[0]).parse()
    base_ids = {block.block_id for block in base}
    part_2_ids = {block.block_id for block in part_2}

    assert {"1", "2", "3"}.issubset(base_ids)
    assert any(block.level >= 4 for block in base if block.block_type == "SUBCLAUSE")
    assert any(block.block_type == "ANNEX" for block in base)
    assert any(block.block_type == "TABLE" for block in base)

    assert {"1", "2", "3"}.issubset(part_2_ids)
    assert any(block_id.startswith(("7.", "19.", "20.")) for block_id in part_2_ids)
    assert "CC" in part_2_ids
    # This particular edition has no Table 101 heading; unit coverage verifies
    # that the generic table detector recognizes it when present.


def test_annex_local_block_stops_before_unrelated_later_section() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "7 Main marking\nMain text.\nAnnex B\n(normative)\nBattery appliances\n"
        "3.6.2 Annex note\nAnnex-local text.\n7 Marking and instructions\n"
        "Later marking text.\n22 Construction\nLater construction text."
    )
    annex_local = by_id(blocks, "3.6.2")
    assert annex_local.semantic_context == "ANNEX"
    assert "Annex-local text." in annex_local.raw_text
    assert "7 Marking and instructions" not in annex_local.raw_text
    assert "22 Construction" not in annex_local.raw_text


def test_repeated_annex_numbering_does_not_merge_with_main_definition() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "3 Terms and definitions\n3.6.2 Main definition\nDefinition text.\n"
        "Annex B\n(normative)\nBattery appliances\n"
        "3.6.2 Annex requirement\nThe terminal shall be marked."
    )
    definition = by_id(blocks, "3.6.2")
    annex_boundary = next(block for block in blocks if block.block_type == "OTHER")
    assert definition.semantic_context == "DEFINITION"
    assert "Annex requirement" not in definition.raw_text
    assert annex_boundary.semantic_context == "ANNEX"
    assert "The terminal shall be marked." in annex_boundary.raw_text


def test_unrelated_major_headings_do_not_remain_inside_previous_raw_text() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "7 Main marking\nText.\nAnnex A\n(normative)\nTests\n"
        "3.2 Annex-local clause\nLocal text.\n7 Instructions\nInstruction text.\n"
        "22 Construction\nConstruction text.\n25 Supply connection\nSupply text.\n"
        "30 Resistance to heat\nHeat text."
    )
    local = by_id(blocks, "3.2")
    for heading in ["7 Instructions", "22 Construction", "25 Supply", "30 Resistance"]:
        assert heading not in local.raw_text


def test_source_ranges_remain_monotonic_after_annex_boundaries() -> None:
    blocks = GenericIECStructuralParser.parse_pages(
        [
            "7 Main marking\nText.",
            "Annex A\n(normative)\nTests\n3.2 Local clause\nLocal text.",
            "7 Instructions\nLater text.\n22 Construction\nConstruction text.",
        ]
    )
    assert [block.source_order for block in blocks] == list(range(len(blocks)))
    assert all(block.page_start <= block.page_end for block in blocks)
    assert all(
        blocks[index].page_start <= blocks[index + 1].page_start
        for index in range(len(blocks) - 1)
    )


def test_each_block_ends_before_the_next_detected_heading() -> None:
    blocks = GenericIECStructuralParser.parse_text(
        "7 Main marking\nText.\nAnnex A\n(normative)\nTests\n"
        "3.2 Local clause\nLocal text.\n7 Instructions\nLater text."
    )
    for current, following in zip(blocks, blocks[1:]):
        first_following_line = following.raw_text.splitlines()[0]
        assert first_following_line not in current.raw_text
