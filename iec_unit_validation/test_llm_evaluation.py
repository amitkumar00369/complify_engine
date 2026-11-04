"""AI evaluation layer: context building, markdown parsing, quote check, no network."""
import json
from types import SimpleNamespace as NS

from llm_evaluation.context_builder import build_context
from llm_evaluation.service import evaluate_run, rebuild_run

KB = {
    "base_standard": {"standard_number": "IEC 99999-1", "year": 2020},
    "delta_standard": {"standard_number": "IEC 99999-2-5", "year": 2021},
    "clauses": [{
        "clause_id": "7", "title": "Marking", "raw_text": "7 Marking", "applied_operations": [],
        "base_sources": [{"page_start": 10}], "delta_sources": [], "requirements": [], "children": [{
            "clause_id": "7.1", "title": "Rated values",
            "raw_text": "7.1 Appliances shall be marked with the rated voltage in volts.\nLicensed copy",
            "applied_operations": [{"operation_type": "ADDITION"}],
            "base_sources": [{"page_start": 10}], "delta_sources": [{"page_start": 4}],
            "requirements": [{"effective_source_type": "PART_2_ADDITION",
                              "text": "Addition: Appliances shall be marked with the maximum water level."}],
            "children": []}]}],
    "tables": [], "annexes": [], "definitions": [],
}
EV = {
    "report_number": "R-1", "file_name": "r.pdf", "standard_numbers": ["IEC 99999-1"],
    "unmapped_sections": [{"raw_text": "Model: X1\nRated 230 V", "page_start": 1, "page_end": 1}],
    "clauses": [{"clause_id": "7.1", "children": [], "evidence_items": [{
        "raw_text": "7.1 Rated voltage marked 230 V P", "raw_verdict_text": "P", "page_start": 3, "page_end": 3,
        "evidence_type": "CLAUSE_ROW", "parent_evidence_id": None}]}],
}
MD = """## Report identity
| Field | Value |
|---|---|
| Report number | R-1 |

## Findings
| Clause | Gap type | Priority | Normative requirement | Finding reason | Required action | Pages | Report quote | Standard quote |
|---|---|---|---|---|---|---|---|---|
| 7.1 | CLAUSE_NOT_ADDRESSED | HIGH | Max water level marked. | Not recorded. | Add it. | 3 | Rated voltage marked 230 V | marked with the maximum water level |

## Final decision
**Verdict:** REPORT ACCEPTED SUBJECT TO MINOR CORRECTIONS
**Reason:** One gap.
**Recommended action:** Correct the report.

## Overall conclusion
Minor.
"""


def test_context_has_part2_text_and_pages():
    ctx = build_context(KB, EV)
    assert "[7.1] Rated values | Part 2: ADDITION | P1 p.10, P2 p.4" in ctx.standard_text
    assert "+ Part 2 ADDITION: Addition: Appliances shall be marked with the maximum water level." in ctx.standard_text
    assert "[7.1] p.3 | verdict P" in ctx.report_text and "Model: X1" in ctx.report_text


def test_evaluate_run_writes_pdf_xlsx_json_md(tmp_path):
    (tmp_path / "standards").mkdir()
    (tmp_path / "report").mkdir()
    (tmp_path / "standards/effective_kb.json").write_text(json.dumps(KB))
    (tmp_path / "report/report_evidence.json").write_text(json.dumps(EV))
    calls = []
    resp = NS(output_text=MD, model="m", id="r", status="completed", incomplete_details=None,
              usage=NS(input_tokens=1000, output_tokens=100, input_tokens_details=NS(cached_tokens=0)))
    client = NS(responses=NS(create=lambda **kw: calls.append(kw) or resp))
    res = evaluate_run(tmp_path, client=client)
    gap = res["result"]["gaps"][0]
    assert gap["clause_id"] == "7.1" and gap["verification_status"] == "CONFIRMED_REPORT_DEFECT"
    assert set(res["usage"]) == {"input_tokens", "cached_input_tokens", "output_tokens", "seconds"}
    out = tmp_path / "evaluation"
    assert (out / res["files"]["pdf"]).read_bytes().startswith(b"%PDF")
    assert (out / res["files"]["xlsx"]).read_bytes().startswith(b"PK")
    assert json.loads((out / res["files"]["json"]).read_text()) == res["result"]
    assert "model" not in (out / "run_info.json").read_text().lower()
    assert evaluate_run(tmp_path, client=None)["from_cache"] is True and len(calls) == 1
    edited = (out / res["files"]["md"]).read_text().replace("| 7.1 |", "| 7.2 |")
    rb = rebuild_run(tmp_path, edited)
    assert rb["result"]["gaps"][0]["clause_id"] == "7.2" and rb["usage"]["input_tokens"] == 0 and len(calls) == 1