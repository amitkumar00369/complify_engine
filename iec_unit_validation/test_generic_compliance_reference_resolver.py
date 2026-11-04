import copy
import json
from pathlib import Path

from iec_par.generic_compliance_reference_resolver import GenericComplianceReferenceResolver


def put(root, relative, value):
    path = root / relative; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture(root: Path):
    put(root, "manifest/pipeline_manifest.json", {"run_id": "RUN-1"})
    put(root, "standards/effective_kb.json", {"effective_kb_id": "KB", "clauses": [{"clause_id": "1", "requirements": [{"effective_requirement_id": "E-R-1", "clause_id": "1", "text": "shall", "effective_status": "ACTIVE"}]}]})
    put(root, "report/requirement_grouping_result.json", {"groups": [{"group_id": "RG-1", "clause_id": "1", "members": [{"effective_requirement_id": "E-R-1"}]}]})
    put(root, "report/report_evidence.json", {"document_id": "DOC", "clauses": [{"clause_id": "1", "evidence_items": [{"evidence_id": "REPORT-EV-1", "raw_text": "row", "children": [{"evidence_id": "REPORT-EV-1-SUBROW-1", "parent_evidence_id": "REPORT-EV-1"}]}]}]})
    put(root, "report/product_profile.json", {"profile_id": "P", "facts": [{"fact_id": "FACT-1", "canonical_feature": "feature"}], "identity": {"product_identities": [{"identity_id": "IDENTITY-1", "value": "M"}]}})
    for rel, value in {
        "report/applicability_result.json": {"results": [{"effective_requirement_id": "E-R-1", "decision": "APPLICABLE"}]},
        "report/group_aware_applicability_result.json": {"results": [{"effective_requirement_id": "E-R-1", "decision": "APPLICABLE"}]},
        "report/na_validation_result.json": {"results": [{"effective_requirement_id": "E-R-1", "state": "INITIAL"}]},
        "report/group_aware_na_validation_result.json": {"member_results": [{"effective_requirement_id": "E-R-1", "state": "GROUP"}]},
        "report/scope_aware_na_validation_result.json": {"member_results": [{"effective_requirement_id": "E-R-1", "state": "SCOPE"}]},
        "report/technical_constraint_result.json": {"results": [{"effective_requirement_id": "E-R-1", "state": "PASS"}]},
        "report/evidence_match_result.json": {"matches": [{"effective_requirement_id": "E-R-1", "evidence_refs": ["REPORT-EV-1-SUBROW-1"]}]},
        "decisions/final_requirement_decision.json": {"results": [{"effective_requirement_id": "E-R-1", "compliance_conclusion": "COMPLIANT"}]},
    }.items(): put(root, rel, value)
    issue = {"issue_id": "FINAL-ISSUE-1", "clause_id": "1", "requirement_group_id": "RG-1", "requirement_ids": ["E-R-1"], "evidence_refs": ["REPORT-EV-1"], "product_fact_ids": ["FACT-1"], "product_identity_ids": ["IDENTITY-1"]}
    put(root, "decisions/final_compliance_issues.json", {"issues": [issue]})
    put(root, "decisions/aggregated_compliance_issues.json", {"actionable_groups": [{"group_id": "AGG-1", "issue_ids": ["FINAL-ISSUE-1"]}]})
    put(root, "decisions/prioritized_next_actions.json", {"actions": [{"action_id": "ACT-1", "affected_aggregate_group_ids": ["AGG-1"]}]})
    return issue


def test_resolves_full_context_and_nested_evidence(tmp_path):
    fixture(tmp_path); result = GenericComplianceReferenceResolver().resolve_run(tmp_path)
    context = result.contexts[0]
    assert context.resolution_integrity.status == "COMPLETE"
    assert [x["effective_requirement_id"] for x in context.requirements] == ["E-R-1"]
    assert {x["evidence_id"] for x in context.report_evidence} == {"REPORT-EV-1", "REPORT-EV-1-SUBROW-1"}
    assert len(context.applicability_results) == 2 and len(context.na_results) == 3
    assert context.aggregate_context[0]["group_id"] == "AGG-1" and context.action_context[0]["action_id"] == "ACT-1"


def test_missing_optional_and_missing_reference_are_recorded(tmp_path):
    issue = fixture(tmp_path); issue["product_fact_ids"] = ["UNKNOWN"]
    put(tmp_path, "decisions/final_compliance_issues.json", {"issues": [issue]})
    (tmp_path / "report/technical_constraint_result.json").unlink()
    context = GenericComplianceReferenceResolver().resolve_run(tmp_path).contexts[0]
    assert context.resolution_integrity.status == "PARTIAL"
    assert context.resolution_integrity.artifact_availability["report/technical_constraint_result.json"] == "MISSING"


def test_duplicate_id_is_ambiguous_and_deterministic_without_mutation(tmp_path):
    fixture(tmp_path); path = tmp_path / "report/report_evidence.json"; before = path.read_bytes()
    data = json.loads(before); data["clauses"][0]["evidence_items"].append({"evidence_id": "REPORT-EV-1", "raw_text": "duplicate"}); path.write_text(json.dumps(data))
    resolver = GenericComplianceReferenceResolver(); one = resolver.resolve_run(tmp_path); two = resolver.resolve_run(tmp_path)
    assert one.contexts[0].resolution_integrity.status == "INVALID_REFERENCE"
    assert one.contexts[0].context_id == two.contexts[0].context_id
    assert path.read_bytes() == json.dumps(data).encode()
    assert (tmp_path / "llm/resolved_compliance_context.json").is_file()
