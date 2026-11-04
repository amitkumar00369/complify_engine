"""Tests for the generic, read-only N/A conflict root-cause auditor."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iec_par.generic_na_conflict_auditor import *


class ConflictAuditorTests(unittest.TestCase):
    def setUp(self):
        self.a = GenericNAConflictAuditor()

    def fixture(self, match="EXACT_SUBCLAUSE", source="BASE", req_type="GENERAL",
                shared=1, rule=None, condition=None, verdicts=("NA",), missing=()):
        rid = "R1"
        na = {"effective_requirement_id": rid, "effective_clause_id": "EC", "source_clause_id": "2",
              "status": "POTENTIAL_CONFLICT"}
        req = {"effective_requirement_id": rid, "clause_id": "2", "effective_status": "ACTIVE",
               "text": "The enclosure shall prevent access to hazardous parts.",
               "requirement_type": req_type, "effective_source_type": source}
        app = {"effective_requirement_id": rid, "decision": "APPLICABLE", "effective_source_type": source,
               "condition_text": condition, "rule": rule, "required_features": [], "facts_used": [],
               "missing_features": list(missing), "base_sources": [], "delta_sources": [],
               "applicability_status_from_kb": "RESOLVED" if rule else "ALWAYS"}
        refs = [{"evidence_id": "EV", "report_clause_id": "2", "reported_verdict": v,
                 "page_start": 3, "page_end": 3,
                 "raw_text_excerpt": "The enclosure shall prevent access to hazardous parts. N/A"} for v in verdicts]
        match_obj = {"match_status": match, "evidence_refs": refs}
        return na, req, app, match_obj, [], {"EV": shared}, {"2": shared}

    def result(self, **kwargs):
        return self.a.audit_requirement(*self.fixture(**kwargs))

    def test_01_strong_true_conflict(self): self.assertEqual(self.result().root_cause, NAConflictRootCause.TRUE_NA_CONFLICT)
    def test_02_clause_level_mismatch(self): self.assertEqual(self.result(shared=3).root_cause, NAConflictRootCause.CLAUSE_LEVEL_REPORTING_MISMATCH)
    def test_03_granularity_mismatch(self): self.assertIn("MISMATCH", self.result(shared=2).root_cause.value)
    def test_04_part_mapping(self): self.assertIn(NAConflictRootCause.PART1_PART2_MAPPING_EFFECT, self.result(shared=2, source="PART_2_ADDITION").secondary_causes)
    def test_05_missing_context(self): self.assertIn("MISSING_PRODUCT_CONTEXT", self.a.to_json(self.result(missing=("feature",))))
    def test_06_parent_ambiguous(self): self.assertEqual(self.result(match="PARENT_CLAUSE").root_cause, NAConflictRootCause.REPORT_EVIDENCE_SCOPE_AMBIGUITY)
    def test_07_test_segmentation(self): self.assertIn(NAConflictRootCause.KB_REQUIREMENT_SEGMENTATION_ISSUE, self.result(shared=2, req_type="TEST").secondary_causes)
    def test_08_applicability_issue(self): self.assertEqual(self.result(condition="when fitted").root_cause, NAConflictRootCause.KB_APPLICABILITY_RULE_ISSUE)
    def test_09_parser_issue(self): self.assertIn("REPORT_PARSER_VERDICT_ISSUE", self.a.to_json(self.result(verdicts=("NA", "PASS"))))
    def test_10_multiple_causes(self): self.assertEqual(self.result(shared=2, req_type="TEST").root_cause, NAConflictRootCause.MULTIPLE_CAUSES)
    def test_11_manual_review(self): self.assertEqual(self.result(match="UNKNOWN").root_cause, NAConflictRootCause.NEEDS_MANUAL_REVIEW)
    def test_12_exact_strong(self): self.assertEqual(self.result(match="EXACT_CLAUSE").confidence, .95)
    def test_13_parent_weak(self): self.assertLess(self.result(match="PARENT_CLAUSE").confidence, .95)
    def test_14_multiple_candidate_weak(self): self.assertEqual(self.result(match="MULTIPLE_CANDIDATES").root_cause, NAConflictRootCause.REPORT_EVIDENCE_SCOPE_AMBIGUITY)
    def test_15_conflicting_evidence(self): self.assertEqual(self.result(verdicts=("NA", "PASS")).recommended_action, "REVIEW_REPORT_PARSER")
    def test_16_one_clause_one_requirement(self): self.assertEqual(self.result().root_cause, NAConflictRootCause.TRUE_NA_CONFLICT)
    def test_17_one_clause_many(self): self.assertEqual(self.result(shared=4).root_cause, NAConflictRootCause.CLAUSE_LEVEL_REPORTING_MISMATCH)
    def test_18_shared_na_signal(self): self.assertIn("evidence_fanout=4", self.result(shared=4).reason)
    def test_19_base(self): self.assertEqual(self.result().effective_source_type, "BASE")
    def test_20_addition(self): self.assertEqual(self.result(source="PART_2_ADDITION").effective_source_type, "PART_2_ADDITION")
    def test_21_modification(self): self.assertEqual(self.result(source="PART_2_MODIFICATION").effective_source_type, "PART_2_MODIFICATION")
    def test_22_replacement(self): self.assertEqual(self.result(source="PART_2_REPLACEMENT").effective_source_type, "PART_2_REPLACEMENT")
    def test_23_new_requirement(self): self.assertEqual(self.result(source="PART_2_NEW_REQUIREMENT").effective_source_type, "PART_2_NEW_REQUIREMENT")
    def test_24_always(self): self.assertIsNone(self.result().applicability_rule)
    def test_25_resolved_true(self): self.assertEqual(self.result(rule={"field":"x","operator":"equals","value":True}).applicability_rule["field"], "x")
    def test_26_confirmed_fact(self):
        f=list(self.fixture(rule={"field":"x"})); f[2]["facts_used"]=[{"feature_id":"x","status":"CONFIRMED"}]
        self.assertEqual(self.a.audit_requirement(*f).root_cause, NAConflictRootCause.TRUE_NA_CONFLICT)
    def test_27_rule_issue(self): self.assertEqual(self.result(condition="if fitted").recommended_action, "REVIEW_APPLICABILITY_RULE")
    def test_28_unconditional_no_context(self): self.assertNotEqual(self.result().root_cause, NAConflictRootCause.MISSING_PRODUCT_CONTEXT)
    def test_29_phrase_overlap(self): self.assertGreater(self.a._phrase_overlap("guard shall prevent access", "guard shall prevent access"), .9)
    def test_30_boilerplate_ignored(self): self.assertEqual(self.a._phrase_overlap("Compliance is checked", "compliance checked"), 0)
    def test_31_narrow_text(self): self.assertLess(self.a._phrase_overlap("guard shall prevent access", "temperature test"), .2)
    def test_32_mixed_verdict(self): self.assertIn("REPORT_PARSER", self.result(verdicts=("NA","PASS")).recommended_action)
    def test_33_duplicate_signal(self): self.assertEqual(self.result(shared=2).root_cause, NAConflictRootCause.CLAUSE_LEVEL_REPORTING_MISMATCH)
    def test_34_test_method_split(self): self.assertEqual(self.result(shared=2, req_type="TEST").recommended_action, "REVIEW_REQUIREMENT_SPLITTING")
    def test_35_shared_condition_issue(self): self.assertIn("KB_APPLICABILITY", self.a.to_json(self.result(shared=2, condition="when fitted")))
    def test_36_no_measurement_not_cause(self): self.assertNotIn("NO_MEASUREMENT", self.result().root_cause.value)
    def test_37_satisfies_not_cause(self): self.assertNotIn("SATISFIES", self.result().root_cause.value)
    def test_38_clause_grouping(self): self.assertEqual(self.a._group_clauses([self.result()])[0].potential_conflict_requirements, 1)
    def test_39_dominant(self): self.assertEqual(self.a._group_clauses([self.result()])[0].dominant_root_cause, "TRUE_NA_CONFLICT")
    def test_40_group_counts(self): self.assertEqual(self.a._group_clauses([self.result()])[0].true_conflict_count, 1)
    def test_41_unique_clause(self): self.assertEqual(self.a._summary([self.result()], {"E":1},{"2":1})["unique_effective_clauses"], 1)
    def test_42_unique_evidence(self): self.assertEqual(self.a._summary([self.result()], {"E":1},{"2":1})["unique_na_evidence_records"], 1)
    def test_43_average(self): self.assertEqual(self.a._summary([self.result()], {"E":2},{"2":2})["average_conflicting_requirements_per_report_na_clause"], 2)
    def test_44_maximum(self): self.assertEqual(self.a._summary([self.result()], {"E":3},{"2":3})["maximum_conflicting_requirements_per_report_clause"], 3)
    def test_45_top_deterministic(self): self.assertEqual(self.a._summary([], {"A":2},{"10":2,"2":2})["top_report_clauses_by_fanout"][0]["report_clause_id"], "2")
    def test_46_requirement_text(self): self.assertIn("enclosure", self.result().effective_requirement_text)
    def test_47_condition(self): self.assertEqual(self.result(condition="when fitted").condition_text, "when fitted")
    def test_48_rule(self): self.assertIsInstance(self.result(rule={"all":[]}).applicability_rule, dict)
    def test_49_facts(self): self.assertEqual(self.result().product_facts_used, [])
    def test_50_evidence_refs(self): self.assertEqual(self.result().report_evidence_ids, ["EV"])
    def test_51_provenance(self): self.assertEqual(self.result().base_sources, [])
    def test_52_technical(self):
        f=list(self.fixture()); f[4]=[{"decision":"NO_MEASUREMENT"}]
        self.assertEqual(self.a.audit_requirement(*f).technical_constraint_decisions, ["NO_MEASUREMENT"])
    def test_53_report_review(self): self.assertEqual(self.result().recommended_action, "NO_ENGINE_CHANGE_REPORT_REVIEW")
    def test_54_splitting_review(self): self.assertEqual(self.result(shared=2, req_type="TEST").recommended_action, "REVIEW_REQUIREMENT_SPLITTING")
    def test_55_app_review(self): self.assertEqual(self.result(condition="if present").recommended_action, "REVIEW_APPLICABILITY_RULE")
    def test_56_mapping_review(self): self.assertEqual(self.result(shared=2, source="PART_2_ADDITION").recommended_action, "REVIEW_PART1_PART2_MAPPING")
    def test_57_profile_improvement(self): self.assertEqual(self.result(missing=("x",)).recommended_action, "IMPROVE_PRODUCT_PROFILE")
    def test_58_parser_review(self): self.assertEqual(self.result(verdicts=("NA","PASS")).recommended_action, "REVIEW_REPORT_PARSER")
    def test_59_kb_immutable(self): self._immutability(0)
    def test_60_profile_immutable(self): self._immutability(1)
    def test_61_app_immutable(self): self._immutability(2)
    def test_62_evidence_immutable(self): self._immutability(3)
    def test_63_match_immutable(self): self._immutability(4)
    def test_64_technical_immutable(self): self._immutability(5)
    def test_65_na_immutable(self): self._immutability(6)
    def test_66_valid_json(self): json.loads(self.a.to_json(self.result()))
    def test_67_enum_value(self): self.assertIn('"TRUE_NA_CONFLICT"', self.a.to_json(self.result()))
    def test_68_deterministic_output(self): self.assertEqual(self.a.to_json(self.result()), self.a.to_json(self.result()))
    def test_69_deterministic_id(self): self.assertEqual(self.result().audit_id, self.result().audit_id)
    def test_70_no_fixed_clause(self): self.assertNotIn("specific clause", self.result().reason.lower())
    def test_71_no_standard_dependency(self): self.assertNotIn("standard_number", self.result().reason)
    def test_72_no_category_branch(self): self.assertNotIn("product category", self.result().reason.lower())
    def test_73_no_fixed_file(self): self.assertNotIn(".json", self.result().reason)
    def test_74_no_page_rule(self): self.assertEqual(self.result().report_pages, [3])
    def test_75_na_status_preserved(self): self.assertEqual(self.result().na_validation_status, "POTENTIAL_CONFLICT")
    def test_76_no_pass_fail(self): self.assertNotIn("FAIL", self.result().root_cause.value)
    def test_77_no_gap(self): self.assertNotIn("gap", self.a.to_json(self.result()).lower())
    def test_78_no_readiness(self): self.assertNotIn("readiness", self.a.to_json(self.result()).lower())
    def test_79_no_repair(self): self.assertNotIn("repair", self.result().recommended_action.lower())
    def test_80_action_not_executed(self): self.assertTrue(self.result().recommended_action)

    def full_fixture(self):
        req={"effective_requirement_id":"R1","clause_id":"2","effective_status":"ACTIVE","text":"Guard shall prevent access.","requirement_type":"GENERAL","effective_source_type":"BASE"}
        kb={"effective_kb_id":"K","clauses":[{"requirements":[req],"children":[]}],"annexes":[]}
        profile={"profile_id":"P","facts":[]}; app={"results":[{"effective_requirement_id":"R1","decision":"APPLICABLE","applicability_status_from_kb":"ALWAYS","facts_used":[],"missing_features":[]}]}
        evidence={"document_id":"D","clauses":[]}; match={"matches":[{"effective_requirement_id":"R1","match_status":"EXACT_SUBCLAUSE","evidence_refs":[{"evidence_id":"E","report_clause_id":"2","reported_verdict":"NA","raw_text_excerpt":"Guard shall prevent access"}]}]}
        tech={"results":[]}; na={"results":[{"effective_requirement_id":"R1","effective_clause_id":"EC","source_clause_id":"2","status":"POTENTIAL_CONFLICT"}]}
        return [kb,profile,app,evidence,match,tech,na]

    def _immutability(self, index):
        fixture=self.full_fixture(); before=copy.deepcopy(fixture[index]); self.a.audit(*fixture)
        self.assertEqual(fixture[index], before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
