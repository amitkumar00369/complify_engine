"""Read-only acceptance gates for the Step 31M-D structural audit."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "test_reports/regression_results/step_31md_structural_architecture_acceptance.json"


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(x for x in path.rglob("*") if x.is_file() and "__pycache__" not in x.parts):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class Step31MDStructuralArchitectureAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(ARTIFACT.read_text(encoding="utf-8"))

    def test_01_artifact_accounting(self):
        self.assertEqual(self.data["step"], "31M-D")
        self.assertEqual(len(self.data["immutability"]["accepted_run_hashes"]), 6)

    def test_02_iec_61058_fake_clause_gate(self):
        self.assertEqual(self.data["table_row_contamination_search"]["confirmed_table_derived_fake_clauses"], 0)

    def test_03_heading_retention_gate(self):
        heading = self.data["heading_retention"]
        self.assertGreaterEqual(heading["independent_source_headings_sampled"], 50)
        self.assertEqual(heading["lost"], 0)

    def test_04_table_ownership_gate(self):
        table = self.data["table_ownership_audit"]
        self.assertEqual(sum(table[key] for key in ("ownership_leaks", "premature_termination", "overrun_into_normative_prose", "orphan_continuation_blocks", "cross_table_leakage")), 0)

    def test_05_parent_recovery_gate(self):
        parent = self.data["parent_recovery_audit"]
        self.assertTrue(parent["all_recovered_parents_source_supported"])
        self.assertEqual(parent["speculative_parents"], parent["recovery_errors"])

    def test_06_definition_gate(self):
        definitions = self.data["definitions"]
        self.assertEqual((definitions["definition_count"], definitions["duplicate_definitions"], definitions["clause_3_requirements"]), (85, 0, 0))

    def test_07_annex_gate(self):
        annex = self.data["annex_audit"]
        self.assertGreaterEqual(len(annex["iec_61058_sampled_annexes"]), 5)
        self.assertEqual(annex["nested_hierarchy_errors"], 0)

    def test_08_v4_structural_regression(self):
        cross = self.data["cross_family_regression"]
        self.assertEqual(sum(cross[key] for key in ("false_clauses_introduced", "real_clauses_lost", "material_requirement_loss", "definition_loss", "annex_hierarchy_regression", "table_ownership_regression")), 0)

    def test_09_behavioral_fp_fn_gate(self):
        behavior = self.data["downstream_behavioral_regression"]
        self.assertEqual((behavior["introduced_material_false_positives"], behavior["introduced_material_false_negatives"]), (0, 0))

    def test_10_integrity(self):
        self.assertEqual(self.data["integrity"]["material_counters"], 0)

    def test_11_genericity(self):
        genericity = self.data["genericity"]
        self.assertEqual(sum(value for key, value in genericity.items() if key.endswith("_branches")), 0)

    def test_12_determinism(self):
        self.assertTrue(all(value["repeated_build_identical"] for key, value in self.data["determinism"].items() if isinstance(value, dict)))

    def test_13_structural_readiness(self):
        self.assertEqual(self.data["readiness"], "STRUCTURAL_FOUNDATION_READY")
        self.assertEqual(self.data["final_decision"], "READY_FOR_31M_E_V1_FREEZE")

    def test_14_production_immutability(self):
        self.assertEqual(tree_hash(ROOT / "iec_par"), self.data["immutability"]["production_tree_sha256"])

    def test_15_prior_artifact_immutability(self):
        for name, expected in self.data["immutability"]["prior_artifacts"].items():
            actual = hashlib.sha256((ROOT / "test_reports/regression_results" / name).read_bytes()).hexdigest()
            self.assertEqual(actual, expected)

    def test_16_accepted_run_immutability(self):
        for name, expected in self.data["immutability"]["accepted_run_hashes"].items():
            self.assertEqual(tree_hash(ROOT / "test_reports/output" / name), expected)

    def test_17_v4_immutable(self):
        path = ROOT / "test_reports/regression_results/step_31kg_cross_family_controlled_pilot_v4.json"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), self.data["immutability"]["v4_sha256"])

    def test_18_no_v5(self):
        self.assertFalse(self.data["v5_created"])

    def test_19_no_llm(self):
        self.assertFalse(self.data["llm_used"])
        self.assertFalse(self.data["genericity"]["llm_usage"])

    def test_20_no_step_32(self):
        self.assertFalse(self.data["step_32_started"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
