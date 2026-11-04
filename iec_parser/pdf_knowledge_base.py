"""Convert an IEC-style PDF into a clause-oriented JSON knowledge base.

The parser uses PDF typography as well as clause-number patterns.  This is more
reliable than splitting plain text on numbers, because standards contain many
cross-references that look like clause identifiers.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pymupdf


CLAUSE_ID_RE = re.compile(r"^(?P<id>(?:\d+|[A-Z]{1,2})(?:\.\d+)+)\s*(?P<rest>.*)$")
MAIN_CLAUSE_RE = re.compile(r"^(?P<id>\d{1,2})\s{1,}(?P<title>\S.*)$")
ANNEX_CLAUSE_RE = re.compile(r"^(?P<id>[A-Z]{1,2}\.\d+(?:\.\d+)*)\s{1,}(?P<title>\S.*)$")
ANNEX_RE = re.compile(
    r"^Annex\s+(?P<letter>[A-Z]{1,2})\s+\((?P<kind>[^)]+)\)$", re.I
)
LANGUAGE_TITLES = {
    "english", "french", "français", "francais", "german", "deutsch",
    "spanish", "español", "espanol", "italian", "italiano", "portuguese",
    "português", "portugues", "russian", "русский", "chinese", "中文",
    "japanese", "日本語", "korean", "한국어", "arabic", "العربية",
}


def _repair_mojibake(text: str) -> str:
    """Repair UTF-8 text that was decoded once with a legacy single-byte codec."""
    if not re.search(r"(?:Ã.|Â.|â€|â€¦|â‰)", text):
        return text
    for encoding in ("cp1252", "latin1"):
        try:
            repaired = text.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if repaired:
            return repaired
    return (text.replace("â€¦", "…").replace("â€“", "–").replace("â€”", "—")
                .replace("â€˜", "‘").replace("â€™", "’").replace("â€œ", "“")
                .replace("â€", "”").replace("â‰¤", "≤").replace("â‰¥", "≥")
                .replace("Â°C", "°C").replace("Â", ""))

@dataclass(slots=True)
class TextBlock:
    """A cleaned paragraph-like block extracted from one PDF page."""

    page: int
    text: str
    style: str
    extraction_confidence: float = 0.85
    domain_review_status: str = "pending_domain_review"


@dataclass(slots=True)
class Clause:
    """One independently retrievable clause or document section."""

    id: str
    title: str | None
    level: int
    parent_id: str | None
    kind: str
    page_start: int
    page_end: int
    text: str = ""
    paragraphs: list[str] = field(default_factory=list)
    semantic_classification: str = ""
    summary: str = ""
    compliance_requirement: str | None = None
    mandatory: bool = False
    optional: bool = False
    test_required: bool = False
    compliance: dict[str, Any] = field(default_factory=dict)
    evidence_expected: list[str] = field(default_factory=list)
    normative_keywords: list[str] = field(default_factory=list)
    enrichment_method: str = "deterministic_rules_v1"
    title_source: str = "pdf_typography"
    scope_applicability: dict[str, Any] = field(default_factory=dict)
    source_trace: dict[str, Any] = field(default_factory=dict)
    normative_status: str = "undetermined"
    cross_references: list[dict[str, Any]] = field(default_factory=list)
    unresolved_cross_references: list[dict[str, Any]] = field(default_factory=list)
    normative_references: list[dict[str, Any]] = field(default_factory=list)
    requirements: list[dict[str, Any]] = field(default_factory=list)
    tests: list[dict[str, Any]] = field(default_factory=list)
    limits: list[dict[str, Any]] = field(default_factory=list)
    scope_limits: list[dict[str, Any]] = field(default_factory=list)
    notes: list[dict[str, Any]] = field(default_factory=list)
    exceptions: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    table_references: list[dict[str, Any]] = field(default_factory=list)
    annex_type: str | None = None
    extraction_confidence: float = 0.0
    domain_review_status: str = "pending_domain_review"


@dataclass(slots=True)
class DocumentKnowledgeBase:
    """Serializable representation of the parsed document."""

    schema_version: str
    source_file: str
    generated_at: str
    metadata: dict[str, Any]
    statistics: dict[str, int]
    sections: list[Clause]
    unassigned_front_matter: list[TextBlock]


@dataclass(slots=True)
class _RawBlock:
    page: int
    text: str
    font_size: float
    first_font: str
    first_bold: bool
    first_italic: bool
    leading_bold_text: str


class IECDocumentProfile:
    """Select one authoritative English document block from an IEC PDF.

    Consolidated publications sometimes contain a redline document followed by a
    final document.  Clause identifiers are repeated in those blocks, so using
    the first English bookmark produces a redline/final concatenation and lets
    the first occurrence incorrectly win.  The selected range below is therefore
    the *English child of the final-version block*, not simply the first English
    range in the file.
    """

    def __init__(self, document: pymupdf.Document) -> None:
        self._main_roots: set[str] = set()
        self._annex_roots: set[str] = set()
        self._main_body_last_page: int | None = None
        self._english_page_start = 1
        self._english_page_end: int | None = None
        self.document_block: dict[str, Any] = {}
        self.configure(document)

    def configure(self, document: pymupdf.Document) -> None:
        """Infer document-specific clause bounds from the embedded IEC TOC."""
        main_entries: list[tuple[str, int]] = []
        toc = [
            (level, self._normalize(title), page)
            for level, title, page in document.get_toc()
            if page > 0
        ]
        block = self._select_document_block(toc, document.page_count)
        self._english_page_start = block["english_start"]
        self._english_page_end = block["english_end"]
        self.document_block = block

        for _level, raw_title, page in toc:
            title = self._normalize(raw_title)
            main = re.match(r"^(?P<id>\d{1,2})\s+\S", title)
            if main and page > 0:
                main_entries.append((main["id"], page))
            annex = re.match(r"^Annex\s+(?P<id>[A-Z]{1,2})\b", title, re.I)
            if annex:
                self._annex_roots.add(annex["id"].upper())
            annex_clause = re.match(
                r"^(?P<id>[A-Z]{1,2})\.\d+(?:\.\d+)*\s+\S", title
            )
            if annex_clause:
                self._annex_roots.add(annex_clause["id"].split(".", 1)[0])

        self._main_roots = {identifier for identifier, _page in main_entries}
        # Do not use the first annex bookmark as the end of the main body.
        # Regional editions can place a preliminary annex (for example EN
        # Annex ZA) before the embedded IEC document. The parser skips annex
        # content explicitly and can therefore still find the main clauses
        # that follow such front matter.
        self._main_body_last_page = None

    @staticmethod
    def _select_document_block(
        toc: list[tuple[int, str, int]], page_count: int
    ) -> dict[str, Any]:
        """Return the pages for the English final version, if present.

        A version marker owns its descendants until the next marker at the same
        or higher TOC level.  This works for the common ``Redline version`` /
        ``Final version`` layout without relying on clause numbers, which are
        deliberately duplicated between the two documents.
        """
        version_entries = [
            (index, level, title, page)
            for index, (level, title, page) in enumerate(toc)
            if re.search(r"\b(?:redline|final)\s+version\b", title, re.I)
        ]
        final_entries = [entry for entry in version_entries if re.search(r"\bfinal\s+version\b", entry[2], re.I)]
        redline_entries = [entry for entry in version_entries if re.search(r"\bredline\s+version\b", entry[2], re.I)]
        if redline_entries and not final_entries:
            raise ValueError(
                "Refusing to extract a redline-only document: no Final Version block was found."
            )

        if final_entries:
            index, level, title, block_start = final_entries[-1]
            next_block_starts = [
                page for other_index, other_level, _other_title, page in version_entries
                if other_index > index and other_level <= level
            ]
            block_end = min(next_block_starts) - 1 if next_block_starts else page_count
            language_entries = [
                (entry_index, language, page)
                for entry_index, (_entry_level, language, page) in enumerate(toc)
                if index < entry_index and block_start <= page <= block_end
                and language.casefold() in LANGUAGE_TITLES
            ]
            english_entries = [entry for entry in language_entries if entry[1].casefold() == "english"]
            if not english_entries:
                raise ValueError("Final Version block has no English document section.")
            _english_index, _english, english_start = english_entries[0]
            non_english_starts = [
                page for entry_index, language, page in language_entries
                if entry_index > _english_index and language.casefold() != "english"
            ]
            english_end = min(non_english_starts) - 1 if non_english_starts else block_end
            return {
                "version": "final",
                "language": "english",
                "block_start_page": block_start,
                "block_end_page": block_end,
                "english_start": english_start,
                "english_end": english_end,
                "selection_method": "toc_final_version_english_child",
                "rejected_blocks": ["redline"] if redline_entries else [],
            }

        language_entries = [
            (index, title.casefold(), page)
            for index, (_level, title, page) in enumerate(toc)
            if title.casefold() in LANGUAGE_TITLES
        ]
        english_entries = [entry for entry in language_entries if entry[1] == "english"]
        if english_entries:
            english_index, _english, english_start = english_entries[0]
            non_english_starts = [
                page for index, language, page in language_entries
                if index > english_index and language != "english"
            ]
            english_end = min(non_english_starts) - 1 if non_english_starts else page_count
        else:
            english_start, english_end = 1, page_count
        return {
            "version": "single_document",
            "language": "english",
            "block_start_page": 1,
            "block_end_page": page_count,
            "english_start": english_start,
            "english_end": english_end,
            "selection_method": "toc_language_boundary" if english_entries else "whole_document_fallback",
            "rejected_blocks": [],
        }

    @staticmethod
    def _normalize(text: str) -> str:
        text = _repair_mojibake(text)
        text = text.replace("\u00ad", "").replace("\xa0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", " ", text)
        return text.strip()


class IECBlockExtractor:
    """Extract cleaned, English-region text blocks from PDF pages."""

    def __init__(self, profile: IECDocumentProfile) -> None:
        self.profile = profile

    @staticmethod
    def _normalize(text: str) -> str:
        text = _repair_mojibake(text)
        text = text.replace("\u00ad", "").replace("\xa0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", " ", text)
        return text.strip()

    @staticmethod
    def _style(font: str, size: float) -> str:
        bold = "Bold" in font
        italic = "Italic" in font
        if size <= 8.5:
            return "note"
        if bold and italic:
            return "bold_italic"
        if bold:
            return "bold"
        if italic:
            return "italic"
        return "normal"

    @staticmethod
    def _furniture_key(text: str) -> str:
        """Normalize variable page numbers in repeated page furniture."""
        key = text.casefold()
        key = re.sub(r"\b\d+\b", "#", key)
        key = re.sub(r"\s+", " ", key)
        return key.strip(" -|#")

    @staticmethod
    def _is_licence_or_footer(text: str) -> bool:
        """Reject licensing and distribution furniture without vendor names."""
        clean = re.sub(r"\s+", " ", text).casefold()
        licence_markers = (
            "personal copy for", "publication is copyright protected",
            "all rights reserved", "reproduction from", "licence agreement",
            "license agreement", "network licence", "network license",
            "publications provided under", "reproduction or utilization",
            "permission in writing from", "copyright ©", "copyright (c)",
            "licensed to", "licensed by", "single-user licence",
            "single-user license", "copying and networking prohibited",
            "max. networking", "max networking",
        )
        return any(marker in clean for marker in licence_markers)

    @staticmethod
    def _strip_licence_contamination(text: str) -> str:
        """Remove an inline license watermark while retaining preceding content."""
        marker = re.search(
            r"\b(?:licensed\s+(?:to|by)|personal copy for|reproduction\s+from|"
            r"this publication is copyright protected|all rights reserved|"
            r"publications provided under|single-user licen[cs]e|"
            r"copying and networking prohibited|max\.?\s*networking)\b",
            text,
            re.I,
        )
        return text[:marker.start()].rstrip(" ,;:|-") if marker else text

    def _repeating_furniture(self, document: pymupdf.Document) -> set[str]:
        """Find headers/footers repeated across multiple document pages."""
        pages_by_key: dict[str, set[int]] = {}
        eligible_pages = max(
            1,
            (self.profile._english_page_end or document.page_count)
            - self.profile._english_page_start
            + 1,
        )
        for page_index, page in enumerate(document):
            page_number = page_index + 1
            if not (
                self.profile._english_page_start
                <= page_number
                <= (self.profile._english_page_end or 0)
            ):
                continue
            page_height = page.rect.height
            for block in page.get_text("dict", sort=True)["blocks"]:
                if "lines" not in block:
                    continue
                text = self._normalize(
                    " ".join(
                        "".join(span.get("text", "") for span in line.get("spans", []))
                        for line in block["lines"]
                    )
                )
                text = self._strip_licence_contamination(text)
                if not text:
                    continue
                if self._is_licence_or_footer(text):
                    continue
                y0, y1 = block["bbox"][1], block["bbox"][3]
                if y0 <= 72 or y1 >= page_height - 54:
                    key = self._furniture_key(text)
                    if key:
                        pages_by_key.setdefault(key, set()).add(page_number)
        threshold = max(3, min(10, int(eligible_pages * 0.05)))
        return {key for key, pages in pages_by_key.items() if len(pages) >= threshold}

    def blocks(self, document: pymupdf.Document) -> Iterable[_RawBlock]:
        repeating_furniture = self._repeating_furniture(document)
        for page_index, page in enumerate(document):
            page_number = page_index + 1
            if not (
                self.profile._english_page_start
                <= page_number
                <= (self.profile._english_page_end or 0)
            ):
                continue
            page_height = page.rect.height
            for block in page.get_text("dict", sort=True)["blocks"]:
                if "lines" not in block:
                    continue
                spans = [
                    span
                    for line in block["lines"]
                    for span in line.get("spans", [])
                    if span.get("text", "").strip()
                ]
                if not spans:
                    continue
                text = self._normalize(
                    "\n".join(
                        "".join(span["text"] for span in line.get("spans", []))
                        for line in block["lines"]
                    )
                )
                text = self._strip_licence_contamination(text)
                if not text:
                    continue
                y0, y1 = block["bbox"][1], block["bbox"][3]
                # Remove hard-margin furniture and content that repeats in the
                # wider header/footer bands across multiple pages.
                if y0 < 35 or y1 > page_height - 32:
                    continue
                if (
                    (y0 <= 72 or y1 >= page_height - 54)
                    and self._furniture_key(text) in repeating_furniture
                ):
                    continue
                if self._is_licence_or_footer(text):
                    continue
                first = spans[0]
                font = first.get("font", "")
                leading_bold_parts: list[str] = []
                for span in spans:
                    if "Bold" not in span.get("font", ""):
                        break
                    leading_bold_parts.append(span.get("text", ""))
                yield _RawBlock(
                    page=page_index + 1,
                    text=text,
                    font_size=float(first.get("size", 0)),
                    first_font=font,
                    first_bold="Bold" in font,
                    first_italic="Italic" in font,
                    leading_bold_text=self._normalize("".join(leading_bold_parts)),
                )

class IECHeadingDetector:
    """Recognize clause and annex headings using typography and document bounds."""

    def __init__(self, profile: IECDocumentProfile) -> None:
        self.profile = profile

    @staticmethod
    def parent_id(identifier: str) -> str | None:
        if identifier.startswith("front:") or identifier.startswith("back:"):
            return None
        if "." in identifier:
            parent = identifier.rsplit(".", 1)[0]
            return f"annex:{parent}" if parent.isalpha() else parent
        return None

    @staticmethod
    def level(identifier: str) -> int:
        return identifier.count(".") + 1

    def heading(
        self, block: _RawBlock
    ) -> tuple[str, str | None, str, str | None] | None:
        text = block.text
        annex = ANNEX_RE.match(text)
        if annex and block.first_bold:
            return f"annex:{annex['letter']}", None, "annex", None

        match = ANNEX_CLAUSE_RE.match(text)
        if match and block.first_bold:
            remainder = match["title"].strip() or None
            is_titled_heading = block.font_size >= 10.5
            recovered_title = self._title_from_bold(block, match["id"])
            return (
                match["id"],
                remainder if is_titled_heading else recovered_title,
                "annex_clause",
                None if is_titled_heading else remainder,
            )

        match = MAIN_CLAUSE_RE.match(text)
        if match and block.first_bold and block.font_size >= 10:
            identifier = match["id"]
            within_body = (
                self.profile._main_body_last_page is None
                or block.page <= self.profile._main_body_last_page
            )
            valid_root = (
                identifier in self.profile._main_roots
                if self.profile._main_roots
                else 0 <= int(identifier) <= 99
            )
            if within_body and valid_root:
                return identifier, match["title"].strip(), "clause", None

        match = CLAUSE_ID_RE.match(text)
        if match and block.first_bold and block.font_size >= 9.5:
            identifier = match["id"]
            root = identifier.split(".", 1)[0]
            if (
                root.isdigit()
                and (
                    self.profile._main_body_last_page is None
                    or block.page <= self.profile._main_body_last_page
                )
                and (
                    root in self.profile._main_roots
                    if self.profile._main_roots
                    else 0 <= int(root) <= 99
                )
            ) or (
                root.isalpha()
                and (
                    root in self.profile._annex_roots
                    if self.profile._annex_roots
                    else 1 <= len(root) <= 2
                )
            ):
                remainder = match["rest"].strip() or None
                is_titled_heading = block.font_size >= 10.5
                recovered_title = self._title_from_bold(block, identifier)
                return (
                    identifier,
                    remainder if is_titled_heading else recovered_title,
                    "annex_clause" if root.isalpha() else "subclause",
                    None if is_titled_heading else remainder,
                )

        if text in {"FOREWORD", "INTRODUCTION", "Bibliography", "Index of defined terms"}:
            prefix = "front" if text in {"FOREWORD", "INTRODUCTION"} else "back"
            return (
                f"{prefix}:{text.lower().replace(' ', '_')}",
                text.title(),
                prefix,
                None,
            )
        return None

    @staticmethod
    def _title_from_bold(block: _RawBlock, identifier: str) -> str | None:
        title = re.sub(rf"^{re.escape(identifier)}\s*", "", block.leading_bold_text).strip()
        return title or None


class IECClauseEnricher:
    """Convert extracted clause text into structured compliance knowledge."""

    def __init__(self, pdf_path: Path) -> None:
        self.pdf_path = pdf_path

    @staticmethod
    def _first_sentence(text: str, limit: int = 280) -> str:
        clean = re.sub(r"\s+", " ", _repair_mojibake(text)).strip()
        if not clean:
            return ""
        match = re.search(r"(?<=[.!?])\s", clean)
        summary = clean[: match.start() + 1] if match else clean
        return summary if len(summary) <= limit else summary[: limit - 1].rstrip() + "…"
    @staticmethod
    def _semantic_classification(section: Clause) -> str:
        root = section.id.split(".", 1)[0]
        title = (section.title or "").casefold()
        if section.kind in {"front", "back"}:
            return "document_context"
        if section.annex_type == "informative":
            return "informative_annex_content"
        # IEC editions do not consistently assign normative references to
        # Clause 2; older editions may place them in a normative annex.
        if "normative reference" in title:
            return "normative_reference"
        if section.kind == "annex":
            return "annex"
        if root == "1":
            return "scope"
        if root == "3":
            return "definition"
        if section.id in {"9", "18"}:
            return "part_2_dependent"
        if section.kind == "annex_clause":
            return "annex_requirement"
        if re.search(r"\b(test|checked|measurement|measure)\b", section.text, re.I):
            return "test_and_compliance_method"
        return "safety_requirement"

    @staticmethod
    def _clean_definition_title(title: str | None) -> str | None:
        """Normalize dictionary terms without turning their definition into a title."""
        if not title:
            return title
        clean = re.sub(r"\s+", " ", title).strip(" .,:;–—-")
        clean = re.sub(r"^(?:term|definition)\s*[:–—-]\s*", "", clean, flags=re.I)
        clean = re.sub(r"\s*[\*†‡]+\s*$", "", clean)
        words = clean.split()
        # OCR/layout extraction can append a repeated final noun phrase, e.g.
        # "self-resetting thermal cut-out thermal cut-out".
        for size in range(min(len(words) // 2, 6), 0, -1):
            if words[:-size] and words[-size:] == words[-2 * size:-size]:
                words = words[:-size]
                break
        # Another frequent layout artifact is a definition's opening noun
        # phrase joining its term, e.g. ``hand-held appliance portable
        # appliance``. The repeated terminal noun identifies the real term.
        if len(words) >= 3:
            terminal = words[-1].casefold()
            prior = [index for index, word in enumerate(words[:-1]) if word.casefold() == terminal]
            if prior:
                words = words[:prior[0] + 1]
        return " ".join(words) or None
    def enrich(self, section: Clause) -> None:
        # This method is intentionally a full overwrite of every derived field.
        # Sections are only enriched after the authoritative document block has
        # been selected, so no redline-derived requirement, test, limit, or
        # acceptance condition can survive into the output.
        text = section.text
        lower = text.lower()
        if not section.title:
            seed = self._first_sentence(text, 120)
            words = seed.split()
            section.title = (
                " ".join(words[:12]).rstrip(".,;:")
                if words
                else f"Clause {section.id}"
            )
            section.title_source = (
                "generated_from_clause_text" if words else "generated_from_clause_id"
            )
        else:
            section.title_source = "pdf_typography"
        keywords = [
            keyword
            for keyword in ("shall", "shall not", "must", "should", "may", "is checked")
            if keyword in lower
        ]
        semantic_classification = self._semantic_classification(section)
        if semantic_classification == "definition":
            section.title = self._clean_definition_title(section.title)
        normative_text = self._normative_text(section, semantic_classification)
        mandatory = bool(
            re.search(r"\b(shall|shall not|must|required)\b", normative_text, re.I)
        )
        # "May" frequently expresses possibility (for example "may occur"),
        # not an optional compliance path. Optionality is only asserted for an
        # explicit labelled option.
        optional = not mandatory and bool(
            re.search(r"\b(optional requirement|optional alternative)\b", normative_text, re.I)
        )
        procedure_pattern = re.compile(
            r"\b(compliance is checked by|checked by the following|"
            r"following test|test is made|test is carried out|"
            r"subjected to (?:the |a )?test|(?:is|are|shall be) tested|"
            r"measure(?:d|ment) (?:by|with|at|"
            r"in accordance)|test voltage|test current|test temperature)\b",
            re.I,
        )
        test_required = bool(procedure_pattern.search(normative_text))
        cross_references = self._cross_references(text)
        # Do not infer unresolved references merely because a clause mentions a
        # test. That produced false review items for ordinary test descriptions.
        unresolved_references: list[dict[str, Any]] = []
        requirement_sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text))
            if re.search(r"\b(shall|shall not|must|required)\b", sentence, re.I)
            and sentence.casefold() in normative_text.casefold()
        ]
        compliance_requirement = " ".join(requirement_sentences[:3]) or None
        # Structural classification has precedence over modal-word detection.
        if section.kind in {"front", "back"} or semantic_classification in {
            "definition", "scope", "normative_reference", "informative_annex_content"
        }:
            mandatory = False
            optional = False
            test_required = False
            compliance_requirement = None
        test_extraction_allowed = semantic_classification not in {
            "definition", "normative_reference", "document_context", "scope",
            "informative_annex_content",
        } and section.kind not in {"front", "back"}
        if semantic_classification in {
            "document_context", "normative_reference", "informative_annex_content"
        } or section.kind in {"front", "back"}:
            # Front matter is retained for provenance and search, but it must
            # never create deterministic compliance requirements or limits.
            structured = {
                "requirements": [], "tests": [], "limits": [], "scope_limits": [],
                "notes": [], "exceptions": [],
            }
        else:
            structured = self._structured_knowledge(
                section, normative_text, test_extraction_allowed,
                scope_only=semantic_classification == "scope",
            )
        self._annotate_test_inputs(structured["tests"])
        if structured["tests"] and semantic_classification not in {
            "definition",
            "normative_reference",
            "document_context",
            "scope",
        }:
            test_required = True
        section.semantic_classification = semantic_classification
        section.summary = self._first_sentence(text) or section.title
        section.compliance_requirement = compliance_requirement
        section.mandatory = mandatory
        section.optional = optional
        section.test_required = test_required
        section.requirements = structured["requirements"]
        section.tests = structured["tests"]
        section.limits = structured["limits"]
        section.scope_limits = structured["scope_limits"]
        section.notes = structured["notes"]
        section.exceptions = structured["exceptions"]
        pass_condition, fail_condition = self._acceptance_criteria(section, structured)
        section.compliance = {
            "evaluation_status": "not_evaluated",
            "pass_condition": pass_condition,
            "fail_condition": fail_condition,
            "test_evaluation_readiness": self._test_evaluation_readiness(
                test_required, structured, pass_condition
            ),
        }
        section.evidence_expected = (
            ["test_result", "measured_values", "test_conditions"]
            if test_required
            else ["documented_conformity"]
            if mandatory
            else []
        )
        section.normative_keywords = keywords
        section.cross_references = cross_references
        section.unresolved_cross_references = unresolved_references
        section.normative_references = (
            self._normative_references(section)
            if semantic_classification == "normative_reference"
            else []
        )
        section.normative_status = (
            "informative_note"
            if text.lstrip().upper().startswith("NOTE")
            else "mandatory_requirement"
            if mandatory
            else "optional_provision"
            if optional
            else "informative_or_contextual"
        )
        section.scope_applicability = self._scope_applicability(
            section, semantic_classification, mandatory, optional
        )
        if section.scope_limits:
            section.scope_applicability["scope_limits"] = section.scope_limits
        section.extraction_confidence = self._extraction_confidence(
            section, semantic_classification
        )
        section.source_trace = {
            "source_file": self.pdf_path.name,
            "page_start": section.page_start,
            "page_end": section.page_end,
            "clause_id": section.id,
        }
    def _structured_knowledge(
        self,
        section: Clause,
        normative_text: str,
        test_extraction_allowed: bool,
        scope_only: bool = False,
    ) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {
            "requirements": [],
            "tests": [],
            "limits": [],
            "scope_limits": [],
            "notes": [],
            "exceptions": [],
        }
        counters: dict[str, int] = {key: 0 for key in result}

        def add(category: str, text: str, normative: bool) -> None:
            clean = re.sub(r"\s+", " ", text).strip()
            if not clean:
                return
            parsed_limits = self._parse_limits(clean) if category in {"limits", "scope_limits"} else [None]
            for parsed_limit in parsed_limits:
                counters[category] += 1
                prefix = {
                    "requirements": "REQ",
                    "tests": "TEST",
                    "limits": "LIMIT",
                    "scope_limits": "SCOPE-LIMIT",
                    "notes": "NOTE",
                    "exceptions": "EXC",
                }[category]
                item: dict[str, Any] = {
                    "id": f"{section.id}-{prefix}-{counters[category]:03d}",
                    "text": clean,
                    "normative": normative,
                    "source_page_start": section.page_start,
                    "source_page_end": section.page_end,
                    "extraction_confidence": 0.90 if normative else 0.82,
                    "domain_review_status": "pending_domain_review",
                }
                if parsed_limit is not None:
                    item.update(parsed_limit)
                result[category].append(item)

        for paragraph in section.paragraphs:
            clean_paragraph = re.sub(r"\s+", " ", paragraph).strip()
            if re.match(r"^(NOTE|EXAMPLE)\b", clean_paragraph, re.I):
                add("notes", clean_paragraph, False)
                continue
            sentences = re.split(r"(?<=[.!?])\s+", clean_paragraph)
            for sentence in sentences:
                if not sentence.strip():
                    continue
                if re.search(
                    r"\b(unless|except(?:ion)?|however|does not apply|need not)\b",
                    sentence,
                    re.I,
                ):
                    add("exceptions", sentence, sentence.casefold() in normative_text.casefold())
                # Preserve every normative statement as a requirement even when
                # it is also a test method or a numeric limit.  IEC clauses
                # commonly combine these concepts in one sentence; treating the
                # categories as mutually exclusive left mandatory clauses with
                # an empty requirements array.
                is_normative_requirement = (
                    not scope_only
                    and bool(re.search(r"\b(?:shall|shall not|must|required)\b", sentence, re.I))
                    and sentence.casefold() in normative_text.casefold()
                )
                if is_normative_requirement:
                    add("requirements", sentence, True)
                if test_extraction_allowed and re.search(
                    r"\b(test(?:ed|ing)?|compliance is checked|measurement|measured)\b",
                    sentence,
                    re.I,
                ):
                    add("tests", sentence, sentence.casefold() in normative_text.casefold())
                elif re.search(
                    r"(?:â‰¤|â‰¥|Â±|<|>|\bnot (?:more|less) than\b|\bat least\b|"
                    r"\bat most\b|\bmaximum\b|\bminimum\b|\d+(?:[.,]\d+)?\s*"
                    r"(?:[ \u00a0\u202f]\d{3})*(?:V|A|W|Hz|K|Â°C|mm|cm|mA|MPa|N|s|min|h)\b)",
                    sentence,
                    re.I,
                ):
                    add(
                        "scope_limits" if scope_only else "limits",
                        sentence,
                        False if scope_only else sentence.casefold() in normative_text.casefold(),
                    )
        return result

    @classmethod
    def _annotate_test_inputs(cls, tests: list[dict[str, Any]]) -> None:
        """Attach normalized, machine-readable inputs to each extracted test."""
        for test in tests:
            quantities = [
                quantity for quantity in cls._parse_limits(test["text"])
                if quantity["value"] is not None
            ]
            test["evaluation_inputs"] = quantities
            test["evaluation_readiness"] = (
                "ready_with_numeric_conditions"
                if any(quantity["operator"] and quantity["numeric_normalization_status"] == "normalized"
                       for quantity in quantities)
                else "procedure_extracted"
                if test["normative"] else "needs_domain_review"
            )

    @staticmethod
    def _test_evaluation_readiness(
        test_required: bool,
        structured: dict[str, list[dict[str, Any]]],
        pass_condition: str | None,
    ) -> dict[str, Any]:
        """Describe whether an IEC test can be evaluated without re-parsing text."""
        if not test_required:
            return {
                "status": "not_applicable",
                "reason": "No deterministic test procedure was extracted.",
                "numeric_criteria_count": 0,
            }
        numeric_criteria = [
            item for item in structured["limits"]
            if item.get("operator")
            and item.get("numeric_normalization_status") == "normalized"
        ]
        numeric_criteria.extend(
            quantity
            for test in structured["tests"]
            for quantity in test.get("evaluation_inputs", [])
            if quantity.get("operator")
            and quantity.get("numeric_normalization_status") == "normalized"
        )
        if numeric_criteria and pass_condition:
            status = "ready_for_numeric_evaluation"
            reason = "Test procedure, normalized numeric criteria, and acceptance condition are present."
        elif pass_condition:
            status = "ready_for_procedure_evaluation"
            reason = "Test procedure and acceptance condition are present; no normalized numeric criterion was extracted."
        else:
            status = "needs_acceptance_criteria"
            reason = "A test procedure was extracted without a deterministic acceptance condition."
        return {
            "status": status,
            "reason": reason,
            "numeric_criteria_count": len(numeric_criteria),
            "test_procedure_count": len(structured["tests"]),
        }

    @staticmethod
    def _parse_limits(text: str) -> list[dict[str, Any]]:
        """Normalize every explicit quantity in a limit sentence."""
        normalized = (text.replace("â‰¤", "≤")
                      .replace("â‰¥", "≥")
                      .replace("Â±", "±")
                      .replace("Â°C", "°C"))
        value_pattern = re.compile(
            # IEC documents commonly use a space, NBSP, or narrow NBSP as a
            # thousands separator (for example ``1 000 V``).  Match that as
            # one token before conversion; otherwise the old expression found
            # only the trailing ``000 V`` and produced 0 V.
            r"(?P<value>[+-]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d+)?)\s*"
            r"(?P<unit>°C|MΩ|kΩ|Ω|µA|μA|mA|kVA|VA|kV|kJ|J|MPa|kPa|Pa|MHz|kHz|Hz|mm(?:2|²)|mm|cm|ms|min|h|s|kg|g|dB|rpm|r/min|V|A|W|K|N|%)\b",
        )
        operator_patterns = (
            (r"\bnot more than\b|\bno (?:more|greater) than\b|\bat most\b|"
             r"\bmaximum(?: of)?\b|\b(?:shall|must|does?|do)\s+not\s+exceed\b|"
             r"\bnot\s+exceed\b|\bdoes not exceed\b|"
             r"\bnot exceeding\b|\bup to(?: and including)?\b|≤|<=", "<="),
            (r"\bnot less than\b|\bno less than\b|\bat least\b|"
             r"\bminimum(?: of)?\b|\b(?:shall|must)\s+be\s+at\s+least\b|"
             r"\bor more\b|≥|>=", ">="),
            (r"(?<!not )(?<!no )\bless than\b|(?<![<>])<(?![=>])", "<"),
            (r"(?<!not )(?<!no )\bmore than\b|(?<!not )(?<!no )\bgreater than\b|"
             r"(?<!not )\bexceed(?:s|ing)?\b|(?<![<>])>(?![=>])", ">"),
            (r"\bequal to\b|(?<![<>])=(?!=)", "=="),
        )
        matches = list(value_pattern.finditer(normalized))
        parsed: list[dict[str, Any]] = []
        inherited_operator: str | None = None
        for index, value_match in enumerate(matches):
            prefix = normalized[:value_match.start()]
            previous_end = matches[index - 1].end() if index else 0
            local_prefix = normalized[previous_end:value_match.start()]
            found = [
                (match.start(), symbol, match)
                for pattern, symbol in operator_patterns
                for match in re.finditer(pattern, prefix, re.I)
            ]
            operator_match = max(found, default=None, key=lambda item: item[0])
            local_has_operator = bool(operator_match and operator_match[0] >= previous_end)
            operator = (
                operator_match[1] if local_has_operator
                else inherited_operator if inherited_operator
                else operator_match[1] if operator_match
                else None
            )
            inherited_operator_used = bool(
                operator and not local_has_operator and inherited_operator == operator
            )
            if index + 1 < len(matches) and re.search(r"\b(?:between|from)\b", local_prefix, re.I):
                operator = ">="
            if index and re.search(r"\b(?:and|to)\s*$", local_prefix, re.I):
                before_start = normalized[:matches[index - 1].start()]
                if re.search(r"\b(?:between|from)\b[^.!?;]*$", before_start, re.I):
                    operator = "<="
            # Some standards place the comparison after the quantity, for
            # example "20 J or more" or "5 mm or less".
            suffix_end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
            local_suffix = normalized[value_match.end():suffix_end]
            if re.match(r"\s*or more\b", local_suffix, re.I):
                operator = ">="
            elif re.match(r"\s*or less\b", local_suffix, re.I):
                operator = "<="
            if operator:
                inherited_operator = operator
            sentence_start = max(
                normalized.rfind(mark, 0, value_match.start())
                for mark in (".", ";", ":")
            ) + 1
            sentence_end_candidates = [
                position for mark in (".", ";")
                if (position := normalized.find(mark, value_match.end())) != -1
            ]
            sentence_end = min(sentence_end_candidates, default=len(normalized))
            sentence = normalized[sentence_start:sentence_end].strip()
            local_value_start = value_match.start() - sentence_start
            local_value_end = value_match.end() - sentence_start
            semantic_parameter, parameter, parameter_resolution = IECClauseEnricher._parameter_details(
                sentence, local_value_start, local_value_end, value_match["unit"]
            )
            raw_value = float(
                re.sub(r"[ \u00a0\u202f]", "", value_match["value"]).replace(",", ".")
            )
            numeric_normalization = IECClauseEnricher._numeric_normalization(
                raw_value, value_match["unit"]
            )
            parsed.append({
                "parameter": semantic_parameter,
                "parameter_context": parameter,
                "operator": operator,
                "value": raw_value,
                "unit": value_match["unit"],
                "matched_text": value_match.group(0),
                "normalization_status": "parsed" if operator else "needs_domain_review",
                "operator_validation": (
                    "validated_normative_phrase"
                    if local_has_operator and operator_match
                    else "inherited_range_operator" if inherited_operator_used
                    else "needs_domain_review"
                ),
                "parameter_resolution": parameter_resolution,
                **numeric_normalization,
            })
        return parsed or [{
            "parameter": None, "parameter_context": None,
            "operator": None, "value": None, "unit": None,
            "matched_text": None, "normalization_status": "needs_domain_review",
        }]

    @staticmethod
    def _numeric_normalization(value: float, unit: str) -> dict[str, Any]:
        """Convert supported IEC quantities to stable evaluation units.

        The raw source value and unit are retained.  Canonical fields make
        comparisons safe across common IEC prefixes (for example kV vs V and
        min vs s) without conflating physical dimensions.
        """
        conversions: dict[str, tuple[str, str, float, float]] = {
            "V": ("voltage", "V", 1.0, 0.0), "kV": ("voltage", "V", 1_000.0, 0.0),
            "A": ("current", "A", 1.0, 0.0), "mA": ("current", "A", 0.001, 0.0),
            "µA": ("current", "A", 0.000001, 0.0), "μA": ("current", "A", 0.000001, 0.0),
            "Hz": ("frequency", "Hz", 1.0, 0.0), "kHz": ("frequency", "Hz", 1_000.0, 0.0),
            "MHz": ("frequency", "Hz", 1_000_000.0, 0.0),
            "ms": ("duration", "s", 0.001, 0.0), "s": ("duration", "s", 1.0, 0.0),
            "min": ("duration", "s", 60.0, 0.0), "h": ("duration", "s", 3_600.0, 0.0),
            "Ω": ("resistance", "Ω", 1.0, 0.0), "kΩ": ("resistance", "Ω", 1_000.0, 0.0),
            "MΩ": ("resistance", "Ω", 1_000_000.0, 0.0),
            "W": ("power", "W", 1.0, 0.0), "VA": ("apparent_power", "VA", 1.0, 0.0),
            "kVA": ("apparent_power", "VA", 1_000.0, 0.0),
            "J": ("energy", "J", 1.0, 0.0), "kJ": ("energy", "J", 1_000.0, 0.0),
            "Pa": ("pressure", "Pa", 1.0, 0.0), "kPa": ("pressure", "Pa", 1_000.0, 0.0),
            "MPa": ("pressure", "Pa", 1_000_000.0, 0.0),
            "mm": ("length", "m", 0.001, 0.0), "cm": ("length", "m", 0.01, 0.0),
            "mm2": ("area", "m²", 0.000001, 0.0), "mm²": ("area", "m²", 0.000001, 0.0),
            "N": ("force", "N", 1.0, 0.0), "kg": ("mass", "kg", 1.0, 0.0),
            "g": ("mass", "kg", 0.001, 0.0), "%": ("percentage", "%", 1.0, 0.0),
            "°C": ("temperature", "°C", 1.0, 0.0), "K": ("temperature", "°C", 1.0, -273.15),
        }
        conversion = conversions.get(unit)
        if not conversion:
            return {
                "dimension": None,
                "normalized_value": None,
                "normalized_unit": None,
                "numeric_normalization_status": "needs_domain_review",
            }
        dimension, normalized_unit, multiplier, offset = conversion
        normalized_value = round(value * multiplier + offset, 12)
        return {
            "dimension": dimension,
            "normalized_value": normalized_value,
            "normalized_unit": normalized_unit,
            "numeric_normalization_status": "normalized",
        }

    @staticmethod
    def _parameter_details(
        text: str, value_start: int, value_end: int, unit: str | None = None
    ) -> tuple[str | None, str | None, str]:
        """Resolve a parameter using full sentence context and unit validation.

        IEC sentences often contain several engineering quantities.  A nearby
        word such as ``current`` must not label a kV value, and an earlier
        ``voltage`` must not label a duration.  Unit family is therefore a
        hard compatibility rule, while the full sentence supplies the most
        specific matching source phrase.
        """
        unit_families = {
            "V": "voltage", "kV": "voltage",
            "A": "current", "mA": "current", "µA": "current", "μA": "current",
            "Hz": "frequency", "kHz": "frequency", "MHz": "frequency",
            "ms": "duration", "s": "duration", "min": "duration", "h": "duration",
            "Ω": "resistance", "kΩ": "resistance", "MΩ": "resistance",
            "W": "power", "VA": "power", "kVA": "power",
            "J": "energy", "kJ": "energy",
            "°C": "temperature", "K": "temperature",
            "Pa": "pressure", "kPa": "pressure", "MPa": "pressure",
            "mm": "length", "cm": "length", "mm2": "area", "mm²": "area",
            "N": "force", "%": "percentage", "kg": "mass", "g": "mass",
        }
        unit_family = unit_families.get(unit or "")
        context = text.casefold()
        vocabulary = (
            ("fault loop impedance", "fault_loop_impedance", "resistance"),
            ("insulation resistance", "insulation_resistance", "resistance"),
            ("leakage current", "leakage_current", "current"),
            ("touch current", "touch_current", "current"),
            ("rated input voltage", "rated_input_voltage", "voltage"),
            ("test voltage", "test_voltage", "voltage"),
            ("rated voltage", "rated_voltage", "voltage"),
            ("supply voltage", "supply_voltage", "voltage"),
            ("withstand voltage", "withstand_voltage", "voltage"),
            ("test current", "test_current", "current"),
            ("rated current", "rated_current", "current"),
            ("rated frequency", "rated_frequency", "frequency"),
            ("supply frequency", "supply_frequency", "frequency"),
            ("operating altitude", "operating_altitude", "length"),
            ("ambient temperature", "ambient_temperature", "temperature"),
            ("test temperature", "test_temperature", "temperature"),
            ("creepage distance", "creepage_distance", "length"),
            ("clearance", "clearance", "length"),
            ("temperature", "temperature", "temperature"),
            ("frequency", "frequency", "frequency"),
            ("voltage", "voltage", "voltage"),
            ("current", "current", "current"),
            ("power", "power", "power"),
            ("altitude", "altitude", "length"),
            ("distance", "distance", "length"),
            ("duration", "duration", "duration"),
            ("time", "time", "duration"),
        )
        candidates = []
        for phrase, name, family in vocabulary:
            if unit_family and family != unit_family:
                continue
            for match in re.finditer(rf"\b{re.escape(phrase)}\b", context):
                # Prefer phrases immediately preceding a value, then the
                # nearest one.  This handles multiple limits in one sentence.
                absolute_end = match.end()
                candidates.append((0 if absolute_end <= value_start else 1,
                                   abs(absolute_end - value_start), -len(phrase),
                                   phrase, name))
        if not candidates:
            if unit_family:
                return unit_family, f"{unit_family} (unit validated)", "unit_inferred"
            return None, None, "needs_domain_review"
        _side, _distance, _specificity, phrase, name = min(candidates)
        return name, phrase, "context_and_unit_validated" if unit_family else "context_validated"

    @staticmethod
    def _semantic_parameter_name(
        text: str, value_start: int, value_end: int, fallback: str | None = None
    ) -> str | None:
        """Backward-compatible stable parameter-name view."""
        name, _context, _resolution = IECClauseEnricher._parameter_details(
            text, value_start, value_end
        )
        return name or fallback

    @staticmethod
    def _parse_limit(text: str) -> dict[str, Any]:
        """Backward-compatible first-limit view."""
        return IECClauseEnricher._parse_limits(text)[0]
    @staticmethod
    def _acceptance_criteria(
        section: Clause, structured: dict[str, list[dict[str, Any]]]
    ) -> tuple[str | None, str | None]:
        applicable: list[str] = []
        seen: set[str] = set()
        for category in ("requirements", "tests", "limits"):
            for item in structured[category]:
                if not item["normative"]:
                    continue
                criterion = item["text"]
                key = re.sub(r"[^a-z0-9]+", " ", criterion.casefold()).strip()
                if key and key not in seen:
                    seen.add(key)
                    applicable.append(criterion)
        if not applicable:
            return None, None
        criteria = " | ".join(applicable[:3])
        return (
            f"Clause {section.id} passes when the following source-derived "
            f"criteria are satisfied: {criteria}",
            f"Clause {section.id} fails when any applicable source-derived "
            f"criterion is not satisfied or its stated limit is violated: {criteria}",
        )
    @staticmethod
    def _normative_text(section: Clause, classification: str) -> str:
        """Return only text eligible to create normative requirements."""
        if section.kind in {"front", "back"} or classification in {
            "definition",
            "normative_reference",
            "document_context",
        }:
            return ""
        retained: list[str] = []
        for paragraph in section.paragraphs:
            stripped = paragraph.strip()
            if re.match(r"^(NOTE|EXAMPLE)\b", stripped, re.I):
                continue
            if re.search(
                r"\b(copyright|all rights reserved|publication|reproduction|"
                r"IEC shall not be held responsible|no liability shall)\b",
                stripped,
                re.I,
            ):
                continue
            # Quoted material is evidence/context, not a requirement originating
            # in this clause.
            stripped = re.sub(r'["â€œ][^"â€]*["â€]', "", stripped)
            retained.append(stripped)
        return "\n".join(retained)
    @staticmethod
    def _cross_references(text: str) -> list[dict[str, Any]]:
        """Return deduplicated, typed cross-reference objects."""
        references: dict[tuple[str, str], dict[str, Any]] = {}
        patterns = (
            ("clause", r"\b(?:Clause|Subclause)\s+([A-Z]?\d+(?:\.\d+)*)"),
            ("figure", r"\bFigure\s+([A-Z]?\d+(?:\.\d+)*)"),
            ("table", r"\bTable\s+([A-Z]?\d+(?:\.\d+)*)"),
            ("annex", r"\bAnnex\s+([A-Z](?:\.\d+(?:\.\d+)*)?)"),
            ("external_standard", r"\b(IEC\s+\d+(?:-\d+)*(?::\d{4})?)"),
        )
        for reference_type, pattern in patterns:
            for match in re.finditer(pattern, text, re.I):
                target = re.sub(r"\s+", " ", match.group(1)).strip().upper()
                key = (reference_type, target)
                references[key] = {
                    "type": reference_type,
                    "target": target,
                    "raw_text": match.group(0).strip(),
                    "resolution_status": "external" if reference_type == "external_standard" else "resolved_syntactically",
                    "extraction_confidence": 0.96,
                    "domain_review_status": "pending_domain_review",
                }
        return [references[key] for key in sorted(references)]
    @staticmethod
    def _normative_references(section: Clause) -> list[dict[str, Any]]:
        """Extract deduplicated standard references from a reference section."""
        references: dict[str, dict[str, Any]] = {}
        identifier_pattern = re.compile(
            r"\b(?P<identifier>"
            r"(?:ISO/IEC|IEC|ISO|EN|CISPR|ASTM)"
            r"(?:\s+(?:TR|TS|PAS|Guide))?\s+"
            r"[A-Z0-9]+(?:[-–][A-Z0-9]+)*"
            r"(?::\d{4})?"
            r"(?:/(?:AMD|COR)\d+(?::\d{4})?)*"
            r")",
            re.I,
        )
        for paragraph in section.paragraphs:
            clean = re.sub(r"\s+", " ", paragraph).strip().rstrip(".")
            matches = list(identifier_pattern.finditer(clean))
            for index, match in enumerate(matches):
                identifier = re.sub(r"\s+", " ", match["identifier"]).upper()
                organization_match = re.match(
                    r"(?P<org>ISO/IEC|IEC|ISO|EN|CISPR|ASTM)(?:\s+(?:TR|TS|PAS|GUIDE))?\s+",
                    identifier,
                )
                organization = organization_match["org"] if organization_match else identifier.split()[0]
                number_part = identifier[organization_match.end():] if organization_match else identifier.split(maxsplit=1)[1]
                year_match = re.search(r":(\d{4})(?:/|$)", identifier)
                title_start = match.end()
                title_end = matches[index + 1].start() if index + 1 < len(matches) else len(clean)
                title = clean[title_start:title_end].lstrip(" :,;–-").strip() or None
                references[identifier] = {
                    "identifier": identifier,
                    "organization": organization,
                    "document_number": number_part.split(":", 1)[0],
                    "edition_year": int(year_match.group(1)) if year_match else None,
                    "title": title,
                    "dated": bool(year_match),
                    "source_page_start": section.page_start,
                    "source_page_end": section.page_end,
                    "extraction_confidence": 0.95,
                    "domain_review_status": "pending_domain_review",
                }
        return [references[key] for key in sorted(references)]
    @staticmethod
    def _scope_applicability(section: Clause, classification: str,
                             mandatory: bool, optional: bool) -> dict[str, Any]:
        scope_text = section.text if classification == "scope" else None
        return {
            "status": "informative_annex" if section.annex_type == "informative" else "requires_product_context" if classification != "scope" else "document_scope",
            "basis": "annex_heading" if section.annex_type else "clause_1_scope" if classification != "scope" else "source_text",
            "annex_type": section.annex_type,
            "scope_text": IECClauseEnricher._first_sentence(scope_text, 500) if scope_text else None,
            "requirement_mode": "mandatory" if mandatory else "optional" if optional else "contextual",
            "assessment_status": "not_assessed",
        }
    @staticmethod
    def _extraction_confidence(section: Clause, classification: str) -> float:
        score = 0.92 if section.title_source == "pdf_typography" else 0.82
        if not section.text:
            score -= 0.12
        if classification in {"definition", "normative_reference", "document_context"}:
            score += 0.02
        return round(max(0.0, min(score, 0.99)), 2)


class IECClauseParser:
    """Coordinate IEC PDF extraction and return the stable knowledge-base model."""

    def __init__(self, pdf_path: Path) -> None:
        self.pdf_path = pdf_path

    @staticmethod
    def _join_paragraphs(paragraphs: list[str]) -> str:
        return "\n\n".join(paragraphs).strip()

    @staticmethod
    def _table_semantic_validation(
        header: list[str | None], rows: list[list[str | None]]
    ) -> dict[str, Any]:
        """Record whether extracted table geometry is usable as IEC evidence.

        Table detection alone is not enough: malformed headers and ragged rows
        must remain visible for review instead of looking like validated data.
        """
        clean_header = [str(cell).strip() if cell else "" for cell in header]
        header_complete = bool(clean_header) and all(clean_header)
        column_count = len(clean_header)
        nonempty_rows = [row for row in rows if any(cell is not None for cell in row)]
        shape_valid = bool(nonempty_rows) and all(
            len(row) == column_count for row in nonempty_rows
        )
        table_text = " ".join(
            clean_header + [str(cell) for row in nonempty_rows for cell in row if cell]
        )
        contains_compliance_terms = bool(re.search(
            r"\b(?:shall|shall not|must|pass|fail|acceptance|limit|"
            r"minimum|maximum|not exceed|at least|not less than)\b|[≤≥]",
            table_text,
            re.I,
        ))
        valid = header_complete and shape_valid
        return {
            "status": "validated" if valid else "needs_domain_review",
            "header_complete": header_complete,
            "row_shape_valid": shape_valid,
            "column_count": column_count,
            "row_count": len(nonempty_rows),
            "classification": (
                "compliance_or_limit_table"
                if contains_compliance_terms else "reference_or_data_table"
            ),
            "contains_compliance_terms": contains_compliance_terms,
        }

    @staticmethod
    def _tables_by_page(
        document: pymupdf.Document, profile: IECDocumentProfile
    ) -> dict[int, list[dict[str, Any]]]:
        """Extract native PDF tables as rows and columns, retaining page trace."""
        extracted: dict[int, list[dict[str, Any]]] = {}
        for page_number in range(
            profile._english_page_start, (profile._english_page_end or 0) + 1
        ):
            page = document[page_number - 1]
            try:
                tables = page.find_tables().tables
            except (AttributeError, RuntimeError, ValueError):
                # Some scanned or malformed pages cannot expose vector table
                # geometry. Their text remains available through block parsing.
                continue
            for table_number, table in enumerate(tables, 1):
                rows = table.extract()
                if not rows or len(rows) < 2 or max(map(len, rows), default=0) < 2:
                    continue
                columns = [
                    re.sub(r"\s+", " ", name or "").strip() or f"column_{index + 1}"
                    for index, name in enumerate(table.header.names)
                ]
                normalized_rows = [
                    [re.sub(r"\s+", " ", cell or "").strip() or None for cell in row]
                    for row in rows
                ]
                # Header-only detection on cover sheets is not compliance data.
                if not any(any(cell for cell in row) for row in normalized_rows[1:]):
                    continue
                header = columns if table.header.external else normalized_rows[0]
                data_rows = normalized_rows if table.header.external else normalized_rows[1:]
                semantic_validation = IECClauseParser._table_semantic_validation(header, data_rows)
                extracted.setdefault(page_number, []).append({
                    "id": f"TABLE-P{page_number:04d}-{table_number:02d}",
                    "page": page_number,
                    "bbox": [round(value, 2) for value in table.bbox],
                    "columns": columns,
                    "rows": data_rows,
                    "header": header,
                    "extraction_method": "pymupdf_table_geometry",
                    "extraction_confidence": 0.90 if semantic_validation["status"] == "validated" else 0.65,
                    "domain_review_status": (
                        "pending_domain_review"
                        if semantic_validation["status"] == "validated"
                        else "semantic_validation_required"
                    ),
                    "semantic_validation": semantic_validation,
                })
        return extracted

    def parse(self) -> DocumentKnowledgeBase:
        with pymupdf.open(self.pdf_path) as document:
            profile = IECDocumentProfile(document)
            block_extractor = IECBlockExtractor(profile)
            heading_detector = IECHeadingDetector(profile)
            enricher = IECClauseEnricher(self.pdf_path)
            tables_by_page = self._tables_by_page(document, profile)
            sections: list[Clause] = []
            front_matter: list[TextBlock] = []
            current: Clause | None = None
            pending_annex: Clause | None = None
            seen_ids: set[str] = set()
            active_annex_root: str | None = None

            for block in block_extractor.blocks(document):
                heading = heading_detector.heading(block)
                # A real clause identifier occurs only once. Repeated bold IDs
                # in tables, figures, and cross-references remain body text.
                if heading and heading[0] in seen_ids:
                    heading = None

                # Annex-style IDs in the main body are normally table entries
                # or cross-references. They become sections only after their
                # matching actual "Annex X (...)" heading has been encountered.
                if heading and heading[2] == "annex_clause":
                    root = heading[0].split(".", 1)[0]
                    if root != active_annex_root:
                        heading = None

                # Bibliography and anything following it are intentionally
                # outside the deterministic compliance knowledge base.
                if heading and heading[0] == "back:bibliography":
                    if current is not None:
                        current.text = self._join_paragraphs(current.paragraphs)
                    current = None
                    break

                if heading and heading[2] == "annex":
                    active_annex_root = heading[0].split(":", 1)[1]
                elif heading and heading[2] in {"front", "clause", "subclause"}:
                    active_annex_root = None

                if heading:
                    if current is not None:
                        current.text = self._join_paragraphs(current.paragraphs)
                    identifier, title, kind, initial_text = heading
                    if (
                        kind in {"clause", "subclause"}
                        and identifier.split(".", 1)[0].isdigit()
                    ):
                        main_content_started = True
                    current = Clause(
                        id=identifier,
                        title=title,
                        level=heading_detector.level(identifier),
                        parent_id=heading_detector.parent_id(identifier),
                        kind=kind,
                        page_start=block.page,
                        page_end=block.page,
                        annex_type=(
                            (ANNEX_RE.match(block.text)["kind"].strip().casefold())
                            if kind == "annex" and ANNEX_RE.match(block.text)
                            else None
                        ),
                    )
                    if initial_text:
                        current.paragraphs.append(initial_text)
                    sections.append(current)
                    seen_ids.add(identifier)
                    pending_annex = current if kind == "annex" else None
                    continue

                # The annex title is the bold 12 pt block immediately following
                # "Annex X (normative/informative)".
                if (
                    pending_annex is not None
                    and block.page == pending_annex.page_start
                    and block.first_bold
                    and block.font_size >= 11
                ):
                    pending_annex.title = block.text
                    pending_annex = None
                    continue

                if current is None:
                    front_matter.append(
                        TextBlock(
                            page=block.page,
                            text=block.text,
                            style=block_extractor._style(block.first_font, block.font_size),
                        )
                    )
                else:
                    current.paragraphs.append(block.text)
                    current.page_end = block.page
                    pending_annex = None

            if current is not None:
                current.text = self._join_paragraphs(current.paragraphs)

            existing_ids = {section.id for section in sections}
            annex_types = {
                section.id.split(":", 1)[1]: section.annex_type
                for section in sections
                if section.kind == "annex" and section.annex_type
            }
            for section in sections:
                parent = section.parent_id
                while parent and parent not in existing_ids:
                    if parent.startswith("annex:"):
                        parent = None
                    elif "." in parent:
                        parent = parent.rsplit(".", 1)[0]
                        if parent.isalpha():
                            parent = f"annex:{parent}"
                    elif parent.isalpha():
                        parent = f"annex:{parent}"
                    else:
                        parent = None
                section.parent_id = parent
                if section.kind == "annex_clause":
                    section.annex_type = annex_types.get(section.id.split(".", 1)[0])
                enricher.enrich(section)

            # A table can share a page with its parent clause, a child clause,
            # and an annex. Store its structured payload once with the most
            # specific owner; all other overlapping sections receive a light
            # reference rather than a duplicate copy.
            for page_number, tables in tables_by_page.items():
                candidates = [
                    section for section in sections
                    if section.page_start <= page_number <= section.page_end
                ]
                if not candidates:
                    continue
                owner = max(
                    candidates,
                    key=lambda section: (section.level, section.page_start, section.id),
                )
                for table in tables:
                    table["owner_clause_id"] = owner.id
                    table["references"] = [
                        {
                            "clause_id": section.id,
                            "relationship": "owner" if section is owner else "page_overlap",
                        }
                        for section in candidates
                    ]
                    owner.tables.append(table)
                    for section in candidates:
                        if section is not owner:
                            section.table_references.append({
                                "table_id": table["id"],
                                "owner_clause_id": owner.id,
                                "relationship": "page_overlap",
                            })

            metadata = dict(document.metadata)
            metadata.update(
                {
                    "page_count": document.page_count,
                    "toc_entry_count": len(document.get_toc()),
                    "selected_document_block": profile.document_block,
                }
            )

        return DocumentKnowledgeBase(
            schema_version="3.0",
            source_file=str(self.pdf_path),
            generated_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata,
            statistics={
                "section_count": len(sections),
                "clause_count": sum(
                    section.kind in {"clause", "subclause", "annex_clause"}
                    for section in sections
                ),
                "annex_count": sum(section.kind == "annex" for section in sections),
                "front_matter_block_count": len(front_matter),
                "total_text_characters": sum(len(section.text) for section in sections)
                + sum(len(block.text) for block in front_matter),
                "titled_section_count": sum(bool(section.title) for section in sections),
                "semantically_classified_count": sum(
                    bool(section.semantic_classification) for section in sections
                ),
                "summarized_section_count": sum(bool(section.summary) for section in sections),
                "mandatory_requirement_count": sum(section.mandatory for section in sections),
                "test_required_count": sum(section.test_required for section in sections),
                "compliance_requirement_count": sum(
                    section.compliance_requirement is not None for section in sections
                ),
                "structured_requirement_count": sum(
                    len(section.requirements) for section in sections
                ),
                "structured_test_count": sum(len(section.tests) for section in sections),
                "structured_limit_count": sum(len(section.limits) for section in sections),
                "scope_limit_count": sum(len(section.scope_limits) for section in sections),
                "structured_note_count": sum(len(section.notes) for section in sections),
                "structured_exception_count": sum(
                    len(section.exceptions) for section in sections
                ),
                "structured_table_count": sum(len(section.tables) for section in sections),
                "table_reference_count": sum(
                    len(section.table_references) for section in sections
                ),
                "unresolved_cross_reference_count": sum(
                    len(section.unresolved_cross_references) for section in sections
                ),
                "normative_reference_count": sum(
                    len(section.normative_references) for section in sections
                ),
                "typed_cross_reference_count": sum(
                    len(section.cross_references) for section in sections
                ),
                "normalized_limit_count": sum(
                    item.get("normalization_status") == "parsed"
                    for section in sections for item in section.limits
                ),
                "pending_domain_review_count": sum(
                    section.domain_review_status == "pending_domain_review"
                    for section in sections
                ),
            },
            sections=sections,
            unassigned_front_matter=front_matter,
        )



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="PDF file to parse")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("output.json"), help="JSON output path"
    )
    args = parser.parse_args()

    if not args.pdf.is_file():
        parser.error(f"PDF does not exist: {args.pdf}")

    knowledge_base = IECClauseParser(args.pdf).parse()
    args.output.write_text(
        json.dumps(asdict(knowledge_base), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"Wrote {knowledge_base.statistics['section_count']} sections "
        f"from {knowledge_base.metadata['page_count']} pages to {args.output}"
    )


if __name__ == "__main__":
    main()
