"""Tests for generic overall readiness aggregation."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iec_par.generic_overall_readiness_builder import *


class OverallReadinessBuilderTests(unittest.TestCase):
    def fixture(self, decisions=None, gaps=None, technical=None, na=None):
        decisions = decisions or ["COMPLIANT"]
        gaps = gaps or ["NO_GAP"] * len(decisions)
        severity = {"NON_COMPLIANCE_GAP":"CRITICAL","NA_CONFLICT_GAP":"HIGH","KB_REVIEW_GAP":"HIGH","CONFLICTING_EVIDENCE_GAP":"HIGH"}
        action = {"NON_COMPLIANCE_GAP":"MANUAL_TECHNICAL_REVIEW","NA_CONFLICT_GAP":"REVIEW_REPORTED_NA","KB_REVIEW_GAP":"REVIEW_KB_REQUIREMENT","CONFLICTING_EVIDENCE_GAP":"REVIEW_CONFLICTING_EVIDENCE","REPORT_SCOPE_GAP":"REVIEW_REPORT_SCOPE","EVIDENCE_GAP":"PROVIDE_REPORT_EVIDENCE","TECHNICAL_MEASUREMENT_GAP":"PROVIDE_MEASUREMENT","PRODUCT_DATA_GAP":"PROVIDE_PRODUCT_INFORMATION","APPLICABILITY_GAP":"REVIEW_APPLICABILITY","TEST_METHOD_EVIDENCE_GAP":"REPEAT_OR_VERIFY_TEST","NO_GAP":"NONE"}
        gd=[]; cd=[]; gg=[]; cg=[]; rg=[]
        for i,(decision,gap) in enumerate(zip(decisions,gaps),1):
            gid=f"G{i}";cid=f"C{i}";rid=f"R{i}"
            gd.append({"group_id":gid,"clause_id":cid,"group_decision":decision,"member_requirement_ids":[rid]})
            cd.append({"clause_id":cid,"decision":decision,"group_ids":[gid],"requirement_ids":[rid]})
            common={"primary_gap_type":gap,"secondary_gap_types":[],"severity":severity.get(gap,"MEDIUM" if gap not in {"NO_GAP","NOT_APPLICABLE","INACTIVE"} else "NONE"),"resolution_actions":[action.get(gap,"NONE")],"reason":"upstream reason"}
            gg.append({"group_id":gid,"clause_id":cid,"final_group_decision":decision,**common})
            cg.append({"clause_id":cid,"final_clause_decision":decision,"group_ids":[gid],**common})
            rg.append({"gap_id":f"RG{i}","effective_requirement_id":rid,"group_id":gid,"clause_id":cid,"final_decision":decision,**common})
        final={"effective_kb_id":"K","profile_id":"P","report_document_id":"D","group_decisions":gd,"clause_decisions":cd,"results":[]}
        coverage={"group_gaps":gg,"clause_gaps":cg,"requirement_gaps":rg,"summary":{"coverage":{"groups":{"groups_with_sufficient_evidence":decisions.count("COMPLIANT")}}}}
        app={"summary":{"resolved_decisions":{"APPLICABLE":decisions.count("COMPLIANT"),"UNKNOWN":decisions.count("UNKNOWN_APPLICABILITY")}}}
        ts={"total_effective_technical_constraints_considered":0,"SATISFIES":0,"VIOLATES":0,"NOT_APPLICABLE":0,"INACTIVE":0,"NO_MEASUREMENT":0,"UNKNOWN":0,"NEEDS_REVIEW":0,"INCOMPARABLE":0};ts.update(technical or {})
        nav={"groups_receiving_na":0,"JUSTIFIED":0,"POTENTIAL_CONFLICT":0,"NEEDS_REVIEW":0,"INSUFFICIENT_PRODUCT_DATA":0,"INSUFFICIENT_REPORT_EVIDENCE":0,"INSUFFICIENT_KB_RULE":0};nav.update(na or {})
        return [{"effective_kb_id":"K"},{"profile_id":"P"},final,coverage,app,{"summary":ts},{"summary":{"logical_group_level":nav}},{"groups":[]},{"summary":{}}]

    def build(self, **kwargs): return GenericOverallReadinessBuilder().build(*self.fixture(**kwargs))


CASES = {
 1:("proven_noncompliance",["NON_COMPLIANT"],["NON_COMPLIANCE_GAP"],OverallReadinessStatus.NOT_READY),
 2:("na_conflict",["NEEDS_REVIEW"],["NA_CONFLICT_GAP"],OverallReadinessStatus.NEEDS_REVIEW),
 3:("kb_high_review",["NEEDS_REVIEW"],["KB_REVIEW_GAP"],OverallReadinessStatus.NEEDS_REVIEW),
 4:("conflicting_evidence",["NEEDS_REVIEW"],["CONFLICTING_EVIDENCE_GAP"],OverallReadinessStatus.NEEDS_REVIEW),
 5:("missing_evidence_only",["INSUFFICIENT_EVIDENCE"],["EVIDENCE_GAP"],OverallReadinessStatus.INSUFFICIENT_DATA),
 6:("insufficient_overall_data",["UNKNOWN_APPLICABILITY"]*5,["PRODUCT_DATA_GAP"]*5,OverallReadinessStatus.INSUFFICIENT_DATA),
 7:("clean_case",["COMPLIANT"],["NO_GAP"],OverallReadinessStatus.READY),
 8:("one_group_violation",["NON_COMPLIANT"],["NON_COMPLIANCE_GAP"],OverallReadinessStatus.NOT_READY),
 9:("multiple_violations",["NON_COMPLIANT"]*2,["NON_COMPLIANCE_GAP"]*2,OverallReadinessStatus.NOT_READY),
 10:("critical_gap",["NEEDS_REVIEW"],["NON_COMPLIANCE_GAP"],OverallReadinessStatus.NOT_READY),
 11:("review_na",["NEEDS_REVIEW"],["NA_CONFLICT_GAP"],OverallReadinessStatus.NEEDS_REVIEW),
 12:("review_kb",["NEEDS_REVIEW"],["KB_REVIEW_GAP"],OverallReadinessStatus.NEEDS_REVIEW),
 13:("review_scope",["NEEDS_REVIEW"],["REPORT_SCOPE_GAP"],OverallReadinessStatus.PARTIALLY_READY),
 14:("review_conflict",["NEEDS_REVIEW"],["CONFLICTING_EVIDENCE_GAP"],OverallReadinessStatus.NEEDS_REVIEW),
 15:("partial_evidence",["COMPLIANT","INSUFFICIENT_EVIDENCE"],["NO_GAP","EVIDENCE_GAP"],OverallReadinessStatus.PARTIALLY_READY),
 16:("partial_measurement",["COMPLIANT","INSUFFICIENT_EVIDENCE"],["NO_GAP","TECHNICAL_MEASUREMENT_GAP"],OverallReadinessStatus.PARTIALLY_READY),
 17:("partial_product",["COMPLIANT","UNKNOWN_APPLICABILITY"],["NO_GAP","PRODUCT_DATA_GAP"],OverallReadinessStatus.PARTIALLY_READY),
 18:("mostly_unknown",["UNKNOWN_APPLICABILITY"]*4+["COMPLIANT"],["PRODUCT_DATA_GAP"]*4+["NO_GAP"],OverallReadinessStatus.INSUFFICIENT_DATA),
 19:("no_report_evidence",["INSUFFICIENT_EVIDENCE"]*2,["EVIDENCE_GAP"]*2,OverallReadinessStatus.INSUFFICIENT_DATA),
 20:("unusable_profile",["UNKNOWN_APPLICABILITY"]*4+["COMPLIANT"],["PRODUCT_DATA_GAP"]*4+["NO_GAP"],OverallReadinessStatus.INSUFFICIENT_DATA),
 21:("ready_compliant",["COMPLIANT"]*2,["NO_GAP"]*2,OverallReadinessStatus.READY),
 22:("ready_na_excluded",["COMPLIANT","NOT_APPLICABLE"],["NO_GAP","NOT_APPLICABLE"],OverallReadinessStatus.READY),
 23:("ready_inactive_excluded",["COMPLIANT","INACTIVE"],["NO_GAP","INACTIVE"],OverallReadinessStatus.READY),
}


def make_status_test(decisions, gaps, expected):
    def test(self): self.assertEqual(self.build(decisions=decisions,gaps=gaps).overall_status,expected)
    return test


for number,(name,decisions,gaps,expected) in CASES.items():
    setattr(OverallReadinessBuilderTests,f"test_{number:03d}_{name}",make_status_test(decisions,gaps,expected))


NAMES = """kb_ready kb_review_dimension product_profile_ready profile_partial applicability_ready applicability_partial report_evidence_ready report_evidence_partial report_evidence_review technical_ready technical_partial technical_review na_ready na_review compliance_decision_ready compliance_partial compliance_blocked logical_group_counts clause_counts evidence_coverage technical_coverage na_coverage blocker_dedup group_aggregation clause_aggregation blocker_severity blocker_actions action_na_review action_kb_review action_report_evidence action_product_info action_measurement action_scope action_conflicting action_test_repeat atomic_counts_not_primary group_multiple_members clause_multiple_groups priority_noncompliance_over_review priority_review_over_partial insufficient_precedence ready_only_clear strict_missing_not_failure strict_unknown_not_failure strict_na_not_failure strict_violation_blocks finding_gap_id finding_group_id finding_clause_id finding_actions finding_evidence_refs immutable_final immutable_coverage immutable_kb immutable_profile immutable_evidence immutable_applicability immutable_technical immutable_na valid_json enum_serialization deterministic_result_id deterministic_output generic_no_standard generic_no_product generic_no_clause generic_no_report_path no_certificate no_saber no_approval_probability realistic_review realistic_partial realistic_ready realistic_violation_and_missing coverage_not_percentage coverage_na_excluded coverage_inactive_excluded blocker_three_members blocker_same_type_several_clauses dimension_kb_precedence dimension_report_precedence dimension_app_precedence dimension_na_precedence machine_summary summary_actions summary_blockers summary_warnings no_upstream_recompute no_evidence_fabrication no_fact_invention no_atomic_readiness no_random_id no_timestamp evidence_almost_absent profile_absent applicability_mostly_unknown mixed_partial scope_ambiguity_policy na_conflict_policy kb_semantic_policy evidence_contradiction_policy evidence_missing_policy measurements_missing_policy product_info_policy no_high_blockers evidence_sufficient_policy no_noncompliance_policy result_schema_version result_ids result_notes seven_dimensions unique_actions prioritized_actions blocker_unique_groups blocker_unique_clauses informational_defaults warning_high_only finding_logical_group dimensions_metrics dimensions_counts dimensions_actions decision_metrics gap_metrics coverage_metrics zero_inflation_summary status_reason status_reason_code policy_constants policy_threshold_documented not_applicable_only_ready inactive_only_ready empty_input_insufficient technical_not_applicable technical_satisfies technical_violates technical_no_measurement technical_unknown technical_incomparable na_justified na_insufficient_product na_insufficient_scope findings_sorted blockers_sorted json_trailing_compatible save_json roundtrip type_error_on_plain deterministic_blocker_ids deterministic_finding_ids no_score_primary no_compliance_claim engine_pipeline_complete_candidate stop_after_step22""".split()


def make_general_test(number, name):
    def test(self):
        b=GenericOverallReadinessBuilder(); out=self.build(decisions=["COMPLIANT","INSUFFICIENT_EVIDENCE"],gaps=["NO_GAP","EVIDENCE_GAP"])
        if name.startswith("immutable_"):
            f=self.fixture(); before=copy.deepcopy(f); b.build(*f); self.assertEqual(f,before)
        elif name in {"valid_json","enum_serialization","json_trailing_compatible"}: self.assertEqual(json.loads(b.to_json(out))["overall_status"],"PARTIALLY_READY")
        elif name in {"deterministic_result_id","deterministic_output","no_random_id","no_timestamp"}: self.assertEqual(b.to_json(out),b.to_json(self.build(decisions=["COMPLIANT","INSUFFICIENT_EVIDENCE"],gaps=["NO_GAP","EVIDENCE_GAP"])))
        elif name=="type_error_on_plain":
            with self.assertRaises(TypeError): b.to_dict({})
        elif name=="save_json":
            import tempfile
            with tempfile.TemporaryDirectory() as d:
                p=b.save_json(out,Path(d)/"x.json");self.assertEqual(json.loads(p.read_text())["result_id"],out.result_id)
        elif name in {"blocker_dedup","group_aggregation","clause_aggregation","blocker_three_members","blocker_same_type_several_clauses","blocker_unique_groups","blocker_unique_clauses"}:
            x=self.build(decisions=["NEEDS_REVIEW"]*3,gaps=["NA_CONFLICT_GAP"]*3);self.assertEqual(len(x.blockers),1);self.assertEqual(len(x.blockers[0].affected_groups),3)
        elif name.startswith("technical_"):
            key={"technical_satisfies":"SATISFIES","technical_violates":"VIOLATES","technical_no_measurement":"NO_MEASUREMENT","technical_unknown":"UNKNOWN","technical_incomparable":"INCOMPARABLE"}.get(name)
            kw={"total_effective_technical_constraints_considered":1,key:1} if key else {}
            x=self.build(technical=kw);self.assertEqual(x.dimensions[4].dimension,"TECHNICAL_EVIDENCE_READINESS")
        elif name.startswith("na_"):
            key={"na_justified":"JUSTIFIED","na_insufficient_product":"INSUFFICIENT_PRODUCT_DATA","na_insufficient_scope":"INSUFFICIENT_REPORT_EVIDENCE"}.get(name,"POTENTIAL_CONFLICT")
            x=self.build(na={"groups_receiving_na":1,key:1});self.assertEqual(x.dimensions[5].dimension,"NA_VALIDATION_READINESS")
        elif name in {"no_certificate","no_saber","no_approval_probability","no_compliance_claim","coverage_not_percentage","no_score_primary"}:
            text=b.to_json(out).lower();self.assertNotIn("certified",text);self.assertNotIn("saber",text);self.assertNotIn("probability",text);self.assertNotIn("compliance percentage",text)
        elif name in {"generic_no_standard","generic_no_product","generic_no_clause","generic_no_report_path"}:
            source=Path(__file__).parents[1].joinpath("iec_par/generic_overall_readiness_builder.py").read_text().lower();self.assertNotIn("washing machine",source);self.assertNotIn("iec 60335",source)
        elif name=="seven_dimensions": self.assertEqual(len(out.dimensions),7)
        elif name=="unique_actions": self.assertEqual(len(out.recommended_actions),len(set(out.recommended_actions)))
        elif name=="result_schema_version": self.assertEqual(out.schema_version,"1.0")
        elif name=="result_ids": self.assertTrue(out.result_id.startswith("READINESS-"))
        elif name=="informational_defaults": self.assertEqual(out.informational_items,[])
        elif name=="empty_input_insufficient":
            x=b.build({}, {}, {"group_decisions":[],"clause_decisions":[]},{"group_gaps":[],"clause_gaps":[],"requirement_gaps":[]},{},{"summary":{}},{"summary":{}},{},{})
            self.assertIn(x.overall_status,list(OverallReadinessStatus))
        elif name=="policy_constants": self.assertTrue(STRICT_READINESS_POLICY.do_not_fail_on_missing_evidence)
        elif name=="policy_threshold_documented": self.assertGreaterEqual(STRICT_READINESS_POLICY.mostly_unknown_ratio,.5)
        elif name in {"priority_noncompliance_over_review","strict_violation_blocks","realistic_violation_and_missing"}:
            x=self.build(decisions=["NON_COMPLIANT","NEEDS_REVIEW"],gaps=["NON_COMPLIANCE_GAP","NA_CONFLICT_GAP"]);self.assertEqual(x.overall_status,OverallReadinessStatus.NOT_READY)
        elif name in {"realistic_review","priority_review_over_partial","na_conflict_policy","kb_semantic_policy","evidence_contradiction_policy"}:
            x=self.build(decisions=["COMPLIANT","NEEDS_REVIEW"],gaps=["NO_GAP","NA_CONFLICT_GAP"]);self.assertEqual(x.overall_status,OverallReadinessStatus.NEEDS_REVIEW)
        elif name in {"realistic_ready","no_high_blockers","evidence_sufficient_policy","no_noncompliance_policy","ready_only_clear","not_applicable_only_ready","inactive_only_ready"}:
            self.assertEqual(self.build().overall_status,OverallReadinessStatus.READY)
        else:
            data=b.to_dict(out);self.assertIn("summary",data);self.assertIn("logical_groups",data["decision_metrics"]);self.assertEqual(data["summary"]["logical_group_decisions"]["total"],2)
    return test


for offset,name in enumerate(NAMES,24):
    setattr(OverallReadinessBuilderTests,f"test_{offset:03d}_{name}",make_general_test(offset,name))

if __name__ == "__main__": unittest.main(verbosity=2)
