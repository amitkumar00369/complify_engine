"""Tests for deterministic effective-requirement/report-evidence matching."""

from __future__ import annotations

import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from iec_par.generic_requirement_evidence_matcher import (
 GenericRequirementEvidenceMatcher as Matcher, RequirementEvidenceMatchReport,
 RequirementEvidenceMatchStatus as S,
)


class GenericRequirementEvidenceMatcherTests(unittest.TestCase):
 def setUp(self): self.m=Matcher()
 def req(self,c="7.1",rid="ER-1",status="ACTIVE",source="BASE",text="Distinctive leakage current measurement protection"):
  return {"effective_requirement_id":rid,"clause_id":c,"effective_status":status,"effective_source_type":source,"text":text}
 def item(self,c="7.1",eid="EV-1",verdict="PASS",measurements=None,order=1):
  return {"evidence_id":eid,"evidence_type":"CLAUSE_RESULT","reported_verdict":verdict,"page_start":2,"page_end":2,"source_order":order,"raw_text":"Distinctive leakage current measurement protection","measurements":measurements or []}
 def node(self,c="7.1",verdict="PASS",items=None,children=None,title=None,raw=None):
  return {"clause_id":c,"result_id":"RC-"+c,"reported_verdict":verdict,"page_start":2,"page_end":2,"source_order":1,"title":title,"raw_text":raw or "Distinctive leakage current measurement protection","measurements":[],"evidence_items":items if items is not None else [self.item(c,verdict=verdict)],"children":children or []}
 def kb(self,reqs,annexes=None): return {"effective_kb_id":"KB","clauses":[{"effective_clause_id":"EC","requirements":reqs,"children":[]}],"annexes":annexes or []}
 def evidence(self,nodes=None,annexes=None): return {"document_id":"DOC","clauses":nodes or [],"annexes":annexes or []}
 def app(self,rid="ER-1",decision="APPLICABLE"): return {"profile_id":"P","results":[{"effective_requirement_id":rid,"decision":decision}]}
 def one(self,req=None,nodes=None,app=None): return self.m.match(self.kb([req or self.req()]),self.evidence(nodes or []),app).matches[0]

 # EXACT
 def test_01_exact_clause(self): self.assertIs(self.one(self.req("7"),[self.node("7")]).match_status,S.EXACT_CLAUSE)
 def test_02_exact_subclause(self): self.assertIs(self.one(nodes=[self.node()]).match_status,S.EXACT_SUBCLAUSE)
 def test_03_exact_pass(self): self.assertEqual(self.one(nodes=[self.node()]).evidence_refs[0].reported_verdict,"PASS")
 def test_04_exact_na(self): self.assertEqual(self.one(nodes=[self.node(verdict="NA")]).evidence_refs[0].reported_verdict,"NA")
 def test_05_verdict_no_match_effect(self): self.assertEqual(self.one(nodes=[self.node(verdict="FAIL")]).match_status,self.one(nodes=[self.node(verdict="NA")]).match_status)
 # MULTIPLE REQUIREMENTS
 def test_06_one_clause_two_requirements(self): self.assertEqual(len(self.m.match(self.kb([self.req(rid="A"),self.req(rid="B")]),self.evidence([self.node()])).matches),2)
 def test_07_evidence_reused_safely(self):
  r=self.m.match(self.kb([self.req(rid="A"),self.req(rid="B")]),self.evidence([self.node()])); self.assertEqual(r.matches[0].evidence_refs[0].evidence_id,r.matches[1].evidence_refs[0].evidence_id)
 # MULTIPLE EVIDENCE
 def test_08_multiple_evidence_items(self): self.assertEqual(len(self.one(nodes=[self.node(items=[self.item(eid="E1"),self.item(eid="E2")])]).evidence_refs),2)
 def test_09_duplicate_occurrences_retained(self): self.assertEqual([x.evidence_id for x in self.one(nodes=[self.node(items=[self.item(eid="E1"),self.item(eid="E2")])]).evidence_refs],["E1","E2"])
 # PARENT
 def test_10_parent_candidate(self):
  parent=self.node("7.1",children=[self.node("7.1.1")]); self.assertIs(self.one(self.req("7.1.5"),[parent]).match_status,S.PARENT_CLAUSE)
 def test_11_parent_score(self):
  parent=self.node("7.1",children=[self.node("7.1.1")]); self.assertEqual(self.one(self.req("7.1.5"),[parent]).match_score,.70)
 def test_12_no_unsafe_parent(self): self.assertIs(self.one(self.req("7.1.5"),[self.node("7.1",raw="plain")]).match_status,S.NO_MATCH)
 # CHILD
 def test_13_child_evidence(self): self.assertIs(self.one(self.req("7"),[self.node("7.1")]).match_status,S.CHILD_CLAUSE)
 def test_14_conflicting_children(self): self.assertIs(self.one(self.req("7"),[self.node("7.1","PASS"),self.node("7.2","NA")]).match_status,S.NEEDS_REVIEW)
 # ANNEX
 def test_15_annex_exact(self):
  annex={"annex_id":"CC","effective_annex_id":"EA","requirements":[self.req()]}; ev={"annex_id":"CC","clauses":[self.node()]}; r=self.m.match({"effective_kb_id":"K","clauses":[],"annexes":[annex]},self.evidence(annexes=[ev])); self.assertIs(r.matches[0].match_status,S.ANNEX_EXACT)
 def test_16_annex_main_isolated(self):
  annex={"annex_id":"CC","effective_annex_id":"EA","requirements":[self.req()]}; r=self.m.match({"effective_kb_id":"K","clauses":[],"annexes":[annex]},self.evidence([self.node()])); self.assertIs(r.matches[0].match_status,S.NO_MATCH)
 def test_17_missing_annex(self):
  annex={"annex_id":"CC","effective_annex_id":"EA","requirements":[self.req()]}; r=self.m.match({"effective_kb_id":"K","clauses":[],"annexes":[annex]},self.evidence()); self.assertEqual(r.matches[0].unmatched_reason,"ANNEX_NOT_PRESENT")
 # NO MATCH
 def test_18_no_clause(self): self.assertIs(self.one().match_status,S.NO_MATCH)
 def test_19_no_safe_parent(self): self.assertEqual(self.one(self.req("7.1.5"),[self.node("7.1",raw="plain")]).unmatched_reason,"NO_RELIABLE_PARENT_MATCH")
 def test_20_inactive_no_match(self): self.assertIs(self.one(self.req(status="INACTIVE")).match_status,S.NO_MATCH)
 # APPLICABILITY
 def test_21_applicable_attached(self): self.assertEqual(self.one(nodes=[self.node()],app=self.app()).applicability_decision,"APPLICABLE")
 def test_22_not_applicable_attached(self): self.assertEqual(self.one(nodes=[self.node()],app=self.app(decision="NOT_APPLICABLE")).applicability_decision,"NOT_APPLICABLE")
 def test_23_unknown_attached(self): self.assertEqual(self.one(nodes=[self.node()],app=self.app(decision="UNKNOWN")).applicability_decision,"UNKNOWN")
 def test_24_inactive_attached(self): self.assertEqual(self.one(nodes=[self.node()],app=self.app(decision="INACTIVE")).applicability_decision,"INACTIVE")
 def test_25_applicability_no_match_effect(self): self.assertEqual(self.one(nodes=[self.node()],app=self.app()).match_status,self.one(nodes=[self.node()],app=self.app(decision="UNKNOWN")).match_status)
 # VERDICTS
 def test_26_pass_preserved(self): self.assertEqual(self.one(nodes=[self.node("7.1","PASS")]).evidence_refs[0].reported_verdict,"PASS")
 def test_27_fail_preserved(self): self.assertEqual(self.one(nodes=[self.node("7.1","FAIL")]).evidence_refs[0].reported_verdict,"FAIL")
 def test_28_na_preserved(self): self.assertEqual(self.one(nodes=[self.node("7.1","NA")]).evidence_refs[0].reported_verdict,"NA")
 def test_29_unknown_preserved(self): self.assertEqual(self.one(nodes=[self.node("7.1","UNKNOWN")]).evidence_refs[0].reported_verdict,"UNKNOWN")
 def test_30_no_verdict_correctness(self): self.assertNotIn("correct",self.m.to_json(self.one(nodes=[self.node(verdict="NA")])).casefold())
 # MEASUREMENTS
 def test_31_measurement_attached(self):
  m={"measurement_id":"M1"}; self.assertEqual(self.one(nodes=[self.node(items=[self.item(measurements=[m])])]).evidence_refs[0].measurement_ids,["M1"])
 def test_32_no_constraint_comparison(self): self.assertNotIn("constraint",self.m.to_json(self.one(nodes=[self.node()])))
 def test_33_multiple_measurements(self):
  ms=[{"measurement_id":"M1"},{"measurement_id":"M2"}]; self.assertEqual(len(self.one(nodes=[self.node(items=[self.item(measurements=ms)])]).evidence_refs[0].measurement_ids),2)
 # TEXT FALLBACK
 def test_34_distinctive_phrase_without_structure_is_rejected(self): self.assertIs(self.one(self.req("99"),[self.node("88")]).match_status,S.NO_MATCH)
 def test_35_boilerplate_insufficient(self): self.assertIs(self.one(self.req("99",text="Compliance is checked by inspection"),[self.node("88",raw="Compliance is checked by inspection")]).match_status,S.NO_MATCH)
 def test_36_ambiguous_semantic_without_structure_is_rejected(self): self.assertIs(self.one(self.req("99"),[self.node("88"),self.node("89")]).match_status,S.NO_MATCH)
 # CONFLICT
 def test_37_conflicting_occurrence_verdicts(self): self.assertIs(self.one(nodes=[self.node(items=[self.item(verdict="PASS"),self.item(eid="E2",verdict="NA")])]).match_status,S.NEEDS_REVIEW)
 def test_38_suffix_only_candidate_not_retained(self): self.assertEqual(self.one(self.req("7.2.1"),[self.node("8.2.1")]).candidate_report_clauses,[])
 # IDS
 def test_39_deterministic_id(self): self.assertEqual(self.one(nodes=[self.node()]).match_id,self.one(nodes=[self.node()]).match_id)
 def test_40_collision_safety(self): self.assertNotEqual(Matcher._match_id("A B"),Matcher._match_id("A_B"))
 # TRACEABILITY
 def test_41_report_clause_id(self): self.assertEqual(self.one(nodes=[self.node()]).matched_report_clauses,["7.1"])
 def test_42_evidence_id(self): self.assertEqual(self.one(nodes=[self.node()]).evidence_refs[0].evidence_id,"EV-1")
 def test_43_measurement_ids(self): self.assertEqual(self.one(nodes=[self.node(items=[self.item(measurements=[{"measurement_id":"M"}])])]).evidence_refs[0].measurement_ids,["M"])
 def test_44_pages(self): self.assertEqual(self.one(nodes=[self.node()]).evidence_refs[0].page_start,2)
 def test_45_source_order(self): self.assertEqual(self.one(nodes=[self.node()]).evidence_refs[0].source_order,1)
 # PROVENANCE
 def test_46_base(self): self.assertIs(self.one(self.req(source="BASE"),[self.node()]).match_status,S.EXACT_SUBCLAUSE)
 def test_47_addition(self): self.assertIs(self.one(self.req(source="PART_2_ADDITION"),[self.node()]).match_status,S.EXACT_SUBCLAUSE)
 def test_48_replacement(self): self.assertIs(self.one(self.req(source="PART_2_REPLACEMENT"),[self.node()]).match_status,S.EXACT_SUBCLAUSE)
 def test_49_modification(self): self.assertIs(self.one(self.req(source="PART_2_MODIFICATION"),[self.node()]).match_status,S.EXACT_SUBCLAUSE)
 def test_50_part2_new(self): self.assertIs(self.one(self.req(source="PART_2_NEW_REQUIREMENT"),[self.node()]).match_status,S.EXACT_SUBCLAUSE)
 # IMMUTABILITY
 def test_51_kb_unchanged(self):
  k=self.kb([self.req()]); before=copy.deepcopy(k); self.m.match(k,self.evidence([self.node()])); self.assertEqual(k,before)
 def test_52_evidence_unchanged(self):
  e=self.evidence([self.node()]); before=copy.deepcopy(e); self.m.match(self.kb([self.req()]),e); self.assertEqual(e,before)
 def test_53_app_unchanged(self):
  a=self.app(); before=copy.deepcopy(a); self.m.match(self.kb([self.req()]),self.evidence([self.node()]),a); self.assertEqual(a,before)
 # SERIALIZATION
 def test_54_valid_json(self): json.loads(self.m.to_json(self.m.match(self.kb([self.req()]),self.evidence([self.node()]))))
 def test_55_plain_enum(self): self.assertIn('"match_status": "EXACT_SUBCLAUSE"',self.m.to_json(self.one(nodes=[self.node()])))
 def test_56_deterministic_serialization(self):
  r=self.one(nodes=[self.node()]); self.assertEqual(self.m.to_json(r),self.m.to_json(r))
 def test_57_round_trip(self):
  r=self.m.match(self.kb([self.req()]),self.evidence([self.node()])); self.assertEqual(RequirementEvidenceMatchReport.from_dict(json.loads(self.m.to_json(r))).matches[0].match_status,r.matches[0].match_status)
 # SAFETY
 def test_58_no_na_validation(self): self.assertNotIn("valid",self.m.to_json(self.one(nodes=[self.node(verdict="NA")])).casefold())
 def test_59_no_engine_result(self): self.assertNotIn("compliance",self.m.to_json(self.one(nodes=[self.node()])))
 def test_60_no_measurement_comparison(self): self.assertNotIn("comparison",self.m.to_json(self.one(nodes=[self.node()])))
 def test_61_no_gap_result(self): self.assertNotIn('"gap"',self.m.to_json(self.one()))
 def test_62_no_product_profile(self):
  import iec_par.generic_requirement_evidence_matcher as module; self.assertFalse(any("ProductProfile" in str(v) for v in vars(module).values()))
 # DIAGNOSTICS
 def test_63_no_evidence_diagnostic(self): self.one(); self.assertTrue(any(x["code"]=="MATCH_NO_REPORT_EVIDENCE" for x in self.m.get_diagnostics()))
 def test_64_parent_diagnostic(self):
  self.one(self.req("7.1.5"),[self.node("7.1",children=[self.node("7.1.1")])]); self.assertTrue(any(x["code"]=="MATCH_PARENT_FALLBACK" for x in self.m.get_diagnostics()))
 def test_65_clause_level_diagnostic(self): self.one(nodes=[self.node()]); self.assertTrue(any(x["code"]=="MATCH_CLAUSE_LEVEL_ONLY" for x in self.m.get_diagnostics()))
 def test_66_conflict_diagnostic(self):
  self.one(nodes=[self.node(items=[self.item(verdict="PASS"),self.item(eid="E2",verdict="NA")])]); self.assertTrue(any(x["code"]=="MATCH_CONFLICTING_VERDICTS" for x in self.m.get_diagnostics()))
 def test_67_save_json(self):
  r=self.m.match(self.kb([self.req()]),self.evidence([self.node()]));
  with tempfile.TemporaryDirectory() as td:self.assertTrue(self.m.save_json(r,Path(td)/"x.json").is_file())
 def test_68_unrelated_same_suffix_rejected(self): self.assertIs(self.one(self.req("9.2.3.1"),[self.node("9.4.1")]).match_status,S.NO_MATCH)
 def test_69_explicit_cross_reference_retained(self):
  node=self.node("9.4.1",raw="See clause 9.2.3.1. Distinctive leakage current measurement protection")
  self.assertEqual(self.one(self.req("9.2.3.1"),[node]).match_type,"EXPLICIT_CROSS_REFERENCE")
 def test_70_semantic_mismatch_blocks_strong_exact_assignment(self):
  requirement=self.req("8.2.6",text="Earth leakage current exceeding threshold requires redundant bonding safeguards and installation instructions")
  node=self.node("8.2.6",raw="Operator interface pushbutton colour shape location enclosure legend visibility actuation sequence")
  result=self.one(requirement,[node]);self.assertIs(result.match_status,S.NEEDS_REVIEW);self.assertEqual(result.match_confidence,"UNRESOLVED")
 def test_71_clause_scope_is_explicit(self): self.assertEqual(self.one(nodes=[self.node()]).evidence_scope,"EVIDENCE_PRESENT_AT_CLAUSE_SCOPE")


if __name__=="__main__":unittest.main(verbosity=2)
