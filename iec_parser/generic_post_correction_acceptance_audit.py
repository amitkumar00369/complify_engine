"""Read-only semantic comparison helpers for post-correction acceptance audits."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


class GenericPostCorrectionAcceptanceAudit:
    """Compare pipeline artifacts by meaning rather than run-local identifiers."""

    _SPACE = re.compile(r"\s+")
    _BOILERPLATE = re.compile(
        r"(?:page\s+\d+\s+of\s+\d+|report\s+no\.?|trf\s+no\.?|"
        r"clause\s+requirement\s*\+\s*test\s+result)", re.IGNORECASE
    )

    def __init__(self, before_run: Any, after_run: Any) -> None:
        self.before_run = Path(before_run).resolve()
        self.after_run = Path(after_run).resolve()
        for path in (self.before_run, self.after_run):
            if not path.is_dir():
                raise FileNotFoundError(path)
        self.before = self._load_run(self.before_run)
        self.after = self._load_run(self.after_run)

    @classmethod
    def semantic_issue_fingerprint(
        cls, issue: Mapping[str, Any], requirement_texts: Mapping[str, str]
    ) -> str:
        """Return a stable fingerprint that deliberately excludes local IDs."""

        texts = sorted({
            cls._normalize(requirement_texts.get(str(identifier), ""))
            for identifier in issue.get("requirement_ids", []) or []
            if requirement_texts.get(str(identifier))
        })
        action = issue.get("next_action") or {}
        evidence_classes = sorted({cls._evidence_class(value)
                                   for value in issue.get("evidence_refs", []) or []})
        payload = {
            "clause": cls._normalize(str(issue.get("clause_id") or "")),
            "requirement_meaning": texts,
            "issue_type": str(issue.get("issue_type") or ""),
            "conclusion": str(issue.get("compliance_conclusion") or ""),
            "action": str(action.get("type") or ""),
            "evidence_classes": evidence_classes,
            "reason": cls._normalize(str((issue.get("provenance") or {}).get("upstream_reason") or "")),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def issue_delta(self) -> Dict[str, Any]:
        """Decompose issue changes using semantic multiset matching."""

        before_issues = self.before["issues"].get("issues", [])
        after_issues = self.after["issues"].get("issues", [])
        before_text = self._requirement_texts(self.before["effective"])
        after_text = self._requirement_texts(self.after["effective"])
        before_counts = Counter(self.semantic_issue_fingerprint(x, before_text) for x in before_issues)
        after_counts = Counter(self.semantic_issue_fingerprint(x, after_text) for x in after_issues)
        persisted = sum((before_counts & after_counts).values())
        added = sum((after_counts - before_counts).values())
        removed = sum((before_counts - after_counts).values())
        before_requirements = {self._normalize(text) for text in before_text.values()}
        evidence = self._evidence_index(self.after["evidence"])
        attribution = Counter()
        for issue in after_issues:
            fingerprint = self.semantic_issue_fingerprint(issue, after_text)
            if before_counts[fingerprint]:
                before_counts[fingerprint] -= 1
                continue
            meanings = {self._normalize(after_text.get(str(x), ""))
                        for x in issue.get("requirement_ids", []) or []}
            refs = [evidence.get(str(x)) for x in issue.get("evidence_refs", []) or []]
            if any(value and value not in before_requirements for value in meanings):
                attribution["changed_due_to_new_requirements"] += 1
            elif any((item or {}).get("evidence_type") == "SUBROW" for item in refs):
                attribution["changed_due_to_subrow_split"] += 1
            elif str((issue.get("provenance") or {}).get("upstream_reason", "")).startswith("REPORT_SCOPE"):
                attribution["changed_due_to_evidence_scope"] += 1
            elif issue.get("product_fact_ids"):
                attribution["changed_due_to_product_profile"] += 1
            else:
                attribution["changed_due_to_effective_kb"] += 1
        return {
            "before_total": len(before_issues), "after_total": len(after_issues),
            "added": added, "removed": removed, "persisted_semantically": persisted,
            **{key: attribution[key] for key in (
                "changed_due_to_new_requirements", "changed_due_to_subrow_split",
                "changed_due_to_evidence_scope", "changed_due_to_product_profile",
                "changed_due_to_effective_kb")},
            "before_by_type": dict(sorted(Counter(x.get("issue_type") for x in before_issues).items())),
            "after_by_type": dict(sorted(Counter(x.get("issue_type") for x in after_issues).items())),
            "before_by_severity": dict(sorted(Counter(x.get("severity") for x in before_issues).items())),
            "after_by_severity": dict(sorted(Counter(x.get("severity") for x in after_issues).items())),
            "before_by_conclusion": dict(sorted(Counter(x.get("compliance_conclusion") for x in before_issues).items())),
            "after_by_conclusion": dict(sorted(Counter(x.get("compliance_conclusion") for x in after_issues).items())),
        }

    def subrow_audit(self, limit: int = 60) -> Dict[str, Any]:
        """Classify a source-distributed sample of extracted subrows."""

        evidence = [item for item in self._evidence_index(self.after["evidence"]).values()
                    if item.get("evidence_type") == "SUBROW"]
        sampled = self._distributed(evidence, max(50, limit))
        classifications = Counter()
        probes = []
        matches = self._matches_by_evidence(self.after["matches"])
        issues = self._issues_by_evidence(self.after["issues"])
        for item in sampled:
            classification = self.classify_subrow(item)
            classifications[classification] += 1
            evidence_id = str(item.get("evidence_id"))
            probes.append({
                "evidence_id": evidence_id, "clause_id": item.get("clause_id"),
                "parent_evidence_id": item.get("parent_evidence_id"),
                "verdict": item.get("reported_verdict"),
                "classification": classification,
                "text": str(item.get("raw_text") or "")[:400],
                "matched_requirements": sorted(matches.get(evidence_id, set())),
                "final_issue_types": sorted(issues.get(evidence_id, set())),
            })
        return {
            "sample": len(sampled), "valid_subrows": classifications["VALID_SUBROW"],
            "over_split": classifications["OVER_SPLIT_SUBROW"],
            "under_split": classifications["UNDER_SPLIT_ROW"],
            "ambiguous": classifications["AMBIGUOUS_ROW"], "probes": probes,
        }

    @classmethod
    def classify_subrow(cls, item: Mapping[str, Any]) -> str:
        text = cls._normalize(str(item.get("raw_text") or ""))
        verdict = str(item.get("reported_verdict") or "")
        if not text or cls._BOILERPLATE.search(text):
            return "OVER_SPLIT_SUBROW"
        embedded = len(re.findall(r"\b(?:P|PASS|N/?A|FAIL|F)\b", text, re.I))
        if embedded > 1:
            return "UNDER_SPLIT_ROW"
        if verdict in {"PASS", "NA", "FAIL", "NOT_TESTED"} and len(text) >= 8:
            return "VALID_SUBROW"
        return "AMBIGUOUS_ROW"

    def conflict_audit(self) -> Dict[str, Any]:
        """Classify all post-run conflict issues by their evidence ownership."""

        evidence = self._evidence_index(self.after["evidence"])
        results = Counter()
        probes = []
        conflicts = [item for item in self.after["issues"].get("issues", [])
                     if "CONFLICT" in str(item.get("issue_type", ""))]
        for issue in conflicts:
            refs = [evidence.get(str(value)) for value in issue.get("evidence_refs", []) or []]
            refs = [item for item in refs if item]
            parents = defaultdict(set)
            for item in refs:
                if item.get("evidence_type") == "SUBROW":
                    parents[str(item.get("parent_evidence_id"))].add(item.get("reported_verdict"))
            if any(len(verdicts - {"NOT_STATED"}) > 1 for verdicts in parents.values()):
                classification = "FALSE_CONFLICT_SCOPE_LEAKAGE"
            elif len({str(item.get("evidence_id")) for item in refs}) < len(refs):
                classification = "FALSE_CONFLICT_DUPLICATE_EVIDENCE"
            elif refs and len({item.get("reported_verdict") for item in refs} - {"NOT_STATED"}) > 1:
                classification = "TRUE_CONFLICT"
            elif issue.get("product_fact_ids") or issue.get("product_identity_ids"):
                classification = "CORRECT_BUT_TOO_GENERIC"
            else:
                classification = "UNRESOLVED"
            results[classification] += 1
            probes.append({"issue_id": issue.get("issue_id"), "clause_id": issue.get("clause_id"),
                           "classification": classification,
                           "evidence_refs": issue.get("evidence_refs", [])})
        return {"sample": len(conflicts), "true_conflict": results["TRUE_CONFLICT"],
                "false_scope_leakage": results["FALSE_CONFLICT_SCOPE_LEAKAGE"],
                "false_duplicate": results["FALSE_CONFLICT_DUPLICATE_EVIDENCE"],
                "generic": results["CORRECT_BUT_TOO_GENERIC"],
                "unresolved": results["UNRESOLVED"], "probes": probes}

    @staticmethod
    def aggregate_hash(path: Any) -> str:
        target = Path(path)
        if target.is_file():
            return hashlib.sha256(target.read_bytes()).hexdigest()
        digest = hashlib.sha256()
        for item in sorted(value for value in target.rglob("*") if value.is_file()):
            digest.update(str(item.relative_to(target)).encode())
            digest.update(b"\0")
            digest.update(hashlib.sha256(item.read_bytes()).digest())
        return digest.hexdigest()

    @classmethod
    def _load_run(cls, root: Path) -> Dict[str, Any]:
        paths = {"effective": "standards/effective_kb.json",
                 "evidence": "report/report_evidence.json",
                 "matches": "report/evidence_match_result.json",
                 "issues": "decisions/final_compliance_issues.json"}
        return {key: json.loads((root / value).read_text(encoding="utf-8"))
                for key, value in paths.items()}

    @classmethod
    def _requirement_texts(cls, artifact: Mapping[str, Any]) -> Dict[str, str]:
        output: Dict[str, str] = {}
        def walk(items: Iterable[Mapping[str, Any]]) -> None:
            for clause in items or []:
                for requirement in clause.get("requirements", []) or []:
                    identifier = requirement.get("effective_requirement_id") or requirement.get("requirement_id")
                    if identifier: output[str(identifier)] = str(requirement.get("text") or "")
                walk(clause.get("children", []) or [])
        walk(artifact.get("clauses", []) or [])
        for annex in artifact.get("annexes", []) or []:
            walk(annex.get("clauses", []) or [])
            for requirement in annex.get("requirements", []) or []:
                identifier = requirement.get("effective_requirement_id") or requirement.get("requirement_id")
                if identifier: output[str(identifier)] = str(requirement.get("text") or "")
        return output

    @classmethod
    def _evidence_index(cls, artifact: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
        output: Dict[str, Dict[str, Any]] = {}
        def walk(items: Iterable[Mapping[str, Any]]) -> None:
            for clause in items or []:
                for evidence in clause.get("evidence_items", []) or []:
                    output[str(evidence.get("evidence_id"))] = dict(evidence)
                walk(clause.get("children", []) or [])
        walk(artifact.get("clauses", []) or [])
        return output

    @staticmethod
    def _matches_by_evidence(artifact: Mapping[str, Any]) -> Dict[str, set]:
        output = defaultdict(set)
        for match in artifact.get("matches", []) or []:
            for reference in match.get("evidence_refs", []) or []:
                output[str(reference.get("evidence_id"))].add(str(match.get("effective_requirement_id")))
        return output

    @staticmethod
    def _issues_by_evidence(artifact: Mapping[str, Any]) -> Dict[str, set]:
        output = defaultdict(set)
        for issue in artifact.get("issues", []) or []:
            for reference in issue.get("evidence_refs", []) or []:
                output[str(reference)].add(str(issue.get("issue_type")))
        return output

    @staticmethod
    def _distributed(items: Sequence[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
        if len(items) <= count: return list(items)
        indexes = sorted({round(index * (len(items) - 1) / (count - 1)) for index in range(count)})
        return [items[index] for index in indexes]

    @classmethod
    def _normalize(cls, value: str) -> str:
        return cls._SPACE.sub(" ", re.sub(r"[^a-z0-9%./+<>=-]+", " ", value.casefold())).strip()

    @staticmethod
    def _evidence_class(value: Any) -> str:
        text = str(value)
        if "SUBROW" in text: return "SUBROW"
        if "TABLE" in text: return "TABLE"
        return "CLAUSE_ROW"


__all__ = ["GenericPostCorrectionAcceptanceAudit"]
