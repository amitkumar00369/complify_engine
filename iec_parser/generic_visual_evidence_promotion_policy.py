"""Conservative simulation-only promotion eligibility policy."""

from __future__ import annotations

from .generic_visual_evidence_reconciliation_models import PromotionEligibilityDecision,ReconciliationStatus


class GenericVisualEvidencePromotionPolicy:
    POLICY_VERSION="STEP46M_PROMOTION_POLICY_V1"
    SUPPORTED={"rated_voltage","rated_frequency","rated_power_input","rated_current","ip_rating","protection_class","model_identifier"}
    ROLE_REQUIRED={"rated_voltage","rated_frequency","rated_power_input","rated_current"}
    def __init__(self,*,minimum_confidence=.75,canonical_visual_promotion_enabled=False):
        self.minimum_confidence=minimum_confidence
        self.canonical_visual_promotion_enabled=canonical_visual_promotion_enabled
    def evaluate(self,visual,status,lineage_valid=True,conflict=False):
        blockers=[]
        if visual.candidate_type not in self.SUPPORTED:blockers.append("UNSUPPORTED_CANDIDATE_TYPE")
        if visual.confidence is None or visual.confidence<self.minimum_confidence:blockers.append("LOW_EXTRACTION_CONFIDENCE")
        if visual.normalized_value in (None,""):blockers.append("UNPARSEABLE_VALUE")
        if visual.scope in ("UNKNOWN",None):blockers.append("INSUFFICIENT_SCOPE")
        if visual.candidate_type in self.ROLE_REQUIRED and visual.role in ("UNKNOWN",None):blockers.append("UNKNOWN_PARAMETER_ROLE")
        if visual.polarity in ("UNKNOWN",None):blockers.append("UNKNOWN_POLARITY")
        if not visual.candidate_id or visual.page is None or visual.bbox is None:blockers.append("INCOMPLETE_PROVENANCE")
        if not lineage_valid:blockers.append("INVALID_LINEAGE")
        if conflict or status is ReconciliationStatus.CONFLICT:blockers.append("UNRESOLVED_CONFLICT")
        eligible=not blockers
        return PromotionEligibilityDecision(eligible,"product_fact."+visual.candidate_type if eligible else None,
            "ALL_PROMOTION_GATES_PASSED" if eligible else "PROMOTION_BLOCKED",sorted(set(blockers)),True,False)
