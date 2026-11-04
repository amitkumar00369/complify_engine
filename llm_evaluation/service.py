"""Run folder -> technical evaluation -> PDF / Excel / JSON / MD inside the same run folder.

Input  (written by the engine pipeline for every run, BLOCKED runs included):
    <run_dir>/standards/effective_kb.json
    <run_dir>/report/report_evidence.json
Output (inside the run folder, so the existing S3 sync uploads it with the rest of the run;
        the PDF goes to compliance_file/, everything else to evaluation_engine/):
    <run_dir>/evaluation/Technical_Evaluation_<report no>.pdf    same layout as complify-chat
    <run_dir>/evaluation/Technical_Evaluation_<report no>.xlsx   same layout as complify-chat
    <run_dir>/evaluation/Technical_Evaluation_<report no>.json   gap JSON (report_id, gaps, final_summary)
    <run_dir>/evaluation/Technical_Evaluation_<report no>.md     the evaluation in markdown
    <run_dir>/evaluation/evaluation_input.md                     text the evaluation was made from
    <run_dir>/evaluation/run_info.json                           files, tokens, quote-check counts
The model name is written only to the server log, never to a file or a response.

Settings (.env):
    OPENAI_API_KEY               required
    OPENAI_MODEL                 default gpt-6.1-terra
    OPENAI_MAX_OUTPUT_TOKENS     default 24000
    OPENAI_TIMEOUT_SECONDS       default 900
    AI_EVALUATION_ENABLED        default true (false -> POST /reports skips the evaluation)
    BRAND_NAME / BRAND_COLOR     PDF / Excel branding (default Complify, #086457)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from llm_evaluation.context_builder import BuiltContext, build_context
from llm_evaluation.evidence_check import evidence_summary, verify_findings
from llm_evaluation.gap_report import GapReportParser
from llm_evaluation.md_parser import parse_chat_markdown, report_meta_from_text
from llm_evaluation.prompt import SYSTEM_INSTRUCTIONS, build_input
from llm_evaluation.schema import EvaluationAI, EvaluationDocument

logger = logging.getLogger(__name__)

OUT_DIR = "evaluation"
FORMATS = ("pdf", "xlsx", "json", "md")
MEDIA = {"pdf": "application/pdf", "json": "application/json", "md": "text/markdown; charset=utf-8",
         "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
NEUTRAL_ERROR = "The evaluation could not be completed right now. Please try again later."


class EvaluationError(RuntimeError):
    """Message is safe to show to a client (no vendor / model details)."""


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def enabled() -> bool:
    return os.environ.get("AI_EVALUATION_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off") \
        and bool(os.environ.get("OPENAI_API_KEY"))


# ------------------------------------------------------------------ inputs
def _load_inputs(run_dir: Path) -> tuple[dict, dict]:
    kb_path = run_dir / "standards" / "effective_kb.json"
    ev_path = run_dir / "report" / "report_evidence.json"
    missing = [str(p.relative_to(run_dir)) for p in (kb_path, ev_path) if not p.is_file()]
    if missing:
        raise EvaluationError(f"Run has no {', '.join(missing)} (the pipeline stopped before these steps)")
    return (json.loads(kb_path.read_text(encoding="utf-8")),
            json.loads(ev_path.read_text(encoding="utf-8")))


def load_context(run_dir: Path) -> BuiltContext:
    return build_context(*_load_inputs(run_dir))


def _page_list(pages: dict[int, str]) -> list[str]:
    out = [""] * (max(pages) if pages else 0)
    for p, t in pages.items():
        if p >= 1:
            out[p - 1] = t
    return out


def _last_page(ev: dict) -> int:
    def walk(nodes):
        for n in nodes or []:
            yield n
            yield from walk(n.get("children"))
    ends = [e.get("page_end") or 0 for n in walk(ev.get("clauses")) for e in n.get("evidence_items") or []]
    ends += [s.get("page_end") or 0 for s in ev.get("unmapped_sections") or []]
    return max(ends, default=0)


def _standards_labels(kb: dict) -> tuple[list[str], str]:
    """'IEC 60335-1:2010 (Part 1)', 'IEC 60335-2-7:2012 (Part 2 2-7)' - same wording as complify-chat."""
    base, delta = kb.get("base_standard") or {}, kb.get("delta_standard") or {}

    def ref(m):
        return f"{m.get('standard_number') or '?'}{':' + str(m['year']) if m.get('year') else ''}"
    if not delta:
        return ([f"{ref(base)} (Standard)"] if base else []), "Standard"
    pn = delta.get("part_number") or ""
    return [f"{ref(base)} (Part 1)", f"{ref(delta)} (Part 2 {pn})".rstrip()], (f"Part {pn}" if pn else "Part 2")


def _pdf_pages(run_dir: Path) -> list[str]:
    """Layout text of <run_dir>/report.pdf (the numeric code checks read table rows); [] if absent."""
    pdf = run_dir / "report.pdf"
    if not pdf.is_file():
        return []
    try:
        import pdfplumber

        with pdfplumber.open(str(pdf), password="") as doc:
            return [(p.extract_text(layout=True, x_tolerance=1, x_density=5, y_density=13) or "")
                    for p in doc.pages[:400]]
    except Exception as exc:  # noqa: BLE001
        logger.warning("report.pdf text for code checks not available: %s", exc)
        return []


def _code_checks(run_dir: Path, evidence_pages: list[str]):
    """IEC 60335-1 numeric rules (clause 10 power, heating limits, 19.10 voltage, rating identity), same as
    complify-chat. Only for reports of that series. Reads report.pdf when the run has it, else the report
    evidence text. Returns (facts, findings, prompt text) - prompt text only when the code found something."""
    from llm_evaluation.objective_checks import applies_to, checks_as_prompt, run_objective_checks

    pages = _pdf_pages(run_dir) or evidence_pages
    if not pages or not applies_to(pages):
        return None, [], ""
    try:
        facts, checks = run_objective_checks(pages)
        if not checks and not (facts.declared_voltage or facts.declared_power_w):
            return facts, checks, ""                     # nothing usable read -> do not send an empty block
        return facts, checks, checks_as_prompt(facts, checks)
    except Exception as exc:  # noqa: BLE001  checks must never stop the evaluation
        logger.warning("Code checks skipped: %s", exc)
        return None, [], ""


# ------------------------------------------------------------------ model call
def call_model(ctx: BuiltContext, checks_text: str = "", client=None) -> dict:
    """One Responses API call: no conversation, no file upload."""
    if client is None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise EvaluationError(NEUTRAL_ERROR)
        from openai import OpenAI
        client = OpenAI(timeout=_env_float("OPENAI_TIMEOUT_SECONDS", 900))
    model = os.environ.get("OPENAI_MODEL", "gpt-6.1-terra")
    max_out = int(_env_float("OPENAI_MAX_OUTPUT_TOKENS", 24000))
    t0 = time.time()
    try:
        resp = client.responses.create(model=model, instructions=SYSTEM_INSTRUCTIONS,
                                       input=build_input(ctx.standard_text, ctx.report_text, checks_text),
                                       max_output_tokens=max_out)
    except Exception as exc:  # noqa: BLE001
        logger.error("Evaluation call failed: %s: %s", type(exc).__name__, exc)
        raise EvaluationError(NEUTRAL_ERROR) from exc
    usage = getattr(resp, "usage", None)
    inc = getattr(resp, "incomplete_details", None)
    if getattr(resp, "status", "") == "incomplete" and getattr(inc, "reason", "") == "max_output_tokens":
        logger.error("Evaluation answer cut off at OPENAI_MAX_OUTPUT_TOKENS=%s - raise it", max_out)
        raise EvaluationError(NEUTRAL_ERROR)
    out = {
        "text": (getattr(resp, "output_text", "") or "").strip(),
        "input_tokens": getattr(usage, "input_tokens", None),
        "cached_input_tokens": getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "seconds": round(time.time() - t0, 1),
    }
    logger.info("Evaluation call done: model=%s input=%s cached=%s output=%s tokens, %ss",
                getattr(resp, "model", model), out["input_tokens"], out["cached_input_tokens"],
                out["output_tokens"], out["seconds"])
    if "## Findings" not in out["text"]:
        logger.error("Evaluation answer has no '## Findings' section")
        raise EvaluationError(NEUTRAL_ERROR)
    return out


# ------------------------------------------------------------------ public
def evaluate_run(run_dir: str | Path, *, client=None, force: bool = False) -> dict:
    """Evaluate one engine run and write PDF / Excel / JSON / MD into <run_dir>/evaluation/.
    A stored result is returned unless force=True."""
    run_dir = Path(run_dir)
    if not force and (stored := stored_result(run_dir)):
        return stored
    kb, ev = _load_inputs(run_dir)
    ctx = build_context(kb, ev)
    facts, checks, checks_text = _code_checks(run_dir, _page_list(ctx.report_pages))
    out = run_dir / OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / "evaluation_input.md").write_text(f"{ctx.standard_text}\n\n---\n\n{ctx.report_text}\n"
                                             + (f"\n---\n\n{checks_text}\n" if checks_text else ""),
                                             encoding="utf-8")
    logger.info("Evaluation %s: ~%s input tokens (standard %s chars, report %s chars)",
                run_dir.name, ctx.est_tokens, len(ctx.standard_text), len(ctx.report_text))
    result = call_model(ctx, checks_text, client)
    usage = {k: result[k] for k in ("input_tokens", "cached_input_tokens", "output_tokens", "seconds")}
    return _build_outputs(run_dir, kb, ev, ctx, result["text"], usage, facts, checks)


def rebuild_run(run_dir: str | Path, markdown: str | None = None) -> dict:
    """PDF / Excel / JSON / MD again from the stored (or an edited) markdown - no model call, no cost."""
    run_dir = Path(run_dir)
    info = _read_info(run_dir)
    if markdown is None:
        if not info:
            raise EvaluationError("This run has no evaluation yet")
        markdown = (run_dir / OUT_DIR / info["files"]["md"]).read_text(encoding="utf-8")
    md = _strip_header(markdown)
    if "## Findings" not in md:
        raise EvaluationError("The markdown has no '## Findings' section")
    kb, ev = _load_inputs(run_dir)
    ctx = build_context(kb, ev)
    facts, checks, _ = _code_checks(run_dir, _page_list(ctx.report_pages))
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "seconds": 0}
    return _build_outputs(run_dir, kb, ev, ctx, md, usage, facts, checks)


def stored_result(run_dir: str | Path) -> dict | None:
    run_dir = Path(run_dir)
    info = _read_info(run_dir)
    if not info:
        return None
    path = run_dir / OUT_DIR / info["files"]["json"]
    if not path.is_file():
        return None
    return {"result": json.loads(path.read_text(encoding="utf-8")), "usage": info.get("usage"),
            "files": info["files"], "from_cache": True}


def file_path(run_dir: str | Path, fmt: str) -> Path | None:
    info = _read_info(Path(run_dir))
    if not info or fmt not in info["files"]:
        return None
    p = Path(run_dir) / OUT_DIR / info["files"][fmt]
    return p if p.is_file() else None


def dry_run(run_dir: str | Path) -> dict:
    """Build evaluation/evaluation_input.md and report its size - no model call."""
    run_dir = Path(run_dir)
    ctx = load_context(run_dir)
    _, _, checks_text = _code_checks(run_dir, _page_list(ctx.report_pages))
    out = run_dir / OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / "evaluation_input.md").write_text(f"{ctx.standard_text}\n\n---\n\n{ctx.report_text}\n", encoding="utf-8")
    est = ctx.est_tokens + (len(SYSTEM_INSTRUCTIONS) + len(checks_text)) // 4
    return {"standards": ctx.standard_labels, "standard_chars": len(ctx.standard_text),
            "report_chars": len(ctx.report_text), "input_tokens_estimate": est,
            "code_checks": bool(checks_text)}


# ------------------------------------------------------------------ outputs
def _build_outputs(run_dir: Path, kb: dict, ev: dict, ctx: BuiltContext, md: str, usage: dict,
                   facts, checks) -> dict:
    from llm_evaluation.objective_checks import apply_objective_checks
    from llm_evaluation.render.excel_renderer import render_xlsx
    from llm_evaluation.render.pdf_renderer import render_pdf

    ai: EvaluationAI = parse_chat_markdown(md, report_meta_from_text(ctx.report_text[:6000]))
    if checks:
        ai = apply_objective_checks(ai, facts, checks)        # code results win over the model text
    ai = verify_findings(ai, ctx)

    created = datetime.now(timezone.utc)
    labels, part2_label = _standards_labels(kb)
    doc = EvaluationDocument(
        evaluation_id=run_dir.name, created_at=created,
        report_filename=ev.get("file_name") or f"{ctx.report_number}.pdf",
        report_pages=max(len(ctx.report_pages and _page_list(ctx.report_pages)), _last_page(ev)),
        standards=labels, part2_label=part2_label, ai=ai, model=None,
    )
    gap_json = GapReportParser.from_evaluation(ai)

    out = run_dir / OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("Technical_Evaluation_*"):             # one current set of files per run
        old.unlink()
    stem = "Technical_Evaluation_" + _safe(ai.report_number or ctx.report_number or run_dir.name)
    files = {fmt: f"{stem}.{fmt}" for fmt in FORMATS}
    (out / files["pdf"]).write_bytes(render_pdf(doc))
    (out / files["xlsx"]).write_bytes(render_xlsx(doc))
    (out / files["json"]).write_text(json.dumps(gap_json, indent=2, ensure_ascii=False), encoding="utf-8")
    header = (f"# Evaluation output\n\n- Report: {doc.report_filename}\n- Standards: {', '.join(labels)}\n"
              f"- Created: {created:%Y-%m-%d %H:%M} UTC\n\n---\n\n")
    (out / files["md"]).write_text(header + md.strip() + "\n", encoding="utf-8")

    checks_count = [g["verification_status"] for g in gap_json["gaps"]]
    info = {"created_at": created.isoformat(), "report_number": ai.report_number, "standards": labels,
            "files": files, "usage": usage, "evidence": evidence_summary(ai.findings),
            "verification": {s: checks_count.count(s) for s in sorted(set(checks_count))}}
    (out / "run_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return {"result": gap_json, "usage": usage, "files": files, "from_cache": False}


def _read_info(run_dir: Path) -> dict | None:
    p = run_dir / OUT_DIR / "run_info.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _strip_header(md: str) -> str:
    if md.lstrip().startswith("# Evaluation output") and "\n---" in md:
        return md.split("\n---", 1)[1].strip()
    return md.strip()


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name.split(",")[0].strip()).strip("_")[:80] or "report"