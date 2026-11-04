"""Model markdown answer -> gap JSON (same structure as complify-chat's GapReportParser).

{
  "report_id": "...",
  "gaps": [ { "clause_id", "gap_type", "priority", "normative_requirement", "finding_reason",
              "evidence_reference", "evidence_confidence", "verification_status", "required_action" } ],
  "final_summary": { "final_disposition", "evaluation_conclusion", "total_gaps", "recommended_action" }
}
evidence_confidence / verification_status come from code: were the model's quotes found in the
report and standard text it was given (evidence_check.py)?
"""
from __future__ import annotations

import re

from llm_evaluation.schema import EvaluationAI, Finding

_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Not stated": 4}


def _ok(check: str) -> bool:
    return check.startswith(("verified", "found", "checked by code"))


def _approx(check: str) -> bool:
    return check.startswith("approximate")


def _upper_code(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", (text or "").upper()).strip("_") or "NOT_STATED"


def _evidence_reference(pages: str) -> str:
    nums: list[str] = re.findall(r"\d+(?:\s*[–-]\s*\d+)?", pages or "")
    nums = [re.sub(r"\s", "", n).replace("-", "–") for n in nums]
    if not nums:
        return "Not stated"
    if len(nums) == 1:
        return f"Report page{'s' if '–' in nums[0] else ''} {nums[0]}"
    return f"Report pages {', '.join(nums[:-1])} and {nums[-1]}"


def _nothing_to_check(f: Finding) -> bool:
    """Checks not run, or the AI gave no quotes at all (older answers)."""
    no = ("not checked", "no quote given", "report not available", "standard not available")
    return f.report_check in no and f.standard_check in no


def _confidence(f: Finding) -> str:
    """HIGH: report evidence and requirement both found by code (or a code check); MEDIUM: one of them;
    LOW: neither found; NOT_CHECKED: PDFs not available or no quotes given."""
    if f.code_verified:
        return "HIGH"
    if _nothing_to_check(f):
        return "NOT_CHECKED"
    absence = f.report_check == "no quote given"           # e.g. clause not addressed: nothing to quote
    rep = _ok(f.report_check)
    std = _ok(f.standard_check)
    if rep and std or absence and std:
        return "HIGH" if rep else "MEDIUM"
    if rep or std or _approx(f.report_check) or _approx(f.standard_check):
        return "MEDIUM"
    return "LOW"


def _status(f: Finding) -> str:
    """CONFIRMED_REPORT_DEFECT  report evidence found (or the gap is an absence) and the requirement found
    REPORT_EVIDENCE_CONFIRMED report evidence found, requirement not found in the supplied standards
    REQUIREMENT_CONFIRMED     requirement found, report evidence not found
    REQUIRES_MANUAL_REVIEW    neither found -> a person must check this gap
    NOT_VERIFIED              the PDFs were not available, or the AI gave no quotes to check"""
    if f.code_verified:
        return "CONFIRMED_REPORT_DEFECT"
    if _nothing_to_check(f):
        return "NOT_VERIFIED"
    rep = _ok(f.report_check) or _approx(f.report_check) or f.report_check == "no quote given"
    std = _ok(f.standard_check) or _approx(f.standard_check)
    if rep and std:
        return "CONFIRMED_REPORT_DEFECT"
    if rep and f.report_check != "no quote given":
        return "REPORT_EVIDENCE_CONFIRMED"
    if std:
        return "REQUIREMENT_CONFIRMED"
    return "REQUIRES_MANUAL_REVIEW"


class GapReportParser:
    # ------------------------------------------------------------ builder
    @staticmethod
    def from_evaluation(ai: EvaluationAI) -> dict:
        findings = sorted(ai.findings, key=lambda f: _RANK.get(f.severity, 4))
        gaps = [{
            "clause_id": f.clause,
            "gap_type": f.gap_type,
            "priority": _upper_code(f.severity),
            "normative_requirement": f.reason,
            "finding_reason": f.finding,
            "evidence_reference": _evidence_reference(f.pages),
            "evidence_confidence": _confidence(f),
            "verification_status": _status(f),
            "required_action": f.required_action,
        } for f in findings]
        return {
            "report_id": (ai.report_number or "NOT_STATED").split(",")[0].strip(),
            "gaps": gaps,
            "final_summary": {
                "final_disposition": _upper_code(ai.final_verdict),
                "evaluation_conclusion": ai.conclusion,
                "total_gaps": len(gaps),
                "recommended_action": ai.recommended_action,
            },
        }