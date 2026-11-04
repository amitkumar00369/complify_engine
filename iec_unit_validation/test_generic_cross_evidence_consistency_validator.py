"""Step 31E unit tests for conservative cross-evidence comparisons."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iec_par.generic_cross_evidence_consistency_models import (
    ConsistencyFindingType as FindingType,
    ConsistencyStatus as Status,
    CrossEvidenceConsistencyResult,
)
from iec_par.generic_cross_evidence_consistency_validator import (
    GenericCrossEvidenceConsistencyValidator,
)


def identity(value, role, number):
    return {
        "identity_id": f"identity-{number}", "identity_type": "MODEL", "role": role,
        "value": value, "normalized_value": value, "source_evidence_ids": [f"identity-evidence-{number}"],
        "evidence": [{"evidence_id": f"identity-evidence-{number}", "page": number}],
    }


def profile(*identities, rated_voltage=None):
    facts = {}
    if rated_voltage is not None:
        facts["rated_voltage"] = {"fact_id": "fact-voltage", "value": rated_voltage,
                                  "evidence": [{"evidence_id": "rating-evidence"}]}
    return {"identity": {"product_identities": list(identities)}, "facts": facts}


def report(text="", clause_id="1", verdict="NOT_STATED", measurements=None):
    return {"clauses": [{"clause_id": clause_id, "evidence_items": [{
        "evidence_id": "report-evidence", "clause_id": clause_id,
        "reported_verdict": verdict, "raw_text": text,
        "measurements": measurements or [], "page_start": 2,
    }]}]}


class CrossEvidenceConsistencyValidatorTests(unittest.TestCase):
    def setUp(self):
        self.validator = GenericCrossEvidenceConsistencyValidator()

    def identity_result(self, declared="A", tested="B", text="", tested_role="TESTED_MODEL"):
        result = self.validator.validate({}, profile(identity(declared, "DECLARED_MODEL", 1),
                                                      identity(tested, tested_role, 2)), {}, report(text))
        return result.findings

    def test_same_declared_and_tested_model_is_consistent(self):
        self.assertEqual(self.identity_result("A", "A")[0].status, Status.CONSISTENT)

    def test_explicit_equivalence_reconciles_different_models(self):
        finding = self.identity_result(text="A and B are equivalent representative variants.")[0]
        self.assertEqual(finding.status, Status.RECONCILED)

    def test_different_models_without_relationship_are_unresolved(self):
        finding = self.identity_result()[0]
        self.assertEqual((finding.finding_type, finding.status),
                         (FindingType.IDENTITY_RELATIONSHIP_UNRESOLVED, Status.UNRESOLVED))

    def test_explicit_contradictory_ownership_is_material(self):
        finding = self.identity_result(text="A was not tested. B is the only model tested.")[0]
        self.assertEqual(finding.status, Status.MATERIAL_CONFLICT)

    def test_unknown_identity_role_is_not_forced_comparable(self):
        self.assertEqual(self.identity_result(tested_role="UNKNOWN"), [])

    def test_identity_provenance_is_complete(self):
        finding = self.identity_result()[0]
        self.assertEqual(finding.product_identity_ids, ["identity-1", "identity-2"])
        self.assertEqual(finding.evidence_ids, ["identity-evidence-1", "identity-evidence-2"])
        self.assertTrue(all(item.page_refs for item in finding.observations))

    def test_same_parameter_same_value_is_consistent(self):
        status, _ = self.validator.compare_values(5, 5, same_parameter=True, same_scope=True)
        self.assertEqual(status, Status.CONSISTENT)

    def test_same_parameter_different_value_without_gates_is_unresolved(self):
        status, _ = self.validator.compare_values(5, 6, same_parameter=True)
        self.assertEqual(status, Status.UNRESOLVED)

    def test_all_material_value_gates_are_required(self):
        status, gates = self.validator.compare_values(5, 6, same_parameter=True, same_scope=True,
            same_context=True, reliable=True, material_rule="explicit", affects_validity=True)
        self.assertEqual(status, Status.MATERIAL_CONFLICT)
        self.assertTrue(all(gates.values()))

    def test_reconciliation_prevents_material_value_conflict(self):
        status, _ = self.validator.compare_values(5, 6, same_parameter=True, same_scope=True,
            same_context=True, reliable=True, material_rule="explicit", reconciliation="supported",
            affects_validity=True)
        self.assertEqual(status, Status.RECONCILED)

    def test_different_parameter_same_unit_is_not_comparable(self):
        result = self.validator.validate({}, profile(rated_voltage=230), {}, report(measurements=[
            {"measurement_id": "m", "parameter": "dielectric_test_voltage", "value": 1250, "unit": "V"}]))
        self.assertEqual(result.findings[0].status, Status.NOT_COMPARABLE)
        self.assertFalse(result.findings[0].comparison["same_parameter"])

    def test_rated_voltage_measurement_can_be_semantically_identified(self):
        result = self.validator.validate({}, profile(rated_voltage=230), {}, report(measurements=[
            {"measurement_id": "m", "parameter": "rated_voltage", "value": 230, "unit": "V"}]))
        self.assertFalse(any(x.finding_type == FindingType.UNIT_OR_PARAMETER_AMBIGUITY for x in result.findings))

    def test_rated_power_requires_explicit_semantic_relationship(self):
        status, _ = self.validator.compare_values(500, 510, same_parameter=False, same_scope=True)
        self.assertEqual(status, Status.NOT_COMPARABLE)

    def test_ambiguous_sample_scope_is_unresolved(self):
        status, _ = self.validator.compare_values(5, 6, same_parameter=True, same_scope=False,
                                                   same_context=True, reliable=True)
        self.assertEqual(status, Status.UNRESOLVED)

    def test_same_logical_context_can_satisfy_material_gate(self):
        status, gates = self.validator.compare_values(5, 6, same_parameter=True, same_scope=True,
            same_context=True, reliable=True, material_rule=True, affects_validity=True)
        self.assertTrue(gates["same_test_context"])
        self.assertEqual(status, Status.MATERIAL_CONFLICT)

    def test_missing_rating_observation_is_diagnostic_not_conflict(self):
        result = self.validator.validate({}, profile(rated_voltage=230), {}, report())
        self.assertEqual(result.findings, [])
        self.assertEqual(result.diagnostics[0]["code"], "CONSISTENCY_RATED_VOLTAGE_NO_COMPARABLE_TEST_OBSERVATION")

    def test_not_applicable_without_execution_has_no_conflict(self):
        result = self.validator.validate({}, {}, {"results": [{"effective_requirement_id": "r", "clause_id": "2", "decision": "NOT_APPLICABLE", "reason_code": "EXCLUSION_CONDITION_TRUE"}]}, report(clause_id="2"))
        self.assertEqual(result.findings, [])

    def test_confirmed_exclusion_with_execution_is_material_candidate(self):
        result = self.validator.validate({}, {}, {"results": [{"effective_requirement_id": "r", "clause_id": "2", "decision": "NOT_APPLICABLE", "reason_code": "EXCLUSION_CONDITION_TRUE"}]}, report("test performed", "2", "PASS"))
        finding = result.findings[0]
        self.assertEqual((finding.finding_type, finding.status), (FindingType.APPLICABILITY_EXECUTION_CONFLICT, Status.MATERIAL_CONFLICT))

    def test_unresolved_exclusion_with_execution_stays_unresolved(self):
        result = self.validator.validate({}, {}, {"results": [{"effective_requirement_id": "r", "clause_id": "2", "decision": "NOT_APPLICABLE", "reason_code": "UNKNOWN"}]}, report("tested", "2", "PASS"))
        self.assertEqual(result.findings[0].status, Status.UNRESOLVED)

    def test_pass_fail_verdict_integrity_remains_owned_downstream(self):
        source = report("", "2", "PASS")
        source["clauses"][0]["evidence_items"].append({"evidence_id": "fail", "clause_id": "2",
            "reported_verdict": "FAIL", "raw_text": "", "measurements": []})
        result = self.validator.validate({}, {}, {}, source)
        self.assertFalse(any(x.finding_type == FindingType.VERDICT_CONFLICT for x in result.findings))

    def test_na_pass_verdict_integrity_remains_owned_downstream(self):
        source = report("", "2", "PASS")
        source["clauses"][0]["evidence_items"].append({"evidence_id": "na", "clause_id": "2",
            "reported_verdict": "NOT_APPLICABLE", "raw_text": "", "measurements": []})
        result = self.validator.validate({}, {}, {}, source)
        self.assertFalse(any(x.finding_type == FindingType.VERDICT_CONFLICT for x in result.findings))

    def test_parent_table_verdict_reconciliation_is_not_duplicated(self):
        source = report("", "2", "PASS")
        source["clauses"][0]["evidence_items"].append({"evidence_id": "table", "clause_id": "2",
            "reported_verdict": "FAIL", "parent_evidence_id": "report-evidence", "table_reference": "T1",
            "raw_text": "", "measurements": []})
        result = self.validator.validate({}, {}, {}, source)
        self.assertFalse(any(x.finding_type == FindingType.VERDICT_CONFLICT for x in result.findings))

    def test_applicability_execution_finding_preserves_requirement_and_evidence(self):
        result = self.validator.validate({}, {}, {"results": [{"effective_requirement_id": "r", "clause_id": "2", "decision": "NOT_APPLICABLE", "reason_code": "EXCLUSION_CONDITION_TRUE"}]}, report("tested", "2", "PASS"), {"groups": [{"group_id": "g", "members": [{"effective_requirement_id": "r"}]}]})
        finding = result.findings[0]
        self.assertEqual((finding.requirement_ids, finding.requirement_group_ids, finding.evidence_ids), (["r"], ["g"], ["report-evidence"]))

    def test_only_executable_test_requirement_gets_execution_conflict(self):
        kb = {"clauses": [{"clause_id": "2", "requirements": [
            {"effective_requirement_id": "test", "requirement_type": "TEST"},
            {"effective_requirement_id": "condition", "requirement_type": "CONDITIONAL"}]}]}
        applicability = {"results": [
            {"effective_requirement_id": "test", "clause_id": "2", "decision": "NOT_APPLICABLE", "reason_code": "EXCLUSION_CONDITION_TRUE"},
            {"effective_requirement_id": "condition", "clause_id": "2", "decision": "NOT_APPLICABLE", "reason_code": "EXCLUSION_CONDITION_TRUE"}]}
        result = self.validator.validate(kb, {}, applicability, report("tested", "2", "PASS"))
        self.assertEqual([item.requirement_ids for item in result.findings], [["test"]])

    def test_explicit_calculation_correct(self):
        self.assertEqual(self.validator.validate_calculation([2, 3], {"operation": "multiply"}, 6), (Status.CONSISTENT, 6))

    def test_explicit_calculation_wrong(self):
        self.assertEqual(self.validator.validate_calculation([2, 3], {"operation": "multiply"}, 7), (Status.MATERIAL_CONFLICT, 6))

    def test_missing_formula_is_not_comparable(self):
        self.assertEqual(self.validator.validate_calculation([2, 3], None, 6), (Status.NOT_COMPARABLE, None))

    def test_unknown_formula_is_not_comparable(self):
        self.assertEqual(self.validator.validate_calculation([2], {"operation": "unknown"}, 2), (Status.NOT_COMPARABLE, None))

    def test_limit_exceeded(self):
        self.assertEqual(self.validator.validate_limit(11, 10, "<=", "A", "A"), Status.MATERIAL_CONFLICT)

    def test_limit_satisfied(self):
        self.assertEqual(self.validator.validate_limit(10, 10, "<=", "A", "A"), Status.CONSISTENT)

    def test_limit_unit_mismatch_is_unresolved(self):
        self.assertEqual(self.validator.validate_limit(10, 10, "<=", "A", "V"), Status.UNRESOLVED)

    def test_missing_limit_data_is_unresolved(self):
        self.assertEqual(self.validator.validate_limit(None, 10, "<=", "A", "A"), Status.UNRESOLVED)

    def test_unknown_comparator_is_unresolved(self):
        self.assertEqual(self.validator.validate_limit(1, 2, "about", "A", "A"), Status.UNRESOLVED)

    def test_no_tolerance_is_invented(self):
        _, gates = self.validator.compare_values(1, 2, same_parameter=True)
        self.assertNotIn("tolerance", gates)

    def test_missing_data_does_not_become_material(self):
        self.assertNotEqual(self.validator.validate_limit(None, None, "<=", "A", "A"), Status.MATERIAL_CONFLICT)

    def test_different_model_scope_does_not_become_material(self):
        status, _ = self.validator.compare_values(1, 2, same_parameter=True, same_scope=False,
            same_context=True, reliable=True, material_rule=True, affects_validity=True)
        self.assertEqual(status, Status.UNRESOLVED)

    def test_different_sample_scope_does_not_become_material(self):
        status, _ = self.validator.compare_values(1, 2, same_parameter=True, same_scope=False)
        self.assertEqual(status, Status.UNRESOLVED)

    def test_unknown_is_not_noncompliant(self):
        result = self.validator.validate({}, {}, {}, {})
        self.assertFalse(any(x.effect.get("recommended_disposition") == "NONCOMPLIANT" for x in result.findings))

    def test_deterministic_ids(self):
        self.assertEqual(self.identity_result()[0].finding_id, self.identity_result()[0].finding_id)

    def test_deterministic_serialization(self):
        result = self.validator.validate({}, profile(identity("A", "DECLARED_MODEL", 1), identity("B", "TESTED_MODEL", 2)), {}, report())
        self.assertEqual(self.validator.to_json(result), self.validator.to_json(result))

    def test_artifact_round_trip_is_backward_compatible(self):
        result = self.validator.validate({}, profile(identity("A", "DECLARED_MODEL", 1), identity("B", "TESTED_MODEL", 2)), {}, report())
        restored = CrossEvidenceConsistencyResult.from_dict(json.loads(self.validator.to_json(result)))
        self.assertEqual(restored.to_json(), result.to_json())

    def test_quality_audit_is_zero(self):
        audit = self.validator.validate({}, {}, {}, {}).quality_audit
        self.assertTrue(audit and all(value == 0 for value in audit.values()))

    def test_empty_artifacts_are_safe(self):
        result = self.validator.validate(None, None, None, None)
        self.assertEqual((result.findings, result.diagnostics), ([], []))

    def test_source_supported_representative_relationship_reconciles(self):
        text="All tests are performed on model B. All models are same except colour and model number."
        result=self.validator.validate({},profile(identity("A","DECLARED_MODEL",1),identity("B","TESTED_MODEL",2)),{},report(text))
        self.assertEqual(result.findings[0].status,Status.RECONCILED)

    def test_incomplete_representative_relationship_remains_unresolved(self):
        result=self.validator.validate({},profile(identity("A","DECLARED_MODEL",1),identity("B","TESTED_MODEL",2)),{},report("Tested model B"))
        self.assertEqual(result.findings[0].status,Status.UNRESOLVED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
