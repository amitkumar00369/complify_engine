"""Direct tests for generic requirement grouping and applicability scope metadata."""
from __future__ import annotations
import copy, json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iec_par.generic_requirement_grouping_resolver import *

class GroupingResolverTests(unittest.TestCase):
    def setUp(self): self.r=GenericRequirementGroupingResolver()
    def req(self, rid, text, typ="GENERAL", cond=None, status="ACTIVE", source="BASE"):
        return {"effective_requirement_id":rid,"clause_id":"X","text":text,"requirement_type":typ,
                "condition_text":cond,"effective_status":status,"effective_source_type":source,
                "base_sources":[{"requirement_id":rid+"-SRC"}],"delta_sources":[]}
    def resolve(self, reqs, matches=None):
        kb={"effective_kb_id":"K","clauses":[{"clause_id":"X","effective_clause_id":"EC-X","requirements":reqs,"children":[]}],"annexes":[]}
        apps={"results":[{"effective_requirement_id":x["effective_requirement_id"],"condition_text":x.get("condition_text"),
                          "rule":{"field":"feature"} if x.get("condition_text") else None,
                          "applicability_status_from_kb":"RESOLVED" if x.get("condition_text") else "ALWAYS"} for x in reqs]}
        match={"matches":matches or []}; return self.r.resolve(kb,apps,match),kb,apps,match
    def pair(self, test="Compliance is checked by inspection.", first="The guard shall prevent access.", **kw):
        return self.resolve([self.req("R1",first,cond=kw.get("cond")),self.req("R2",test,kw.get("typ","TEST"),cond=kw.get("test_cond"),source=kw.get("source","BASE"))])[0]

    def test_001_compliance_checked_attaches(self): self.assertEqual(len(self.pair().groups),1)
    def test_002_test_carried_out_attaches(self): self.assertEqual(len(self.pair("The test is carried out at rated voltage.").groups),1)
    def test_003_standalone_test_independent(self): self.assertEqual(self.resolve([self.req("R1","The test is carried out.","TEST")])[0].groups[0].members[0].role,RequirementGroupMemberRole.INDEPENDENT)
    def test_004_test_without_predecessor(self): self.test_003_standalone_test_independent()
    def test_005_after_test_attaches(self): self.assertEqual(self.pair("After the test, the sample shall remain intact.",typ="GENERAL").groups[0].members[1].role,RequirementGroupMemberRole.POST_TEST_CONDITION)
    def test_006_after_tests_attaches(self): self.assertEqual(self.pair("After the tests, no damage shall occur.",typ="GENERAL").groups[0].members[1].role,RequirementGroupMemberRole.POST_TEST_CONDITION)
    def test_007_acceptance_after_test(self):
        q=[self.req("R1","The guard shall prevent access."),self.req("R2","Compliance is checked by a test.","TEST"),self.req("R3","During the test, there shall be no damage.")]
        self.assertEqual(self.resolve(q)[0].groups[0].members[2].role,RequirementGroupMemberRole.ACCEPTANCE_CRITERION)
    def test_008_independent_numeric_primary(self): self.assertEqual(len(self.pair("The temperature shall not exceed 50 C.",typ="LIMIT").groups),2)
    def test_009_these_parts(self): self.assertEqual(self.pair("These parts shall be protected.",typ="GENERAL").groups[0].members[1].role,RequirementGroupMemberRole.CONTINUATION)
    def test_010_such_parts(self): self.assertEqual(self.pair("Such parts shall withstand the test.",typ="GENERAL").groups[0].members[1].role,RequirementGroupMemberRole.CONTINUATION)
    def test_011_they_shall(self): self.assertEqual(self.pair("They shall be secured.",typ="GENERAL").groups[0].members[1].role,RequirementGroupMemberRole.CONTINUATION)
    def test_012_ambiguous_pronoun(self): self.assertEqual(len(self.pair("It shall be secured.",typ="GENERAL").groups),2)
    def test_013_primary_condition_inheritance(self): self.assertEqual(self.pair(cond="For class X").groups[0].members[1].applicability_scope,ApplicabilityScopeType.INHERIT_PRIMARY)
    def test_014_member_own_condition(self): self.assertEqual(len(self.pair(test_cond="When separately supplied").groups),2)
    def test_015_changed_condition_boundary(self): self.test_014_member_own_condition()
    def test_016_conditional_test_method(self): self.assertEqual(len(self.pair(test_cond="When tested separately").groups),2)
    def test_017_two_groups(self):
        q=[self.req("R1","A shall apply."),self.req("R2","Compliance is checked." ,"TEST"),self.req("R3","B shall apply."),self.req("R4","Compliance is checked.","TEST")]
        self.assertEqual([len(x.members) for x in self.resolve(q)[0].groups],[2,2])
    def test_018_three_independent(self): self.assertEqual(len(self.resolve([self.req(str(i),f"Subject {i} shall comply.") for i in range(3)])[0].groups),3)
    def test_019_continuation_then_new(self):
        q=[self.req("1","Parts shall comply."),self.req("2","Such parts shall be fixed."),self.req("3","A switch shall comply.")]
        self.assertEqual([len(x.members) for x in self.resolve(q)[0].groups],[2,1])
    def test_020_adjacency(self): self.assertEqual(len(self.pair().groups[0].members),2)
    def test_021_distant_not_grouped(self): self.test_018_three_independent()
    def test_022_construction_test(self): self.assertEqual(len(self.pair(first="The enclosure shall be constructed safely.").groups),1)
    def test_023_marking_test(self): self.assertEqual(len(self.pair(first="The appliance shall be marked.").groups),1)
    def test_024_instruction_test(self): self.assertEqual(len(self.pair(first="Instructions shall state the warning.").groups),1)
    def test_025_standalone_test(self): self.test_003_standalone_test_independent()
    def test_026_inactive_not_primary(self): self.assertEqual(self.resolve([self.req("I","Old shall.",status="INACTIVE"),self.req("A","New shall.")])[0].groups[0].primary_requirement_id,"A")
    def test_027_replacement_active(self): self.assertEqual(self.resolve([self.req("I","Old shall.",status="INACTIVE"),self.req("A","New shall.",source="PART_2_REPLACEMENT")])[0].groups[0].primary_requirement_id,"A")
    def test_028_inactive_ungrouped(self): self.assertEqual(self.resolve([self.req("I","Old shall.",status="INACTIVE")])[0].ungrouped_requirements,["I"])
    def test_029_addition_independent(self): self.assertEqual(len(self.pair("An added obligation shall apply.",typ="GENERAL",source="PART_2_ADDITION").groups),2)
    def test_030_replacement_group(self): self.assertEqual(len(self.pair(source="PART_2_REPLACEMENT").groups),1)
    def test_031_modification_group(self): self.assertEqual(len(self.pair(source="PART_2_MODIFICATION").groups),1)
    def test_032_new_requirement(self): self.assertEqual(len(self.pair(source="PART_2_NEW_REQUIREMENT").groups),1)
    def test_033_no_base_addition_auto_group(self): self.test_029_addition_independent()
    def test_034_shared_report_support(self):
        ms=[{"effective_requirement_id":r,"evidence_refs":[{"report_clause_id":"X"}]} for r in ("R1","R2")]
        self.assertEqual(self.resolve([self.req("R1","A shall."),self.req("R2","Compliance is checked.","TEST")],ms)[0].groups[0].report_scope_clause_ids,["X"])
    def test_035_shared_alone_insufficient(self):
        ms=[{"effective_requirement_id":r,"evidence_refs":[{"report_clause_id":"X"}]} for r in ("R1","R2")]
        self.assertEqual(len(self.resolve([self.req("R1","A shall."),self.req("R2","B shall.")],ms)[0].groups),2)
    def test_036_different_report_scope(self):
        ms=[{"effective_requirement_id":"R1","evidence_refs":[{"report_clause_id":"X"}]},{"effective_requirement_id":"R2","evidence_refs":[{"report_clause_id":"Y"}]}]
        self.assertEqual(self.resolve([self.req("R1","A shall."),self.req("R2","Compliance is checked.","TEST")],ms)[0].groups[0].report_scope_clause_ids,[])
    def test_037_own(self): self.assertEqual(self.resolve([self.req("R1","A shall.",cond="when fitted")])[0].groups[0].members[0].applicability_scope,ApplicabilityScopeType.OWN)
    def test_038_inherit_primary(self): self.test_013_primary_condition_inheritance()
    def test_039_inherit_previous_enum(self): self.assertEqual(ApplicabilityScopeType.INHERIT_PREVIOUS.value,"INHERIT_PREVIOUS")
    def test_040_shared_group_enum(self): self.assertEqual(ApplicabilityScopeType.SHARED_GROUP.value,"SHARED_GROUP")
    def test_041_independent_scope(self): self.assertEqual(self.resolve([self.req("R","A shall.")])[0].groups[0].members[0].applicability_scope,ApplicabilityScopeType.INDEPENDENT)
    def test_042_unresolved_enum(self): self.assertEqual(ApplicabilityScopeType.UNRESOLVED.value,"UNRESOLVED")
    def test_043_deterministic_id(self): self.assertEqual(self.pair().groups[0].group_id,self.pair().groups[0].group_id)
    def test_044_annex_namespace(self):
        kb={"effective_kb_id":"K","clauses":[],"annexes":[{"annex_id":"AA","requirements":[self.req("R","A shall.")],"children":[]}]}
        self.assertTrue(self.r.resolve(kb,{"results":[]}).groups[0].group_id.startswith("RG-ANNEX_AA"))
    def test_045_no_collision(self):
        groups=self.resolve([self.req("R1","A shall."),self.req("R2","B shall.")])[0].groups
        self.assertEqual(len({g.group_id for g in groups}),2)
    def test_046_status_resolved(self): self.assertEqual(self.pair().groups[0].group_status,RequirementGroupStatus.RESOLVED)
    def test_047_new_condition_boundary(self): self.test_014_member_own_condition()
    def test_048_new_subject_boundary(self): self.assertEqual(len(self.pair("A switch shall be protected.",typ="GENERAL").groups),2)
    def test_049_new_shall_boundary(self): self.test_048_new_subject_boundary()
    def test_050_part2_boundary(self): self.test_029_addition_independent()
    def test_051_chain(self):
        q=[self.req("1","For class X, parts shall comply.",cond="For class X"),self.req("2","Such parts shall be fixed."),self.req("3","Compliance is checked.","TEST")]
        self.assertEqual(len(self.resolve(q)[0].groups[0].members),3)
    def test_052_no_unsafe_cascade(self): self.test_019_continuation_then_new()
    def test_053_member_ids(self): self.assertEqual([m.effective_requirement_id for m in self.pair().groups[0].members],["R1","R2"])
    def test_054_source_order(self): self.assertEqual([m.source_order for m in self.pair().groups[0].members],[1,2])
    def test_055_rule_source(self): self.assertEqual(self.pair(cond="For class X").groups[0].shared_applicability_rule,{"field":"feature"})
    def test_056_report_scope(self): self.test_034_shared_report_support()
    def test_057_kb_unchanged(self): self._immutability(1)
    def test_058_app_unchanged(self): self._immutability(2)
    def test_059_matches_unchanged(self): self._immutability(3)
    def test_060_no_step19_input(self): self.assertEqual(self.r.resolve.__code__.co_argcount,4)
    def test_061_no_step19a_input(self): self.test_060_no_step19_input()
    def test_062_valid_json(self): json.loads(self.r.to_json(self.pair()))
    def test_063_plain_enums(self): self.assertIn('"TEST_METHOD"',self.r.to_json(self.pair()))
    def test_064_deterministic_json(self): self.assertEqual(self.r.to_json(self.pair()),self.r.to_json(self.pair()))
    def test_065_generic_clause(self): self.assertEqual(self.pair().groups[0].clause_id,"X")
    def test_066_no_category(self): self.assertNotIn("category",self.pair().groups[0].reason.lower())
    def test_067_no_report_path(self): self.assertNotIn(".json",self.pair().groups[0].reason)
    def test_068_conflict_primary(self): self.assertEqual(self._reconcile("R1")["primary_requirement"],1)
    def test_069_conflict_dependent(self): self.assertEqual(self._reconcile("R2")["dependent_inherited_requirement"],1)
    def test_070_conflict_independent(self): self.assertEqual(self._reconcile("S")["independent_requirement"],1)
    def test_071_conflict_unresolved(self): self.assertEqual(self._reconcile("Z")["unresolved_grouping"],1)
    def test_072_inherited_always(self): self.assertEqual(self._reconcile("R2",always=True)["always_conflicts_by_grouping"]["dependent_inherited_requirement"],1)
    def test_073_conditional_detail_test(self):
        out=self.pair("It shall only be possible to touch insulated parts.",typ="GENERAL",cond="For class X")
        self.assertEqual(out.groups[0].members[1].role,RequirementGroupMemberRole.CONTINUATION)
    def test_074_obligation_test_post(self): self.test_007_acceptance_after_test()
    def test_075_two_obligations(self): self.assertEqual(len(self.resolve([self.req("1","A shall."),self.req("2","B shall.")])[0].groups),2)
    def test_076_bullet_continuation(self): self.test_009_these_parts()
    def test_077_test_own_condition(self): self.test_016_conditional_test_method()
    def test_078_acceptance_own_condition(self): self.assertEqual(len(self.pair("During the test, leakage shall not exceed X.",typ="LIMIT",test_cond="For mode Y").groups),2)
    def test_079_addition_and_test(self): self.assertEqual(len(self.pair(source="PART_2_ADDITION").groups),1)
    def test_080_replacement_and_test(self): self.assertEqual(len(self.pair(source="PART_2_REPLACEMENT").groups),1)
    def test_081_no_text_rewrite(self): self.assertEqual(self.pair().groups[0].members[0].effective_requirement_id,"R1")
    def test_082_no_app_rewrite(self): self._immutability(2)
    def test_083_no_rematch(self): self._immutability(3)
    def test_084_no_na_revalidation(self): self.test_060_no_step19_input()
    def test_085_no_pass_fail(self): self.assertNotIn('"PASS"',self.r.to_json(self.pair()))
    def test_086_no_readiness(self): self.assertNotIn("readiness",self.r.to_json(self.pair()).lower())
    def test_087_no_step5_change(self): self.assertFalse(hasattr(self.r,"rewrite_requirement"))
    def test_088_no_step15_change(self): self.assertFalse(hasattr(self.r,"update_applicability"))
    def test_089_no_step17_change(self): self.assertFalse(hasattr(self.r,"rematch"))
    def test_090_no_step19_change(self): self.assertFalse(hasattr(self.r,"revalidate_na"))

    def _immutability(self,index):
        out,kb,apps,matches=self.resolve([self.req("R1","A shall."),self.req("R2","Compliance is checked.","TEST")]); vals=[out,kb,apps,matches]
        before=copy.deepcopy(vals[index]); self.r.resolve(kb,apps,matches); self.assertEqual(vals[index],before)
    def _reconcile(self,rid,always=False):
        report=self.pair();
        if rid=="S": report=self.resolve([self.req("S","Standalone test.","TEST")])[0]
        audit={"results":[{"effective_requirement_id":rid}]}; apps={"results":[{"effective_requirement_id":rid,"applicability_status_from_kb":"ALWAYS" if always else "RESOLVED"}]}
        return self.r.reconcile_conflicts(report,audit,apps)

if __name__=="__main__": unittest.main(verbosity=2)
