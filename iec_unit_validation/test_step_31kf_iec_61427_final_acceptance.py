"""Read-only acceptance assertions for Step 31K-F."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "test_reports/regression_results/step_31kf_iec_61427_final_post_comparator_acceptance.json"


def audit() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    h = hashlib.sha256()
    if path.is_file():
        h.update(path.read_bytes())
    else:
        for item in sorted(x for x in path.rglob("*") if x.is_file()):
            h.update(item.relative_to(path).as_posix().encode())
            h.update(b"\0"); h.update(item.read_bytes()); h.update(b"\0")
    return h.hexdigest()


def test_issue_accounting() -> None:
    data = audit()["iec_61427"]
    assert len(data["issue_audit"]) == data["final_issues"] == 18
    assert sum(data["classification"].values()) == 18
    assert data["classification"] == {
        "TRUE_NONCOMPLIANCE": 1, "TRUE_APPLICABILITY_GAP": 7,
        "TRUE_MISSING_EVIDENCE": 4, "ACCEPTABLE_CONSERVATIVE_REVIEW": 6,
        "STANDARD_SOURCE_GAP": 0, "FALSE_POSITIVE": 0,
        "OTHER_MATERIAL_DEFECT": 0,
    }


def test_material_false_positive_gate() -> None:
    assert audit()["iec_61427"]["classification"]["FALSE_POSITIVE"] == 0


def test_material_false_negative_gate() -> None:
    search = audit()["iec_61427"]["false_negative_search"]
    assert search["probe_count"] >= 40
    assert len(search["probes"]) >= 40
    assert search["material_false_negatives"] == 0


def test_greater_than_12_violation() -> None:
    probe = audit()["iec_61427"]["mandatory_probe"]
    assert probe["canonical_operator"] == "GT"
    assert probe["threshold"] == probe["observed"] == 12
    assert probe["unit"] == probe["observation_unit"] == "V"
    assert probe["numeric_result"] == "VIOLATES"
    assert probe["final_decision"] == "NON_COMPLIANT"
    assert probe["final_issue"] == "CONFIRMED_NONCOMPLIANCE"


def test_contradictory_pass_retained() -> None:
    probe = audit()["iec_61427"]["mandatory_probe"]
    assert probe["report_verdict"] == "PASS"
    assert probe["pass_traceable"] and not probe["pass_suppressed_violation"]


def test_gt_boundary() -> None:
    assert audit()["iec_61427"]["boundary_sanity"]["GT_equal"] == "VIOLATES"


def test_gte_boundary() -> None:
    assert audit()["iec_61427"]["boundary_sanity"]["GTE_equal"] == "SATISFIES"


def test_lt_boundary() -> None:
    assert audit()["iec_61427"]["boundary_sanity"]["LT_equal"] == "VIOLATES"


def test_lte_boundary() -> None:
    assert audit()["iec_61427"]["boundary_sanity"]["LTE_equal"] == "SATISFIES"


def test_comparator_matrix() -> None:
    matrix = audit()["iec_61427"]["comparator_sanity"]
    assert matrix["operators"] == ["GT", "GTE", "LT", "LTE", "EQ", "NEQ"]
    assert matrix["decimals"] and matrix["signed_values"] and matrix["unicode"]
    assert matrix["incompatible_units"] == "INCOMPARABLE"
    assert not matrix["tolerance_flattened"]


def test_numeric_constraint_audit() -> None:
    numeric = audit()["iec_61427"]["numeric_constraint_audit"]
    assert numeric["subject_count"] >= 20
    assert len(numeric["items"]) >= 20
    assert numeric["material_misparsed"] == numeric["miscompared"] == 0


def test_conditional_threshold_protection() -> None:
    protection = audit()["iec_61427"]["conditional_threshold_protection"]
    assert all(value == 0 for value in protection.values())


def test_chemistry_remains_unknown() -> None:
    app = audit()["iec_61427"]["applicability_audit"]
    assert app["chemistry"] == "UNKNOWN"
    assert app["gaps"] == 7 and app["8.4.2.2_gaps"] == 4
    assert not app["chemistry_inferred_from_voltage"]
    assert not app["chemistry_inferred_from_capacity"]


def test_missing_evidence_validity() -> None:
    section = audit()["iec_61427"]["missing_evidence_audit"]
    assert section["count"] == 4 and section["real_requirements"]
    assert section["specific_evidence_absent"]
    assert section["child_evidence_ignored"] == section["matcher_loss"] == 0
    assert section["over_granular_causes"] == 0


def test_conservative_review_validity() -> None:
    section = audit()["iec_61427"]["conservative_review_audit"]
    assert section["count"] == 6
    assert section["deterministically_resolvable_but_unresolved"] == 0
    assert section["reasons"]


def test_product_profile() -> None:
    profile = audit()["iec_61427"]["product_profile"]
    assert profile["product_identity"] and profile["manufacturer"]
    assert profile["capacity_observations"] == [{"value":100,"unit":"Ah"},{"value":200,"unit":"Ah"}]
    assert profile["authoritative_capacity"] is None and not profile["capacity_conflict"]
    assert profile["chemistry"] == "UNKNOWN" and profile["fabricated_facts"] == 0


def test_clause_9_integrity() -> None:
    integrity = audit()["iec_61427"]["structural_integrity"]
    assert integrity["false_numeric_clause_9"] == 0
    assert integrity["genuine_clause_ids"] == ["9", "9.1", "9.2", "9.2.1", "9.2.2"]
    assert not integrity["8.4.5_owns_8.4.6"]


def test_evidence_integrity() -> None:
    assert all(value == 0 for value in audit()["iec_61427"]["evidence_integrity"].values())


def test_cross_standard_isolation() -> None:
    assert audit()["iec_61427"]["evidence_integrity"]["cross_standard_leakage"] == 0


def test_five_family_behavioral_regression() -> None:
    section = audit()["v3_behavioral_regression"]
    for name in ("washing_machine", "submersible_pump", "plastic_tube_welding", "iec_60204", "iec_62841"):
        assert section[name]["pipeline"] == "SUCCESS_WITH_REVIEW"
    assert section["introduced_material_false_positives"] == 0
    assert section["introduced_material_false_negatives"] == 0


def test_hash_sentinels_are_separate() -> None:
    section = audit()["test_interpretation"]
    assert section["behavioral_tests"]["failed"] == 0
    assert section["historical_source_hash_sentinels"]["failed"] == 2
    assert section["historical_source_hash_sentinels"]["behavioral_regressions"] == 0


def test_genericity() -> None:
    assert all(value == 0 for value in audit()["genericity"].values())


def test_explanation_readiness() -> None:
    section = audit()["client_style_readiness"]
    assert section["status"] == "STRUCTURED_EXPLANATION_READY"
    assert all(section[key] for key in ("confirmed_noncompliance", "applicability_gap", "missing_evidence", "conservative_review"))
    assert len(section["fields_available"]) == 12


def test_production_immutability() -> None:
    imm = audit()["immutability"]
    assert imm["production_modifications"] == 0
    for relative, expected in imm["production_modules"].items():
        assert digest(ROOT / relative) == expected


def test_run_immutability() -> None:
    imm = audit()["immutability"]
    assert imm["candidate_run"]["before"] == imm["candidate_run"]["after"]
    assert digest(ROOT / "test_reports/output/iec_61427_1_battery_post_31ke") == imm["candidate_run"]["after"]
    assert imm["run_mutations"] == 0


def test_v3_immutability() -> None:
    imm = audit()["immutability"]
    assert imm["v3_artifact"]["before"] == imm["v3_artifact"]["after"]
    assert digest(ROOT / "test_reports/regression_results/step_31ji_cross_family_controlled_pilot_v3.json") == imm["v3_artifact"]["after"]
    assert imm["v3_mutation"] == 0


def test_no_v4() -> None:
    assert not audit()["decision"]["v4_created"]
    assert not list((ROOT / "test_reports/regression_results").glob("*v4*"))


def test_no_llm() -> None:
    assert not audit()["decision"]["llm_introduced"]


def test_no_step_32() -> None:
    assert not audit()["decision"]["step_32_started"]
    assert not list((ROOT / "test_reports/regression_results").glob("step_32*"))


def test_final_acceptance() -> None:
    decision = audit()["decision"]
    assert decision["iec_61427_status"] == "ACCEPTED_WITH_CONSERVATIVE_REVIEW"
    assert decision["unseen_family_validation"] == "PASS_WITH_LIMITATIONS"
    assert decision["v4_recommendation"] == "RECOMMEND_SEPARATE_CONTROLLED_V4_FREEZE_STEP"
