"""Check every AI quote against the text the AI was given (report rows / standard clauses), page by page.

report_check / standard_check on each finding:
  "verified p.N"            quote found on the page the finding cites (report) or anywhere (standard)
  "found on p.N (not cited)" quote found, but not on a page the finding names
  "approximate p.N"         >= 80 % of the quote's words found close together
  "NOT FOUND"               quote not in the supplied text -> the finding needs manual review
  "no quote given"          'none' / empty (e.g. a clause that is absent from the report)
"""
from __future__ import annotations

import re
from functools import lru_cache

from llm_evaluation.context_builder import BuiltContext


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = s.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "−": "-",
                                   " ": " ", " ": " ", " ": " ", "×": "x"}))
    s = re.sub(r"(?<=\d)[ ,](?=\d{3}\b)", "", s)          # 50 000 / 1,000 -> 50000 / 1000
    s = re.sub(r"[^a-z0-9.%°ω/+-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _pages(ref: str) -> list[int]:
    out: list[int] = []
    for a, b in re.findall(r"(\d+)(?:\s*[–-]\s*(\d+))?", ref or ""):
        out += list(range(int(a), int(b) + 1)) if b and 0 <= int(b) - int(a) < 50 else [int(a)]
    return out


@lru_cache(maxsize=8192)
def _words(s: str) -> tuple[str, ...]:
    return tuple(w for w in s.split() if len(w) > 1 or w.isdigit())


def _approx(q: str, page: str) -> bool:
    qw = _words(q)
    if len(qw) < 4:
        return False
    pw = _words(page)
    need = set(qw)
    if len(need & set(pw)) < 0.8 * len(need):
        return False
    n = len(qw) + 6
    for i in range(0, max(1, len(pw) - n + 1), 3):
        if len(need & set(pw[i:i + n])) >= 0.8 * len(need):
            return True
    return False


def _hit(q: str, t: str) -> bool:
    return q in t or (len(q) >= 12 and q.replace(" ", "") in t.replace(" ", ""))


def find_quote(quote: str, docs: list[tuple[str, dict[int, str]]], cited: list[int] | None = None) -> str:
    q = _norm(quote).strip(" .\"'")
    if not q or q in ("not stated", "none", "n a", "-", "not given") or len(q) < 6:
        return "no quote given"
    cited = cited or []
    for label, pages in docs:
        for p in cited:
            for pp in (p, p - 1, p + 1):
                if pp in pages and _hit(q, pages[pp]):
                    return f"verified{_lbl(label)} p.{pp}"
    for label, pages in docs:
        for p, t in sorted(pages.items()):
            if _hit(q, t):
                return f"verified{_lbl(label)} p.{p}" if not cited else f"found{_lbl(label)} on p.{p} (not cited)"
    for label, pages in docs:
        for p, t in sorted(pages.items()):
            if _approx(q, t):
                return f"approximate{_lbl(label)} p.{p}"
    return "NOT FOUND"


def _lbl(label: str) -> str:
    return f" in {label}" if label else ""


def verify_findings(ai, ctx: BuiltContext):
    rep = [("", {p: _norm(t) for p, t in ctx.report_pages.items()})]
    stds = [(lbl, {p: _norm(t) for p, t in pages.items()}) for lbl, pages in ctx.standard_pages.items() if pages]
    for f in ai.findings:
        f.report_check = find_quote(f.report_quote, rep, _pages(f.pages))
        if f.standard_quote.strip().lower().startswith("not in supplied"):
            f.standard_check = "requirement not in supplied standards"
        else:
            f.standard_check = find_quote(f.standard_quote, stds)
    return ai

def evidence_summary(findings) -> dict[str, int]:
    def ok(s: str) -> bool:
        return s.startswith(("verified", "found", "approximate", "checked by code"))
    return {
        "report_quote_verified": sum(ok(f.report_check) for f in findings),
        "standard_quote_verified": sum(ok(f.standard_check) for f in findings),
        "not_found": sum("NOT FOUND" in (f.report_check + f.standard_check) for f in findings),
        "findings": len(findings),
    }