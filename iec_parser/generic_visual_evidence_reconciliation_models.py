"""Decision-isolated models for deterministic native/visual reconciliation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class _StringEnum(str, Enum): pass


class ReconciliationStatus(_StringEnum):
    AGREEMENT="AGREEMENT";VISUAL_SUPPLEMENTS_NATIVE="VISUAL_SUPPLEMENTS_NATIVE"
    NATIVE_SUPPLEMENTS_VISUAL="NATIVE_SUPPLEMENTS_VISUAL";CONFLICT="CONFLICT"
    DUPLICATE="DUPLICATE";VISUAL_LOW_CONFIDENCE="VISUAL_LOW_CONFIDENCE"
    INSUFFICIENT_SCOPE="INSUFFICIENT_SCOPE";INSUFFICIENT_AUTHORITY="INSUFFICIENT_AUTHORITY"
    UNMATCHED_VISUAL="UNMATCHED_VISUAL";REVIEW_REQUIRED="REVIEW_REQUIRED"


class ComparisonRelationship(_StringEnum):
    EXACT_MATCH="EXACT_MATCH";EQUIVALENT_UNIT="EQUIVALENT_UNIT";WITHIN_RANGE="WITHIN_RANGE"
    CONTAINS_RANGE="CONTAINS_RANGE";RANGE_EQUAL="RANGE_EQUAL";RANGE_OVERLAP="RANGE_OVERLAP"
    MEMBER_OF_NATIVE_SET="MEMBER_OF_NATIVE_SET";NATIVE_MEMBER_OF_VISUAL_SET="NATIVE_MEMBER_OF_VISUAL_SET"
    SET_EQUAL="SET_EQUAL";SET_OVERLAP="SET_OVERLAP";SET_DISJOINT="SET_DISJOINT"
    SYMBOLIC_EQUIVALENT="SYMBOLIC_EQUIVALENT";INSUFFICIENT_INFORMATION="INSUFFICIENT_INFORMATION"
    OVERLAPPING_RANGE="OVERLAPPING_RANGE";DISJOINT="DISJOINT";NOT_COMPARABLE="NOT_COMPARABLE"


class SourceRelationship(_StringEnum):
    SAME_SOURCE="SAME_SOURCE";INDEPENDENT_SOURCE="INDEPENDENT_SOURCE";UNKNOWN="UNKNOWN"


@dataclass
class CandidateReference:
    candidate_id:str;candidate_type:str;raw_value:Any;normalized_value:Any;raw_unit:Optional[str]
    canonical_unit:Optional[str];polarity:str;scope:str;role:str;confidence:Optional[float]
    authority:str;source_artifact:str;page:Optional[int];bbox:Optional[List[float]];source_text:Optional[str]


@dataclass
class PromotionEligibilityDecision:
    promotion_eligible:bool;promotion_target:Optional[str];promotion_reason:str
    promotion_blockers:List[str];simulation_only:bool=True;canonical_promotion_enabled:bool=False


@dataclass
class EvidenceReconciliationRecord:
    reconciliation_id:str;candidate_type:str;visual_candidate:CandidateReference
    native_candidates:List[CandidateReference];comparison_relationship:ComparisonRelationship
    source_relationship:SourceRelationship;reconciliation_status:ReconciliationStatus
    reconciliation_confidence:float;conflict_severity:Optional[str]
    promotion:PromotionEligibilityDecision;blocking_reasons:List[str];lineage:Dict[str,Any]


@dataclass
class VisualEvidenceReconciliationResult:
    schema_version:str;run_id:str;source_lineage:Dict[str,Any];summary:Dict[str,Any]
    reconciliations:List[EvidenceReconciliationRecord];promotion_candidates:List[Dict[str,Any]]
    diagnostics:List[Dict[str,Any]]=field(default_factory=list);authority:str="RECONCILED_EVIDENCE"
    decision_authority:str="NONE";canonical_visual_promotion_enabled:bool=False
    def to_dict(self):return asdict(self)
    def to_json(self,indent=None):return json.dumps(self.to_dict(),ensure_ascii=False,sort_keys=True,indent=indent)
