import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from meguvizbench.reporting import DIMENSIONS, build_public_report, publish_site, validate_public_report


def trial(name, family, variant, repeat, *, dimension=DIMENSIONS[0], config="oracle"):
    return {
        "trial_id": f"{config}-{name}", "task_id": name, "family_id": family, "variant_id": variant,
        "dimension": dimension, "subtype": "svg", "scorer_version": "1.0", "task_version": "1.0",
        "model_id": "reference", "agent_id": "fixture", "config_id": config, "config_digest": "a" * 64,
        "seed": repeat, "repeat": repeat,
    }


def plan(trials):
    return {
        "protocol_version": "1.0", "run_id": "run-test", "mode": "platform_validation",
        "taskset_id": "public", "taskset_version": "1.0", "budget_id": "zero", "budget_digest": "b",
        "tools_profile": "shell", "environment": "linux", "trial_microusd": 0,
        "score_weights": dict.fromkeys(DIMENSIONS, 1),
        "expected_trials": trials, "private_path": "SYNTHETIC_PRIVATE_MARKER",
    }


def result(trial_id, score, *, status="passed", attempt=1, cost=0):
    return {
        "protocol_version": "1.0", "run_id": "run-test", "trial_id": trial_id, "attempt": attempt,
        "attempt_id": f"{trial_id}-{attempt}", "mode": "platform_validation", "status": status,
        "score": score, "duration_seconds": 1.5, "cost_usd": cost,
        "verifier": {"score": 999, "trace": "SYNTHETIC_PRIVATE_MARKER"},
    }


class ReportingTests(unittest.TestCase):
    def test_repeats_then_variants_then_families_have_fixed_weight(self):
        trials = [
            trial("a0", "a", "variant-a1", 0),
            trial("a1", "a", "variant-a1", 1),
            trial("a2", "a", "variant-a2", 0),
            trial("b0", "b", "variant-b", 0),
        ]
        results = [result(case["trial_id"], score) for case, score in zip(trials, [0, 100, 100, 0])]
        row, = build_public_report([plan(trials)], results)["rows"]
        self.assertEqual(row["dimensions"][DIMENSIONS[0]]["score"], 37.5)
        self.assertEqual(row["dimensions"][DIMENSIONS[0]]["uncertainty"]["status"], "insufficient")
        self.assertIsNone(row["dimensions"][DIMENSIONS[1]]["score"])
        self.assertIsNone(row["composite_score"])

    def test_latest_attempt_decides_score_but_earlier_cost_and_failure_are_retained(self):
        trials = [trial("a0", "a", "a", 0), trial("b0", "b", "b", 0), trial("c0", "c", "c", 0)]
        results = [
            result("oracle-a0", 75, attempt=2, cost=0.1),
            result("oracle-a0", None, attempt=1, status="api_error", cost=None),
            result("oracle-b0", None, status="budget_exhausted", cost=0.05),
        ]
        row, = build_public_report([plan(trials)], results)["rows"]
        self.assertEqual(row["state"], "provisional")
        self.assertEqual(row["failure_types"]["missing"], 1)
        self.assertEqual(row["failure_types"]["budget_exhausted"], 1)
        self.assertEqual(row["attempt_statuses"]["api_error"], 1)
        self.assertEqual(row["dimensions"][DIMENSIONS[0]]["score"], 37.5)
        self.assertEqual(row["dimensions"][DIMENSIONS[0]]["coverage"], 0.666667)
        self.assertEqual(row["attempts"], 3)
        self.assertIsNone(row["cost_usd"])
        self.assertEqual(row["unknown_cost_attempts"], 1)
        self.assertEqual(row["duration_seconds"], 4.5)
        with self.assertRaises(ValueError):
            build_public_report([plan(trials)], [*results, results[0]])

    def test_compares_same_conditions_and_requires_complete_eight_dimensions(self):
        trials = [
            trial(f"{dimension}-{family}", f"{dimension}-{family}", "base", 0, dimension=dimension, config=config)
            for dimension in DIMENSIONS
            for family in range(3)
            for config in ("a", "b")
        ]
        results = [result(case["trial_id"], 80 if case["config_id"] == "a" else 70) for case in trials]
        a, b = build_public_report([plan(trials)], results)["rows"]
        self.assertEqual(a["cohort"], b["cohort"])
        self.assertEqual(a["composite_score"], 80)
        self.assertEqual(b["composite_score"], 70)
        interval = a["dimensions"][DIMENSIONS[0]]["uncertainty"]
        self.assertEqual(interval, {"status": "family_bootstrap", "lower": 80, "upper": 80})
        trials[-1]["seed"] = 42
        a, b = build_public_report([plan(trials)], results[:-1])["rows"]
        self.assertNotEqual(a["cohort"], b["cohort"])
        self.assertEqual(b["state"], "provisional")
        self.assertEqual(a["state"], "complete")
        self.assertEqual(a["batch_state"], "provisional")
        self.assertIsNone(a["composite_score"])
        self.assertIsNone(b["composite_score"])

    def test_export_drops_private_fields_and_rejects_nested_extras(self):
        trials = [trial("a0", "a", "a", 0)]
        trials[0]["subtype"] = "SYNTHETIC_PRIVATE_MARKER"
        payload = build_public_report([plan(trials)], [result("oracle-a0", 100)])
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", json.dumps(payload))
        with TemporaryDirectory() as target:
            output = Path(target) / "pages"
            web_dir = Path(__file__).resolve().parents[1] / "web"
            publish_site(payload, web_dir, output)
            self.assertEqual(json.loads((output / "data.json").read_text(encoding="utf-8")), payload)
            self.assertEqual(
                {path.name for path in output.iterdir()}, {"index.html", "style.css", "app.js", "data.json", ".nojekyll"}
            )
            with self.assertRaises(ValueError):
                publish_site(payload, web_dir, output)
        payload["rows"][0]["dimensions"][DIMENSIONS[0]]["secret"] = "SYNTHETIC_PRIVATE_MARKER"
        with self.assertRaises(ValueError):
            validate_public_report(payload)
