"""Tests for source-backed generic IEC definition extraction."""

import copy
import json

from iec_par.generic_iec_definition_parser import GenericIECDefinitionParser
from iec_par.generic_iec_kb_models import DocumentType, RelationshipType, StandardDocument
from iec_par.generic_iec_structural_parser import StructuralBlock


def document(kind=DocumentType.BASE):
    return StandardDocument(kind, standard_id="base" if kind is DocumentType.BASE else "delta")


def block(raw, context="DEFINITION", page_start=4, block_id="3.1"):
    return StructuralBlock("DEFINITION_SECTION", block_id, "Definitions", 2, "3",
                           page_start, page_start + 1, raw, 0, context)


def parse(raw, kind=DocumentType.BASE, **changes):
    return GenericIECDefinitionParser().parse(document(kind), [block(raw, **changes)])


BASE = "3.1\nDefinitions relating to use\n3.1.9\nnormal operation\noperation under stated conditions\ncontinued body"


def test_01_base_definition_extraction(): assert parse(BASE)[0].clause_id == "3.1.9"
def test_02_definition_term_extraction(): assert parse(BASE)[0].term == "normal operation"
def test_03_definition_body_preservation(): assert parse(BASE)[0].definition == "operation under stated conditions\ncontinued body"
def test_04_source_page_preservation(): assert (parse(BASE)[0].source.page_start, parse(BASE)[0].source.page_end) == (4,5)
def test_05_definition_note_not_emitted_as_requirement():
    item=parse(BASE+"\nNOTE explanatory material\ncontinued note\nSubsequent definition text.")[0]
    assert "NOTE" not in item.definition and "continued note" not in item.definition
    assert "Subsequent definition text." in item.definition and not hasattr(item,"requirements")
def test_06_semantic_context_required(): assert GenericIECDefinitionParser().parse(document(), [block(BASE, context="MAIN_CLAUSE")]) == []
def test_07_annex_3x_not_main_definition(): assert GenericIECDefinitionParser().parse(document(), [block(BASE, context="ANNEX")]) == []
def test_08_part_2_replacement_definition(): assert parse("3.1.9 Replacement:\nnormal operation\nreplacement body", DocumentType.PART_2)[0].relationship_to_parent.type is RelationshipType.REPLACEMENT
def test_09_part_2_addition_definition(): assert parse("3.1.10 Addition:\nnew term\nnew body", DocumentType.PART_2)[0].relationship_to_parent.type is RelationshipType.ADDITION
def test_10_definition_relationship_preservation(): assert parse("3.1.9 Replacement:\nnormal operation\nbody", DocumentType.PART_2)[0].relationship_to_parent.parent_clause_id == "3.1.9"
def test_11_base_relationship_none(): assert parse(BASE)[0].relationship_to_parent.type is RelationshipType.NONE
def test_12_deterministic_serialization(): assert json.dumps([x.to_dict() for x in parse(BASE)],sort_keys=True) == json.dumps([x.to_dict() for x in parse(BASE)],sort_keys=True)
def test_13_no_clause_duplication(): assert len(parse(BASE+"\n3.1.9\nnormal operation\nduplicate")) == 1
def test_14_no_requirement_generation(): assert all(not hasattr(item,"requirements") for item in parse(BASE))
def test_15_inputs_not_mutated():
    item=block(BASE); before=copy.deepcopy(item); GenericIECDefinitionParser().parse(document(),[item]); assert item == before
