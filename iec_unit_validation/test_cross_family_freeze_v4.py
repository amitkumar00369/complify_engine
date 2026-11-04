"""Integrity sentinels for the current controlled-pilot V4 baseline."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "test_reports/regression_results/step_31kg_cross_family_controlled_pilot_v4.json"
V4_SHA256 = "0a7d1699592cb10db55ac30e1f13e8958396f78ac541d4b56ef5cd3287c99708"


def data() -> dict:
    return json.loads(V4.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def directory_sha(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(x for x in path.rglob("*") if x.is_file()):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0"); digest.update(item.read_bytes()); digest.update(b"\0")
    return digest.hexdigest()


def test_01_baseline_name():
    assert data()["baseline"] == "CROSS_FAMILY_CONTROLLED_PILOT_BASELINE_V4"


def test_02_baseline_status():
    assert data()["baseline_status"] == "ACCEPTED"


def test_03_engine_state():
    assert data()["engine_state"] == "FROZEN"


def test_04_parent_v3():
    assert data()["parent_baseline"] == "CROSS_FAMILY_CONTROLLED_PILOT_BASELINE_V3"


def test_05_four_accepted_families():
    assert data()["accepted_families"] == ["IEC_60335_FAMILY", "IEC_60204_FAMILY", "IEC_62841_FAMILY", "IEC_61427_FAMILY"]


def test_06_standalone_mode():
    assert "STANDALONE" in data()["pipeline_modes"]
    mode = data()["pipeline_mode_coverage"]["standalone"]
    assert mode["covered"] and not mode["fake_delta_created"] and mode["effective_kb_present"]


def test_07_base_plus_companion_mode():
    assert "BASE_PLUS_COMPANION" in data()["pipeline_modes"]
    mode = data()["pipeline_mode_coverage"]["base_plus_companion"]
    assert mode["covered"] and mode["delta_validation_present"] and mode["pair_validation_present"]


def test_08_six_accepted_runs():
    runs = data()["accepted_runs"]
    assert len(runs) == 6
    assert all(run["pipeline_status"] == "SUCCESS_WITH_REVIEW" for run in runs.values())


def test_09_acceptance_classifications():
    assert {name: run["acceptance"] for name, run in data()["accepted_runs"].items()} == {
        "washing_machine":"ACCEPTED", "submersible_pump":"ACCEPTED_WITH_CONSERVATIVE_REVIEW",
        "plastic_tube_welding":"ACCEPTED", "iec_60204":"ACCEPTED",
        "iec_62841":"ACCEPTED_WITH_REVIEW", "iec_61427":"ACCEPTED_WITH_CONSERVATIVE_REVIEW"}


def test_10_zero_introduced_false_positives():
    assert data()["behavioral_acceptance"]["introduced_material_false_positives"] == 0


def test_11_zero_introduced_false_negatives():
    assert data()["behavioral_acceptance"]["introduced_material_false_negatives"] == 0


def test_12_numeric_operators():
    assert data()["numeric_constraint_baseline"]["operators"] == ["GT", "GTE", "LT", "LTE", "EQ", "NEQ"]


def test_13_strict_boundaries():
    numeric = data()["numeric_constraint_baseline"]
    assert numeric["strict_boundary_verified"]
    assert numeric["boundaries"]["GT_equal"] == numeric["boundaries"]["LT_equal"] == "VIOLATES"


def test_14_inclusive_boundaries():
    numeric = data()["numeric_constraint_baseline"]
    assert numeric["inclusive_boundary_verified"]
    assert numeric["boundaries"]["GTE_equal"] == numeric["boundaries"]["LTE_equal"] == "SATISFIES"


def test_15_pass_cannot_override_violation():
    numeric = data()["numeric_constraint_baseline"]
    assert not numeric["report_verdict_override_allowed"]
    assert numeric["mandatory_probe"]["report_verdict"] == "PASS"
    assert numeric["mandatory_probe"]["numeric_result"] == "VIOLATES"


def test_16_iec_61427_accepted():
    item = data()["iec_61427_acceptance"]
    assert item["status"] == "ACCEPTED_WITH_CONSERVATIVE_REVIEW"
    assert item["unseen_family_validation"] == "PASS_WITH_LIMITATIONS"
    assert item["material_false_positives"] == item["material_false_negatives"] == 0


def test_17_iec_61427_comparator_probe():
    probe = data()["numeric_constraint_baseline"]["mandatory_probe"]
    assert probe["requirement"] == "> 12 V" and probe["observation"] == "12 V"
    assert probe["final_decision"] == "NON_COMPLIANT"
    assert probe["final_issue"] == "CONFIRMED_NONCOMPLIANCE"
    assert probe["contradictory_pass_retained"]


def test_18_known_limitations():
    limits = data()["known_limitations"]
    assert len(limits) >= 10
    assert any("chemistry remains UNKNOWN" in value for value in limits)
    assert any("amendments" in value for value in limits)


def test_19_genericity_counters():
    assert all(value == 0 for value in data()["genericity"].values())


def test_20_integrity_counters():
    assert all(value == 0 for value in data()["integrity"].values())


def test_21_module_hash_manifest():
    manifest = data()["module_hash_manifest"]
    assert len(manifest) == 47
    for relative, expected in manifest.items():
        assert sha(ROOT / relative) == expected


def test_22_deterministic_v4_serialization():
    assert sha(V4) == V4_SHA256
    assert json.loads(V4.read_text()) == json.loads(V4.read_text())


def test_23_v2_artifact_preserved():
    item = data()["historical_artifacts"]["v2"]
    assert not item["modified"] and sha(ROOT / item["path"]) == item["sha256"]


def test_24_v3_artifact_preserved():
    item = data()["historical_artifacts"]["v3"]
    assert not item["modified"] and sha(ROOT / item["path"]) == item["sha256"]


def test_25_accepted_runs_preserved():
    for run in data()["accepted_runs"].values():
        assert directory_sha(ROOT / run["run"]) == run["run_sha256"]


def test_26_client_style_readiness():
    readiness = data()["client_style_readiness"]
    assert readiness["status"] == "STRUCTURED_EXPLANATION_READY"
    assert len(readiness["representative_issue_types"]) == 6
    assert len(readiness["fields"]) == 13


def test_27_historical_sentinel_policy():
    policy = data()["historical_hash_sentinel_policy"]
    assert policy["v2_v3_source_hash_mismatches_are_historical"]
    assert not policy["rewrite_v2"] and not policy["rewrite_v3"]


def test_28_no_production_mutation():
    assert not data()["freeze_conditions"]["production_modified"]


def test_29_no_llm():
    assert not data()["freeze_conditions"]["llm_present"]


def test_30_no_step_32():
    assert not data()["freeze_conditions"]["step_32_started"]
    assert not list((ROOT / "test_reports/regression_results").glob("step_32*"))


def test_31_no_next_family_run():
    assert not data()["freeze_conditions"]["next_family_run_performed"]


def test_32_next_recommendation():
    assert data()["next_recommendation"] == "Run one final unseen-family validation against frozen V4 before starting Step 32."
