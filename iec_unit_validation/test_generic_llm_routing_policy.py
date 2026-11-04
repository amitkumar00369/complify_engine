import json

from iec_par.generic_llm_routing_models import LLMDecisionAuthority, LLMRoute
from iec_par.generic_llm_routing_policy import GenericLLMRoutingPolicy


def context(issue_type="UNKNOWN", integrity="COMPLETE", **extra):
    value = {"context_id": "CTX-1", "final_issue_id": "FINAL-ISSUE-1", "final_issue": {"issue_type": issue_type},
             "technical_results": [], "final_requirement_decisions": [],
             "resolution_integrity": {"status": integrity, "missing_references": [], "ambiguous_references": [], "duplicate_ids": [], "cross_scope_conflicts": []}}
    value.update(extra); return value


def route(value): return GenericLLMRoutingPolicy().route_context(value)


def test_integrity_precedence_and_default():
    assert route(context("UNKNOWN_APPLICABILITY", "INVALID_REFERENCE")).route == LLMRoute.HUMAN_REVIEW
    assert route(context("UNKNOWN_APPLICABILITY", "PARTIAL")).primary_reason_code == "PARTIAL_CONTEXT"
    duplicate = context("UNKNOWN_APPLICABILITY"); duplicate["resolution_integrity"]["duplicate_ids"] = [{"id": "X"}]
    assert route(duplicate).primary_reason_code == "DUPLICATE_REFERENCE"
    assert route(context()).primary_reason_code == "UNRECOGNIZED_ROUTING_SEMANTICS"


def test_locked_deterministic_routes():
    for state in ("SATISFIES", "VIOLATES"):
        decision = route(context(technical_results=[{"state": state}]))
        assert decision.route == LLMRoute.DETERMINISTIC_ONLY and decision.numeric_result_locked
    decision = route(context(final_requirement_decisions=[{"compliance_conclusion": "COMPLIANT"}]))
    assert decision.deterministic_result_locked and decision.llm_decision_authority == LLMDecisionAuthority.EXPLANATION_ONLY
    source = route(context("STANDARD_SOURCE_GAP")); assert source.source_gap_locked and source.deterministic_result_locked


def test_missing_information_is_explanation_only():
    for issue in ("MISSING_EVIDENCE", "MISSING_REPORT_EVIDENCE", "MISSING_MEASUREMENT", "MISSING_PRODUCT_INFORMATION"):
        decision = route(context(issue)); assert decision.route == LLMRoute.DETERMINISTIC_ONLY
        assert decision.llm_decision_authority == LLMDecisionAuthority.EXPLANATION_ONLY
        assert all("INTERPRETATION" not in task.value for task in decision.allowed_llm_tasks)


def test_semantic_ambiguities_are_advisory_candidates():
    expected = {
        "UNKNOWN_APPLICABILITY": "APPLICABILITY_INTERPRETATION", "NA_APPLICABILITY_CONFLICT": "NA_JUSTIFICATION_INTERPRETATION",
        "KB_SEMANTIC_UNRESOLVED": "KB_SEMANTIC_INTERPRETATION", "AMBIGUOUS_REPORT_SCOPE": "REPORT_SCOPE_INTERPRETATION",
        "CONFLICTING_REPORT_VERDICT": "GROUPED_EVIDENCE_INTERPRETATION", "EVIDENCE_SEMANTIC_AMBIGUITY": "EVIDENCE_SEMANTIC_INTERPRETATION",
        "GROUPED_EVIDENCE_AMBIGUITY": "GROUPED_EVIDENCE_INTERPRETATION",
    }
    for issue, task in expected.items():
        decision = route(context(issue)); assert decision.route == LLMRoute.LLM_CANDIDATE
        assert decision.llm_decision_authority == LLMDecisionAuthority.INTERPRETATION_ONLY
        assert task in {x.value for x in decision.allowed_llm_tasks}


def test_bundle_accounting_and_serialization_are_deterministic():
    policy = GenericLLMRoutingPolicy(); bundle = {"run_id": "R", "contexts": [context("MISSING_EVIDENCE"), context("UNKNOWN_APPLICABILITY"), context("X", "PARTIAL")]}
    one = policy.route_bundle(bundle); two = policy.route_bundle(bundle)
    assert one.accounting["total_contexts"] == 3
    assert one.accounting["deterministic_only_count"] == one.accounting["llm_candidate_count"] == one.accounting["human_review_count"] == 1
    assert policy.to_json(one) == policy.to_json(two)
    assert all(x.llm_decision_authority.value != "UNRESTRICTED" for x in one.routes)
    json.loads(policy.to_json(one))
