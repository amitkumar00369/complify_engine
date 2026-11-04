"""Extract clause-level evidence stated by IEC/IECEE-style PDF reports."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from iec_parser.generic_report_evidence_models import (
    ReportClauseResult, ReportEvidenceDocument, ReportEvidenceItem,
    ReportEvidenceType, ReportMeasurement, ReportedVerdict,
)


PathLike = Union[str, Path]


class GenericReportEvidenceExtractor:
    """Preserve reported results without deciding applicability or compliance."""

    _CLAUSE_RE = re.compile(r"^(?:\d{1,2}|\d{1,2}(?:\.\d+)+)$")
    _REPORT_RE = re.compile(r"(?:Report\s*(?:No\.?|Number))\s*[:.]\s*([^\n]+)", re.I)
    _STANDARD_RE = re.compile(
        r"\b(?:US\s+)?IEC\s+\d{3,6}(?:-\d+)*(?::\s*\d{4})?"
        r"(?:\s*/\s*(?:AMD|A)\s*\d+(?::\s*\d{4})?)*",
        re.I,
    )
    _MEASUREMENT_RE = re.compile(
        r"(?<![\w.])(?P<a>(?:\d{1,3}(?: \d{3})+|\d+)(?:[.,]\d+)?)"
        r"(?:\s*(?:-|–|—|to)\s*(?P<b>(?:\d{1,3}(?: \d{3})+|\d+)(?:[.,]\d+)?))?\s*"
        r"(?P<unit>mA|µA|uA|kV|V|Hz|kW|W|°C|℃|K|r/min|rpm|L/min|l/min|"
        r"mL/min|ml/min|N·m|Nm|MΩ|kΩ|Ω|µC|uC|mJ|mA|A|J|C|N|mm²|mm2|mm|cm|%|h|ms|s)\b", re.I,
    )
    _REQUIREMENT_WORDING = re.compile(
        r"\b(?:shall|must|required|requirement|not\s+more\s+than|not\s+less\s+than|"
        r"shall\s+not|at\s+least|maximum|minimum|exceed)\b", re.I,
    )
    _EVIDENCE_SIGNAL = re.compile(
        r"(?:[:：]\s*$|\b(?:measured|observed|actual|reading|test\s+voltage|"
        r"test\s+current|test\s+temperature)\b)", re.I,
    )
    _HEADER_FOOTER = re.compile(
        r"^(?:TRF\s+No\.?|Report\s+No\.?|Page\s+\d+\s+of\s+\d+|"
        r"(?:IEC|EN|UL|ISO)\s+\d|Copyright\b|Licensed\s+to\b)", re.I,
    )
    _TABLE_HEADING = re.compile(r"^(?:supplementary\s+information\s*:)?\s*(?:table\s*:|appended\s+table\b|enclosure\s*#)",re.I)
    _TABLE_POINTER = re.compile(r"\b(?:see|refer(?:red)?\s+to)\s+(?:the\s+)?(?:appended\s+)?(?:table|enclosure)\b",re.I)
    _TABLE_HEADER = re.compile(
        r"^(?:measured(?:\s+value)?|required|limit|result|parameter|value|unit|"
        r"temperature|location|condition|component|test\s+point|remarks?)\s*:?$", re.I
    )

    def __init__(self) -> None:
        self._diagnostics: List[Dict[str, Any]] = []
        self._page_count = 0

    def extract(self, pdf_path: PathLike) -> ReportEvidenceDocument:
        """Extract evidence from a text-bearing PDF using installed PyMuPDF."""

        path = Path(pdf_path)
        if not path.is_file(): raise FileNotFoundError(f"Report PDF not found: {path}")
        try:
            import fitz
            with fitz.open(path) as pdf:
                pages = []
                layouts: List[Tuple[int, str]] = []
                table_owner: Optional[str] = None
                for page_number, page in enumerate(pdf, 1):
                    table_text, table_owner = self._layout_table_rows(page, table_owner)
                    pages.append(page.get_text("text"))
                    if table_text:
                        layouts.append((page_number, table_text))
        except (OSError, RuntimeError, ValueError) as error:
            raise ValueError(f"Unable to read report PDF {path}: {error}") from error
        if not any(page.strip() for page in pages):
            raise ValueError(f"No extractable text found in report PDF: {path}")
        document = self.extract_from_pages(pages, file_name=path.name)
        self._attach_layout_evidence(document, layouts)
        document.diagnostics = copy.deepcopy(self._diagnostics)
        return document

    @classmethod
    def _layout_table_text(cls, page: Any) -> str:
        """Render source-grounded table cells as labelled observations.

        PyMuPDF's table geometry restores row/column ownership which flattened
        page text cannot represent.  The emitted text deliberately reuses the
        ordinary deterministic parser rather than creating a second evidence
        model.
        """

        return cls._layout_table_rows(page, None)[0]

    @classmethod
    def _layout_table_rows(
        cls, page: Any, initial_clause_id: Optional[str]
    ) -> Tuple[str, Optional[str]]:
        """Return labelled table observations and the last structural owner."""

        if not hasattr(page, "find_tables"):
            return "", initial_clause_id
        try:
            tables = page.find_tables().tables
        except Exception:
            return "", initial_clause_id
        rendered: List[str] = []
        numeric = re.compile(
            r"^[<>≤≥±]?\s*(?P<value>\d+(?:[.,]\d+)?)\s*"
            r"(?P<unit>VDC|MΩ|kΩ|Ω|µC|uC|mJ|mA|µA|uA|kV|V|A|Hz|kW|W|°?C|℃|K|"
            r"r/min|rpm|L/min|mL/min|N·m|Nm|N|mm²|mm2|mm|cm|%|hours?|hrs?|h|mins?|min|ms|s)?\s*$",
            re.I,
        )
        unit_re = re.compile(
            r"(?:\(|\b)(MΩ|kΩ|Ω|µC|uC|mJ|mA|µA|uA|kV|V|A|Hz|kW|W|°?C|K|"
            r"r/min|rpm|L/min|mL/min|N·m|Nm|N|mm²|mm2|mm|cm|%|h|min|ms|s)(?:\)|\b)", re.I
        )
        owner = initial_clause_id
        for table in tables:
            rows = table.extract()
            if not rows:
                continue
            explicit_owner = next((str(row[0]).strip() for row in rows[:3]
                              if row and row[0] and cls._CLAUSE_RE.fullmatch(str(row[0]).strip())
                              and any(cell and re.search(r"\btable\b",str(cell),re.I) for cell in row)), None)
            if explicit_owner:
                owner = explicit_owner
            if owner is None:
                continue
            caption = next((str(cell).strip() for row in rows[:2] for cell in row
                            if cell and re.search(r"\btable\b", str(cell), re.I)), "TABLE: appended values")
            if not explicit_owner and caption != "TABLE: appended values":
                # A newly captioned table without its own clause reference is
                # not a continuation merely because it follows another table.
                owner = None
                continue
            width = max(len(row) for row in rows)
            headers: List[List[str]] = [[] for _ in range(width)]
            observations: List[str] = []
            for row in rows:
                cells = [str(cell).replace("\n", " ").strip() if cell is not None else ""
                         for cell in row] + [""] * (width - len(row))
                matches = [numeric.fullmatch(cell) for cell in cells]
                if not any(matches):
                    for column, cell in enumerate(cells):
                        if cell and cell != owner and not re.search(r"\btable\b", cell, re.I):
                            headers[column].append(cell)
                    continue
                row_label = next((cell for column, cell in enumerate(cells)
                                  if cell and not matches[column] and not re.search(r"\b(?:table|result)\b",cell,re.I)), "")
                for column, match in enumerate(matches):
                    if match is None:
                        continue
                    header = " ".join(dict.fromkeys(headers[column])).strip() or "observed value"
                    unit_match = unit_re.search(header)
                    raw_unit = match.group("unit")
                    if raw_unit == "a":
                        # Lower-case list markers following clause identifiers
                        # are not ampere units.
                        continue
                    unit = raw_unit or (unit_match.group(1) if unit_match else None)
                    if unit is None:
                        continue
                    if unit == "a":
                        continue
                    unit = {"vdc":"V","hour":"h","hours":"h","hr":"h","hrs":"h",
                            "minute":"min","minutes":"min","mins":"min","℃":"°C"}.get(unit.casefold(), unit)
                    label = re.sub(r"\([^)]*\)", " ", header)
                    label = re.sub(r"\s+", " ", label).strip() or "observed value"
                    if row_label:
                        label = f"{label} {row_label}"
                    observations.append(f"Measured {label}: {match.group('value')} {unit}")
            if observations:
                rendered.extend([owner, caption, *observations])
        return ("\n" + "\n".join(rendered) + "\n" if rendered else "", owner)

    def _attach_layout_evidence(
        self, document: ReportEvidenceDocument, layouts: Sequence[Tuple[int, str]]
    ) -> None:
        """Attach geometric table observations without changing clause parsing."""

        index = {item.clause_id: item for item in self._walk(document.clauses)}
        counts: Counter[str] = Counter()
        for page, text in layouts:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            starts = [i for i, line in enumerate(lines) if self._CLAUSE_RE.fullmatch(line)]
            for ordinal, start in enumerate(starts, 1):
                end = starts[ordinal] if ordinal < len(starts) else len(lines)
                owner = lines[start]
                target = index.get(owner)
                if target is None:
                    self._diagnostics.append({"code":"REPORT_TABLE_OWNER_UNRESOLVED",
                                              "page":page,"clause_id":owner})
                    continue
                block = lines[start + 1:end]
                measurements = self._extract_measurements(owner, [owner, *block], page, counts)
                if not measurements:
                    continue
                evidence_id = f"REPORT-EV-{owner}-LAYOUT-{page:03d}-{ordinal:03d}"
                item = ReportEvidenceItem(
                    evidence_id=evidence_id, evidence_type=ReportEvidenceType.TABLE_VALUE,
                    page_start=page, page_end=page, clause_id=owner,
                    subclause_id=owner if "." in owner else None,
                    reported_verdict=ReportedVerdict.NOT_STATED,
                    raw_text="\n".join(block), measurements=measurements,
                    table_reference=block[0] if block else "TABLE: appended values",
                    source_order=target.source_order,
                    notes="Geometric table rows with explicit or bounded continuation ownership.",
                    logical_row_id=evidence_id, evidence_scope_type="TABLE_LAYOUT",
                    measurement_owner_evidence_id=evidence_id,
                )
                target.evidence_items.append(item)

    def extract_from_pages(
        self, pages: Sequence[str], *, file_name: Optional[str] = None
    ) -> ReportEvidenceDocument:
        """Extract from page text for deterministic tests and diagnostics."""

        if isinstance(pages, (str, bytes)) or not pages or not all(isinstance(x, str) for x in pages):
            raise TypeError("pages must be a non-empty sequence of strings")
        if not any(page.strip() for page in pages): raise ValueError("No extractable report text supplied")
        self._diagnostics = []; self._page_count = len(pages)
        front = "\n".join(pages[:min(3, len(pages))])
        report_number = self._first_group(self._REPORT_RE, front)
        standards = self._unique(self._normalize_standard(m.group(0))
                                 for m in self._STANDARD_RE.finditer(front))
        document_id = report_number or self._document_id(file_name, "\n".join(pages))
        occurrences, preamble = self._parse_occurrences(pages, document_id)
        clauses = self._combine_occurrences(occurrences)
        roots = self._build_hierarchy(clauses)
        unmapped: List[ReportEvidenceItem] = []
        if preamble.strip():
            unmapped.append(ReportEvidenceItem(
                evidence_id="REPORT-EV-UNMAPPED-001", evidence_type=ReportEvidenceType.OTHER,
                page_start=1, page_end=max(1, occurrences[0]["page_start"] - 1) if occurrences else len(pages),
                raw_text=preamble.strip(), source_order=0,
                notes="Report preamble/metadata not mapped to a clause result.",
            ))
        return ReportEvidenceDocument(
            document_id=document_id, file_name=file_name, report_number=report_number,
            standard_numbers=standards, clauses=roots, unmapped_sections=unmapped,
            diagnostics=copy.deepcopy(self._diagnostics),
        )

    @staticmethod
    def to_dict(document: ReportEvidenceDocument) -> Dict[str, Any]:
        if not isinstance(document, ReportEvidenceDocument): raise TypeError("document must be ReportEvidenceDocument")
        return document.to_dict()

    @staticmethod
    def to_json(document: ReportEvidenceDocument, indent: Optional[int] = 2) -> str:
        return json.dumps(document.to_dict(), ensure_ascii=False, sort_keys=True, indent=indent)

    def save_json(self, document: ReportEvidenceDocument, output_path: PathLike) -> Path:
        path = Path(output_path); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(document, 2) + "\n", encoding="utf-8")
        return path

    def get_summary(self, document: ReportEvidenceDocument) -> Dict[str, Any]:
        clauses = list(self._walk(document.clauses)); verdicts = Counter(c.reported_verdict.value for c in clauses)
        return {
            "document_id": document.document_id, "pages": self._page_count,
            "total_clause_results": len(clauses),
            "reported_verdicts": {v.value: verdicts[v.value] for v in ReportedVerdict},
            "clauses_with_measurements": sum(bool(c.measurements) for c in clauses),
            "total_measurements": sum(len(c.measurements) for c in clauses),
            "unmapped_sections": len(document.unmapped_sections),
            "diagnostics": len(document.diagnostics),
            "unique_clause_ids": len({c.clause_id for c in clauses}),
            "duplicate_clause_occurrences": sum(max(0, len(c.evidence_items)-1) for c in clauses),
            "clauses_without_verdict": sum(c.reported_verdict is ReportedVerdict.NOT_STATED for c in clauses),
            "clauses_with_only_raw_text": sum(bool(c.raw_text) and not c.remarks and not c.measurements for c in clauses),
            "clauses_with_remarks": sum(bool(c.remarks) for c in clauses),
        }

    def get_diagnostics(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._diagnostics)

    @classmethod
    def normalize_verdict(cls, value: Optional[str], *, result_context: bool = True) -> ReportedVerdict:
        """Normalize exact result-field tokens; reject incidental letters."""

        if value is None or not value.strip(): return ReportedVerdict.NOT_STATED
        if not result_context: return ReportedVerdict.UNKNOWN
        cleaned = re.sub(r"[.\s]", "", value).upper()
        if cleaned in {"P", "PASS"}: return ReportedVerdict.PASS
        if cleaned in {"F", "FAIL"}: return ReportedVerdict.FAIL
        if cleaned in {"N/A", "NA", "NOTAPPLICABLE", "N"}: return ReportedVerdict.NA
        if cleaned in {"NT", "NOTTESTED", "NOTTEST"}: return ReportedVerdict.NOT_TESTED
        return ReportedVerdict.UNKNOWN

    @classmethod
    def is_clause_id(cls, value: str, previous_line: Optional[str] = None) -> bool:
        """Recognize clause identifiers while excluding common numeric lookalikes."""

        cleaned = value.strip()
        if not cls._CLAUSE_RE.fullmatch(cleaned): return False
        if previous_line and re.search(r"\b(?:IEC|table|figure|page|model)\s*$", previous_line, re.I): return False
        return True

    def _parse_occurrences(self, pages: Sequence[str], document_id: str) -> Tuple[List[Dict[str, Any]], str]:
        occurrences: List[Dict[str, Any]] = []; preamble: List[str] = []; current: Optional[Dict[str, Any]] = None
        source_order = 0; seen_clause = False
        seen_ids: set[str] = set(); maximum_top_level = -1
        for page_number, page in enumerate(pages, 1):
            lines = [re.sub(r"[ \t]+", " ", line).strip() for line in page.splitlines()]
            previous = ""
            for index, line in enumerate(lines):
                next_nonempty = next((item for item in lines[index + 1:] if item), "")
                candidate = self._confirmed_clause_boundary(lines,index,previous,seen_ids,maximum_top_level,current)
                if candidate:
                    if current: occurrences.append(current)
                    source_order += 1; seen_clause = True
                    current = {"clause_id":line,"page_start":page_number,"page_end":page_number,
                               "lines":[line],"source_order":source_order}
                    seen_ids.add(line)
                    if "." not in line: maximum_top_level=max(maximum_top_level,int(line))
                elif current is not None:
                    current["lines"].append(line); current["page_end"] = page_number
                elif line:
                    preamble.append(line)
                if line: previous = line
        if current: occurrences.append(current)
        if not seen_clause:
            self._diagnostics.append({"code":"REPORT_SECTION_UNMAPPED","message":"No reliable clause result rows were detected."})
        return occurrences, "\n".join(preamble)

    def _confirmed_clause_boundary(self,lines,index,previous,seen_ids,maximum_top_level,current=None):
        line=lines[index];raw_next=next((x for x in lines[index+1:] if x),"");next_items=[x for x in lines[index+1:] if x and not self._HEADER_FOOTER.search(x)];next_line=next_items[0] if next_items else ""
        if not self.is_clause_id(line,previous):return False
        if re.fullmatch(r"(?:[a-z]|\d+)\)", previous.strip(), re.I):return False
        if raw_next and self._HEADER_FOOTER.search(raw_next):return False
        # Inside an explicit appended table, isolated numeric cells are values
        # unless they introduce another labelled table or an explicit result.
        # This retains constructs such as ``16.2 / TABLE: ...`` without
        # promoting measurements or row labels to clause boundaries.
        in_table_region=(any(self._TABLE_HEADING.search(x) for x in lines[:index])
                         or bool(current and any(self._TABLE_HEADING.search(x)
                                                 for x in current.get("lines",()))))
        next_verdict=self.normalize_verdict(next_line)
        if (in_table_region and not self._TABLE_HEADING.search(next_line)
                and next_verdict not in {ReportedVerdict.PASS,ReportedVerdict.FAIL,
                                         ReportedVerdict.NA,ReportedVerdict.NOT_TESTED}):
            return False
        if previous and (previous.rstrip().endswith((":","：")) or re.search(r"\([^)]*(?:V|A|Hz|W|mm|mA|°C|K)\)[ .:]*$",previous,re.I)):return False
        if not next_line or self._HEADER_FOOTER.search(next_line):return False
        if next_verdict in {ReportedVerdict.PASS,ReportedVerdict.FAIL,ReportedVerdict.NA,ReportedVerdict.NOT_TESTED}:
            return not any(self._HEADER_FOOTER.search(x) for x in lines[max(0,index-3):index+5])
        if not re.search(r"[A-Za-z]",next_line):return False
        if re.fullmatch(r"[A-Za-z]*\d+(?:[.,]\d+)?\s*\([^)]{1,12}\)",next_line):return False
        if re.fullmatch(r"\d+(?:[.,]\d+)?\s*(?:%|°?C|K|V|A|W|Hz|mm|cm|h)",next_line,re.I):return False
        if re.search(r"\b(?:page|report|trf)\b",next_line,re.I):return False
        if "." not in line:
            number=int(line)
            if number==0:return False
            if line not in seen_ids and number<maximum_top_level:return False
        else:
            top=line.split(".")[0]
        return True

    def _combine_occurrences(self, occurrences: Sequence[Dict[str, Any]]) -> List[ReportClauseResult]:
        grouped: Dict[str, ReportClauseResult] = {}; measurement_counts: Counter[str] = Counter()
        for occurrence_index, raw in enumerate(occurrences, 1):
            clause_id = raw["clause_id"]; lines = raw["lines"]; text = "\n".join(lines).strip()
            explicit_verdict_lines=[line for line in lines[1:] if self.normalize_verdict(line) not in {ReportedVerdict.UNKNOWN,ReportedVerdict.NOT_STATED}]
            verdict_tokens = [self.normalize_verdict(line) for line in explicit_verdict_lines]
            verdict_tokens = [v for v in verdict_tokens if v is not ReportedVerdict.NOT_STATED]
            distinct = set(verdict_tokens)
            if verdict_tokens: verdict = verdict_tokens[0]
            else: verdict = ReportedVerdict.NOT_STATED
            if len(distinct) > 1:
                self._diagnostics.append({"code":"REPORT_VERDICT_AMBIGUOUS","clause_id":clause_id,
                    "page":raw["page_start"],"values":sorted(v.value for v in distinct)})
            measurements = self._extract_measurements(clause_id, lines, raw["page_start"], measurement_counts)
            model_results = re.findall(
                r"(?im)^.*\bmodel\s+([A-Za-z0-9_./-]+).*?\b(P|PASS|F|FAIL|N/?A)\s*$", text
            )
            if len({self.normalize_verdict(value) for _, value in model_results}) > 1:
                self._diagnostics.append({"code":"PER_MODEL_RESULT_VARIATION",
                    "clause_id":clause_id,"page":raw["page_start"],
                    "models":[model for model, _ in model_results]})
            remarks = self._remarks(lines)
            table_ref = self._table_reference(text)
            evidence = ReportEvidenceItem(
                evidence_id=f"REPORT-EV-{clause_id}-{sum(1 for item in occurrences[:occurrence_index] if item['clause_id']==clause_id):03d}",
                evidence_type=ReportEvidenceType.MEASUREMENT if measurements else ReportEvidenceType.CLAUSE_RESULT,
                page_start=raw["page_start"], page_end=raw["page_end"], clause_id=clause_id,
                subclause_id=clause_id if "." in clause_id else None,
                reported_verdict=verdict, raw_text=text,
                remarks="\n".join(remarks) if remarks else None, measurements=copy.deepcopy(measurements),
                table_reference=table_ref, source_order=raw["source_order"],
                raw_verdict_text=explicit_verdict_lines[0] if explicit_verdict_lines else None,
                row_ordinal=occurrence_index,
                row_group_id=f"REPORT-ROW-GROUP-{clause_id}-{sum(1 for item in occurrences[:occurrence_index] if item['clause_id']==clause_id):03d}",
                logical_row_id=f"REPORT-LOGICAL-ROW-{clause_id}-{occurrence_index:03d}",
                verdict_scope="GROUP_CONTEXT",
                evidence_scope_type="CLAUSE_ROW_CONTEXT",
            )
            clause_occurrence=sum(1 for item in occurrences[:occurrence_index] if item['clause_id']==clause_id)
            subrows=self._subrow_children(
                clause_id, lines, raw, clause_occurrence, evidence.evidence_id,
                measurement_counts,
            )
            table_children=self._table_children(clause_id,lines,raw,clause_occurrence,evidence.evidence_id,measurement_counts)
            evidence.evidence_type=ReportEvidenceType.CLAUSE_ROW
            if subrows:
                evidence.reported_verdict=ReportedVerdict.NOT_STATED
            evidence.child_evidence_ids=[x.evidence_id for x in [*subrows,*table_children]]
            if clause_id not in grouped:
                grouped[clause_id] = ReportClauseResult(
                    result_id=f"REPORT-CLAUSE-{clause_id}", clause_id=clause_id,
                    title=self._title(lines), reported_verdict=verdict,
                    page_start=raw["page_start"], page_end=raw["page_end"], raw_text=text,
                    remarks=remarks, measurements=measurements,
                    source_order=raw["source_order"], evidence_items=[evidence]+subrows+table_children,
                )
            else:
                result = grouped[clause_id]
                result.page_end = raw["page_end"]; result.raw_text = (result.raw_text or "") + "\n" + text
                result.remarks.extend(x for x in remarks if x not in result.remarks)
                result.measurements.extend(measurements); result.evidence_items.extend([evidence]+subrows+table_children)
                values = {item.reported_verdict for item in result.evidence_items
                          if item.reported_verdict is not ReportedVerdict.NOT_STATED}
                result.reported_verdict = next(iter(values)) if len(values) == 1 else (
                    ReportedVerdict.NOT_STATED if not values else ReportedVerdict.UNKNOWN)
                self._diagnostics.append({"code":"REPORT_DUPLICATE_CLAUSE_OCCURRENCE",
                    "clause_id":clause_id,"occurrences":len(result.evidence_items)})
        return sorted(grouped.values(), key=lambda item:item.source_order)

    def _subrow_children(self,clause_id,lines,raw,occurrence_index,parent_id,counts):
        """Split independently verdicted report text while retaining clause ownership."""

        output=[]; pending=[]; ordinal=0
        for line in lines[1:]:
            verdict=self.normalize_verdict(line)
            if verdict in {ReportedVerdict.PASS,ReportedVerdict.FAIL,ReportedVerdict.NA,ReportedVerdict.NOT_TESTED}:
                meaningful=[item.strip() for item in pending if self._meaningful_subrow_line(item)]
                text=" ".join(meaningful).strip()
                pending=[]
                if not text or self._TABLE_HEADING.search(text):
                    continue
                ordinal+=1
                evidence_id=f"REPORT-EV-{clause_id}-{occurrence_index:03d}-SUBROW-{ordinal:03d}"
                measurements=self._extract_measurements(
                    clause_id, ["", text], raw["page_start"], counts
                )
                output.append(ReportEvidenceItem(
                    evidence_id=evidence_id,evidence_type=ReportEvidenceType.SUBROW,
                    page_start=raw["page_start"],page_end=raw["page_end"],clause_id=clause_id,
                    subclause_id=clause_id if "." in clause_id else None,
                    reported_verdict=verdict,raw_text=text,source_order=raw["source_order"],
                    measurements=measurements,
                    notes="Independently verdicted report subrow.",raw_verdict_text=line,
                    parent_evidence_id=parent_id,row_ordinal=occurrence_index,
                    subrow_ordinal=ordinal,raw_requirement_text=text,
                    row_group_id=f"REPORT-ROW-GROUP-{clause_id}-{occurrence_index:03d}",
                    logical_row_id=evidence_id,verdict_scope="INDIVIDUAL_VERDICT",
                    evidence_scope_type="LOGICAL_SUBROW",
                    verdict_owner_evidence_id=evidence_id,
                    result_owner_evidence_id=evidence_id,
                    measurement_owner_evidence_id=evidence_id if measurements else None,
                ))
            elif line.strip():
                pending.append(line)
        # A single independently verdicted line is already represented by its
        # clause-row parent.  Child structure is material only when siblings
        # must remain isolated.
        return output if len(output) > 1 else []

    def _meaningful_subrow_line(self,line):
        """Reject repeated layout chrome without using report-specific text."""

        value=re.sub(r"\s+"," ",line).strip()
        if not value or self._HEADER_FOOTER.search(value):return False
        if re.search(r"\b(?:clause\s+requirement\s*\+\s*test|result\s*-\s*remark\s+verdict|trf\s+no\.)\b",value,re.I):return False
        if re.fullmatch(r"(?:page\s+)?\d+\s+of\s+\d+.*",value,re.I):return False
        return True

    def _table_children(self,clause_id,lines,raw,occurrence_index,parent_id,counts):
        starts=[i for i,line in enumerate(lines[1:],1) if self._TABLE_HEADING.search(line)]
        output=[]
        for number,start in enumerate(starts,1):
            end=starts[number] if number<len(starts) else len(lines);block=lines[start:end]
            if not block:continue
            explicit=[x for x in block if self.normalize_verdict(x) not in {ReportedVerdict.UNKNOWN,ReportedVerdict.NOT_STATED}]
            verdict=self.normalize_verdict(explicit[0]) if explicit else ReportedVerdict.NOT_STATED
            evidence_id=f"REPORT-EV-{clause_id}-{occurrence_index:03d}-TABLE-{number:03d}"
            measurements=self._extract_measurements(clause_id,block,raw["page_start"],counts)
            output.append(ReportEvidenceItem(evidence_id=evidence_id,evidence_type=ReportEvidenceType.TABLE_VALUE,page_start=raw["page_start"],page_end=raw["page_end"],clause_id=clause_id,subclause_id=clause_id if "." in clause_id else None,reported_verdict=verdict,raw_text="\n".join(block),measurements=measurements,table_reference=self._table_reference("\n".join(block)) or block[0],source_order=raw["source_order"],notes="Structurally owned appended/table evidence.",raw_verdict_text=explicit[0] if explicit else None,parent_evidence_id=parent_id,row_group_id=f"REPORT-ROW-GROUP-{clause_id}-{occurrence_index:03d}",logical_row_id=evidence_id,verdict_scope="INDIVIDUAL_VERDICT" if explicit else "NOT_STATED",evidence_scope_type="TABLE_CHILD",verdict_owner_evidence_id=evidence_id if explicit else None,result_owner_evidence_id=evidence_id,measurement_owner_evidence_id=evidence_id if measurements else None))
        return output

    def _extract_measurements(
        self, clause_id: str, lines: Sequence[str], page: int, counts: Counter[str]
    ) -> List[ReportMeasurement]:
        output: List[ReportMeasurement] = []
        for index, line in enumerate(lines):
            if self._TABLE_HEADER.fullmatch(line.strip()):
                continue
            context_lines = [item for item in lines[max(0,index-2):index+1] if item]
            context = " ".join(context_lines)
            line_matches = list(self._MEASUREMENT_RE.finditer(line))
            if len(line_matches) > 1 and re.search(r"\bor\b", line, re.I):
                self._diagnostics.append({"code":"REPORT_MEASUREMENT_AMBIGUOUS",
                    "clause_id":clause_id,"page":page,"raw_text":line})
            for match in line_matches:
                prefix = " ".join(context_lines[:-1]) + " " + line[:match.start()]
                requirement_wording = bool(self._REQUIREMENT_WORDING.search(context))
                tail_start = max(line.rfind(";"), line.rfind(":")) + 1
                tail = line[tail_start:].strip() if tail_start else ""
                explicit_result_tail = bool(
                    tail_start and match.start() >= tail_start
                    and re.fullmatch(
                        r"(?:[<>≤≥±]?\s*\d+(?:[.,]\d+)?\s*"
                        r"(?:%|°?C|K|V|m?A|W|Hz|mm|cm|h|min|s)\s*[,/]?\s*)+",
                        tail, re.IGNORECASE,
                    )
                )
                if requirement_wording and not explicit_result_tail: continue
                if re.search(r"(?:[<>≤≥]=?|\bmax(?:imum)?\.?\s+(?:allowed\s+)?)\s*$", line[:match.start()], re.I):
                    continue
                if not (explicit_result_tail or self._EVIDENCE_SIGNAL.search(prefix)
                        or re.search(r"[:：]\s*"+re.escape(match.group(0)), context, re.I)):
                    continue
                counts[clause_id] += 1
                unit = match.group("unit"); parameter_text = self._measurement_parameter_text(
                    line, match.start(), context_lines
                )
                # A compact value after a requirement/result delimiter is the
                # reported observation, even when the copied requirement uses
                # the word "test".  The wording must not turn that result into
                # a test-setup parameter.
                role = ("REFERENCE_VALUE" if re.search(r"\b(?:required|limit|maximum|minimum)\b",parameter_text or "",re.I)
                        else "TEST_PARAMETER" if re.search(r"\btest\s+(?:voltage|current|time|duration|force)\b",parameter_text or "",re.I)
                        else "OBSERVED_VALUE" if explicit_result_tail else
                        "TEST_PARAMETER" if re.search(r"\btest\b",parameter_text or "",re.I)
                        else "OBSERVED_VALUE")
                output.append(ReportMeasurement(
                    measurement_id=f"REPORT-MEAS-{clause_id}-{counts[clause_id]:03d}",
                    parameter=self._parameter_key(parameter_text), parameter_text=parameter_text,
                    value=self._number(match.group("a")),
                    value_secondary=self._number(match.group("b")) if match.group("b") else None,
                    unit=unit, unit_normalized=self._normalize_unit(unit),
                    operator="range" if match.group("b") else None,
                    raw_text=context.strip(), page=page, row_label=parameter_text,
                    notes=f"Measurement role: {role}",
                ))
        return output

    @classmethod
    def _measurement_parameter_text(
        cls, line: str, value_start: int, context_lines: Sequence[str]
    ) -> Optional[str]:
        """Return the closest non-header label that owns a numeric value."""

        inline = re.sub(r"[|:：.\-_]+\s*$", "", line[:value_start]).strip()
        candidates = [inline, *reversed(context_lines[:-1])]
        for candidate in candidates:
            cleaned = re.sub(r"\s+", " ", candidate).strip(" |:：")
            if not cleaned or cls._TABLE_HEADER.fullmatch(cleaned):
                continue
            if re.fullmatch(r"[-—–]+", cleaned):
                continue
            return cleaned
        return None

    @staticmethod
    def _remarks(lines: Sequence[str]) -> List[str]:
        pattern = re.compile(
            r"^(?:see\s+(?:table|annex|page|appended|photograph|remark)|remark\b|"
            r"(?:complies\s+)?by\s+inspection\b|not\s+applicable\s+because\b)", re.I
        )
        return [line for line in lines[1:] if pattern.search(line)]

    @staticmethod
    def _table_reference(text: str) -> Optional[str]:
        match = re.search(r"\b(?:see\s+)?table\s+([A-Z]?\d+(?:\.\d+)*)\b",text,re.I)
        return f"Table {match.group(1)}" if match else None

    @classmethod
    def _build_hierarchy(cls, clauses: Sequence[ReportClauseResult]) -> List[ReportClauseResult]:
        by_id = {item.clause_id:item for item in clauses}; roots: List[ReportClauseResult] = []
        for item in clauses: item.children = []
        for item in clauses:
            parts = item.clause_id.split("."); parent = by_id.get(".".join(parts[:-1])) if len(parts)>1 else None
            if parent: parent.children.append(item)
            else: roots.append(item)
        return roots

    @staticmethod
    def _title(lines: Sequence[str]) -> Optional[str]:
        for line in lines[1:5]:
            if not line or GenericReportEvidenceExtractor.normalize_verdict(line) is not ReportedVerdict.UNKNOWN or line == "/": continue
            if re.search(r"[A-Za-z]",line): return line
        return None

    @staticmethod
    def _parameter_key(value: Optional[str]) -> Optional[str]:
        if not value: return None
        cleaned=re.sub(r"\b(?:measured|observed|actual|required|limit|maximum|minimum|value|of|the)\b"," ",value.casefold())
        cleaned=re.sub(r"[^a-z0-9]+","_",cleaned).strip("_")
        aliases={"current":"current","voltage":"voltage","test_voltage":"test_voltage",
                 "temperature":"temperature","temperature_rise":"temperature_rise",
                 "dt":"temperature_rise","force":"applied_force","duration":"test_duration",
                 "test_time":"test_duration","resistance":"resistance","insulation_resistance_r":"resistance",
                 "clearance_cl":"clearance","creepage_distance_dcr":"creepage_distance",
                 "charge":"charge","energy":"energy","frequency":"frequency","power":"power"}
        cleaned=aliases.get(cleaned,cleaned)
        contains=(("temperature_rise","temperature_rise"),("dt","temperature_rise"),
                  ("test_voltage","test_voltage"),("test_time","test_duration"),
                  ("duration","test_duration"),("insulation_resistance","resistance"),
                  ("creepage","creepage_distance"),("clearance","clearance"),
                  ("current","current"),("voltage","voltage"),("frequency","frequency"),
                  ("force","applied_force"),("torque","torque"),("power","power"))
        cleaned=next((canonical for token,canonical in contains if token in cleaned),cleaned)
        return cleaned[:80] or None

    @staticmethod
    def _normalize_unit(unit: str) -> str:
        mapping={"l/min":"L/min","ml/min":"mL/min","rpm":"r/min","nm":"N·m","mm2":"mm²","℃":"°C","ua":"µA","uc":"µC"}
        return mapping.get(unit.casefold(),unit)

    @staticmethod
    def _number(value: str) -> Union[int,float]:
        number=float(value.replace(" ","").replace(",",".")); return int(number) if number.is_integer() else number

    @staticmethod
    def _first_group(pattern: re.Pattern[str], text: str) -> Optional[str]:
        match=pattern.search(text); return match.group(1).strip(" .:") if match else None

    @staticmethod
    def _normalize_standard(value: str) -> str:
        return re.sub(r":\s*",":",re.sub(r"\s+"," ",value).upper().strip())

    @staticmethod
    def _unique(values: Iterable[str]) -> List[str]:
        output=[]; seen=set()
        for value in values:
            if value not in seen: seen.add(value); output.append(value)
        return output

    @staticmethod
    def _document_id(file_name: Optional[str], text: str) -> str:
        if file_name:
            token=re.sub(r"[^A-Za-z0-9]+","_",Path(file_name).stem).strip("_")
            if token: return f"REPORT_{token}"
        return "REPORT_"+hashlib.sha256(text.encode()).hexdigest()[:16]

    @classmethod
    def _walk(cls, clauses: Sequence[ReportClauseResult]) -> Iterable[ReportClauseResult]:
        for clause in clauses: yield clause; yield from cls._walk(clause.children)


__all__ = ["GenericReportEvidenceExtractor"]
