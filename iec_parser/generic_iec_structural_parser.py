"""Generic structural block detection for IEC standard documents."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from iec_parser.generic_document_block_classifier import (
    DocumentBlockType,
    GenericDocumentBlockClassifier,
    SourceTextBlock,
)
from iec_parser.generic_document_stream_resolver import (
    GenericDocumentStreamResolver,
)
from iec_parser.generic_structural_parent_resolver import (
    GenericStructuralParentResolver,
)


BLOCK_TYPES = {
    "CLAUSE",
    "SUBCLAUSE",
    "ANNEX",
    "TABLE",
    "DEFINITION_SECTION",
    "BIBLIOGRAPHY",
    "OTHER",
}


@dataclass(frozen=True)
class StructuralBlock:
    """One ordered, source-backed structural region of a standard."""

    block_type: str
    block_id: str
    title: Optional[str]
    level: int
    parent_id: Optional[str]
    page_start: int
    page_end: int
    raw_text: str
    source_order: int
    semantic_context: str = "MAIN_CLAUSE"
    structural_origin: str = "DIRECT_SOURCE"
    source_supported: bool = True
    normative_text_fabricated: bool = False
    recovery_evidence: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.block_type not in BLOCK_TYPES:
            raise ValueError(f"Unsupported structural block type: {self.block_type}")


@dataclass(frozen=True)
class _Line:
    text: str
    page: int


@dataclass(frozen=True)
class _Heading:
    index: int
    block_type: str
    block_id: str
    title: Optional[str]
    level: int
    semantic_context: str = "MAIN_CLAUSE"


class GenericIECStructuralParser:
    """Detect document hierarchy without interpreting requirement semantics."""

    _CLAUSE_RE = re.compile(
        r"^\s*(?P<id>(?:[A-Z]{1,3}\.)?\d+(?:\.\d+)*)\s+(?P<title>\S.*)\s*$",
        re.IGNORECASE,
    )
    _ANNEX_RE = re.compile(
        r"^\s*Annex\s+(?P<id>[A-Z]{1,3})(?:\s*[-:–—]\s*(?P<title>.*))?\s*$",
        re.IGNORECASE,
    )
    _TABLE_RE = re.compile(
        r"^\s*Table\s+(?P<id>(?:[A-Z]{1,3}\.)?\d+)"
        r"(?:\s*(?:[-:–—]\s*|[a-z]\s*[-:–—]\s*|"
        r"\((?:continued|continuation|concluded|cont\.?)\)\s*)"
        r"(?P<title>.*))?\s*$",
        re.IGNORECASE,
    )
    _BIBLIOGRAPHY_RE = re.compile(r"^\s*Bibliography\s*$", re.IGNORECASE)
    _DEFINITION_TITLE_RE = re.compile(
        r"\b(?:terms?(?:\s+and\s+definitions?)?|definitions?)\b", re.IGNORECASE
    )
    _UNIT_VALUE_RE = re.compile(
        # A standalone ``A`` can be an ampere unit, while ``A`` followed by an
        # alphabetic word is the English indefinite article at the start of a
        # legitimate heading.  Keep the distinction generic and linguistic.
        r"^(?:A(?!\s+[A-Za-z])|V|W|Hz|mm|cm|m|kg|g|J|N|Pa|K|C|°C|IRHD|%)(?:\b|\s|$)",
        re.IGNORECASE,
    )

    def __init__(self, pdf_path: Union[str, os.PathLike[str]]) -> None:
        """Configure the source PDF, validating the path value's type."""

        if not isinstance(pdf_path, (str, os.PathLike)):
            raise TypeError("pdf_path must be a string or path-like value")
        self.pdf_path = Path(pdf_path)
        self.selected_page_start: Optional[int] = None
        self.selected_page_end: Optional[int] = None
        self.coverage_metadata: Dict[str, Any] = {}

    def parse(self) -> List[StructuralBlock]:
        """Extract and parse all text-bearing pages in the configured PDF."""

        if not self.pdf_path.is_file():
            raise FileNotFoundError(f"IEC standard PDF not found: {self.pdf_path}")
        pages = self._extract_pages()
        if not any(page.strip() for page in pages):
            raise ValueError(f"No readable text found in PDF: {self.pdf_path}")
        selected, page_start, page_end = self._select_language_block(pages)
        self.selected_page_start = page_start
        self.selected_page_end = page_end
        blocks = self._parse_selected_pages(selected, page_offset=page_start - 1)
        self.coverage_metadata = self._coverage(selected, blocks)
        resolution = GenericDocumentStreamResolver().resolve(pages)
        self.coverage_metadata["primary_stream_range"] = list(resolution.primary_range)
        self.coverage_metadata["parallel_stream_ranges"] = [
            list(item) for item in resolution.parallel_ranges
        ]
        self.coverage_metadata["stream_selection_signals"] = list(
            resolution.selection_signals
        )
        return blocks

    @classmethod
    def parse_text(cls, text: str) -> List[StructuralBlock]:
        """Parse text, treating form-feed characters as page boundaries."""

        if not text or not text.strip():
            raise ValueError("No readable document text was supplied")
        return cls.parse_pages(text.split("\f"))

    @classmethod
    def parse_pages(cls, pages: Sequence[str]) -> List[StructuralBlock]:
        """Parse a sequence of page texts with one-based page attribution."""

        if isinstance(pages, (str, bytes)):
            raise TypeError("pages must be a sequence of page text strings")
        if not pages or not any(isinstance(page, str) and page.strip() for page in pages):
            raise ValueError("No readable document text was supplied")
        if any(not isinstance(page, str) for page in pages):
            raise TypeError("Every page must be a string")
        selected, page_start, _ = cls._select_language_block(pages)
        return cls._parse_selected_pages(selected, page_offset=page_start - 1)

    @classmethod
    def _parse_selected_pages(
        cls, pages: Sequence[str], page_offset: int
    ) -> List[StructuralBlock]:
        lines = cls._make_lines(pages, page_offset=page_offset)
        headings = cls._detect_headings(lines)
        return GenericStructuralParentResolver().resolve(
            cls._build_blocks(lines, headings)
        )

    @classmethod
    def _select_language_block(
        cls, pages: Sequence[str]
    ) -> Tuple[Sequence[str], int, int]:
        """Select one canonical structural stream from a publication."""

        resolution = GenericDocumentStreamResolver().resolve(pages)
        return resolution.selected_pages, resolution.page_start, resolution.page_end

    @classmethod
    def _coverage(
        cls, pages: Sequence[str], blocks: Sequence[StructuralBlock]
    ) -> Dict[str, Any]:
        """Return conservative structural completeness metadata."""

        parsed = [
            block.block_id for block in blocks
            if block.block_type in {"CLAUSE", "DEFINITION_SECTION"}
            and block.level == 1
        ]
        detected: List[str] = []
        lines = cls._make_lines(pages)
        start = cls._first_scope_index(lines) or 0
        expected = 1
        for index in range(start, len(lines)):
            text = cls._clean_line(lines[index].text)
            if cls._ANNEX_RE.fullmatch(text) or cls._BIBLIOGRAPHY_RE.fullmatch(text):
                break
            heading = cls._clause_heading(lines, index)
            if heading is None or heading.level != 1:
                continue
            clause_id = heading.block_id
            if int(clause_id) == expected:
                detected.append(clause_id)
                expected += 1
        gaps = [item for item in detected if item not in parsed]
        sequence_breaks: List[Dict[str, str]] = []
        for left, right in zip(parsed, parsed[1:]):
            if int(right) != int(left) + 1:
                sequence_breaks.append({"previous": left, "next": right})
        return {
            "document_detected_main_clause_ids": detected,
            "parsed_main_clause_ids": parsed,
            "coverage_gaps": gaps,
            "unexpected_sequence_breaks": sequence_breaks,
            "last_source_main_clause": detected[-1] if detected else None,
            "last_parsed_main_clause": parsed[-1] if parsed else None,
            "needs_review": bool(gaps or sequence_breaks),
        }

    def get_coverage_metadata(self) -> Dict[str, Any]:
        """Return an independent copy of the latest coverage diagnostics."""

        return {
            key: list(value) if isinstance(value, list) else value
            for key, value in self.coverage_metadata.items()
        }

    def _extract_pages(self) -> List[str]:
        try:
            import fitz

            with fitz.open(self.pdf_path) as pdf:
                return [page.get_text("text") for page in pdf]
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(f"Unable to read PDF {self.pdf_path}: {exc}") from exc

    @staticmethod
    def _make_lines(pages: Sequence[str], page_offset: int = 0) -> List[_Line]:
        lines: List[_Line] = []
        for page_number, page in enumerate(pages, start=page_offset + 1):
            normalized = page.replace("\r\n", "\n").replace("\r", "\n")
            for text in normalized.split("\n"):
                lines.append(_Line(text=text.rstrip(), page=page_number))
        return lines

    @classmethod
    def _detect_headings(cls, lines: Sequence[_Line]) -> List[_Heading]:
        headings: List[_Heading] = []
        contents_pages = cls._contents_pages(lines)
        seen_block_ids = set()
        scope_start = cls._first_scope_index(lines)
        content_start = scope_start if scope_start is not None else 0
        classifications = [None] * content_start + GenericDocumentBlockClassifier().classify([
            SourceTextBlock(line.text, line.page, index)
            for index, line in enumerate(lines[content_start:], start=content_start)
        ])
        enforce_top_level_sequence = scope_start is not None
        last_top_level = 0
        active_context = "MAIN_CLAUSE"
        active_annex_id: Optional[str] = None

        for index, line in enumerate(lines):
            text = cls._clean_line(line.text)
            if not text or index < content_start or line.page in contents_pages:
                continue

            annex = cls._ANNEX_RE.fullmatch(text)
            if annex:
                annex_id = annex.group("id").upper()
                key = ("ANNEX", annex_id)
                if key in seen_block_ids:
                    continue
                seen_block_ids.add(key)
                active_context = "ANNEX"
                active_annex_id = annex_id
                title = cls._annex_title(lines, index, annex.group("title"))
                headings.append(
                    _Heading(index, "ANNEX", annex_id, title, 1, "ANNEX")
                )
                continue

            table = cls._TABLE_RE.fullmatch(text)
            if table:
                table_id = table.group("id").upper()
                key = ("TABLE", table_id)
                if key in seen_block_ids:
                    continue
                seen_block_ids.add(key)
                title = cls._clean_optional_title(table.group("title"))
                headings.append(
                    _Heading(index, "TABLE", table_id, title, 1, "TABLE")
                )
                continue

            if cls._BIBLIOGRAPHY_RE.fullmatch(text):
                active_context = "OTHER"
                active_annex_id = None
                headings.append(
                    _Heading(
                        index,
                        "BIBLIOGRAPHY",
                        "BIBLIOGRAPHY",
                        text,
                        1,
                        "OTHER",
                    )
                )
                continue

            classification = classifications[index]
            if classification is None:
                continue
            if classification.block_type not in {
                DocumentBlockType.CLAUSE_HEADING,
                DocumentBlockType.DEFINITION_ENTRY,
            }:
                continue
            clause = cls._clause_heading(lines, index)
            if clause is None:
                continue
            if ("CLAUSE", clause.block_id) in seen_block_ids:
                if active_context == "ANNEX":
                    boundary_id = (
                        f"ANNEX_{active_annex_id or 'UNKNOWN'}_BOUNDARY_{index}"
                    )
                    headings.append(
                        _Heading(
                            index,
                            "OTHER",
                            boundary_id,
                            clause.title,
                            clause.level,
                            "ANNEX",
                        )
                    )
                continue
            if clause.level == 1 and enforce_top_level_sequence:
                number = int(clause.block_id)
                if cls._duplicate_top_level_precedes_support(lines, index, number):
                    continue
                if number != last_top_level + 1:
                    if active_context == "ANNEX":
                        headings.append(
                            _Heading(
                                index,
                                "OTHER",
                                f"ANNEX_{active_annex_id or 'UNKNOWN'}_BOUNDARY_{index}",
                                clause.title,
                                clause.level,
                                "ANNEX",
                            )
                        )
                    continue
                last_top_level = number
            if active_context == "ANNEX":
                context = "ANNEX"
            elif clause.block_type == "DEFINITION_SECTION":
                context = "DEFINITION"
                active_context = "DEFINITION"
            elif clause.level == 1:
                context = "MAIN_CLAUSE"
                active_context = "MAIN_CLAUSE"
                active_annex_id = None
            else:
                context = active_context
            clause = replace(clause, semantic_context=context)
            seen_block_ids.add(("CLAUSE", clause.block_id))
            headings.append(clause)

        return sorted(headings, key=lambda heading: heading.index)

    @classmethod
    def _duplicate_top_level_precedes_support(
        cls, lines: Sequence[_Line], index: int, number: int
    ) -> bool:
        """Reject a footnote/value when the real same-ID heading follows it."""

        prefix = f"{number}."
        for cursor in range(index + 1, min(len(lines), index + 240)):
            candidate = cls._clause_heading(lines, cursor)
            if candidate is None:
                continue
            if candidate.block_id.startswith(prefix):
                return False
            if candidate.level == 1:
                candidate_number = int(candidate.block_id)
                if candidate_number == number:
                    return True
                if candidate_number == number + 1:
                    return False
        return False

    @classmethod
    def _first_scope_index(cls, lines: Sequence[_Line]) -> Optional[int]:
        """Skip front-matter listings when an unambiguous first clause exists."""

        for index, line in enumerate(lines):
            text = cls._clean_line(line.text)
            if re.fullmatch(r"1\s+Scope", text, re.IGNORECASE):
                return index
            if text == "1":
                next_index = cls._next_nonempty_index(lines, index + 1)
                if next_index is not None and cls._clean_line(lines[next_index].text).lower() == "scope":
                    return index
            clause = cls._clause_heading(lines, index)
            if clause and clause.block_id == "1":
                for candidate in range(index + 1, min(len(lines), index + 160)):
                    nested = cls._clause_heading(lines, candidate)
                    if (nested and nested.block_id == "1.1"
                            and GenericDocumentStreamResolver._is_scope_title(
                                nested.title or ""
                            )):
                        return index
        return None

    @staticmethod
    def _contents_pages(lines: Sequence[_Line]) -> set:
        return {
            line.page
            for line in lines
            if re.fullmatch(r"\s*(?:CONTENTS|TABLE OF CONTENTS)\s*", line.text, re.IGNORECASE)
        }

    @classmethod
    def _clause_heading(
        cls, lines: Sequence[_Line], index: int
    ) -> Optional[_Heading]:
        text = cls._clean_line(lines[index].text)
        match = cls._CLAUSE_RE.fullmatch(text)
        heading_index = index
        lowercase_split_supported = False
        if match:
            clause_id = match.group("id")
            title = cls._clean_line(match.group("title"))
        elif re.fullmatch(r"\d+(?:\.\d+)*", text):
            next_index = cls._next_nonempty_index(lines, index + 1)
            if next_index is None or lines[next_index].page != lines[index].page:
                return None
            clause_id = text
            title = cls._clean_line(lines[next_index].text)
            body_index = cls._next_nonempty_index(lines, next_index + 1)
            lowercase_split_supported = bool(
                title[:1].islower()
                and body_index is not None
                and lines[body_index].page == lines[index].page
                and cls._looks_like_normative_body(lines[body_index].text)
            )
            # A table body commonly exposes an isolated integer followed by a
            # compact current/voltage cell (for example ``I10 (A)``).  Such a
            # value has clause-like typography but no heading semantics.
            if cls._looks_like_table_value_title(title):
                return None
            # Some multi-column PDF extractors emit a wrapped heading as
            # ``title prefix / clause number / title suffix``.  Recover that
            # boundary only when both adjacent fragments are prose and the
            # following fragment is visibly a continuation.
            previous_index = cls._previous_nonempty_index(lines, index - 1)
            previous_fragment = (cls._clean_line(lines[previous_index].text)
                                 if previous_index is not None else "")
            if (previous_index is not None
                    and lines[previous_index].page == lines[index].page
                    and cls._CLAUSE_RE.fullmatch(previous_fragment) is None
                    and (title[:1].islower() or cls._looks_like_normative_body(title))
                    and cls._looks_like_heading_fragment(lines[previous_index].text)):
                previous_title = previous_fragment
                title = f"{previous_title} {title}"
                heading_index = previous_index
        else:
            return None

        if not cls._looks_like_heading(clause_id, title) and not lowercase_split_supported:
            return None
        level = clause_id.count(".") + 1
        block_type = "CLAUSE" if level == 1 else "SUBCLAUSE"
        if cls._DEFINITION_TITLE_RE.search(title):
            block_type = "DEFINITION_SECTION"
        return _Heading(heading_index, block_type, clause_id, title, level)

    @classmethod
    def _looks_like_table_value_title(cls, title: str) -> bool:
        """Identify compact numeric/unit cells that cannot be section titles."""

        value = cls._clean_line(title)
        words = re.findall(r"[A-Za-z]+", value)
        return bool(
            len(words) <= 3
            and (
                re.fullmatch(r"[A-Za-z]*\d+(?:[.,]\d+)?\s*\([^)]{1,12}\)", value)
                or re.fullmatch(r"\d+(?:[.,]\d+)?\s*(?:%|°?C|K|V|A|W|Hz|mm|cm|h)", value, re.I)
            )
        )

    @classmethod
    def _looks_like_heading_fragment(cls, value: str) -> bool:
        text = cls._clean_line(value)
        return bool(
            2 <= len(re.findall(r"[A-Za-z]+", text)) <= 18
            and not re.search(r"[.;:]\s*$", text)
            and not cls._looks_like_table_value_title(text)
        )

    @staticmethod
    def _looks_like_normative_body(value: str) -> bool:
        """Return whether text after a split ID reads as clause body, not title."""

        return bool(re.search(
            r"\b(?:shall|must|is\s+required\s+to|are\s+required\s+to|"
            r"is\s+to\s+be|are\s+to\s+be)\b", value, re.IGNORECASE
        ))

    @classmethod
    def _looks_like_heading(cls, clause_id: str, title: str) -> bool:
        if not title or len(title) > 240 or re.search(r"\.{2,}", title):
            return False
        if cls._UNIT_VALUE_RE.match(title):
            return False
        if title.lower().startswith(("times ", "times the ")):
            return False
        if re.fullmatch(r"\d+(?:[-/.]\d+)*", title):
            return False
        first_alpha = next((character for character in title if character.isalpha()), "")
        if not first_alpha or not first_alpha.isupper():
            return False
        # Decimal measurements such as "1.06 times ..." are not hierarchy IDs.
        if "." in clause_id and title.lower().startswith("times"):
            return False
        return True

    @staticmethod
    def _next_nonempty_index(lines: Sequence[_Line], start: int) -> Optional[int]:
        for index in range(start, min(len(lines), start + 4)):
            if lines[index].text.strip():
                return index
        return None

    @staticmethod
    def _previous_nonempty_index(lines: Sequence[_Line], start: int) -> Optional[int]:
        for index in range(start, max(-1, start - 4), -1):
            if lines[index].text.strip():
                return index
        return None

    @classmethod
    def _annex_title(
        cls, lines: Sequence[_Line], index: int, inline_title: Optional[str]
    ) -> Optional[str]:
        parts: List[str] = []
        cleaned_inline = cls._clean_optional_title(inline_title)
        if cleaned_inline:
            parts.append(cleaned_inline)
        cursor = index + 1
        while cursor < len(lines) and cursor <= index + 3:
            candidate = cls._clean_line(lines[cursor].text)
            if candidate:
                if re.fullmatch(r"\((?:normative|informative)\)", candidate, re.IGNORECASE):
                    parts.append(candidate)
                elif not parts or all(part.startswith("(") for part in parts):
                    parts.append(candidate)
                    break
                else:
                    break
            cursor += 1
        return " ".join(parts) or None

    @staticmethod
    def _clean_line(text: str) -> str:
        text = text.translate(str.maketrans({"–": "-", "—": "-", "−": "-"}))
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _clean_optional_title(cls, title: Optional[str]) -> Optional[str]:
        if title is None:
            return None
        cleaned = cls._clean_line(title).strip(" -:")
        return cleaned or None

    @classmethod
    def _build_blocks(
        cls, lines: Sequence[_Line], headings: Sequence[_Heading]
    ) -> List[StructuralBlock]:
        blocks: List[StructuralBlock] = []
        active_clause: Optional[str] = None
        hierarchy_ids = {
            heading.block_id
            for heading in headings
            if heading.block_type in {"CLAUSE", "SUBCLAUSE", "DEFINITION_SECTION"}
        }
        for source_order, heading in enumerate(headings):
            end_index = headings[source_order + 1].index if source_order + 1 < len(headings) else len(lines)
            owned_lines = list(lines[heading.index:end_index])
            while owned_lines and not owned_lines[-1].text.strip():
                owned_lines.pop()
            raw_text = "\n".join(line.text for line in owned_lines).strip()
            page_end = owned_lines[-1].page if owned_lines else lines[heading.index].page

            if heading.block_type in {"CLAUSE", "SUBCLAUSE", "DEFINITION_SECTION"}:
                parent_id = cls._nearest_existing_parent(heading.block_id, hierarchy_ids)
                active_clause = heading.block_id
            elif heading.block_type == "TABLE":
                parent_id = active_clause
            else:
                parent_id = None
                if heading.block_type in {"ANNEX", "BIBLIOGRAPHY"}:
                    active_clause = None

            blocks.append(
                StructuralBlock(
                    block_type=heading.block_type,
                    block_id=heading.block_id,
                    title=heading.title,
                    level=heading.level,
                    parent_id=parent_id,
                    page_start=lines[heading.index].page,
                    page_end=page_end,
                    raw_text=raw_text,
                    source_order=source_order,
                    semantic_context=heading.semantic_context,
                )
            )
        return blocks

    @staticmethod
    def _nearest_existing_parent(
        block_id: str, hierarchy_ids: set
    ) -> Optional[str]:
        """Return the closest explicitly detected ancestor without synthesizing one."""

        components = block_id.split(".")
        while len(components) > 1:
            components.pop()
            candidate = ".".join(components)
            if candidate in hierarchy_ids:
                return candidate
        return None
