"""Diagnose ownership between extracted test conditions and structural links."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


class ConditionOwnershipStatus(str, Enum):
    """Relationship between a condition and the structural layer."""

    EXACT_OWNER = "EXACT_OWNER"
    COMPATIBLE_OWNER = "COMPATIBLE_OWNER"
    PARENT_OWNER = "PARENT_OWNER"
    CHILD_OWNER = "CHILD_OWNER"
    ORPHANED = "ORPHANED"
    AMBIGUOUS_OWNER = "AMBIGUOUS_OWNER"
    NO_STRUCTURAL_LINK = "NO_STRUCTURAL_LINK"


class BridgeClassification(str, Enum):
    """Condition coverage classification for one structural link."""

    FULL_BRIDGE = "FULL_BRIDGE"
    REQUIRED_SIDE_ONLY = "REQUIRED_SIDE_ONLY"
    ACTUAL_SIDE_ONLY = "ACTUAL_SIDE_ONLY"
    NO_CONDITION_DATA = "NO_CONDITION_DATA"
    OWNERSHIP_MAPPING_GAP = "OWNERSHIP_MAPPING_GAP"
    SEMANTIC_CONDITION_MISMATCH = "SEMANTIC_CONDITION_MISMATCH"


@dataclass
class ConditionOwnershipResult:
    condition_id: str
    side: str
    parameter_type: Optional[str]
    condition_role: Optional[str]
    clause_id: Optional[str]
    group_ids: List[str]
    structure_id: Optional[str]
    owner_id: Optional[str]
    source_id: Optional[str]
    ownership_status: ConditionOwnershipStatus
    structural_link_ids: List[str] = field(default_factory=list)
    structural_link_statuses: List[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class StructureLinkBridgeResult:
    link_id: str
    link_status: str
    clause_id: Optional[str]
    group_id: Optional[str]
    standard_step_ids: List[str]
    report_row_ids: List[str]
    required_condition_ids: List[str]
    actual_condition_ids: List[str]
    compatible_required_condition_ids: List[str]
    compatible_actual_condition_ids: List[str]
    semantic_compatibility: Optional[bool]
    classification: BridgeClassification
    reason: str


@dataclass
class DerivedIdentifierMismatch:
    side: str
    condition_id: str
    declared_owner_id: Optional[str]
    equivalent_owner_ids: List[str]
    source_id: Optional[str]
    reason: str


@dataclass
class ConditionOwnershipReconciliationReport:
    effective_kb_id: str
    report_document_id: str
    required_ownership: List[ConditionOwnershipResult] = field(default_factory=list)
    actual_ownership: List[ConditionOwnershipResult] = field(default_factory=list)
    structure_link_bridges: List[StructureLinkBridgeResult] = field(default_factory=list)
    potential_full_bridges_on_possible_structure: List[str] = field(default_factory=list)
    derived_id_mismatches: List[DerivedIdentifierMismatch] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)


class GenericConditionOwnershipReconciler:
    """Reconcile existing condition ownership without changing source artifacts."""

    def reconcile(self, evidence_enrichment, test_structure, pair_result,
                  source_conditions, effective_kb, report_evidence,
                  grouping, evidence_scope):
        structures = list(self._get(test_structure, "standard_test_structures", []) or [])
        reports = list(self._get(test_structure, "report_clause_structures", []) or [])
        links = list(self._get(test_structure, "structure_links", []) or [])
        requirements = list(self._get(source_conditions, "required_conditions", []) or [])
        actuals = list(self._get(source_conditions, "actual_conditions", []) or [])
        step_index, step_meta = self._standard_index(structures)
        row_index, row_meta = self._report_index(reports)
        links_by_step, links_by_row = self._link_indexes(links)
        diagnostics: List[Dict[str, Any]] = []
        mismatches: List[DerivedIdentifierMismatch] = []

        required_results = [self._ownership(c, "REQUIRED", step_index, step_meta,
                            links_by_step, links, mismatches) for c in requirements]
        actual_results = [self._ownership(c, "ACTUAL", row_index, row_meta,
                          links_by_row, links, mismatches) for c in actuals]

        req_by_owner = self._conditions_by_owner(requirements, "standard_step_id")
        act_by_owner = self._conditions_by_owner(actuals, "report_row_id")
        bridges = []
        for link in links:
            bridges.append(self._bridge(link, requirements, actuals, req_by_owner,
                                        act_by_owner, step_meta, row_meta))
        possible = [b.link_id for b in bridges
                    if b.link_status == "POSSIBLE" and b.classification == BridgeClassification.FULL_BRIDGE]
        for mismatch in mismatches:
            diagnostics.append({"code": "OWNERSHIP_DERIVED_ID_MISMATCH",
                                "side": mismatch.side,
                                "condition_id": mismatch.condition_id,
                                "equivalent_owner_ids": mismatch.equivalent_owner_ids})
        for bridge in bridges:
            diagnostics.append({"code": "OWNERSHIP_LINK_RECONCILED",
                                "link_id": bridge.link_id,
                                "classification": bridge.classification.value})

        ownership_keys = [x.value for x in ConditionOwnershipStatus]
        bridge_keys = [x.value for x in BridgeClassification]
        req_counts = Counter(x.ownership_status.value for x in required_results)
        act_counts = Counter(x.ownership_status.value for x in actual_results)
        bridge_counts = Counter(x.classification.value for x in bridges)
        matched = [x for x in bridges if x.link_status == "MATCHED"]
        summary = {
            "required_conditions": {k: req_counts[k] for k in ownership_keys},
            "actual_conditions": {k: act_counts[k] for k in ownership_keys},
            "structure_links": {k: bridge_counts[k] for k in bridge_keys},
            "total_required_conditions": len(requirements),
            "total_actual_conditions": len(actuals),
            "total_structure_links": len(links),
            "full_bridges_on_matched_structural_links": sum(
                x.classification == BridgeClassification.FULL_BRIDGE for x in matched),
            "potential_full_bridges_on_possible_links": len(possible),
            "conditions_orphaned_from_structural_layer": req_counts["ORPHANED"] + act_counts["ORPHANED"],
            "derived_id_mismatches": len(mismatches),
        }
        return ConditionOwnershipReconciliationReport(
            str(self._get(effective_kb, "effective_kb_id", "") or ""),
            str(self._get(report_evidence, "document_id", "") or ""),
            sorted(required_results, key=lambda x: x.condition_id),
            sorted(actual_results, key=lambda x: x.condition_id),
            sorted(bridges, key=lambda x: x.link_id), sorted(possible),
            sorted(mismatches, key=lambda x: (x.side, x.condition_id)),
            summary, sorted(diagnostics, key=lambda x: json.dumps(x, sort_keys=True)))

    def _ownership(self, condition, side, owner_index, owner_meta, links_by_owner,
                   links, mismatches):
        owner_field = "standard_step_id" if side == "REQUIRED" else "report_row_id"
        structure_field = "standard_structure_id" if side == "REQUIRED" else "report_structure_id"
        owner_id = self._string(self._get(condition, owner_field))
        structure_id = self._string(self._get(condition, structure_field))
        condition_id = self._string(self._get(condition, "condition_id")) or ""
        clause = self._string(self._get(condition, "clause_id"))
        groups = ([self._string(self._get(condition, "group_id"))] if side == "REQUIRED"
                  else [self._string(x) for x in self._get(condition, "group_ids", []) or []])
        groups = [x for x in groups if x]
        source_id = self._condition_source(condition, side)
        exact = owner_index.get(owner_id) if owner_id else None
        candidates = self._compatible_owners(condition, side, owner_meta)
        if exact:
            owner_links = links_by_owner.get(owner_id, [])
            if owner_links:
                status = ConditionOwnershipStatus.EXACT_OWNER
                reason = "Condition explicitly references the exact structural owner."
            else:
                status = ConditionOwnershipStatus.NO_STRUCTURAL_LINK
                reason = "Exact structural ownership is clear, but that owner has no structural link."
        elif len(candidates) == 1:
            candidate = owner_meta[candidates[0]]
            rel = self._clause_relation(clause, candidate.get("clause_id"))
            status = (ConditionOwnershipStatus.PARENT_OWNER if rel == "CONDITION_PARENT"
                      else ConditionOwnershipStatus.CHILD_OWNER if rel == "CONDITION_CHILD"
                      else ConditionOwnershipStatus.COMPATIBLE_OWNER)
            reason = "Equivalent provenance and compatible group/semantic source identify one owner."
            if owner_id and owner_id != candidates[0]:
                mismatches.append(DerivedIdentifierMismatch(side, condition_id, owner_id,
                                  candidates, source_id,
                                  "Equivalent source ownership has a different derived identifier."))
        elif len(candidates) > 1:
            status = ConditionOwnershipStatus.AMBIGUOUS_OWNER
            reason = "Several structural owners have equally compatible provenance."
        else:
            status = ConditionOwnershipStatus.ORPHANED
            reason = "Condition provenance cannot be associated with a structural owner."
        relevant_owners = [owner_id] if exact else candidates
        relevant_links = sorted({self._string(self._get(x, "link_id"))
                                 for oid in relevant_owners for x in links_by_owner.get(oid, [])})
        link_statuses = sorted({self._string(self._get(x, "candidate_status"))
                                for oid in relevant_owners for x in links_by_owner.get(oid, [])})
        return ConditionOwnershipResult(condition_id, side,
                self._enum(self._get(condition, "parameter_type")),
                self._string(self._get(condition, "condition_role")), clause, groups,
                structure_id, owner_id, source_id, status,
                [x for x in relevant_links if x], [x for x in link_statuses if x], reason)

    def _bridge(self, link, requirements, actuals, req_by_owner, act_by_owner,
                step_meta, row_meta):
        step_ids = [self._string(x) for x in self._get(link, "standard_step_ids", []) or []]
        row_ids = [self._string(x) for x in self._get(link, "report_row_ids", []) or []]
        direct_req = self._unique([c for oid in step_ids for c in req_by_owner.get(oid, [])])
        direct_act = self._unique([c for oid in row_ids for c in act_by_owner.get(oid, [])])
        compatible_req = self._cross_location(requirements, "REQUIRED", step_ids, step_meta,
                                              self._get(link, "group_id"))
        compatible_act = self._cross_location(actuals, "ACTUAL", row_ids, row_meta,
                                              self._get(link, "group_id"))
        req_pool = direct_req or compatible_req
        act_pool = direct_act or compatible_act
        semantic = None
        if req_pool and act_pool:
            semantic = any(self._semantic_compatible(r, a) for r in req_pool for a in act_pool)
        mapping_gap = (not direct_req and bool(compatible_req)) or (not direct_act and bool(compatible_act))
        if direct_req and direct_act:
            classification = (BridgeClassification.FULL_BRIDGE if semantic
                              else BridgeClassification.SEMANTIC_CONDITION_MISMATCH)
            reason = ("Both exact owners contain semantically compatible conditions." if semantic
                      else "Both exact owners contain conditions, but parameter or role semantics differ.")
        elif mapping_gap and req_pool and act_pool:
            classification = (BridgeClassification.OWNERSHIP_MAPPING_GAP if semantic
                              else BridgeClassification.SEMANTIC_CONDITION_MISMATCH)
            reason = ("Equivalent source provenance contains condition data not attached to the exact owner."
                      if semantic else "Cross-location condition candidates have incompatible semantics.")
        elif direct_req:
            classification = BridgeClassification.REQUIRED_SIDE_ONLY
            reason = "Only the exact standard step owns condition data."
        elif direct_act:
            classification = BridgeClassification.ACTUAL_SIDE_ONLY
            reason = "Only the exact report row owns condition data."
        elif mapping_gap:
            classification = BridgeClassification.OWNERSHIP_MAPPING_GAP
            reason = "Equivalent provenance contains condition data on only one side."
        else:
            classification = BridgeClassification.NO_CONDITION_DATA
            reason = "Neither matched structural owner contains usable condition data or equivalent provenance."
        return StructureLinkBridgeResult(
            self._string(self._get(link, "link_id")) or "",
            self._string(self._get(link, "candidate_status")) or "",
            self._string(self._get(link, "clause_id")),
            self._string(self._get(link, "group_id")), step_ids, row_ids,
            self._ids(direct_req), self._ids(direct_act), self._ids(compatible_req),
            self._ids(compatible_act), semantic, classification, reason)

    def _cross_location(self, conditions, side, owner_ids, owner_meta, link_group):
        targets = [owner_meta[x] for x in owner_ids if x in owner_meta]
        out = []
        for condition in conditions:
            declared = self._string(self._get(condition,
                "standard_step_id" if side == "REQUIRED" else "report_row_id"))
            if declared in owner_ids:
                continue
            for target in targets:
                if self._source_compatible(condition, side, target, link_group):
                    out.append(condition); break
        return self._unique(out)

    def _compatible_owners(self, condition, side, owner_meta):
        return sorted(oid for oid, meta in owner_meta.items()
                      if self._source_compatible(condition, side, meta, None))

    def _source_compatible(self, condition, side, meta, link_group):
        clause = self._string(self._get(condition, "clause_id"))
        if self._clause_relation(clause, meta.get("clause_id")) == "UNRELATED":
            return False
        condition_groups = ({self._string(self._get(condition, "group_id"))} if side == "REQUIRED"
                            else {self._string(x) for x in self._get(condition, "group_ids", []) or []})
        condition_groups.discard(None)
        meta_group = meta.get("group_id")
        if condition_groups and meta_group and meta_group not in condition_groups:
            return False
        if link_group and condition_groups and link_group not in condition_groups:
            return False
        source = self._condition_source(condition, side)
        source_match = bool(source and source in meta.get("source_ids", set()))
        text_match = self._text_overlap(self._condition_text(condition), meta.get("text", "")) >= .72
        return source_match or text_match

    @classmethod
    def _semantic_compatible(cls, required, actual):
        rp = cls._enum(cls._get(required, "parameter_type")); ap = cls._enum(cls._get(actual, "parameter_type"))
        rr = cls._string(cls._get(required, "condition_role")); ar = cls._string(cls._get(actual, "condition_role"))
        return bool(rp and rp == ap and rr and rr == ar and rr.startswith("TEST_"))

    @classmethod
    def _standard_index(cls, structures):
        index, meta = {}, {}
        for structure in structures:
            sid = cls._string(cls._get(structure, "structure_id")); clause = cls._string(cls._get(structure, "clause_id")); group = cls._string(cls._get(structure, "group_id"))
            for step in cls._get(structure, "test_method_steps", []) or []:
                oid = cls._string(cls._get(step, "step_id")); index[oid] = step
                prov = cls._get(step, "provenance", []) or []
                meta[oid] = {"structure_id": sid, "clause_id": clause, "group_id": group,
                    "source_ids": {cls._string(cls._get(x, "source_id")) for x in prov} | {cls._string(cls._get(x, "requirement_id")) for x in prov},
                    "text": cls._string(cls._get(step, "text")) or ""}
                meta[oid]["source_ids"].discard(None)
        return index, meta

    @classmethod
    def _report_index(cls, structures):
        index, meta = {}, {}
        for structure in structures:
            sid = cls._string(cls._get(structure, "structure_id")); clause = cls._string(cls._get(structure, "report_clause_id"))
            for row in cls._get(structure, "rows", []) or []:
                oid = cls._string(cls._get(row, "row_id")); index[oid] = row
                prov = cls._get(row, "provenance", []) or []
                groups = {cls._string(cls._get(x, "group_id")) for x in prov}; groups.discard(None)
                meta[oid] = {"structure_id": sid, "clause_id": clause,
                    "group_id": next(iter(groups), None),
                    "source_ids": {cls._string(cls._get(x, "source_id")) for x in prov},
                    "text": cls._string(cls._get(row, "raw_text")) or ""}
                meta[oid]["source_ids"].discard(None)
        return index, meta

    @classmethod
    def _link_indexes(cls, links):
        steps, rows = defaultdict(list), defaultdict(list)
        for link in links:
            for oid in cls._get(link, "standard_step_ids", []) or []: steps[cls._string(oid)].append(link)
            for oid in cls._get(link, "report_row_ids", []) or []: rows[cls._string(oid)].append(link)
        return steps, rows

    @classmethod
    def _conditions_by_owner(cls, conditions, field_name):
        out = defaultdict(list)
        for condition in conditions:
            owner = cls._string(cls._get(condition, field_name))
            if owner: out[owner].append(condition)
        return out

    @classmethod
    def _condition_source(cls, condition, side):
        direct = cls._get(condition, "effective_requirement_id" if side == "REQUIRED" else "report_evidence_id")
        if direct: return cls._string(direct)
        return next((cls._string(cls._get(x, "source_id")) for x in cls._get(condition, "provenance", []) or [] if cls._get(x, "source_id")), None)

    @classmethod
    def _condition_text(cls, condition):
        value = cls._get(condition, "expected_value") or cls._get(condition, "observed_value")
        text = cls._get(value, "raw_text")
        if text: return cls._string(text) or ""
        return next((cls._string(cls._get(x, "raw_excerpt")) for x in cls._get(condition, "provenance", []) or [] if cls._get(x, "raw_excerpt")), "")

    @staticmethod
    def _clause_relation(a, b):
        if not a or not b: return "UNRELATED"
        if a == b: return "SAME"
        if b.startswith(a + "."): return "CONDITION_PARENT"
        if a.startswith(b + "."): return "CONDITION_CHILD"
        return "UNRELATED"

    @staticmethod
    def _text_overlap(a, b):
        tokenize = lambda x: {t for t in __import__("re").findall(r"[a-z0-9]+", str(x).casefold()) if len(t) > 2}
        aa, bb = tokenize(a), tokenize(b)
        return len(aa & bb) / max(1, min(len(aa), len(bb)))

    @classmethod
    def _unique(cls, items):
        return list({cls._string(cls._get(x, "condition_id")): x for x in items}.values())

    @classmethod
    def _ids(cls, items): return sorted(cls._string(cls._get(x, "condition_id")) for x in items)
    @staticmethod
    def _get(value, name, default=None): return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default) if value is not None else default
    @staticmethod
    def _string(value): return None if value is None else str(value.value if isinstance(value, Enum) else value)
    _enum = _string

    @classmethod
    def _plain(cls, value):
        if isinstance(value, Enum): return value.value
        if is_dataclass(value): return cls._plain(asdict(value))
        if isinstance(value, dict): return {k: cls._plain(v) for k, v in value.items()}
        if isinstance(value, list): return [cls._plain(v) for v in value]
        return value

    @classmethod
    def to_dict(cls, report):
        if not is_dataclass(report): raise TypeError("ownership reconciliation report required")
        return cls._plain(asdict(report))

    @classmethod
    def to_json(cls, report, indent=2):
        return json.dumps(cls.to_dict(report), ensure_ascii=False, sort_keys=True, indent=indent)

    @classmethod
    def save_json(cls, report, path):
        target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(cls.to_json(report) + "\n", encoding="utf-8")
        return target


__all__ = ["BridgeClassification", "ConditionOwnershipReconciliationReport",
           "ConditionOwnershipResult", "ConditionOwnershipStatus",
           "DerivedIdentifierMismatch", "GenericConditionOwnershipReconciler",
           "StructureLinkBridgeResult"]
