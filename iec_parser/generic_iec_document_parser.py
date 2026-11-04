"""Document-level metadata parser for generic IEC standard PDFs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Union

from iec_parser.generic_iec_kb_models import DocumentType, StandardDocument


PathLike = Union[str, Path]

# Generic document parser, identify standard pattern, part pattern
class GenericIECDocumentParser:
    """Extract front-matter metadata from one IEC standard PDF."""

    _STANDARD_PATTERN = re.compile(
        r"\bIEC\s+(?P<number>\d{3,6}(?:\s*-\s*\d+)*)",
        re.IGNORECASE,
    )
    _PART_PATTERN = re.compile(
        r"\bPart\s+(?P<part>\d+(?:\s*-\s*\d+)*)\s*:\s*"
        r"(?P<title>[^\n]{2,200})",
        re.IGNORECASE,
    )
    _ORDINAL_EDITIONS = {
        "first": "1",
        "second": "2",
        "third": "3",
        "fourth": "4",
        "fifth": "5",
        "sixth": "6",
        "seventh": "7",
        "eighth": "8",
        "ninth": "9",
        "tenth": "10",
    }

    def __init__(self, pdf_path: PathLike, front_page_limit: int = 12) -> None:
        """Configure a PDF path and maximum number of front pages to inspect."""

        if front_page_limit < 1:
            raise ValueError("front_page_limit must be at least 1")
        self.pdf_path = Path(pdf_path)
        self.front_page_limit = front_page_limit
        self._extracted_front_text: Optional[str] = None

    def parse(self) -> StandardDocument:
        """Read the PDF and return its document-level metadata."""

        if not self.pdf_path.is_file():
            raise FileNotFoundError(f"IEC standard PDF not found: {self.pdf_path}")

        text = self._extract_front_text()
        if not text or not text.strip():
            raise ValueError(f"No readable text found in PDF: {self.pdf_path}")
        self._extracted_front_text = text
        return self._document_from_text(text, filename_hint=self.pdf_path.name)

    @classmethod
    def parse_text(
        cls, text: str, filename_hint: Optional[str] = None
    ) -> StandardDocument:
        """Parse supplied front-matter text for dependency-light unit testing."""

        if not text or not text.strip():
            raise ValueError("No readable document text was supplied")
        return cls._document_from_text(text, filename_hint=filename_hint)

    def get_extracted_front_text(self) -> Optional[str]:
        """Return original text extracted by the most recent ``parse`` call."""

        return self._extracted_front_text

    def _extract_front_text(self) -> str:
        """Extract text from only the configured number of beginning pages."""

        try:
            import fitz

            with fitz.open(self.pdf_path) as pdf:
                page_count = min(len(pdf), self.front_page_limit)
                return "\n".join(pdf[index].get_text("text") for index in range(page_count))
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(f"Unable to read PDF {self.pdf_path}: {exc}") from exc

    @classmethod
    def _document_from_text(
        cls, text: str, filename_hint: Optional[str] = None
    ) -> StandardDocument:
        normalized = cls._normalize_text(text)
        standard_number = cls._extract_standard_number(normalized)

        # A filename is deliberately only a fallback when content has no identifier.
        if standard_number is None and filename_hint:
            standard_number = cls._extract_standard_number(
                cls._normalize_text(filename_hint.replace("_", " "))
            )

        part_number = cls._extract_part_number(normalized, standard_number)
        document_type = cls._classify_document(standard_number, part_number)
        parent_standard = cls._resolve_parent(standard_number, document_type)
        edition = cls._extract_edition(normalized)
        year = cls._extract_year(normalized, standard_number)

        return StandardDocument(
            standard_id=cls._build_standard_id(standard_number, year),
            standard_number=standard_number,
            title=cls._extract_title(text),
            edition=edition,
            year=year,
            part_number=part_number,
            document_type=document_type,
            parent_standard=parent_standard,
            language=cls._extract_language(normalized),
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        translated = text.translate(str.maketrans({"–": "-", "—": "-", "−": "-"}))
        translated = re.sub(r"(?<=\d)\s*-\s*(?=\d)", "-", translated)
        return re.sub(r"\s+", " ", translated).strip()

    @classmethod
    def _extract_standard_number(cls, text: str) -> Optional[str]:
        match = cls._STANDARD_PATTERN.search(text)
        if not match:
            return None
        number = re.sub(r"\s*-\s*", "-", match.group("number"))
        return f"IEC {number}"

    @classmethod
    def _extract_part_number(
        cls, text: str, standard_number: Optional[str]
    ) -> Optional[str]:
        # The standard identity is authoritative.  Searching the whole front
        # matter first can mislabel a standalone standard when it merely cites
        # another document's "Part 2".
        if standard_number:
            components = standard_number.removeprefix("IEC ").split("-")
            if len(components) > 1:
                return "-".join(components[1:])
            return None
        part_match = re.search(
            r"\bPart\s+(\d+(?:\s*-\s*\d+)*)\b", text, re.IGNORECASE
        )
        if part_match:
            return re.sub(r"\s*-\s*", "-", part_match.group(1))
        return None

    @staticmethod
    def _classify_document(
        standard_number: Optional[str], part_number: Optional[str]
    ) -> DocumentType:
        if not standard_number:
            return DocumentType.UNKNOWN
        if part_number == "1":
            return DocumentType.BASE
        if part_number and part_number.startswith("2-"):
            return DocumentType.PART_2
        return DocumentType.OTHER

    @staticmethod
    def _resolve_parent(
        standard_number: Optional[str], document_type: DocumentType
    ) -> Optional[str]:
        if not standard_number or document_type is not DocumentType.PART_2:
            return None
        family = standard_number.removeprefix("IEC ").split("-", 1)[0]
        return f"IEC {family}-1" if family.isdigit() else None

    @classmethod
    def _extract_title(cls, text: str) -> Optional[str]:
        line_text = text.translate(str.maketrans({"–": "-", "—": "-", "−": "-"}))
        line_text = re.sub(r"(?<=\d)-\s*\n\s*(?=\d)", "-", line_text)
        lines = [re.sub(r"\s+", " ", line).strip() for line in line_text.splitlines()]
        for index, line in enumerate(lines):
            match = cls._PART_PATTERN.search(line)
            if match:
                prefix = line[: match.start()].strip(" -")
                title = f"Part {match.group('part')}: {match.group('title').strip()}"
                return f"{prefix} - {title}" if prefix else title
            short_part = re.search(
                r"\bPart\s+(\d+(?:-\d+)*)\s*:\s*$", line, re.IGNORECASE
            )
            if short_part and index + 1 < len(lines) and lines[index + 1]:
                return f"Part {short_part.group(1)}: {lines[index + 1]}"
        return None

    @classmethod
    def _extract_edition(cls, text: str) -> Optional[str]:
        numeric = re.search(
            r"\bEdition\s+(\d{1,2}(?:\.\d+)?)\b", text, re.IGNORECASE
        )
        if numeric:
            return numeric.group(1)
        ordinal = re.search(
            r"\b(" + "|".join(cls._ORDINAL_EDITIONS) + r")\s+edition\b",
            text,
            re.IGNORECASE,
        )
        return cls._ORDINAL_EDITIONS[ordinal.group(1).lower()] if ordinal else None

    @staticmethod
    def _extract_year(text: str, standard_number: Optional[str]) -> Optional[int]:
        if standard_number:
            escaped = re.escape(standard_number).replace(r"\ ", r"\s+")
            match = re.search(escaped + r"\s*:\s*((?:19|20)\d{2})\b", text, re.IGNORECASE)
            if match:
                return int(match.group(1))
        edition_date = re.search(
            r"\bEdition\s+\d+(?:\.\d+)?\s+((?:19|20)\d{2})(?:-\d{1,2})?\b",
            text,
            re.IGNORECASE,
        )
        if edition_date:
            return int(edition_date.group(1))
        publication = re.search(
            r"\b(?:publication|published)\s+(?:date\s*)?:?\s*((?:19|20)\d{2})\b",
            text,
            re.IGNORECASE,
        )
        return int(publication.group(1)) if publication else None

    @staticmethod
    def _extract_language(text: str) -> Optional[str]:
        explicit = re.search(
            r"\b(?:language|language of publication)\s*:\s*(English|French|German)\b",
            text,
            re.IGNORECASE,
        )
        if explicit:
            return {"english": "en", "french": "fr", "german": "de"}[
                explicit.group(1).lower()
            ]
        if "INTERNATIONAL STANDARD" in text.upper() and "NORME INTERNATIONALE" not in text.upper():
            return "en"
        return None

    @staticmethod
    def _build_standard_id(
        standard_number: Optional[str], year: Optional[int]
    ) -> Optional[str]:
        if not standard_number:
            return None
        identifier = re.sub(r"[^A-Za-z0-9]+", "_", standard_number).strip("_").upper()
        return f"{identifier}_{year}" if year is not None else identifier
