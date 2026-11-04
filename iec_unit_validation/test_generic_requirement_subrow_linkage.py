"""Focused generic requirement-to-logical-row linkage tests."""

import copy
import json
import unittest
from pathlib import Path

from iec_par.generic_requirement_evidence_matcher import GenericRequirementEvidenceMatcher as Matcher


def requirement(text="A force of 30 N shall be applied for 1 min.", clause="4.2", rid="R1"):
    return {"effective_requirement_id":rid,"clause_id":clause,"effective_status":"ACTIVE","text":text}


def item(text, verdict="PASS", eid="E-S1", clause="4.2", scope="INDIVIDUAL_VERDICT"):
    return {"evidence_id":eid,"evidence_type":"SUBROW","reported_verdict":verdict,"raw_text":text,
            "logical_row_id":"L-1","verdict_scope":scope,"verdict_owner_evidence_id":eid,
            "page_start":3,"page_end":3,"source_order":2,"clause_id":clause,"measurements":[]}


def node(*items, clause="4.2"):
    return {"clause_id":clause,"result_id":"RESULT","evidence_items":list(items),"children":[],"raw_text":" ".join(x["raw_text"] for x in items)}


class RequirementSubrowLinkageTests(unittest.TestCase):
    def match(self, req, report_node):
        return Matcher().match_requirement(req,{report_node["clause_id"]:report_node},"APPLICABLE",req["clause_id"])

    def test_01_exact_clause_semantic_subrow(self):
        self.assertEqual(self.match(requirement(),node(item("A force of 30 N was applied for 1 min"))).match_type,"EXACT_SUBROW_SEMANTIC")

    def test_02_parameter_value(self):
        self.assertIn("PARAMETER_VALUE_MATCH",self.match(requirement(),node(item("30 N applied for 1 min"))).match_reason)

    def test_03_duration(self):
        self.assertIn("DURATION_MATCH",self.match(requirement(),node(item("30 N applied for 1 minute"))).match_reason)

    def test_04_percentage(self):
        result=self.match(requirement("The result shall be at least 50 %."),node(item("Measured result was 50 %")))
        self.assertIn("PERCENTAGE_MATCH",result.match_reason)

    def test_05_table_reference(self):
        result=self.match(requirement("Clearance shall be 50 % of Table 7."),node(item("Clearance was 50% of Table 7")))
        self.assertIn("TABLE_REFERENCE_MATCH",result.match_reason)

    def test_06_test_action(self):
        result=self.match(requirement("The marking is checked by rubbing."),node(item("Marking was rubbed and withstood the test")))
        self.assertIn("TEST_ACTION_MATCH",result.match_reason)

    def test_07_independent_pass_selected(self):
        self.assertEqual(self.match(requirement(),node(item("30 N applied for 1 min"))).evidence_refs[0].reported_verdict,"PASS")

    def test_08_parent_loses_priority(self):
        n=node(item("30 N applied for 1 min"));n["evidence_items"].insert(0,{"evidence_id":"P","evidence_type":"CLAUSE_ROW","reported_verdict":"NOT_STATED","raw_text":"context"})
        self.assertEqual(self.match(requirement(),n).evidence_refs[0].evidence_id,"E-S1")

    def test_09_sibling_isolation(self):
        n=node(item("30 N applied for 1 min"),item("Condition not applicable","NA","E-S2"))
        self.assertEqual([x.evidence_id for x in self.match(requirement(),n).evidence_refs],["E-S1"])

    def test_10_grouped_not_promoted(self):
        grouped=item("30 N applied for 1 min",scope="GROUP_VERDICT");self.assertEqual(self.match(requirement(),node(grouped)).match_type,"CLAUSE_PRESENCE_ONLY")

    def test_11_same_value_different_clause(self):
        self.assertEqual(Matcher().match_requirement(requirement(clause="4.2"),{"5.2":node(item("30 N applied for 1 min",clause="5.2"),clause="5.2")}).match_status.value,"NO_MATCH")

    def test_12_different_duration_rejected(self):
        self.assertEqual(self.match(requirement(),node(item("30 N applied for 10 s"))).match_type,"CLAUSE_PRESENCE_ONLY")

    def test_13_different_table_rejected(self):
        req=requirement("Clearance shall be 50 % of Table 7.");self.assertEqual(self.match(req,node(item("Clearance was 50 % of Table 8"))).match_type,"CLAUSE_PRESENCE_ONLY")

    def test_14_wrong_parameter_rejected(self):
        self.assertEqual(self.match(requirement(),node(item("Voltage was maintained at 30 V for 1 min"))).match_type,"CLAUSE_PRESENCE_ONLY")

    def test_15_na_sibling_not_propagated(self):
        n=node(item("30 N applied for 1 min"),item("Unrelated option","NA","E2"));self.assertEqual(self.match(requirement(),n).evidence_refs[0].reported_verdict,"PASS")

    def test_16_pass_sibling_not_propagated(self):
        n=node(item("30 N applied for 10 s"),item("Unrelated option","PASS","E2"));self.assertEqual(self.match(requirement(),n).match_type,"CLAUSE_PRESENCE_ONLY")

    def test_17_provenance_retained(self):
        ref=self.match(requirement(),node(item("30 N applied for 1 min"))).evidence_refs[0];self.assertEqual((ref.page_start,ref.source_order),(3,2))

    def test_18_deterministic_reason(self):
        a=self.match(requirement(),node(item("30 N applied for 1 min")));b=self.match(requirement(),node(item("30 N applied for 1 min")));self.assertEqual(a.match_reason,b.match_reason)

    def test_19_deterministic_serialization(self):
        value=self.match(requirement(),node(item("30 N applied for 1 min")));self.assertEqual(Matcher.to_json(value),Matcher.to_json(copy.deepcopy(value)))

    def test_20_no_specific_branch(self):
        source=Path("iec_par/generic_requirement_evidence_matcher.py").read_text().casefold()
        for forbidden in ("62841","27.1","28.1","8.12","21.23","19.101","impact drill"):
            self.assertNotIn(forbidden,source)

    @classmethod
    def real(cls,name,file):
        return json.loads(Path("test_reports/output",name,"decisions",file).read_text())

    def test_21_27_1_regression(self):
        data=json.loads(Path("test_reports/output/iec_62841_impact_drill_post_31jg/report/evidence_match_result.json").read_text())
        matches=[x for x in data["matches"] if x.get("source_clause_id")=="27.1"]
        self.assertTrue(any(x.get("match_type")=="EXACT_SUBROW_SEMANTIC" for x in matches))

    def test_22_28_1_regression(self):
        data=json.loads(Path("test_reports/output/iec_62841_impact_drill_post_31jg/report/evidence_match_result.json").read_text())
        reasons=" ".join(x.get("match_reason") or "" for x in data["matches"] if x.get("source_clause_id")=="28.1")
        self.assertIn("TABLE_REFERENCE_MATCH",reasons);self.assertIn("PERCENTAGE_MATCH",reasons)

    def test_23_8_12_regression(self):
        data=json.loads(Path("test_reports/output/iec_62841_impact_drill_post_31jg/report/evidence_match_result.json").read_text())
        refs=[r["evidence_id"] for x in data["matches"] if x.get("source_clause_id")=="8.12" for r in x.get("evidence_refs",[])]
        self.assertIn("REPORT-EV-8.12-001-SUBROW-002",refs);self.assertIn("REPORT-EV-8.12-001-SUBROW-003",refs)

    def test_24_21_23_regression(self):
        data=json.loads(Path("test_reports/output/iec_62841_impact_drill_post_31jg/report/evidence_match_result.json").read_text())
        self.assertTrue(any(x.get("match_type")=="EXACT_SUBROW_SEMANTIC" for x in data["matches"] if x.get("source_clause_id")=="21.23"))

    def test_25_19_101_conservative_linkage(self):
        data=json.loads(Path("test_reports/output/iec_62841_impact_drill_post_31jg/report/evidence_match_result.json").read_text())
        self.assertTrue(any(x.get("match_type")=="EXPLICIT_PARENT_CHILD_REPORT_OWNERSHIP" for x in data["matches"] if x.get("source_clause_id")=="19.101"))

    def test_26_amendment_source_gap(self):
        issues=self.real("iec_62841_impact_drill_post_31jg","final_compliance_issues.json")["issues"]
        gap=next(x for x in issues if x["issue_type"]=="STANDARD_SOURCE_GAP")
        self.assertEqual(gap["compliance_conclusion"],"NOT_EVALUATED");self.assertEqual(gap["next_action"]["type"],"STANDARD_SOURCE_REQUEST")

    def test_27_washing_regression(self):
        issues=self.real("washing_machine_post_31jg","final_compliance_issues.json")["issues"]
        self.assertEqual(sum(x["issue_type"]=="UNRESOLVED_EVIDENCE_CONFLICT" for x in issues),1)

    def test_28_pump_regression(self):
        issues=self.real("submersible_pump_post_31jg","final_compliance_issues.json")["issues"]
        self.assertEqual(sum(x["issue_type"]=="UNRESOLVED_EVIDENCE_CONFLICT" for x in issues),4)

    def test_29_welding_regression(self):
        issues=self.real("plastic_tube_welding_tools_post_31jg","final_compliance_issues.json")["issues"]
        self.assertFalse(any(x["issue_type"]=="UNRESOLVED_EVIDENCE_CONFLICT" for x in issues))

    def test_30_iec_60204_regression(self):
        issues=self.real("iec_60204_1_post_31jg","final_compliance_issues.json")["issues"]
        self.assertEqual(sum(x["issue_type"]=="UNRESOLVED_EVIDENCE_CONFLICT" for x in issues),1)


if __name__=="__main__":unittest.main(verbosity=2)
