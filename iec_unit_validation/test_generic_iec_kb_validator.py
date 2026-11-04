"""Direct and pytest-compatible tests for the generic IEC KB validator."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iec_par.generic_iec_feature_registry import CanonicalProductFeatureRegistry
from iec_par.generic_iec_kb_models import (
    Annex, ApplicabilityRule, ApplicabilityStatus, Clause, ClauseType,
    ConstraintStatus, ConstraintType, Definition, DocumentType, KnowledgeBase,
    ParentRelationship, RelationshipType, Requirement, RequirementType,
    SourceReference, StandardDocument, StandardTable, TechnicalConstraint,
)
from iec_par.generic_iec_kb_validator import (
    GenericIECKnowledgeBaseValidator, ReconciliationClassification,
    ValidationSeverity,
)


def document(kind=DocumentType.BASE, **changes):
    values = dict(document_type=kind, standard_id="IEC 99999-1:2020",
                  standard_number="IEC 99999-1", title="Example", edition="1.0", year=2020,
                  parent_standard="IEC 99999-1" if kind is DocumentType.PART_2 else None)
    values.update(changes)
    return StandardDocument(**values)


def applicability(status=ApplicabilityStatus.ALWAYS, condition_text=None, logic=None):
    return ApplicabilityRule(status=status, condition_text=condition_text, logic=logic)


def requirement(rid="1-R1", text="The appliance shall be safe.", app=None, constraints=None):
    return Requirement(rid, text, RequirementType.SAFETY, True, app or applicability(),
                       technical_constraints=constraints or [])


def clause(cid="1", requirements=None, children=None, relationship=RelationshipType.NONE,
           parent=None, raw="1 Scope\nThe appliance shall be safe.", page_start=1, page_end=1):
    return Clause(cid, ClauseType.NORMATIVE, SourceReference(page_start, page_end, raw),
                  ParentRelationship(relationship, parent), title="Scope",
                  requirements=requirements or [], children=children or [])


def kb(kind=DocumentType.BASE, clauses=None, **doc_changes):
    return KnowledgeBase(document(kind, **doc_changes), clauses=clauses or [clause()])


def valid_simple(rid="1-R1", cid="1-R1-C1"):
    return TechnicalConstraint(cid, parameter="voltage", operator="less_than_or_equal",
                               value=250, unit="V", raw_text="not exceeding 250 V",
                               constraint_type=ConstraintType.VOLTAGE_LIMIT,
                               status=ConstraintStatus.RESOLVED, source_requirement_id=rid)


class GenericIECKnowledgeBaseValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = GenericIECKnowledgeBaseValidator(CanonicalProductFeatureRegistry())

    def codes(self, report):
        return [item.code for item in report.findings]

    # DOCUMENT
    def test_01_valid_base_metadata(self):
        self.assertTrue(self.validator.validate(kb()).valid)

    def test_02_missing_standard_id(self):
        self.assertIn("KB_STANDARD_ID_MISSING", self.codes(self.validator.validate(kb(standard_id=None))))

    def test_03_part_2_missing_parent(self):
        self.assertIn("KB_PARENT_STANDARD_MISSING", self.codes(
            self.validator.validate(kb(DocumentType.PART_2, parent_standard=None))))

    def test_04_wrong_document_type(self):
        self.assertIn("KB_DOCUMENT_TYPE_UNSUPPORTED", self.codes(
            self.validator.validate(kb(DocumentType.OTHER))))

    # STRUCTURE
    def test_05_duplicate_clause(self):
        self.assertIn("CLAUSE_DUPLICATE", self.codes(self.validator.validate(kb(clauses=[clause(), clause()]))))

    def test_06_duplicate_child(self):
        root = clause(children=[clause("1.1"), clause("1.1")])
        self.assertIn("CLAUSE_DUPLICATE_CHILD", self.codes(self.validator.validate(kb(clauses=[root]))))

    def test_07_invalid_page_range(self):
        self.assertIn("CLAUSE_INVALID_PAGE_RANGE", self.codes(
            self.validator.validate(kb(clauses=[clause(page_start=3, page_end=2)]))))

    def test_08_missing_raw_text(self):
        self.assertIn("CLAUSE_SOURCE_EMPTY", self.codes(
            self.validator.validate(kb(clauses=[clause(raw="")]))))

    def test_09_circular_hierarchy(self):
        root = clause(); root.children.append(root)
        self.assertIn("CLAUSE_SELF_CHILD", self.codes(self.validator.validate(kb(clauses=[root]))))

    # REQUIREMENTS
    def test_10_missing_requirement_id(self):
        self.assertIn("REQ_ID_MISSING", self.codes(self.validator.validate(
            kb(clauses=[clause(requirements=[requirement("")])]))))

    def test_11_duplicate_requirement_id(self):
        self.assertIn("REQ_DUPLICATE", self.codes(self.validator.validate(
            kb(clauses=[clause(requirements=[requirement(), requirement()])]))))

    def test_12_empty_requirement_text(self):
        self.assertIn("REQ_TEXT_EMPTY", self.codes(self.validator.validate(
            kb(clauses=[clause(requirements=[requirement(text="")])]))))

    # APPLICABILITY
    def test_13_always_valid(self):
        self.assertNotIn("APP_ALWAYS_HAS_LOGIC", self.codes(self.validator.validate(
            kb(clauses=[clause(requirements=[requirement()])]))))

    def test_14_always_with_logic(self):
        app = applicability(logic={"field": "has_wheels", "operator": "equals", "value": True})
        self.assertIn("APP_ALWAYS_HAS_LOGIC", self.codes(self.validator.validate(
            kb(clauses=[clause(requirements=[requirement(app=app)])]))))

    def test_15_resolved_without_logic(self):
        app = applicability(ApplicabilityStatus.RESOLVED, "For wheeled appliances")
        self.assertIn("APP_RESOLVED_WITHOUT_LOGIC", self.codes(self.validator.validate(
            kb(clauses=[clause(requirements=[requirement(app=app)])]))))

    def test_16_resolved_valid_logic(self):
        feature = next(f for f in self.validator.feature_registry.get_all() if f.data_type.value == "BOOLEAN")
        app = applicability(ApplicabilityStatus.RESOLVED, "When applicable",
                            {"field": feature.key, "operator": "equals", "value": True})
        self.assertTrue(self.validator.validate(kb(clauses=[clause(requirements=[requirement(app=app)])])).valid)

    def test_17_unknown_feature(self):
        app = applicability(ApplicabilityStatus.RESOLVED, "When applicable",
                            {"field": "feature_that_does_not_exist", "operator": "equals", "value": True})
        self.assertIn("APP_UNKNOWN_FEATURE", self.codes(self.validator.validate(
            kb(clauses=[clause(requirements=[requirement(app=app)])]))))

    def test_18_invalid_enum(self):
        feature = next(f for f in self.validator.feature_registry.get_all() if f.data_type.value == "ENUM")
        app = applicability(ApplicabilityStatus.RESOLVED, "When applicable",
                            {"field": feature.key, "operator": "equals", "value": "NOT_ALLOWED"})
        self.assertIn("APP_INVALID_ENUM_VALUE", self.codes(self.validator.validate(
            kb(clauses=[clause(requirements=[requirement(app=app)])]))))

    def test_19_unknown_operator(self):
        feature = self.validator.feature_registry.get_all()[0]
        app = applicability(ApplicabilityStatus.RESOLVED, "When applicable",
                            {"field": feature.key, "operator": "approximately", "value": True})
        self.assertIn("APP_INVALID_OPERATOR", self.codes(self.validator.validate(
            kb(clauses=[clause(requirements=[requirement(app=app)])]))))

    def test_20_empty_all(self):
        app = applicability(ApplicabilityStatus.RESOLVED, "When applicable", {"all": []})
        self.assertIn("APP_EMPTY_ALL", self.codes(self.validator.validate(
            kb(clauses=[clause(requirements=[requirement(app=app)])]))))

    def test_21_empty_any(self):
        app = applicability(ApplicabilityStatus.RESOLVED, "When applicable", {"any": []})
        self.assertIn("APP_EMPTY_ANY", self.codes(self.validator.validate(
            kb(clauses=[clause(requirements=[requirement(app=app)])]))))

    def test_22_invalid_not(self):
        app = applicability(ApplicabilityStatus.RESOLVED, "When applicable", {"not": []})
        self.assertIn("APP_PARTIAL_LOGIC", self.codes(self.validator.validate(
            kb(clauses=[clause(requirements=[requirement(app=app)])]))))

    def test_23_partial_logic_node(self):
        app = applicability(ApplicabilityStatus.RESOLVED, "When applicable", {"operator": "equals"})
        self.assertIn("APP_PARTIAL_LOGIC", self.codes(self.validator.validate(
            kb(clauses=[clause(requirements=[requirement(app=app)])]))))

    # CONSTRAINTS
    def report_for_constraint(self, item):
        req = requirement(constraints=[item])
        return self.validator.validate(kb(clauses=[clause(requirements=[req])]))

    def test_24_valid_simple(self):
        self.assertTrue(self.report_for_constraint(valid_simple()).valid)

    def test_25_missing_source_requirement(self):
        item = valid_simple(); item.source_requirement_id = None
        self.assertIn("CONSTRAINT_SOURCE_MISMATCH", self.codes(self.report_for_constraint(item)))

    def test_26_duplicate_constraint_id(self):
        req = requirement(constraints=[valid_simple(), valid_simple()])
        self.assertIn("CONSTRAINT_DUPLICATE", self.codes(self.validator.validate(
            kb(clauses=[clause(requirements=[req])]))))

    def test_27_resolved_simple_missing_value(self):
        item = valid_simple(); item.value = None
        self.assertIn("CONSTRAINT_RESOLVED_INCOMPLETE", self.codes(self.report_for_constraint(item)))

    def test_28_valid_range(self):
        item = TechnicalConstraint("1-R1-C1", "temperature", operator="between", value=1,
            value_secondary=5, unit="°C", raw_text="1 °C to 5 °C", constraint_type=ConstraintType.RANGE,
            status=ConstraintStatus.RESOLVED, source_requirement_id="1-R1")
        self.assertTrue(self.report_for_constraint(item).valid)

    def test_29_invalid_range(self):
        item = TechnicalConstraint("1-R1-C1", "temperature", operator="between", value=5,
            value_secondary=1, unit="°C", raw_text="5 °C to 1 °C", constraint_type=ConstraintType.RANGE,
            status=ConstraintStatus.RESOLVED, source_requirement_id="1-R1")
        self.assertIn("CONSTRAINT_RESOLVED_INCOMPLETE", self.codes(self.report_for_constraint(item)))

    def test_30_valid_formula(self):
        item = TechnicalConstraint("1-R1-C1", expression={"selection": "MAX", "operands": [
            {"type": "CONSTANT", "value": 1, "unit": "mA"}]}, raw_text="maximum 1 mA",
            constraint_type=ConstraintType.FORMULA, status=ConstraintStatus.RESOLVED,
            source_requirement_id="1-R1")
        self.assertTrue(self.report_for_constraint(item).valid)

    def test_31_incomplete_formula(self):
        item = TechnicalConstraint("1-R1-C1", expression={"operands": []}, raw_text="formula",
            constraint_type=ConstraintType.FORMULA, status=ConstraintStatus.RESOLVED,
            source_requirement_id="1-R1")
        self.assertIn("CONSTRAINT_INVALID_FORMULA", self.codes(self.report_for_constraint(item)))

    def test_32_valid_compound_any_all(self):
        expression = {"any": [{"field": "x", "operator": "greater_than", "value": 1},
                              {"all": [{"parameter": "y", "operator": "equals", "value": 2}]}]}
        item = TechnicalConstraint("1-R1-C1", expression=expression, raw_text="compound",
            constraint_type=ConstraintType.COMPOUND, status=ConstraintStatus.RESOLVED,
            source_requirement_id="1-R1")
        self.assertTrue(self.report_for_constraint(item).valid)

    def test_33_empty_compound_branch(self):
        item = TechnicalConstraint("1-R1-C1", expression={"any": []}, raw_text="compound",
            constraint_type=ConstraintType.COMPOUND, status=ConstraintStatus.RESOLVED,
            source_requirement_id="1-R1")
        self.assertIn("CONSTRAINT_INVALID_COMPOUND", self.codes(self.report_for_constraint(item)))

    def test_34_valid_test_parameter(self):
        item = TechnicalConstraint("1-R1-C1", "test duration", value=10, unit="s", raw_text="10 s",
            constraint_type=ConstraintType.TEST_PARAMETER, status=ConstraintStatus.RESOLVED,
            source_requirement_id="1-R1")
        self.assertTrue(self.report_for_constraint(item).valid)

    # RELATIONSHIPS
    def test_35_base_non_none_relationship_error(self):
        self.assertIn("REL_BASE_NON_NONE", self.codes(self.validator.validate(
            kb(clauses=[clause(relationship=RelationshipType.ADDITION, parent="1")]))))

    def assert_valid_part2_relationship(self, rel):
        item = clause(relationship=rel, parent="1")
        report = self.validator.validate(kb(DocumentType.PART_2, clauses=[item]))
        self.assertNotIn("REL_TARGET_MISSING", self.codes(report))

    def test_36_valid_part_2_addition(self): self.assert_valid_part2_relationship(RelationshipType.ADDITION)
    def test_37_valid_modification(self): self.assert_valid_part2_relationship(RelationshipType.MODIFICATION)
    def test_38_valid_replacement(self): self.assert_valid_part2_relationship(RelationshipType.REPLACEMENT)
    def test_39_valid_not_applicable(self): self.assert_valid_part2_relationship(RelationshipType.NOT_APPLICABLE)

    # PAIR
    def pair(self, delta_clause=None, parent="IEC 99999-1"):
        base = kb(clauses=[clause("1")])
        delta = kb(DocumentType.PART_2, clauses=[delta_clause or clause("1")], parent_standard=parent,
                   standard_id="IEC 99999-2:2020")
        return base, delta

    def test_40_valid_base_delta_family(self):
        base, delta = self.pair()
        self.assertNotIn("REL_PARENT_STANDARD_MISMATCH", self.codes(self.validator.validate_pair(base, delta)))

    def test_41_wrong_parent_standard(self):
        base, delta = self.pair(parent="IEC 88888-1")
        self.assertIn("REL_PARENT_STANDARD_MISMATCH", self.codes(self.validator.validate_pair(base, delta)))

    def test_42_valid_target_exists(self):
        base, delta = self.pair(clause("1", relationship=RelationshipType.ADDITION, parent="1"))
        self.assertNotIn("REL_TARGET_MISSING", self.codes(self.validator.validate_pair(base, delta)))

    def test_43_target_missing_requires_review(self):
        base, delta = self.pair(clause("2", relationship=RelationshipType.ADDITION, parent="2"))
        report = self.validator.validate_pair(base, delta)
        self.assertTrue(any(x.code == "REL_TARGET_MISSING" and x.severity is ValidationSeverity.REVIEW_REQUIRED
                            for x in report.findings))

    def test_44_new_requirement_without_exact_target_allowed(self):
        base, delta = self.pair(clause("101", relationship=RelationshipType.NEW_REQUIREMENT))
        self.assertNotIn("REL_TARGET_MISSING", self.codes(self.validator.validate_pair(base, delta)))

    # ANNEX / TABLE
    def test_45_duplicate_annex(self):
        item = Annex("A", False, SourceReference(2, 2, "Annex A"), applicability())
        artifact = kb(); artifact.annexes = [item, deepcopy(item)]
        self.assertIn("ANNEX_DUPLICATE", self.codes(self.validator.validate(artifact)))

    def test_46_duplicate_table(self):
        item = StandardTable("1", SourceReference(2, 2, "Table 1"))
        artifact = kb(); artifact.tables = [item, deepcopy(item)]
        self.assertIn("TABLE_DUPLICATE", self.codes(self.validator.validate(artifact)))

    def test_47_annex_main_duplication(self):
        req = requirement(); artifact = kb(clauses=[clause(requirements=[req])])
        artifact.annexes = [Annex("A", False, SourceReference(2, 2, "Annex A"), applicability(),
                                   requirements=[deepcopy(req)])]
        self.assertIn("ANNEX_CONTENT_DUPLICATED", self.codes(self.validator.validate(artifact)))

    # SERIALIZATION
    def test_48_enum_artifact_detection(self):
        payload = kb().to_dict(); payload["document"]["document_type"] = "DocumentType.BASE"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "kb.json"; path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertIn("JSON_ENUM_ARTIFACT", self.codes(self.validator.validate_json(path)))

    def test_49_valid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "kb.json"; path.write_text(kb().to_json(), encoding="utf-8")
            self.assertTrue(self.validator.validate_json(path).valid)

    def test_50_deterministic_representation(self):
        first = kb(); second = deepcopy(first)
        self.assertTrue(self.validator.compare_deterministic(first, second))

    # RECONCILIATION
    def test_51_preserved_main_relationship(self):
        artifact = kb(DocumentType.PART_2, clauses=[clause("1", relationship=RelationshipType.ADDITION, parent="1")])
        result = self.validator.reconcile_pipeline([
            {"clause_id": "1", "relationship_type": "ADDITION", "parent_clause_id": "1",
             "semantic_context": "MAIN_CLAUSE"}], artifact)
        self.assertEqual(ReconciliationClassification.PRESERVED_MAIN, result[0].classification)

    def test_52_preserved_annex_relationship(self):
        artifact = kb(DocumentType.PART_2); artifact.annexes = [Annex(
            "A", False, SourceReference(2, 2, "Annex A"), applicability(),
            requirements=[requirement("A.1-R1")])]
        result = self.validator.reconcile_pipeline([
            {"clause_id": "A.1", "relationship_type": "ADDITION", "parent_clause_id": "A.1",
             "semantic_context": "ANNEX"}], artifact)
        self.assertEqual(ReconciliationClassification.PRESERVED_ANNEX, result[0].classification)

    def test_53_missing_relationship_occurrence(self):
        artifact = kb(DocumentType.PART_2)
        result = self.validator.reconcile_pipeline([
            {"clause_id": "99", "relationship_type": "REPLACEMENT", "parent_clause_id": "99",
             "semantic_context": "MAIN_CLAUSE"}], artifact)
        self.assertEqual(ReconciliationClassification.MISSING_ERROR, result[0].classification)

    def test_54_duplicate_definition_id(self):
        item = Definition("term", "body", SourceReference(2, 2, "raw"), "3.1")
        artifact = kb(); artifact.definitions = [item, deepcopy(item)]
        self.assertIn("DEF_DUPLICATE", self.codes(self.validator.validate(artifact)))

    def test_55_empty_definition_term(self):
        artifact = kb(); artifact.definitions = [Definition("", "body", SourceReference(), "3.1")]
        self.assertIn("DEF_TERM_EMPTY", self.codes(self.validator.validate(artifact)))

    def test_56_empty_definition_body(self):
        artifact = kb(); artifact.definitions = [Definition("term", "", SourceReference(), "3.1")]
        self.assertIn("DEF_BODY_EMPTY", self.codes(self.validator.validate(artifact)))

    def test_57_base_definition_relationship_none(self):
        artifact = kb(); artifact.definitions = [Definition("term", "body", SourceReference(), "3.1")]
        self.assertNotIn("DEF_BASE_NON_NONE", self.codes(self.validator.validate(artifact)))

    def test_58_base_definition_non_none_rejected(self):
        artifact = kb(); artifact.definitions = [Definition(
            "term", "body", SourceReference(), "3.1",
            ParentRelationship(RelationshipType.REPLACEMENT, "3.1"))]
        self.assertIn("DEF_BASE_NON_NONE", self.codes(self.validator.validate(artifact)))

    def test_59_pair_definition_target_compatible(self):
        base, delta = self.pair(); base.definitions = [Definition("term", "base", SourceReference(), "3.1")]
        delta.definitions = [Definition("term", "delta", SourceReference(), "3.1",
            ParentRelationship(RelationshipType.REPLACEMENT, "3.1"))]
        self.assertNotIn("DEF_TARGET_MISSING", self.codes(self.validator.validate_pair(base, delta)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
