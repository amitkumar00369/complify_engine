import copy
import json
import math

from iec_par.generic_llm_context_builder import GenericLLMContextBuilder


def source(status="COMPLETE"):
    return {"run_id":"R","contexts":[{"context_id":"CTX","final_issue_id":"F","clause_id":"A.1","final_issue":{"issue_type":"UNKNOWN_APPLICABILITY","severity":"MEDIUM","product_fact_ids":["PF"]},"requirement_group":{"group_id":"RG","members":[{"effective_requirement_id":"ER"}]},"requirements":[{"effective_requirement_id":"ER","clause_id":"A.1","text":"shall","normative":True,"base_sources":[{"page_start":2}]}],"product_facts":[{"fact_id":"PF","canonical_feature":"feature","normalized_value":"yes"}],"product_identity":[],"report_evidence":[{"evidence_id":"EV","evidence_type":"TABLE_VALUE","raw_text":"x"*5000,"measurements":[{"measurement_id":"M","value":1,"unit":"V","raw_text":"noise"*1000}],"parent_evidence_id":"P","page_start":3}],"evidence_resolution":[],"applicability_results":[{"source_stage":"applicability","effective_requirement_id":"ER","decision":"UNKNOWN","reason":"missing fact"}],"na_results":[{"source_stage":"na_initial","effective_requirement_id":"ER","state":"UNRESOLVED"}],"scope_results":[],"technical_results":[],"final_requirement_decisions":[],"source_provenance":{"standard":[{"effective_kb_id":"KB","base_standard":{"standard_id":"S"}}],"report":[],"product":[],"deterministic_artifacts":[]},"resolution_integrity":{"status":status,"missing_references":[],"duplicate_ids":[],"ambiguous_references":[],"cross_scope_conflicts":[]}}]}


def route(kind="LLM_CANDIDATE"):
    return {"routes":[{"context_id":"CTX","route":kind,"primary_reason_code":"UNKNOWN_APPLICABILITY","allowed_llm_tasks":["CLIENT_EXPLANATION","APPLICABILITY_INTERPRETATION"],"llm_decision_authority":"INTERPRETATION_ONLY","deterministic_result_locked":False,"numeric_result_locked":False,"source_gap_locked":False,"human_review_required":False}]}


def gate(eligible=True): return {"contexts":[{"context_id":"CTX","eligible_for_step_32c":eligible,"blocking_reason_codes":[] if eligible else ["CONTAMINATION_DETECTED"],"contamination_findings":[] if eligible else [{"classification":"DERIVED_ARTIFACT_CONTAMINATION"}]}]}


def test_projection_whitelist_group_locks_and_primary_task():
    result=GenericLLMContextBuilder().build_bundle(source(),route(),gate()); context=result.contexts[0]
    assert context.primary_task=="APPLICABILITY_INTERPRETATION" and context.decision_authority=="INTERPRETATION_ONLY"
    assert context.allowed_ids=={"allowed_requirement_ids":["ER"],"allowed_evidence_ids":["EV"],"allowed_product_fact_ids":["PF"]}
    assert context.requirement_context["group"]["member_requirement_ids"]==["ER"]
    assert context.policy_locks["numeric_result_locked"] is False


def test_large_table_is_referenced_and_measurements_compacted():
    context=GenericLLMContextBuilder().build_bundle(source(),route(),gate()).contexts[0]; evidence=context.report_context["evidence"][0]
    assert "raw_text" not in evidence and evidence["raw_text_ref"]["evidence_id"]=="EV"
    assert evidence["measurements"]==[{"measurement_id":"M","value":1,"unit":"V"}]
    assert evidence["parent_evidence_id"]=="P" and evidence["page_start"]==3


def test_ineligible_routes_integrity_and_contamination_are_excluded():
    builder=GenericLLMContextBuilder()
    for routing,integrity,status in ((route("DETERMINISTIC_ONLY"),gate(),"COMPLETE"),(route("HUMAN_REVIEW"),gate(),"COMPLETE"),(route(),gate(),"PARTIAL"),(route(),gate(False),"COMPLETE")):
        result=builder.build_bundle(source(status),routing,integrity); assert not result.contexts and len(result.exclusions)==1


def test_no_cross_issue_or_unrelated_record_leakage():
    data=source(); other=copy.deepcopy(data["contexts"][0]); other["context_id"]="OTHER"; other["final_issue_id"]="OTHER-F"; other["report_evidence"][0]["evidence_id"]="OTHER-EV"; data["contexts"].append(other)
    result=GenericLLMContextBuilder().build_bundle(data,route(),gate()); assert len(result.contexts)==1 and result.contexts[0].allowed_ids["allowed_evidence_ids"]==["EV"]


def test_ids_signatures_serialization_and_size_are_deterministic():
    builder=GenericLLMContextBuilder(); one=builder.build_bundle(source(),route(),gate()); two=builder.build_bundle(source(),route(),gate())
    assert one.contexts[0].llm_context_id==two.contexts[0].llm_context_id and one.contexts[0].context_signature==two.contexts[0].context_signature
    assert builder.to_json(one)==builder.to_json(two); metrics=one.contexts[0].size_metrics
    assert metrics["approximate_token_count"]==math.ceil(metrics["serialized_char_count"]/4); json.loads(builder.to_json(one))


def test_accounting_and_duplicate_signature_analysis():
    data=source(); second=copy.deepcopy(data["contexts"][0]); second["context_id"]="CTX2"; second["final_issue_id"]="F2"; data["contexts"].append(second)
    routing=route(); routing["routes"].append({**routing["routes"][0],"context_id":"CTX2"}); integrity=gate(); integrity["contexts"].append({**integrity["contexts"][0],"context_id":"CTX2"})
    result=GenericLLMContextBuilder().build_bundle(data,routing,integrity)
    assert result.accounting["contexts_built"]==2 and result.accounting["deduplication_metrics"]["duplicate_signature_count"]==1
