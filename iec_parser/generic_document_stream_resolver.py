"""Resolve the canonical normative stream in sequential multilingual documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence, Tuple


@dataclass(frozen=True)
class DocumentStreamResolution:
    """Canonical page range plus provenance for parallel document streams."""

    selected_pages: Sequence[str]
    page_start: int
    page_end: int
    primary_range: Tuple[int, int]
    parallel_ranges: Tuple[Tuple[int, int], ...] = ()
    selection_signals: Tuple[str, ...] = ()


class GenericDocumentStreamResolver:
    """Choose one repeated normative hierarchy without naming its language."""

    _CONTENTS_MARKERS = {
        "CONTENTS", "TABLE OF CONTENTS", "SOMMAIRE", "TABLE DES MATIERES",
        "INHALT", "INDICE", "ÍNDICE",
    }
    _SCOPE_WORDS = {
        "scope", "domaine d'application", "domaine d’application",
        "domaine d application",
        "anwendungsbereich", "oggetto", "objeto", "campo de aplicación",
    }
    _TOP_ONE = re.compile(r"^1\s+\S.+$")
    _NESTED_ONE = re.compile(r"^1\.1(?:\s+\S.*)?$")

    def resolve(self, pages: Sequence[str]) -> DocumentStreamResolution:
        """Return the earliest complete hierarchy and later-stream provenance."""

        cleaned = [self._lines(page) for page in pages]
        starts = self._body_starts(cleaned)
        if not starts:
            return DocumentStreamResolution(
                pages, 1, len(pages), (1, len(pages)), (),
                ("NO_COMPLETE_BODY_SIGNATURE",),
            )

        primary = starts[0]
        later = starts[1:]
        boundary = len(pages)
        if later:
            boundary = self._parallel_boundary(cleaned, primary, later[0])
        parallel_ranges = tuple(
            (start + 1, (later[index + 1] if index + 1 < len(later) else len(pages)))
            for index, start in enumerate(later)
        )
        return DocumentStreamResolution(
            pages[primary:boundary], primary + 1, boundary,
            (primary + 1, boundary), parallel_ranges,
            ("CLAUSE_1_WITH_NESTED_SCOPE",)
            + (("PARALLEL_HIERARCHY_RESTART",) if later else ()),
        )

    def _body_starts(self, pages: Sequence[Sequence[str]]) -> List[int]:
        starts: List[int] = []
        for page_index, lines in enumerate(pages):
            if self._is_contents(lines):
                continue
            for line_index, line in enumerate(lines):
                if self._direct_scope(line):
                    starts.append(page_index)
                    break
                if (line == "1" and line_index + 1 < len(lines)
                        and self._is_scope_title(lines[line_index + 1])):
                    starts.append(page_index)
                    break
                if not (line == "1" or self._TOP_ONE.fullmatch(line)):
                    continue
                nearby = self._nearby_lines(pages, page_index, line_index, 4)
                if (any(self._nested_scope(value) for value in nearby)
                        or self._contains_split_nested_scope(nearby)):
                    starts.append(page_index)
                    break
        return self._deduplicate_nearby(starts)

    def _parallel_boundary(
        self, pages: Sequence[Sequence[str]], primary: int, later: int
    ) -> int:
        # A translated stream commonly has its own contents immediately before
        # its body.  Preserve that region as parallel provenance, but exclude
        # it from the canonical compliance hierarchy.
        for page_index in range(later - 1, max(primary, later - 24), -1):
            if self._is_contents(pages[page_index]):
                return page_index
        return later

    @classmethod
    def _direct_scope(cls, line: str) -> bool:
        match = re.fullmatch(r"1\s+(.+)", line)
        return bool(match and cls._is_scope_title(match.group(1)))

    @classmethod
    def _nested_scope(cls, line: str) -> bool:
        match = re.fullmatch(r"1\.1\s+(.+)", line)
        return bool(match and cls._is_scope_title(match.group(1)))

    @classmethod
    def _contains_split_nested_scope(cls, lines: Sequence[str]) -> bool:
        return any(
            line == "1.1" and index + 1 < len(lines)
            and cls._is_scope_title(lines[index + 1])
            for index, line in enumerate(lines)
        )

    @classmethod
    def _is_scope_title(cls, title: str) -> bool:
        normalized = re.sub(r"\s+", " ", title).strip().casefold()
        return normalized in cls._SCOPE_WORDS

    @classmethod
    def _nearby_lines(
        cls, pages: Sequence[Sequence[str]], page: int, line: int, page_window: int
    ) -> List[str]:
        values = list(pages[page][line + 1:])
        for offset in range(page + 1, min(len(pages), page + page_window + 1)):
            values.extend(pages[offset])
        return values

    @classmethod
    def _is_contents(cls, lines: Sequence[str]) -> bool:
        return any(line.upper() in cls._CONTENTS_MARKERS for line in lines)

    @staticmethod
    def _deduplicate_nearby(values: Sequence[int]) -> List[int]:
        return list(dict.fromkeys(values))

    @staticmethod
    def _lines(page: str) -> List[str]:
        return [re.sub(r"\s+", " ", line).strip() for line in page.replace("\r", "\n").split("\n") if line.strip()]


__all__ = ["DocumentStreamResolution", "GenericDocumentStreamResolver"]
