"""Acceptance sentinels for the read-only Step 31L blind-family audit."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "test_reports/regression_results/step_31l_final_blind_unseen_family_validation.json"
V4 = ROOT / "test_reports/regression_results/step_31kg_cross_family_controlled_pilot_v4.json"
V4_SHA256 = "0a7d1699592cb10db55ac30e1f13e8958396f78ac541d4b56ef5cd3287c99708"


def data() -> dict:
    return json.loads(RESULT.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def directory_sha(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def test_01_v4_baseline_reference() -> None:
    assert data()["baseline"] == "CROSS_FAMILY_CONTROLLED_PILOT_BASELINE_V4"
    assert data()["baseline_sha256"] == V4_SHA256


def test_02_blind_mode() -> None:
    assert data()["mode"] == "BLIND_UNSEEN_FAMILY_VALIDATION"
    assert data()["input"]["strict_standard_validation"] is True


def test_03_source_alignment_classification() -> None:
    item = data()["input"]
    assert item["source_set_complete"] is False
    assert item["edition_alignment"].startswith("PRIMARY_IEC_61058_1_2016_ALIGNED")
    assert item["source_gap"] == ["IEC 61058-1-1:2016", "IEC 61058-1-2:2016"]
    assert data()["pipeline"]["first_run_classification"] == "STANDARD_SOURCE_GAP"


def test_04_structural_audit_accounting() -> None:
    audit = data()["structural_audit"]
    assert audit["samples_audited"] >= 30
    assert sum(audit["sample_accounting"].values()) == audit["samples_audited"]
    assert audit["confirmed_table_derived_clause_objects"] == len(audit["confirmed_table_derived_ids"])
    assert audit["confirmed_table_derived_clause_objects"] > 0


def test_05_requirement_audit_accounting() -> None:
    audit = data()["requirement_audit"]
    assert audit["samples_audited"] >= 40
    assert sum(audit["sample_accounting"].values()) == audit["samples_audited"]
    assert len(audit["sample_requirement_ids"]) == audit["samples_audited"]


def test_06_evidence_audit_accounting() -> None:
    audit = data()["evidence_audit"]
    assert audit["samples_audited"] >= 40
    assert sum(audit["sample_accounting"].values()) == audit["samples_audited"]
    assert len(audit["sample_evidence_ids"]) == audit["samples_audited"]


def test_07_applicability_audit_accounting() -> None:
    audit = data()["applicability_audit"]
    assert audit["status"] == "NOT_EXECUTED_SOURCE_GATE"
    assert audit["samples_audited"] == 0
    assert audit["required_samples"] == 30


def test_08_numeric_audit_accounting() -> None:
    audit = data()["numeric_audit"]
    assert audit["samples_audited"] >= 30
    assert sum(audit["sample_accounting"].values()) == audit["samples_audited"]
    assert audit["comparison_executed"] is False


def test_09_issue_audit_accounting() -> None:
    audit = data()["final_issue_audit"]
    assert audit["status"] == "NOT_EXECUTED_SOURCE_GATE"
    assert sum(audit["sample_accounting"].values()) == audit["generated_findings_audited"] == 0


def test_10_fp_count_not_fabricated() -> None:
    assert data()["metrics"]["false_positive"] is None
    assert data()["final_issue_audit"]["false_positive"] is None


def test_11_fn_probe_count_and_nonclaim() -> None:
    audit = data()["false_negative_search"]
    assert audit["independent_fn_probes"] >= 50
    assert audit["material_false_negatives"] is None
    assert data()["metrics"]["material_false_negatives"] is None


def test_12_integrity() -> None:
    integrity = data()["integrity"]
    assert integrity["duplicate_evidence_ids"] == 0
    assert integrity["orphan_evidence_refs"] == 0
    assert integrity["cross_clause_leakage"] == "DETECTED_IN_KB_STRUCTURE"
    assert integrity["fabricated_conclusions"] == 0


def test_13_genericity() -> None:
    genericity = data()["genericity"]
    assert genericity["production_code_added"] is False
    assert genericity["production_code_modified"] is False
    counters = [value for key, value in genericity.items() if key.endswith("_branches_added")]
    assert counters and all(value == 0 for value in counters)


def test_14_v4_immutable() -> None:
    assert sha(V4) == V4_SHA256
    immutable = data()["immutability"]
    assert immutable["v4_sha256_before"] == immutable["v4_sha256_after"] == V4_SHA256
    assert immutable["v4_modified"] is False


def test_15_production_immutable() -> None:
    baseline = json.loads(V4.read_text(encoding="utf-8"))
    manifest = baseline["module_hash_manifest"]
    assert len(manifest) == data()["immutability"]["production_manifest_entries_checked"] == 47
    assert all(sha(ROOT / relative) == expected for relative, expected in manifest.items())
    assert data()["decision"]["production_modified"] is False


def test_16_accepted_v4_runs_immutable() -> None:
    baseline = json.loads(V4.read_text(encoding="utf-8"))
    assert all(
        directory_sha(ROOT / run["run"]) == run["run_sha256"]
        for run in baseline["accepted_runs"].values()
    )
    assert data()["immutability"]["accepted_v4_runs_modified"] is False


def test_17_client_readiness() -> None:
    readiness = data()["client_style_readiness"]
    assert readiness["status"] == "PARTIALLY_READY"
    assert "missing companion sources" in readiness["available_fields"]


def test_18_valid_final_decision() -> None:
    decision = data()["decision"]
    assert decision["unseen_family_validation"] in {
        "PASS", "PASS_WITH_LIMITATIONS", "FAIL_GENERICITY", "SOURCE_SET_INCOMPLETE",
        "EDITION_MISMATCH_VALIDATION", "OTHER",
    }
    assert decision["unseen_family_validation"] == "FAIL_GENERICITY"
    assert decision["deterministic_generalization_status"] == "NOT_READY"
    assert decision["recommendation"] == "REASSESS_PARSER_ARCHITECTURE"


def test_19_no_v5_or_llm() -> None:
    decision = data()["decision"]
    assert decision["v5_created"] is False
    assert decision["llm_introduced"] is False
    assert data()["genericity"]["llm_present"] is False
    assert not list((ROOT / "test_reports/regression_results").glob("*v5*"))


def test_20_no_step_32() -> None:
    assert data()["decision"]["step_32_started"] is False
    assert not list((ROOT / "test_reports/regression_results").glob("step_32*"))
