import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iec_par.generic_report_issue_aggregator import GenericReportIssueAggregator


class ReportIssueAggregatorTests(unittest.TestCase):
    def issue(self, iid="I1", kind="MISSING_EVIDENCE", action="PROVIDE_EVIDENCE", conclusion="NOT_EVALUATED", root="EVIDENCE_GAP", clause="1", rg="G1", reqs=None, evidence=None, severity="MEDIUM", blocking=True, actionability="ACTIONABLE"):
        return {"issue_id": iid, "clause_id": clause, "requirement_group_id": rg, "issue_type": kind,
                "compliance_conclusion": conclusion, "severity": severity, "actionability": actionability,
                "blocking": blocking, "user_explanation": "original", "impact": "original impact",
                "next_action": {"type": action, "description": "original action"}, "secondary_actions": [],
                "evidence_refs": evidence or [], "requirement_ids": reqs or [iid + "-R"], "product_fact_ids": [],
                "provenance": {"originating_issue_type": "SOURCE", "upstream_reason": root}}

    def report(self, issues=None, suppressed=None):
        return {"schema_version": "1.0", "issues": issues or [], "suppressed_findings": suppressed or [], "summary": {}}

    def aggregate(self, issues=None, suppressed=None):
        return GenericReportIssueAggregator().aggregate(self.report(issues, suppressed))

    def test_001_same_semantics_group(self):
        self.assertEqual(len(self.aggregate([self.issue(), self.issue("I2")]).actionable_groups), 1)

    def test_002_different_actions_separate(self):
        self.assertEqual(len(self.aggregate([self.issue(), self.issue("I2", action="LAB_CLARIFICATION")]).actionable_groups), 2)

    def test_003_different_types_separate(self):
        self.assertEqual(len(self.aggregate([self.issue(), self.issue("I2", kind="TRACEABILITY_ISSUE")]).actionable_groups), 2)

    def test_004_root_reasons_separate(self):
        self.assertEqual(len(self.aggregate([self.issue(), self.issue("I2", root="OTHER_GAP")]).actionable_groups), 2)

    def test_005_duplicate_ids_deduplicated(self):
        result = self.aggregate([self.issue(), self.issue()]); self.assertEqual(result.actionable_groups[0].issue_count, 1); self.assertEqual(result.summary["duplicate_issue_count_removed"], 1)

    def test_006_distinct_requirements_same_clause_preserved(self):
        group = self.aggregate([self.issue(reqs=["R1"]), self.issue("I2", reqs=["R2"])]).actionable_groups[0]; self.assertEqual(group.requirement_ids, ["R1", "R2"])

    def test_007_unique_clause_count(self):
        group = self.aggregate([self.issue(clause="1"), self.issue("I2", clause="2")]).actionable_groups[0]; self.assertEqual(group.affected_clause_count, 2)

    def test_008_unique_requirement_group_count(self):
        group = self.aggregate([self.issue(rg="G1"), self.issue("I2", rg="G2")]).actionable_groups[0]; self.assertEqual(group.affected_requirement_group_count, 2)

    def test_009_issue_count(self):
        self.assertEqual(self.aggregate([self.issue(), self.issue("I2")]).actionable_groups[0].issue_count, 2)

    def test_010_evidence_refs_deduplicated(self):
        group = self.aggregate([self.issue(evidence=["E1"]), self.issue("I2", evidence=["E1", "E2"])]).actionable_groups[0]; self.assertEqual(group.evidence_refs, ["E1", "E2"])

    def test_011_issue_ids_preserved(self):
        self.assertEqual(self.aggregate([self.issue(), self.issue("I2")]).actionable_groups[0].issue_ids, ["I1", "I2"])

    def test_012_requirement_group_ids_preserved(self):
        self.assertEqual(self.aggregate([self.issue(rg="G2"), self.issue("I2", rg="G1")]).actionable_groups[0].requirement_group_ids, ["G1", "G2"])

    def test_013_highest_severity(self):
        group = self.aggregate([self.issue(severity="MEDIUM"), self.issue("I2", severity="HIGH")]).actionable_groups[0]; self.assertEqual(group.severity_summary.highest, "HIGH")

    def test_014_severity_counts(self):
        group = self.aggregate([self.issue(severity="MEDIUM"), self.issue("I2", severity="HIGH")]).actionable_groups[0]; self.assertEqual((group.severity_summary.medium, group.severity_summary.high), (1, 1))

    def test_015_individual_severity_unmodified(self):
        group = self.aggregate([self.issue(severity="LOW"), self.issue("I2", severity="HIGH")]).actionable_groups[0]; self.assertEqual([x["severity"] for x in group.individual_issues], ["LOW", "HIGH"])

    def test_016_blocking_counts(self):
        group = self.aggregate([self.issue(blocking=True), self.issue("I2", blocking=False), self.issue("I3", blocking=None)]).actionable_groups[0]; self.assertEqual((group.blocking_summary.blocking_count, group.blocking_summary.non_blocking_count, group.blocking_summary.unknown_count), (1, 1, 1))

    def test_017_mixed_conclusions_not_promoted(self):
        result = self.aggregate([self.issue(), self.issue("I2", conclusion="UNRESOLVED")]); self.assertTrue(all(g.compliance_conclusion != "NONCOMPLIANT" for g in result.actionable_groups))

    def test_018_no_noncompliance_invented(self):
        self.assertNotIn("NONCOMPLIANT", [g.compliance_conclusion for g in self.aggregate([self.issue()]).actionable_groups])

    def test_019_suppressed_not_actionable(self):
        suppressed = self.issue("S1", actionability="SUPPRESSED"); result = self.aggregate([], [suppressed]); self.assertEqual(result.actionable_groups, []); self.assertEqual(result.suppressed_issue_ids, ["S1"])

    def test_020_informational_separate(self):
        result = self.aggregate([self.issue("N1"), self.issue("F1", actionability="INFORMATIONAL")]); self.assertEqual((len(result.actionable_groups), len(result.informational_groups)), (1, 1))

    def test_021_deterministic_group_ids(self):
        a = self.aggregate([self.issue(), self.issue("I2")]); b = self.aggregate([self.issue("I2"), self.issue()]); self.assertEqual(a.actionable_groups[0].group_id, b.actionable_groups[0].group_id)

    def test_022_deterministic_ordering(self):
        items = [self.issue("I1", root="B"), self.issue("I2", root="A")]; self.assertEqual([g.group_id for g in self.aggregate(items).actionable_groups], [g.group_id for g in self.aggregate(reversed(items)).actionable_groups])

    def test_023_deterministic_serialization(self):
        r = self.aggregate([self.issue()]); self.assertEqual(GenericReportIssueAggregator.to_json(r), GenericReportIssueAggregator.to_json(r))

    def test_024_input_object_immutable(self):
        source = self.report([self.issue()]); before = copy.deepcopy(source); GenericReportIssueAggregator().aggregate(source); self.assertEqual(source, before)

    def test_025_input_artifact_immutable(self):
        source = self.report([self.issue()])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "source.json"; path.write_text(json.dumps(source), encoding="utf-8"); before = path.read_bytes(); GenericReportIssueAggregator().aggregate(json.loads(path.read_text())); self.assertEqual(path.read_bytes(), before)

    def test_026_no_upstream_decision_modification(self):
        source = self.issue(conclusion="UNRESOLVED"); result = self.aggregate([source]); self.assertEqual(result.actionable_groups[0].individual_issues[0]["compliance_conclusion"], "UNRESOLVED")

    def test_027_no_action_modification(self):
        source = self.issue(action="LAB_CLARIFICATION"); result = self.aggregate([source]); self.assertEqual(result.actionable_groups[0].individual_issues[0]["next_action"], source["next_action"])

    def test_028_no_action_priority(self):
        output = GenericReportIssueAggregator.to_dict(self.aggregate([self.issue()])); self.assertNotIn("action_priority", output); self.assertNotIn("priority", output["summary"])

    def test_029_no_overall_report_status(self):
        self.assertNotIn("overall_status", GenericReportIssueAggregator.to_json(self.aggregate([self.issue()])).casefold())

    def test_030_no_readiness_score(self):
        output = GenericReportIssueAggregator.to_dict(self.aggregate([self.issue()])); self.assertNotIn("readiness_score", output); self.assertNotIn("readiness_score", output["summary"])

    def test_031_no_certification_claim(self):
        self.assertNotIn("certified", GenericReportIssueAggregator.to_json(self.aggregate([self.issue()])).casefold())

    def test_032_generic_production_source(self):
        source = Path(__file__).parents[1].joinpath("iec_par/generic_report_issue_aggregator.py").read_text().casefold()
        for forbidden in ("60335", "washing machine", "clause_id ==", "page ==", "model ==", "report =="):
            self.assertNotIn(forbidden, source)

    def test_033_quality_audit_zero(self):
        self.assertTrue(all(value == 0 for value in self.aggregate([self.issue()]).quality_audit.values()))

    def test_034_accounting(self):
        result = self.aggregate([self.issue(), self.issue("I2")]); self.assertTrue(result.summary["all_actionable_issue_ids_accounted_for"]); self.assertEqual(result.summary["accounted_actionable_issue_count"], 2)

    def test_035_full_individual_records_preserved(self):
        source = self.issue(); self.assertEqual(self.aggregate([source]).actionable_groups[0].individual_issues[0], source)

    def test_036_action_description_preserved(self):
        self.assertEqual(self.aggregate([self.issue()]).actionable_groups[0].primary_action.description, "original action")

    def test_037_unknown_blocking_not_inferred(self):
        self.assertEqual(self.aggregate([self.issue(blocking=None)]).actionable_groups[0].blocking_summary.unknown_count, 1)

    def test_038_save_json(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(GenericReportIssueAggregator.save_json(self.aggregate([self.issue()]), Path(d) / "out.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
