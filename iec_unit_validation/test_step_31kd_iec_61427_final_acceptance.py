"""Read-only acceptance assertions for the Step 31K-D audit artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "test_reports/regression_results/step_31kd_iec_61427_final_acceptance.json"


def _audit() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_all_18_findings_classified() -> None:
    audit = _audit()
    findings = audit["iec_61427"]["finding_audit"]
    assert len(findings) == audit["iec_61427"]["final_issues"] == 18
    assert all(item["classification"] and item["explanation"] for item in findings)


def test_classification_accounting_is_exact() -> None:
    classification = _audit()["iec_61427"]["classification"]
    assert sum(classification.values()) == 18
    assert classification["true_applicability_gap"] == 7
    assert classification["true_missing_evidence"] == 4
    assert classification["acceptable_conservative_review"] == 7


def test_material_false_positive_gate() -> None:
    assert _audit()["iec_61427"]["classification"]["false_positive"] == 0


def test_material_false_negative_gate_detects_failure() -> None:
    section = _audit()["iec_61427"]["false_negative_search"]
    assert section["probe_count"] >= 30
    assert section["material_false_negatives"] == 1
    assert _audit()["decision"]["iec_61427_status"] == "NOT_ACCEPTED"


def test_applicability_gap_audit() -> None:
    findings = _audit()["iec_61427"]["finding_audit"]
    gaps = [x for x in findings if x["classification"] == "TRUE_APPLICABILITY_GAP"]
    assert len(gaps) == 7
    assert all(x["applicability"] == "UNRESOLVED" for x in gaps)


def test_missing_evidence_audit() -> None:
    findings = _audit()["iec_61427"]["finding_audit"]
    missing = [x for x in findings if x["classification"] == "TRUE_MISSING_EVIDENCE"]
    assert len(missing) == 4
    assert all(x["final_issue"] == "MISSING_EVIDENCE" for x in missing)


def test_conservative_review_audit() -> None:
    findings = _audit()["iec_61427"]["finding_audit"]
    reviews = [x for x in findings if x["classification"] == "ACCEPTABLE_CONSERVATIVE_REVIEW"]
    assert len(reviews) == 7
    assert all(x["report_evidence"] and x["explanation"] for x in reviews)


def test_clause_4_3() -> None:
    probe = _audit()["iec_61427"]["key_probes"]["4.3"]
    assert probe == {"status": "PASS", "unconditional": True, "child_pass_linked": True, "issues": 0}


def test_clause_4_4_3() -> None:
    probe = _audit()["iec_61427"]["key_probes"]["4.4.3"]
    assert probe["valid_child_parent_support"] and probe["sibling_leakage"] == 0


def test_clause_4_4_11() -> None:
    probe = _audit()["iec_61427"]["key_probes"]["4.4.11"]
    assert probe["child_linkage"] and probe["chemistry"] == "UNKNOWN"
    assert probe["false_na_conflicts"] == 0


def test_clause_5_1() -> None:
    probe = _audit()["iec_61427"]["key_probes"]["5.1"]
    assert probe["requirements"] == probe["supported_requirements"] == 5
    assert probe["overmatching"] == probe["issues"] == 0


def test_clause_8_1() -> None:
    probe = _audit()["iec_61427"]["key_probes"]["8.1"]
    assert probe["requirements_retained"] and probe["table_4_owned"]
    assert probe["capacity_semantics_retained"] and probe["false_findings"] == 0


def test_clause_8_4_1_records_material_defect() -> None:
    probe = _audit()["iec_61427"]["key_probes"]["8.4.1"]
    assert probe["requirements"] == 6 and probe["duplicate_composites"] == 0
    assert probe["status"] == "FAIL_MATERIAL_FALSE_NEGATIVE"
    assert "12 V does not satisfy >12 V" in probe["material_false_negative"]


def test_clause_8_4_2_2() -> None:
    probe = _audit()["iec_61427"]["key_probes"]["8.4.2.2"]
    assert probe["atomic_requirements"] == probe["applicability_gaps"] == 4
    assert probe["chemistry"] == "UNKNOWN"


def test_clause_8_4_4() -> None:
    probe = _audit()["iec_61427"]["key_probes"]["8.4.4"]
    assert probe["independent_instructions"] == 4
    assert probe["table_4_retained"] and not probe["following_heading_owned"]


def test_clause_8_4_5() -> None:
    probe = _audit()["iec_61427"]["key_probes"]["8.4.5"]
    assert probe["overlap"] == 0 and probe["true_missing_evidence"] == 1
    assert not probe["owns_8.4.6_content"]


def test_clause_8_4_6() -> None:
    probe = _audit()["iec_61427"]["key_probes"]["8.4.6"]
    assert probe["independent_clause"] and probe["independent_requirement"]
    assert probe["evidence_ownership"] == "CORRECT" and probe["false_findings"] == 0


def test_clause_9_family() -> None:
    probe = _audit()["iec_61427"]["key_probes"]["9_family"]
    assert probe["clauses"] == ["9", "9.1", "9.2", "9.2.1", "9.2.2"]
    assert not probe["numeric_table_clause_9"] and not probe["false_report_ev_9_001"]
    assert probe["malformed_requirements"] == 0


def test_rated_capacity() -> None:
    capacity = _audit()["iec_61427"]["rated_capacity"]
    assert capacity["100_Ah"]["value"] == 100 and capacity["100_Ah"]["unit"] == "Ah"
    assert capacity["200_Ah"]["value"] == 200 and capacity["200_Ah"]["unit"] == "Ah"
    assert capacity["authoritative_single_value"] is None and not capacity["conflict"]


def test_numeric_table_evidence() -> None:
    numeric = _audit()["iec_61427"]["numeric_table_audit"]
    assert numeric["subject_count"] >= 15 and len(numeric["subjects"]) >= 15
    assert numeric["values_preserved"] and numeric["units_preserved"]
    assert numeric["table_references_preserved"] and numeric["report_ownership_correct"]
    assert numeric["missed_required_comparisons"] == 1


def test_product_profile() -> None:
    profile = _audit()["iec_61427"]["product_profile"]
    assert profile["fabricated_facts"] == 0 and profile["capacity_observations"] == 2
    assert profile["chemistry"] == "UNKNOWN"


def test_cross_standard_ownership() -> None:
    assert _audit()["integrity"]["cross_standard_leakage"] == 0


def test_integrity() -> None:
    integrity = _audit()["integrity"]
    assert all(value == 0 for value in integrity.values())


def test_v3_regression() -> None:
    regression = _audit()["v3_regression"]
    assert regression["introduced_false_positives"] == 0
    assert regression["introduced_false_negatives"] == 0
    assert regression["washing_machine"] == "ACCEPTED"
    assert regression["iec_62841"] == "ACCEPTED_WITH_REVIEW"


def test_genericity() -> None:
    assert all(value == 0 for value in _audit()["genericity"].values())


def test_explanation_readiness() -> None:
    audit = _audit()
    assert audit["client_style_readiness"] == "STRUCTURED_EXPLANATION_READY"
    defect = audit["iec_61427"]["material_defect"]
    assert all(defect[key] for key in ("exact_finding", "root_cause", "first_incorrect_generic_stage"))


def test_v3_immutable() -> None:
    immutability = _audit()["immutability"]
    assert immutability["v3_artifact"]["before"] == immutability["v3_artifact"]["after"]
    assert immutability["v3_mutation"] == 0
    assert _sha256(ROOT / "test_reports/regression_results/step_31ji_cross_family_controlled_pilot_v3.json") == immutability["v3_artifact"]["after"]


def test_no_v4() -> None:
    audit = _audit()
    assert not audit["decision"]["v4_created"]
    assert not list((ROOT / "test_reports/regression_results").glob("*v4*"))


def test_no_step_32() -> None:
    audit = _audit()
    assert not audit["decision"]["step_32_started"]
    assert not list((ROOT / "test_reports/regression_results").glob("step_32*"))


def test_production_modules_are_immutable() -> None:
    modules = _audit()["immutability"]["production_modules"]
    for filename, expected_hash in modules.items():
        assert _sha256(ROOT / "iec_par" / filename) == expected_hash
    assert _audit()["immutability"]["production_mutation"] == 0
