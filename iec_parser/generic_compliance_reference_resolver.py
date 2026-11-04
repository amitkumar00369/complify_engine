"""Generic, deterministic compliance artifact reference resolver (Step 32-A)."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .generic_compliance_reference_models import (
    ResolutionIntegrity, ResolvedComplianceContext, ResolvedComplianceContextBundle,
)


class ComplianceReferenceResolutionError(ValueError):
    pass


class GenericComplianceReferenceResolver:
    """Resolve references only within one supplied run; never evaluate compliance."""

    SCHEMA_VERSION = "1.0"
    ARTIFACTS = {
        "effective_kb": "standards/effective_kb.json",
        "report_evidence": "report/report_evidence.json",
        "product_profile": "report/product_profile.json",
        "applicability": "report/applicability_result.json",
        "evidence_match": "report/evidence_match_result.json",
        "technical": "report/technical_constraint_result.json",
        "na_initial": "report/na_validation_result.json",
        "requirement_groups": "report/requirement_grouping_result.json",
        "applicability_group": "report/group_aware_applicability_result.json",
        "na_group": "report/group_aware_na_validation_result.json",
        "scope": "report/report_evidence_scope_result.json",
        "na_scope": "report/scope_aware_na_validation_result.json",
        "final_decisions": "decisions/final_requirement_decision.json",
        "originating_issues": "decisions/clause_evaluation_summary.json",
        "final_issues": "decisions/final_compliance_issues.json",
        "aggregates": "decisions/aggregated_compliance_issues.json",
        "actions": "decisions/prioritized_next_actions.json",
        "final_response": "decisions/final_compliance_response.json",
        "manifest": "manifest/pipeline_manifest.json",
    }
    REQUIRED = ("final_issues",)
    ID_FIELDS = {
        "requirements": ("effective_requirement_id", "requirement_id"),
        "requirement_groups": ("group_id", "requirement_group_id", "logical_group_id"),
        "report_evidence": ("evidence_id",), "product_facts": ("fact_id", "product_fact_id"),
        "product_identity": ("identity_id", "product_identity_id"),
        "issues": ("issue_id",), "aggregates": ("aggregate_id", "group_id"),
        "actions": ("action_id",),
    }
    REQUIREMENT_KEYS = ("effective_requirement_id", "requirement_id")

    def resolve_run(self, run_directory: str | Path, output_path: str | Path | None = None) -> ResolvedComplianceContextBundle:
        root = Path(run_directory).resolve()
        if not root.is_dir():
            raise ComplianceReferenceResolutionError(f"run directory does not exist: {root}")
        artifacts, availability = self._load(root)
        missing_required = [self.ARTIFACTS[x] for x in self.REQUIRED if x not in artifacts]
        if missing_required:
            raise ComplianceReferenceResolutionError("missing required artifact(s): " + ", ".join(missing_required))
        indexes, duplicates = self._indexes(artifacts)
        self._stage_indexes = {
            name: self._relationship_index(artifacts.get(name)) for name in (
                "applicability", "applicability_group", "evidence_match", "technical",
                "na_initial", "na_group", "na_scope", "scope", "final_decisions",
            )
        }
        final_records = list((artifacts["final_issues"].get("issues") or []))
        contexts = [self._resolve(copy.deepcopy(x), artifacts, indexes, duplicates, availability) for x in final_records]
        counts = Counter(x.resolution_integrity.status for x in contexts)
        missing = Counter(m.get("reference_type", "unknown") for x in contexts for m in x.resolution_integrity.missing_references)
        accounting = {
            "final_issue_count": len(final_records), "contexts_generated": len(contexts),
            "complete_contexts": counts["COMPLETE"], "partial_contexts": counts["PARTIAL"],
            "invalid_reference_contexts": counts["INVALID_REFERENCE"],
            "missing_references_by_type": dict(sorted(missing.items())),
            "duplicate_ids": sum(len(v) for v in duplicates.values()),
            "canonical_aliases": sum(1 for x in getattr(self, "duplicate_audit", []) if x["classification"] == "CANONICAL_ALIAS"),
            "derived_duplicates": sum(1 for x in getattr(self, "duplicate_audit", []) if x["classification"] == "DERIVED_DUPLICATE"),
            "true_duplicates": sum(1 for x in getattr(self, "duplicate_audit", []) if x["classification"] == "TRUE_DUPLICATE"),
            "ambiguous_duplicates": sum(1 for x in getattr(self, "duplicate_audit", []) if x["classification"] == "AMBIGUOUS_DUPLICATE"),
            "orphan_references": sum(missing.values()),
        }
        manifest = artifacts.get("manifest", {})
        bundle = ResolvedComplianceContextBundle(self.SCHEMA_VERSION, manifest.get("run_id"), {
            "run_directory": str(root), "artifact_policy": {"required": [self.ARTIFACTS[x] for x in self.REQUIRED], "optional": [v for k, v in self.ARTIFACTS.items() if k not in self.REQUIRED]},
            "artifacts": availability,
        }, accounting, contexts)
        destination = Path(output_path) if output_path else root / "llm/resolved_compliance_context.json"
        self.save_json(bundle, destination)
        return bundle

    def _load(self, root: Path) -> Tuple[Dict[str, Any], Dict[str, str]]:
        loaded, status = {}, {}
        for name, relative in self.ARTIFACTS.items():
            path = root / relative
            if not path.is_file(): status[relative] = "MISSING"; continue
            try:
                loaded[name] = json.loads(path.read_text(encoding="utf-8")); status[relative] = "AVAILABLE"
            except (OSError, json.JSONDecodeError) as exc:
                raise ComplianceReferenceResolutionError(f"invalid artifact {relative}: {exc}") from exc
        return loaded, status

    @staticmethod
    def _records(value: Any, path: str = "$") -> Iterable[Tuple[Dict[str, Any], str]]:
        if isinstance(value, Mapping):
            yield dict(value), path
            for key, child in value.items(): yield from GenericComplianceReferenceResolver._records(child, f"{path}.{key}")
        elif isinstance(value, list):
            for pos, child in enumerate(value): yield from GenericComplianceReferenceResolver._records(child, f"{path}[{pos}]")

    def _make_index(self, source: Any, fields: Sequence[str], canonicalize: bool = False) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
        idx: Dict[str, List[Dict[str, Any]]] = defaultdict(list); locations: Dict[str, List[str]] = defaultdict(list)
        for record, path in self._records(source or {}):
            for field in fields:
                value = record.get(field)
                if value is not None and not isinstance(value, (dict, list)):
                    key = str(value); idx[key].append(copy.deepcopy(record)); locations[key].append(path); break
        dup = []
        if canonicalize:
            for key, values in list(idx.items()):
                if len(values) < 2: continue
                cores = {self._substantive_fingerprint(x) for x in values}
                classification = "CANONICAL_ALIAS" if len(cores) == 1 else "TRUE_DUPLICATE"
                audit = {"id": key, "source_locations": locations[key], "classification": classification}
                self.duplicate_audit.append(audit)
                if classification == "CANONICAL_ALIAS":
                    canonical = copy.deepcopy(values[0])
                    canonical["canonical_resolution"] = {"classification": classification, "source_locations": list(locations[key]), "representations": copy.deepcopy(values)}
                    idx[key] = [canonical]
                else: dup.append({"id": key, "source_locations": locations[key], "classification": "TRUE_DUPLICATE_CONFLICT"})
        else:
            dup = [{"id": key, "source_locations": locations[key], "classification": "TRUE_DUPLICATE_CONFLICT"} for key, values in idx.items() if len(values) > 1]
        return dict(idx), dup

    @staticmethod
    def _substantive_fingerprint(record: Mapping[str, Any]) -> str:
        """Ignore location-only provenance while comparing canonical entity semantics."""
        provenance = {"base_sources", "delta_sources", "source_locations", "canonical_resolution"}
        core = {key: value for key, value in record.items() if key not in provenance}
        identity_fields = ("standard_id", "standard_number", "clause_id", "requirement_id", "annex_id", "definition_id")
        for field in ("base_sources", "delta_sources"):
            identities = [{key: source.get(key) for key in identity_fields if source.get(key) is not None} for source in record.get(field, []) if isinstance(source, Mapping)]
            core[field + "_identities"] = sorted(identities, key=lambda x: json.dumps(x, sort_keys=True))
        return json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _indexes(self, a: Dict[str, Any]):
        self.duplicate_audit = []
        origin_records = []
        for clause in (a.get("originating_issues", {}).get("clauses") or []):
            for group in (clause.get("group_summaries") or []): origin_records.extend(group.get("issues") or [])
        specs = {
            "requirements": ("effective_kb", ("effective_requirement_id",)),
            "requirement_groups": ("requirement_groups", ("group_id",)),
            "report_evidence": ("report_evidence", ("evidence_id",)),
            "product_facts": ("product_profile", self.ID_FIELDS["product_facts"]),
            "product_identity": ("product_profile", self.ID_FIELDS["product_identity"]),
            "issues": ("_origin_records", ("issue_id",)), "final_issues": ("final_issues", ("issue_id",)),
            "aggregates": ("aggregates", ("aggregate_id", "group_id")), "actions": ("actions", ("action_id",)),
        }
        indexes, duplicates = {}, {}
        sources = dict(a); sources["_origin_records"] = origin_records
        for name, (artifact, fields) in specs.items():
            indexes[name], duplicates[name] = self._make_index(sources.get(artifact), fields, canonicalize=name == "requirements")
        return indexes, duplicates

    @staticmethod
    def _refs(issue: Mapping[str, Any], *keys: str) -> List[str]:
        found = []
        for key in keys:
            value = issue.get(key)
            if isinstance(value, list): found.extend(str(x.get("evidence_id") if isinstance(x, Mapping) and "evidence_id" in x else x) for x in value)
            elif value is not None: found.append(str(value))
        return sorted(set(x for x in found if x and x != "None"))

    def _lookup(self, kind, ref, indexes, integrity, required=True):
        values = indexes.get(kind, {}).get(str(ref), [])
        if len(values) == 1: return copy.deepcopy(values[0])
        item = {"reference_type": kind, "reference_id": str(ref)}
        if not values:
            if required: integrity.missing_references.append(item)
        else: integrity.ambiguous_references.append(item)
        return None

    def _related(self, artifact: Any, requirement_ids: set[str], group_id: Optional[str] = None) -> List[Dict[str, Any]]:
        result, seen = [], set()
        for record, path in self._records(artifact or {}):
            rid = next((str(record[k]) for k in self.REQUIREMENT_KEYS if record.get(k) is not None), None)
            gid = next((str(record[k]) for k in ("group_id", "requirement_group_id", "logical_group_id") if record.get(k) is not None), None)
            if (rid and rid in requirement_ids) or (group_id and gid == group_id):
                marker = json.dumps(record, sort_keys=True, separators=(",", ":"))
                if marker not in seen: result.append(copy.deepcopy(record)); seen.add(marker)
        return result

    def _relationship_index(self, artifact: Any) -> Dict[str, List[Dict[str, Any]]]:
        result: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        seen: Dict[str, set[str]] = defaultdict(set)
        for record, _ in self._records(artifact or {}):
            keys = []
            for field in (*self.REQUIREMENT_KEYS, "group_id", "requirement_group_id", "logical_group_id"):
                if record.get(field) is not None: keys.append(str(record[field]))
            if not keys: continue
            marker = json.dumps(record, sort_keys=True, separators=(",", ":"))
            for key in keys:
                if marker not in seen[key]: result[key].append(copy.deepcopy(record)); seen[key].add(marker)
        return dict(result)

    def _stage_related(self, stage: str, requirement_ids: set[str], group_id: Optional[str]) -> List[Dict[str, Any]]:
        result, seen = [], set()
        table = self._stage_indexes.get(stage, {})
        for key in sorted(requirement_ids | ({group_id} if group_id else set())):
            for record in table.get(key, []):
                marker = json.dumps(record, sort_keys=True, separators=(",", ":"))
                if marker not in seen: result.append(copy.deepcopy(record)); seen.add(marker)
        return result

    def _resolve(self, issue, a, idx, duplicates, availability):
        integrity = ResolutionIntegrity(artifact_availability=copy.deepcopy(availability))
        issue_id = str(issue.get("issue_id")); clause = None if issue.get("clause_id") is None else str(issue["clause_id"])
        req_ids = self._refs(issue, "requirement_ids"); group_id = issue.get("requirement_group_id") or issue.get("logical_group_id")
        group = self._lookup("requirement_groups", group_id, idx, integrity) if group_id else None
        if group:
            member_ids = self._refs(group, "requirement_ids")
            for member in group.get("members") or []:
                if isinstance(member, Mapping): member_ids += self._refs(member, "effective_requirement_id", "requirement_id")
            for rid in sorted(set(member_ids)):
                if not idx["requirements"].get(rid): integrity.missing_references.append({"reference_type": "group_member_requirement", "reference_id": rid})
        requirements = [x for rid in req_ids if (x := self._lookup("requirements", rid, idx, integrity))]
        evidence_ids = self._refs(issue, "evidence_refs", "evidence_ids")
        matches = self._stage_related("evidence_match", set(req_ids), str(group_id) if group_id else None)
        for match in matches: evidence_ids += self._refs(match, "evidence_refs", "evidence_ids", "selected_evidence_ids")
        evidence_ids = sorted(set(evidence_ids)); evidence = []; evidence_resolution = []
        for ref in evidence_ids:
            value = self._lookup("report_evidence", ref, idx, integrity)
            evidence_resolution.append({"evidence_id": ref, "status": "RESOLVED" if value else ("AMBIGUOUS" if len(idx["report_evidence"].get(ref, [])) > 1 else "UNRESOLVED")})
            if value: evidence.append(value)
        facts = [x for ref in self._refs(issue, "product_fact_ids") if (x := self._lookup("product_facts", ref, idx, integrity))]
        identities = [x for ref in self._refs(issue, "product_identity_ids") if (x := self._lookup("product_identity", ref, idx, integrity))]
        origin_id = ((issue.get("provenance") or {}).get("originating_issue_id")); origin = self._lookup("issues", origin_id, idx, integrity, required=False) if origin_id else None
        origin_resolution = "RESOLVED" if origin else ("PARTIAL" if origin_id or issue.get("provenance") else "UNAVAILABLE")
        aggregates = [copy.deepcopy(r) for values in idx["aggregates"].values() for r in values if issue_id in self._refs(r, "issue_ids", "affected_issue_ids")]
        aggregate_ids = {str(x.get("aggregate_id") or x.get("group_id")) for x in aggregates}
        actions = [copy.deepcopy(r) for values in idx["actions"].values() for r in values if issue_id in self._refs(r, "issue_ids", "affected_issue_ids") or aggregate_ids.intersection(self._refs(r, "affected_aggregate_group_ids"))]
        related = lambda name: self._stage_related(name, set(req_ids), str(group_id) if group_id else None)
        applicability = []
        for stage in ("applicability", "applicability_group"):
            applicability.extend([{**x, "source_stage": stage} for x in related(stage)])
        na = []
        for stage in ("na_initial", "na_group", "na_scope"):
            na.extend([{**x, "source_stage": stage} for x in related(stage)])
        scope = [{**x, "source_stage": "scope"} for x in related("scope")]
        for kind, entries in duplicates.items():
            relevant = {issue_id, *req_ids, *evidence_ids, *(self._refs(issue, "product_fact_ids", "product_identity_ids"))}
            if group_id: relevant.add(str(group_id))
            integrity.duplicate_ids.extend([{**x, "reference_type": kind} for x in entries if x["id"] in relevant])
        if integrity.ambiguous_references or integrity.duplicate_ids: integrity.status = "INVALID_REFERENCE"
        elif integrity.missing_references: integrity.status = "PARTIAL"
        integrity.all_required_references_resolved = not (integrity.missing_references or integrity.ambiguous_references or integrity.duplicate_ids)
        provenance = {
            "standard": [{"effective_kb_id": a.get("effective_kb", {}).get("effective_kb_id"), "base_standard": copy.deepcopy(a.get("effective_kb", {}).get("base_standard")), "delta_standard": copy.deepcopy(a.get("effective_kb", {}).get("delta_standard"))}],
            "report": [{"document_id": a.get("report_evidence", {}).get("document_id"), "report_number": a.get("report_evidence", {}).get("report_number"), "evidence_ids": evidence_ids}],
            "product": [{"profile_id": a.get("product_profile", {}).get("profile_id")}],
            "deterministic_artifacts": [{"artifact_name": path, "stage": name, "availability": availability[path]} for name, path in self.ARTIFACTS.items()],
        }
        content_key = {"final_issue_id": issue_id, "issue": issue, "run_id": a.get("manifest", {}).get("run_id")}
        context_id = "RESOLVED-CONTEXT-" + hashlib.sha256(json.dumps(content_key, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20].upper()
        return ResolvedComplianceContext(context_id, issue_id, clause, issue, origin, origin_resolution, group, requirements, evidence, evidence_resolution, facts, identities, applicability, related("technical"), na, scope, related("final_decisions"), aggregates, actions, provenance, integrity)

    @staticmethod
    def to_dict(bundle: ResolvedComplianceContextBundle) -> Dict[str, Any]: return bundle.to_dict()
    @classmethod
    def to_json(cls, bundle, indent=2): return json.dumps(cls.to_dict(bundle), ensure_ascii=False, sort_keys=True, indent=indent)
    @classmethod
    def save_json(cls, bundle, path):
        target = Path(path); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(cls.to_json(bundle) + "\n", encoding="utf-8"); return target


__all__ = ["ComplianceReferenceResolutionError", "GenericComplianceReferenceResolver"]
