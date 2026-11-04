"""Tests for deterministic, provenance-preserving Effective KB construction."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iec_par.generic_iec_effective_kb_builder import GenericIECEffectiveKnowledgeBaseBuilder
from iec_par.generic_iec_effective_kb_models import (
    EffectiveBuildStatus, EffectiveSourceType, EffectiveStatus,
)
from iec_par.generic_iec_kb_models import (
    Annex, ApplicabilityRule, ApplicabilityStatus, Clause, ClauseType,
    ConstraintStatus, ConstraintType, Definition, DocumentType, KnowledgeBase,
    ParentRelationship, RelationshipType, Requirement, RequirementType,
    SourceReference, StandardDocument, StandardTable, TechnicalConstraint,
)


def doc(kind=DocumentType.BASE, **changes):
    values=dict(document_type=kind, standard_id="IEC_BASE" if kind is DocumentType.BASE else "IEC_DELTA",
                standard_number="IEC 999-1" if kind is DocumentType.BASE else "IEC 999-2-1",
                parent_standard=None if kind is DocumentType.BASE else "IEC 999-1")
    values.update(changes); return StandardDocument(**values)


def req(rid="1-R1", text="The appliance shall comply.", rtype=RequirementType.GENERAL,
        normative=True, constraint=None):
    return Requirement(rid,text,rtype,normative,ApplicabilityRule(ApplicabilityStatus.ALWAYS),
        technical_constraints=[constraint] if constraint else [])


def cl(cid="1", requirements=None, relation=RelationshipType.NONE, target=None, children=None):
    return Clause(cid,ClauseType.NORMATIVE,SourceReference(1,1,f"{cid} Heading\nsource"),
        ParentRelationship(relation,target),title="Heading",requirements=requirements or [],children=children or [])


def pair(base_clauses=None,delta_clauses=None):
    return KnowledgeBase(doc(),clauses=base_clauses or [cl(requirements=[req()])]), KnowledgeBase(
        doc(DocumentType.PART_2),clauses=delta_clauses or [cl(relation=RelationshipType.APPLICABLE,target="1")])


def walk(items):
    for item in items:
        yield item; yield from walk(item.children)


class EffectiveKBBuilderTests(unittest.TestCase):
    def setUp(self): self.builder=GenericIECEffectiveKnowledgeBaseBuilder()
    def build(self,b=None,d=None):
        if b is None or d is None: b,d=pair()
        return self.builder.build(b,d)
    def clause(self,e,cid): return next(x for x in walk(e.clauses) if x.clause_id==cid)

    # VALIDATION GATE
    def test_01_invalid_pair_rejected(self):
        b,d=pair(); d.document.parent_standard="IEC 888-1"; self.assertRaises(ValueError,self.builder.build,b,d)
    def test_02_valid_pair_accepted(self): self.assertEqual(self.build().base_standard.standard_id,"IEC_BASE")

    # BASE INITIALIZATION
    def test_03_base_clause_active(self): self.assertIs(self.clause(self.build(),"1").effective_status,EffectiveStatus.ACTIVE)
    def test_04_base_requirement_active(self): self.assertIs(self.clause(self.build(),"1").requirements[0].effective_status,EffectiveStatus.ACTIVE)
    def test_05_base_provenance(self): self.assertEqual(self.clause(self.build(),"1").base_sources[0].standard_id,"IEC_BASE")
    def test_06_base_definition_active(self):
        b,d=pair(); b.definitions=[Definition("term","body",SourceReference(),"3.1")]; self.assertIs(self.build(b,d).definitions[0].effective_status,EffectiveStatus.ACTIVE)
    def test_07_base_annex_retained(self):
        b,d=pair(); b.annexes=[Annex("A",True,SourceReference(),ApplicabilityRule(ApplicabilityStatus.ALWAYS))]; self.assertEqual(self.build(b,d).annexes[0].annex_id,"A")

    # APPLICABLE
    def test_08_applicable_base_preserved(self): self.assertEqual(self.clause(self.build(),"1").requirements[0].text,"The appliance shall comply.")
    def test_09_applicable_operation_recorded(self): self.assertEqual(self.clause(self.build(),"1").applied_operations[0].operation_type.value,"APPLICABLE")
    def test_10_applicable_no_duplicate_delta_relationship_requirement(self):
        b,d=pair(); d.clauses[0].requirements=[req("1-R9","This clause is applicable.")]; self.assertEqual(len(self.clause(self.build(b,d),"1").requirements),1)

    # APPLICABLE_EXCEPT
    def except_pair(self):
        b=KnowledgeBase(doc(),clauses=[cl("7",[req("7-R1")],children=[cl("7.1",[req("7.1-R1")])])])
        d=KnowledgeBase(doc(DocumentType.PART_2),clauses=[cl("7",relation=RelationshipType.APPLICABLE_EXCEPT,target="7",children=[cl("7.1",[req("7.1-R1","Added shall apply.")],RelationshipType.ADDITION,"7.1")])])
        return b,d
    def test_11_applicable_except_base_preserved(self): b,d=self.except_pair(); self.assertIs(self.clause(self.build(b,d),"7").effective_status,EffectiveStatus.ACTIVE)
    def test_12_applicable_except_child_operation_applied(self): b,d=self.except_pair(); self.assertEqual(len(self.clause(self.build(b,d),"7.1").requirements),2)
    def test_13_applicable_except_unrelated_child_preserved(self):
        b,d=self.except_pair(); b.clauses[0].children.append(cl("7.2",[req("7.2-R1")]))
        self.assertIs(self.clause(self.build(b,d),"7.2").effective_status,EffectiveStatus.ACTIVE)

    # ADDITION
    def addition(self):
        return pair([cl("1",[req("1-R1","Base shall apply.")])],[cl("1",[req("1-R1","Added shall apply.")],RelationshipType.ADDITION,"1")])
    def test_14_addition_base_requirement_active(self): b,d=self.addition(); self.assertIs(self.clause(self.build(b,d),"1").requirements[0].effective_status,EffectiveStatus.ACTIVE)
    def test_15_delta_addition_active(self): b,d=self.addition(); self.assertIs(self.clause(self.build(b,d),"1").requirements[1].effective_status,EffectiveStatus.ACTIVE)
    def test_16_addition_source_types_correct(self): b,d=self.addition(); self.assertEqual([r.effective_source_type for r in self.clause(self.build(b,d),"1").requirements],[EffectiveSourceType.BASE,EffectiveSourceType.PART_2_ADDITION])
    def test_17_addition_ids_collision_safe(self): b,d=self.addition(); ids=[r.effective_requirement_id for r in self.clause(self.build(b,d),"1").requirements]; self.assertEqual(len(ids),len(set(ids)))

    # REPLACEMENT
    def replacement(self,cid="1"):
        return pair([cl(cid,[req(f"{cid}-R1","Old shall apply.")])],[cl(cid,[req(f"{cid}-R1","New shall apply.")],RelationshipType.REPLACEMENT,cid)])
    def test_18_whole_replacement_base_inactive(self): b,d=self.replacement(); self.assertIs(self.clause(self.build(b,d),"1").requirements[0].effective_status,EffectiveStatus.INACTIVE)
    def test_19_replacement_active(self): b,d=self.replacement(); self.assertIs(self.clause(self.build(b,d),"1").requirements[1].effective_status,EffectiveStatus.ACTIVE)
    def test_20_superseded_by_set(self): b,d=self.replacement(); self.assertTrue(self.clause(self.build(b,d),"1").requirements[0].superseded_by)
    def test_21_supersedes_populated(self): b,d=self.replacement(); self.assertTrue(self.clause(self.build(b,d),"1").requirements[1].supersedes)
    def test_22_replacement_siblings_unaffected(self):
        b,d=self.replacement("1.1"); b.clauses=[cl("1",children=[b.clauses[0],cl("1.2",[req("1.2-R1")])])]; d.clauses=[cl("1",relation=RelationshipType.APPLICABLE_EXCEPT,target="1",children=d.clauses)]
        self.assertIs(self.clause(self.build(b,d),"1.2").requirements[0].effective_status,EffectiveStatus.ACTIVE)
    def test_23_subclause_replacement(self):
        b,d=self.replacement("1.1"); b.clauses=[cl("1",children=b.clauses)]; d.clauses=[cl("1",relation=RelationshipType.APPLICABLE_EXCEPT,target="1",children=d.clauses)]
        self.assertIs(self.clause(self.build(b,d),"1.1").requirements[0].effective_status,EffectiveStatus.INACTIVE)
    def test_24_definition_replacement(self):
        b,d=pair(); b.definitions=[Definition("term","old",SourceReference(),"3.1")]; d.definitions=[Definition("term","new",SourceReference(),"3.1",ParentRelationship(RelationshipType.REPLACEMENT,"3.1"))]
        self.assertEqual(self.build(b,d).definitions[0].definition,"new")

    # NOT APPLICABLE
    def not_applicable(self): return pair([cl("1",[req()])],[cl("1",relation=RelationshipType.NOT_APPLICABLE,target="1")])
    def test_25_not_applicable_clause_inactive(self): b,d=self.not_applicable(); self.assertIs(self.clause(self.build(b,d),"1").effective_status,EffectiveStatus.INACTIVE)
    def test_26_not_applicable_requirements_inactive(self): b,d=self.not_applicable(); self.assertIs(self.clause(self.build(b,d),"1").requirements[0].effective_status,EffectiveStatus.INACTIVE)
    def test_27_not_applicable_provenance_preserved(self): b,d=self.not_applicable(); self.assertTrue(self.clause(self.build(b,d),"1").base_sources and self.clause(self.build(b,d),"1").delta_sources)
    def test_28_active_helper_excludes_not_applicable(self): b,d=self.not_applicable(); self.assertEqual(self.builder.get_active_requirements(self.build(b,d)),[])

    # MODIFICATION
    def modification(self,ambiguous=False):
        base=[req("1-R1","Leakage current shall not exceed one unit.",RequirementType.LIMIT)]
        if ambiguous: base.append(req("1-R2","Leakage current shall not exceed one unit.",RequirementType.LIMIT))
        return pair([cl("1",base)],[cl("1",[req("1-R9","Leakage current shall not exceed two units.",RequirementType.LIMIT)],RelationshipType.MODIFICATION,"1")])
    def test_29_safe_one_to_one_modification(self): b,d=self.modification(); self.assertIs(self.clause(self.build(b,d),"1").requirements[-1].effective_status,EffectiveStatus.ACTIVE)
    def test_30_base_modified_requirement_inactive(self): b,d=self.modification(); self.assertIs(self.clause(self.build(b,d),"1").requirements[0].effective_status,EffectiveStatus.INACTIVE)
    def test_31_delta_modified_requirement_active(self): b,d=self.modification(); self.assertIs(self.clause(self.build(b,d),"1").requirements[-1].effective_source_type,EffectiveSourceType.PART_2_MODIFICATION)
    def test_32_ambiguous_mapping_needs_review(self): b,d=self.modification(True); self.assertIs(self.clause(self.build(b,d),"1").requirements[-1].effective_status,EffectiveStatus.NEEDS_REVIEW)
    def test_33_unresolved_operation_recorded(self): b,d=self.modification(True); self.assertEqual(self.build(b,d).unresolved_operations[0]["operation"],"MODIFICATION")
    def test_34_no_blind_text_merge(self): b,d=self.modification(); texts=[r.text for r in self.clause(self.build(b,d),"1").requirements]; self.assertEqual(texts,["Leakage current shall not exceed one unit.","Leakage current shall not exceed two units."])

    # DELTA-ONLY NORMATIVE
    def extension_pair(self,normative=True,with_parent=True):
        b=KnowledgeBase(doc(),clauses=[cl("20",[req("20-R1")])])
        child=cl("20.X",[req("20.X-R1",normative=normative)],RelationshipType.NONE,"20")
        roots=[cl("20",relation=RelationshipType.APPLICABLE_EXCEPT,target="20",children=[child])] if with_parent else [child]
        return b,KnowledgeBase(doc(DocumentType.PART_2),clauses=roots)
    def test_35_delta_only_no_base_match_preserved(self): b,d=self.extension_pair(); self.assertEqual(self.clause(self.build(b,d),"20.X").requirements[0].text,"The appliance shall comply.")
    def test_36_numbering_alone_not_enough(self): b,d=self.extension_pair(with_parent=False); d.clauses[0].clause_id="101"; self.assertNotIn("101",[c.clause_id for c in walk(self.build(b,d).clauses)])
    def test_37_normative_structural_context_required(self): b,d=self.extension_pair(normative=False); self.assertNotIn("20.X",[c.clause_id for c in walk(self.build(b,d).clauses)])
    def test_38_deterministic_parent_placement(self): b,d=self.extension_pair(); self.assertIn("20.X",[c.clause_id for c in self.clause(self.build(b,d),"20").children])

    # DEFINITIONS
    def definition_pair(self):
        b,d=pair(); b.definitions=[Definition("normal","old",SourceReference(),"3.1")]; d.definitions=[Definition("normal","new",SourceReference(),"3.1",ParentRelationship(RelationshipType.REPLACEMENT,"3.1"))]; return b,d
    def test_39_base_definition_retained(self): b,d=pair(); b.definitions=[Definition("term","body",SourceReference(),"3.1")]; self.assertEqual(self.build(b,d).definitions[0].term,"term")
    def test_40_part_2_definition_replacement_active(self): b,d=self.definition_pair(); self.assertIs(self.build(b,d).definitions[0].effective_status,EffectiveStatus.ACTIVE)
    def test_41_old_definition_source_traceable(self): b,d=self.definition_pair(); self.assertTrue(self.build(b,d).definitions[0].supersedes)
    def test_42_definition_id_deterministic(self): b,d=self.definition_pair(); self.assertEqual(self.build(b,d).definitions[0].effective_definition_id,self.build(b,d).definitions[0].effective_definition_id)

    # ANNEX
    def test_43_base_annex_retained_again(self): b,d=pair(); b.annexes=[Annex("A",True,SourceReference(),ApplicabilityRule(ApplicabilityStatus.ALWAYS))]; self.assertEqual(len(self.build(b,d).annexes),1)
    def test_44_part_2_normative_annex_added(self): b,d=pair(); d.annexes=[Annex("CC",True,SourceReference(),ApplicabilityRule(ApplicabilityStatus.ALWAYS),requirements=[req("22.201-R1")])]; self.assertEqual(self.build(b,d).annexes[-1].annex_id,"CC")
    def test_45_annex_cc_stays_annex(self): b,d=pair(); d.annexes=[Annex("CC",True,SourceReference(),ApplicabilityRule(ApplicabilityStatus.ALWAYS),requirements=[req("22.201-R1")])]; self.assertNotIn("22.201",[c.clause_id for c in walk(self.build(b,d).clauses)])
    def test_46_no_annex_main_duplication(self): b,d=pair(); d.annexes=[Annex("CC",True,SourceReference(),ApplicabilityRule(ApplicabilityStatus.ALWAYS),requirements=[req("22.201-R1")])]; e=self.build(b,d); self.assertEqual(sum(r.effective_source_type is EffectiveSourceType.PART_2_NEW_REQUIREMENT for a in e.annexes for r in a.requirements),1)

    # TABLES
    def test_47_base_table_retained(self): b,d=pair(); b.tables=[StandardTable("1",SourceReference())]; self.assertEqual(self.build(b,d).tables[0].table_id,"1")
    def test_48_unique_delta_table_added(self): b,d=pair(); d.tables=[StandardTable("2",SourceReference())]; self.assertEqual(self.build(b,d).tables[-1].table_id,"2")

    # IDS
    def test_49_deterministic_clause_ids(self): self.assertEqual(self.clause(self.build(),"1").effective_clause_id,"E-C-MAIN-1")
    def test_50_deterministic_requirement_ids(self): self.assertEqual(self.clause(self.build(),"1").requirements[0].effective_requirement_id,"E-R-MAIN-1-1_R1-BASE")
    def test_51_global_collision_safety(self): b,d=self.addition(); e=self.build(b,d); ids=[r.effective_requirement_id for c in walk(e.clauses) for r in c.requirements]; self.assertEqual(len(ids),len(set(ids)))
    def test_52_repeat_build_identical_ids(self): b,d=self.addition(); self.assertEqual([r.effective_requirement_id for r in self.clause(self.build(b,d),"1").requirements],[r.effective_requirement_id for r in self.clause(self.build(b,d),"1").requirements])

    # IMMUTABILITY
    def test_53_base_object_unchanged(self): b,d=self.addition(); before=copy.deepcopy(b.to_dict()); self.build(b,d); self.assertEqual(before,b.to_dict())
    def test_54_delta_object_unchanged(self): b,d=self.addition(); before=copy.deepcopy(d.to_dict()); self.build(b,d); self.assertEqual(before,d.to_dict())

    # TECHNICAL
    def technical_pair(self,expression=None):
        kind = ConstraintType.FORMULA if expression and "formula" in expression else ConstraintType.COMPOUND if expression else ConstraintType.VOLTAGE_LIMIT
        c=TechnicalConstraint("1-R1-C1",parameter="x",operator="less_than",value=2,unit="V",expression=expression,
            constraint_type=kind,
            status=ConstraintStatus.RESOLVED,source_requirement_id="1-R1")
        return pair([cl("1",[req(constraint=c)])],[cl("1",relation=RelationshipType.APPLICABLE,target="1")])
    def test_55_applicability_deep_copied(self): b,d=self.technical_pair(); e=self.build(b,d); e.clauses[0].requirements[0].applicability.condition_text="x"; self.assertIsNone(b.clauses[0].requirements[0].applicability.condition_text)
    def test_56_constraints_deep_copied(self): b,d=self.technical_pair(); e=self.build(b,d); e.clauses[0].requirements[0].technical_constraints[0].value=9; self.assertEqual(b.clauses[0].requirements[0].technical_constraints[0].value,2)
    def test_57_formula_preserved(self): b,d=self.technical_pair({"formula":"x*2"}); self.assertEqual(self.clause(self.build(b,d),"1").requirements[0].technical_constraints[0].expression,{"formula":"x*2"})
    def test_58_compound_any_all_preserved(self): expr={"any":[{"all":[{"field":"x","operator":"equals","value":1}]}]}; b,d=self.technical_pair(expr); self.assertEqual(self.clause(self.build(b,d),"1").requirements[0].technical_constraints[0].expression,expr)

    # SERIALIZATION
    def test_59_valid_json(self): self.assertEqual(json.loads(self.builder.to_json(self.build()))["build_status"],"VALID")
    def test_60_enum_values_clean(self): self.assertNotIn("EffectiveStatus.",self.builder.to_json(self.build()))
    def test_61_deterministic_json(self): b,d=self.addition(); self.assertEqual(self.builder.to_json(self.build(b,d)),self.builder.to_json(self.build(b,d)))
    def test_62_save_and_reload_json(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.builder.save_json(self.build(),Path(td)/"e.json"); self.assertEqual(json.loads(p.read_text())["effective_kb_id"],"IEC_BASE__IEC_DELTA")

    # ACTIVE SET
    def test_63_only_active_returned(self): b,d=self.not_applicable(); self.assertEqual(self.builder.get_active_requirements(self.build(b,d)),[])
    def test_64_needs_review_excluded_by_default(self): b,d=self.modification(True); self.assertNotIn(EffectiveStatus.NEEDS_REVIEW,[r.effective_status for r in self.builder.get_active_requirements(self.build(b,d))])
    def test_65_optional_include_review(self): b,d=self.modification(True); self.assertIn(EffectiveStatus.NEEDS_REVIEW,[r.effective_status for r in self.builder.get_active_requirements(self.build(b,d),True)])

    # BUILD STATUS
    def test_66_valid_without_unresolved(self): self.assertIs(self.build().build_status,EffectiveBuildStatus.VALID)
    def test_67_needs_review_with_ambiguous_modification(self): b,d=self.modification(True); self.assertIs(self.build(b,d).build_status,EffectiveBuildStatus.NEEDS_REVIEW)

    # NO EVALUATION
    def test_68_no_pass_generation(self): self.assertNotIn('"PASS"',self.builder.to_json(self.build()))
    def test_69_no_fail_generation(self): self.assertNotIn('"FAIL"',self.builder.to_json(self.build()))
    def test_70_no_na_result_generation(self): self.assertNotIn('"N/A"',self.builder.to_json(self.build()))


if __name__ == "__main__": unittest.main(verbosity=2)
