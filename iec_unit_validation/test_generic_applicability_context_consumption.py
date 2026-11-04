"""Acceptance tests for source-grounded applicability-context consumption."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from iec_par.generic_iec_applicability_normalizer import (
    GenericIECApplicabilityNormalizer,
)
from iec_par.generic_iec_feature_registry import CanonicalProductFeatureRegistry
from iec_par.generic_product_profile_models import (
    EvidenceSourceType,
    ProductFact,
    ProductFactEvidence,
    ProductFactStatus,
    ProductProfile,
)
from iec_par.generic_report_product_profile_builder import (
    GenericReportProductProfileBuilder,
)
from iec_par.generic_requirement_applicability_evaluator import (
    GenericRequirementApplicabilityEvaluator,
    RequirementApplicabilityDecision as Decision,
)


OUTPUT = ROOT / "test_reports" / "output"


class GenericApplicabilityContextConsumptionTests(unittest.TestCase):
    """Exercise generic grammar, source facts, safety states, and real regressions."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = CanonicalProductFeatureRegistry()
        cls.normalizer = GenericIECApplicabilityNormalizer(cls.registry)
        cls.builder = GenericReportProductProfileBuilder(cls.registry)
        cls.evaluator = GenericRequirementApplicabilityEvaluator()

    @staticmethod
    def _fact(value: object, status: ProductFactStatus = ProductFactStatus.CONFIRMED) -> ProductFact:
        evidence = ProductFactEvidence(
            "SOURCE-1", EvidenceSourceType.REPORT_CLAUSE, raw_text="source assertion"
        )
        confidence = None if status in {ProductFactStatus.UNKNOWN, ProductFactStatus.CONFLICT} else .95
        return ProductFact("has_timer", value, status, confidence, [evidence])

    @classmethod
    def _evaluate(cls, fact: ProductFact | None = None):
        requirement = {
            "effective_requirement_id": "ER-1",
            "clause_id": "4",
            "effective_status": "ACTIVE",
            "applicability": {
                "status": "RESOLVED",
                "logic": {"field": "has_timer", "operator": "equals", "value": True},
            },
        }
        facts = {"has_timer": fact} if fact else {}
        return cls.evaluator.evaluate_requirement(requirement, ProductProfile("P", facts=facts))

    @classmethod
    def _logic(cls, text: str):
        return cls.normalizer._parse_presence_usage_condition(text.casefold())

    @staticmethod
    def _json(run: str, relative: str):
        return json.loads((OUTPUT / run / relative).read_text(encoding="utf-8"))

    def test_01_explicit_presence_resolves_positive_predicate(self):
        self.assertIs(self._evaluate(self._fact(True)).decision, Decision.APPLICABLE)

    def test_02_explicit_absence_resolves_positive_predicate_false(self):
        self.assertIs(self._evaluate(self._fact(False)).decision, Decision.NOT_APPLICABLE)

    def test_03_unknown_remains_unresolved_not_false(self):
        self.assertIs(self._evaluate().decision, Decision.UNKNOWN)

    def test_04_conflict_requires_review(self):
        self.assertIs(
            self._evaluate(self._fact(None, ProductFactStatus.CONFLICT)).decision,
            Decision.NEEDS_REVIEW,
        )

    def test_05_report_scope_fact_is_consumable(self):
        profile = self.builder.build_from_pages(["The product is provided with a timer."])
        self.assertIs(profile.facts["has_timer"].value, True)

    def test_06_model_scope_is_preserved(self):
        profile = self.builder.build_from_pages(["Model M1 is provided with a timer."])
        observation = profile.facts["has_timer"].observations[0]
        self.assertEqual((observation.scope_type, observation.model_scope), ("MODEL_SCOPE", "M1"))

    def test_07_model_scope_is_not_promoted_report_wide(self):
        profile = self.builder.build_from_pages(["Model M1 is provided with a timer."])
        self.assertIs(profile.facts["has_timer"].status, ProductFactStatus.UNKNOWN)

    def test_08_test_context_mention_does_not_create_presence(self):
        profile = self.builder.build_from_pages(["The timer endurance test was completed."])
        self.assertNotIn("has_timer", profile.facts)

    def test_09_negative_test_wording_does_not_create_absence(self):
        profile = self.builder.build_from_pages(["No motor windings open-circuited."])
        self.assertNotIn("has_motor", profile.facts)

    def test_10_provided_with_grammar(self):
        self.assertEqual(self._logic("If a product is provided with a timer")["value"], True)

    def test_11_fitted_with_grammar(self):
        self.assertEqual(self._logic("If a product is fitted with a guard")["field"], "has_guard")

    def test_12_having_grammar(self):
        self.assertEqual(self._logic("Products having a timer")["field"], "has_timer")

    def test_13_uses_grammar(self):
        self.assertEqual(self._logic("If a product uses a timer")["value"], True)

    def test_14_without_grammar(self):
        self.assertEqual(self._logic("Products without a timer")["value"], False)

    def test_15_not_fitted_with_grammar(self):
        self.assertEqual(self._logic("Products not fitted with a timer")["value"], False)

    def test_16_registry_alias_resolution(self):
        self.assertEqual(self.normalizer._boolean_alias("adjustable guard"), "has_adjustable_guard")

    def test_17_verdict_alone_creates_no_product_fact(self):
        self.assertFalse(self.builder.build_from_pages(["7.1\nPASS"]).facts)

    def test_18_requirement_language_creates_no_product_fact(self):
        self.assertNotIn(
            "has_timer", self.builder.build_from_pages(["Products with timers shall comply."]).facts
        )

    def test_19_real_19_1_uses_confirmed_absence(self):
        data = self._json("iec_62841_impact_drill_post_31jh", "report/applicability_result.json")
        item = next(x for x in data["results"] if "19.1_R4" in x["effective_requirement_id"])
        self.assertEqual((item["decision"], item["facts_used"][0]["value"]), ("NOT_APPLICABLE", False))

    def test_20_real_21_4_uses_confirmed_presence(self):
        data = self._json("iec_62841_impact_drill_post_31jh", "report/applicability_result.json")
        item = next(x for x in data["results"] if "21.4_R1" in x["effective_requirement_id"])
        self.assertEqual((item["decision"], item["facts_used"][0]["value"]), ("APPLICABLE", True))

    def test_21_all_nine_historical_semantics_recorded(self):
        artifact = json.loads((ROOT / "test_reports/regression_results/step_31jg_generic_requirement_subrow_linkage.json").read_text())
        self.assertEqual(artifact["iec_62841"]["reaudit_known_false_positives"]["total"], 9)

    def test_22_false_negative_probe_count_preserved(self):
        artifact = json.loads((ROOT / "test_reports/regression_results/step_31jg_generic_requirement_subrow_linkage.json").read_text())
        self.assertGreaterEqual(artifact["iec_62841"]["false_negative_recheck"]["probes"], 15)

    def _assert_issue_distribution_unchanged(self, before: str, after: str) -> None:
        def distribution(run: str):
            issues = self._json(run, "decisions/final_compliance_issues.json")["issues"]
            return sorted(item["issue_type"] for item in issues)
        self.assertEqual(distribution(before), distribution(after))

    def test_23_washing_regression(self):
        self._assert_issue_distribution_unchanged("washing_machine_post_31jg", "washing_machine_post_31jh")

    def test_24_pump_regression(self):
        self._assert_issue_distribution_unchanged("submersible_pump_post_31jg", "submersible_pump_post_31jh")

    def test_25_welding_regression(self):
        self._assert_issue_distribution_unchanged("plastic_tube_welding_tools_post_31jg", "plastic_tube_welding_tools_post_31jh")

    def test_26_other_standard_family_regression(self):
        self._assert_issue_distribution_unchanged("iec_60204_1_post_31jg", "iec_60204_1_post_31jh")

    def test_27_amendment_source_gap_preserved(self):
        issues = self._json("iec_62841_impact_drill_post_31jh", "decisions/final_compliance_issues.json")["issues"]
        gap = next(item for item in issues if item["issue_type"] == "STANDARD_SOURCE_GAP")
        self.assertEqual((gap["compliance_conclusion"], gap["next_action"]["type"]),
                         ("NOT_EVALUATED", "STANDARD_SOURCE_REQUEST"))

    def test_28_grouped_verdict_conflicts_not_introduced(self):
        issues = self._json("iec_62841_impact_drill_post_31jh", "decisions/final_compliance_issues.json")["issues"]
        self.assertFalse(any("CONFLICT" in item["issue_type"] for item in issues))

    def test_29_no_fixture_specific_production_branches(self):
        sources = "\n".join((ROOT / name).read_text().casefold() for name in (
            "iec_par/generic_iec_applicability_normalizer.py",
            "iec_par/generic_report_product_profile_builder.py",
        ))
        for forbidden in ("62841", "60335", "60204", "19.1", "21.4", "impact drill", "id6808"):
            self.assertNotIn(forbidden, sources)

    def test_30_deterministic_serialization(self):
        profile = self.builder.build_from_pages(["The product is provided with a timer."])
        self.assertEqual(profile.to_json(), profile.to_json())


if __name__ == "__main__":
    unittest.main(verbosity=2)
