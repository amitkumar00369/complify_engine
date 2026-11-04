"""Tests for generic IEC document-level metadata parsing."""

from pathlib import Path

from iec_par.generic_iec_document_parser import GenericIECDocumentParser
from iec_par.generic_iec_kb_models import DocumentType


def test_detect_base_standard_from_text() -> None:
    document = GenericIECDocumentParser.parse_text(
        "IEC 60335-1\nPart 1: General requirements"
    )
    assert document.standard_number == "IEC 60335-1"
    assert document.part_number == "1"
    assert document.document_type is DocumentType.BASE


def test_detect_part_2_standard_from_text() -> None:
    document = GenericIECDocumentParser.parse_text(
        "IEC 60335-2-7\nPart 2-7: Particular requirements for washing machines"
    )
    assert document.standard_number == "IEC 60335-2-7"
    assert document.part_number == "2-7"
    assert document.document_type is DocumentType.PART_2


def test_resolve_generic_part_2_parent() -> None:
    document = GenericIECDocumentParser.parse_text(
        "IEC 60335-2-7\nPart 2-7: Particular requirements"
    )
    assert document.parent_standard == "IEC 60335-1"


def test_detect_another_standard_family() -> None:
    document = GenericIECDocumentParser.parse_text(
        "IEC 61010-1\nPart 1: General requirements"
    )
    assert document.standard_number == "IEC 61010-1"
    assert document.document_type is DocumentType.BASE
    assert "60335" not in (document.standard_id or "")


def test_normalize_standard_id() -> None:
    document = GenericIECDocumentParser.parse_text(
        "IEC 61010-1:2015\nEdition 3.0\nPart 1: General requirements"
    )
    assert document.standard_id == "IEC_61010_1_2015"


def test_missing_file_raises_file_not_found_error(tmp_path: Path = Path("/tmp")) -> None:
    missing = tmp_path / "generic_iec_missing_document.pdf"
    try:
        GenericIECDocumentParser(missing).parse()
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("A missing PDF must raise FileNotFoundError")


def test_empty_extracted_text_raises_value_error() -> None:
    try:
        GenericIECDocumentParser.parse_text("  \n\t ")
    except ValueError:
        pass
    else:
        raise AssertionError("Empty extracted text must raise ValueError")


def test_unknown_metadata_is_not_guessed() -> None:
    document = GenericIECDocumentParser.parse_text(
        "Technical publication with no reliable identifying metadata."
    )
    assert document.standard_id is None
    assert document.standard_number is None
    assert document.title is None
    assert document.edition is None
    assert document.year is None
    assert document.part_number is None
    assert document.document_type is DocumentType.UNKNOWN
    assert document.parent_standard is None
    assert document.language is None


def test_current_rawdata_pdfs() -> None:
    pdfs = sorted(Path("RawData").glob("*.pdf"))
    base_files = [path for path in pdfs if "60335-1" in path.name]
    part_2_files = [path for path in pdfs if "60335-2-7" in path.name]
    assert base_files, "Expected a current Part 1 PDF in RawData"
    assert part_2_files, "Expected a current Part 2 PDF in RawData"

    base = GenericIECDocumentParser(base_files[0]).parse()
    part_2 = GenericIECDocumentParser(part_2_files[0]).parse()
    assert base.standard_number == "IEC 60335-1"
    assert base.document_type is DocumentType.BASE
    assert part_2.standard_number == "IEC 60335-2-7"
    assert part_2.document_type is DocumentType.PART_2
    assert part_2.parent_standard == "IEC 60335-1"
