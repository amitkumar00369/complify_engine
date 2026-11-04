"""Schema tests for future effective IEC knowledge bases."""

import copy
import json

from iec_par.generic_iec_effective_kb_models import (
    EffectiveAnnex, EffectiveBuildStatus, EffectiveClause, EffectiveDefinition,
    EffectiveKnowledgeBase, EffectiveOperation, EffectiveOperationType,
    EffectiveRequirement, EffectiveSourceReference,
    EffectiveSourceType, EffectiveStatus,
)
from iec_par.generic_iec_kb_models import (
    ApplicabilityRule, ApplicabilityStatus, DocumentType, RequirementType,
    StandardDocument, TechnicalConstraint,
)


def source(**changes):
    values = {"standard_id": "base", "clause_id": "7.1", "requirement_id": "7.1-R1"}
    values.update(changes)
    return EffectiveSourceReference(**values)


def requirement(eid="E-R-7.1-BASE-R1", status=EffectiveStatus.ACTIVE,
                source_type=EffectiveSourceType.BASE):
    return EffectiveRequirement(eid, "7.1", "The appliance shall comply.",
        RequirementType.GENERAL, True, ApplicabilityRule(ApplicabilityStatus.ALWAYS),
        status, source_type)


def artifact():
    base = StandardDocument(DocumentType.BASE, standard_id="base", standard_number="IEC 1-1")
    delta = StandardDocument(DocumentType.PART_2, standard_id="delta",
                             standard_number="IEC 1-2-1", parent_standard="IEC 1-1")
    return EffectiveKnowledgeBase("1.0", "E-base--delta", base, delta,
                                  EffectiveBuildStatus.VALID)


def test_01_effective_status_serialization(): assert EffectiveStatus.INACTIVE.value == "INACTIVE"
def test_02_effective_source_type_serialization(): assert EffectiveSourceType.PART_2_ADDITION.value == "PART_2_ADDITION"
def test_03_base_provenance():
    item=requirement(); item.base_sources.append(source()); assert item.base_sources[0].standard_id == "base"
def test_04_delta_provenance():
    item=requirement(source_type=EffectiveSourceType.PART_2_ADDITION); item.delta_sources.append(source(standard_id="delta")); assert item.delta_sources[0].standard_id == "delta"
def test_05_supersedes():
    item=requirement(source_type=EffectiveSourceType.PART_2_REPLACEMENT); item.supersedes.append(source()); assert item.supersedes[0].requirement_id == "7.1-R1"
def test_06_inactive_requirement(): assert requirement(status=EffectiveStatus.INACTIVE).effective_status is EffectiveStatus.INACTIVE
def test_07_inactive_clause(): assert EffectiveClause("E-C-9", "9", EffectiveStatus.INACTIVE).effective_status is EffectiveStatus.INACTIVE
def test_08_deterministic_ids(): assert requirement().effective_requirement_id == copy.deepcopy(requirement()).effective_requirement_id
def test_09_collision_safe_base_and_addition_ids(): assert "BASE" in requirement().effective_requirement_id and requirement().effective_requirement_id != requirement("E-R-7.1-P2-ADD-R1").effective_requirement_id
def test_10_effective_definition(): assert EffectiveDefinition("E-D-3.1.9", "normal operation", "body", "3.1.9", EffectiveStatus.ACTIVE, EffectiveSourceType.BASE).clause_id == "3.1.9"
def test_11_effective_annex(): assert EffectiveAnnex("E-A-A", "A", True, EffectiveStatus.ACTIVE).normative
def test_12_full_effective_kb_serialization(): assert json.loads(artifact().to_json())["build_status"] == "VALID"
def test_13_mutable_default_isolation():
    first=artifact(); second=artifact(); first.clauses.append(EffectiveClause("E-C-1","1",EffectiveStatus.ACTIVE)); assert second.clauses == []
def test_14_no_source_object_mutation():
    original=TechnicalConstraint("x"); app=ApplicabilityRule(ApplicabilityStatus.ALWAYS)
    item=EffectiveRequirement("E-R-1-BASE-R1","1","text",RequirementType.GENERAL,True,
        app,EffectiveStatus.ACTIVE,EffectiveSourceType.BASE,technical_constraints=[original])
    item.technical_constraints[0].notes="effective"; item.applicability.condition_text="effective"
    assert original.notes is None and app.condition_text is None
def test_15_effective_operation_serialization(): assert EffectiveOperation(EffectiveOperationType.REPLACEMENT).to_dict()["operation_type"] == "REPLACEMENT"
