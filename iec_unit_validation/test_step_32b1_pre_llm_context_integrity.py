import copy
import json

from iec_par.generic_compliance_reference_resolver import GenericComplianceReferenceResolver
from iec_par.generic_pre_llm_context_integrity_gate import GenericPreLLMContextIntegrityGate


def requirement(identifier="E-R-1", text="shall comply", page=1):
    return {"effective_requirement_id": identifier, "clause_id": "A.1", "text": text,
            "effective_status": "ACTIVE", "delta_sources": [{"page_start": page}]}


def test_identical_structural_alias_is_canonical_and_paths_preserved():
    resolver = GenericComplianceReferenceResolver(); resolver.duplicate_audit = []
    one, two = requirement(page=1), requirement(page=2)
    index, duplicates = resolver._make_index({"requirements": [one], "clauses": [{"requirements": [two]}]}, ("effective_requirement_id",), canonicalize=True)
    assert duplicates == [] and len(index["E-R-1"]) == 1
    metadata = index["E-R-1"][0]["canonical_resolution"]
    assert metadata["classification"] == "CANONICAL_ALIAS" and len(metadata["source_locations"]) == 2
    assert len(metadata["representations"]) == 2


def test_materially_different_duplicate_remains_blocked_without_first_win():
    resolver = GenericComplianceReferenceResolver(); resolver.duplicate_audit = []
    index, duplicates = resolver._make_index([requirement(text="shall"), requirement(text="shall not")], ("effective_requirement_id",), canonicalize=True)
    assert len(index["E-R-1"]) == 2
    assert duplicates[0]["classification"] == "TRUE_DUPLICATE_CONFLICT"


def bundles(evidence):
    context = {"context_id": "CTX", "final_issue_id": "F", "report_evidence": [copy.deepcopy(evidence)],
               "resolution_integrity": {"status": "COMPLETE", "duplicate_ids": [], "ambiguous_references": [], "missing_references": [], "cross_scope_conflicts": []}}
    return {"run_id": "R", "contexts": [context]}, {"routes": [{"context_id": "CTX", "route": "LLM_CANDIDATE", "source_gap_locked": False}]}


def test_clean_provenance_is_eligible_and_source_unchanged():
    source = {"clauses": [{"evidence_items": [{"evidence_id": "EV", "raw_text": "source"}]}]}; before = copy.deepcopy(source)
    contexts, routes = bundles(source["clauses"][0]["evidence_items"][0])
    result = GenericPreLLMContextIntegrityGate().audit_bundle(contexts, routes, source)
    assert result.contexts[0].eligible_for_step_32c and result.accounting["blocked_by_contamination"] == 0
    assert source == before


def test_derived_foreign_field_is_traced_and_blocked():
    source = {"evidence_items": [{"evidence_id": "EV", "raw_text": "source"}]}
    contaminated = {"evidence_id": "EV", "raw_text": "source", "unowned_field": "foreign"}
    contexts, routes = bundles(contaminated)
    result = GenericPreLLMContextIntegrityGate().audit_bundle(contexts, routes, source)
    assert not result.contexts[0].eligible_for_step_32c
    assert result.contexts[0].contamination_findings[0]["classification"] == "DERIVED_ARTIFACT_CONTAMINATION"


def test_integrity_and_source_gap_override_candidate():
    evidence = {"evidence_id": "EV"}; source = {"evidence_items": [evidence]}; contexts, routes = bundles(evidence)
    contexts["contexts"][0]["resolution_integrity"]["status"] = "INVALID_REFERENCE"
    contexts["contexts"][0]["resolution_integrity"]["duplicate_ids"] = [{"id": "X"}]
    routes["routes"][0]["source_gap_locked"] = True
    decision = GenericPreLLMContextIntegrityGate().audit_bundle(contexts, routes, source).contexts[0]
    assert not decision.eligible_for_step_32c
    assert {"CONTEXT_NOT_COMPLETE", "UNRESOLVED_DUPLICATE_REFERENCE", "SOURCE_GAP_INTEGRITY_VIOLATION"} <= set(decision.blocking_reason_codes)


def test_serialization_is_deterministic():
    evidence = {"evidence_id": "EV"}; source = {"evidence_items": [evidence]}; contexts, routes = bundles(evidence)
    gate = GenericPreLLMContextIntegrityGate(); one = gate.audit_bundle(contexts, routes, source); two = gate.audit_bundle(contexts, routes, source)
    assert gate.to_json(one) == gate.to_json(two); json.loads(gate.to_json(one))
