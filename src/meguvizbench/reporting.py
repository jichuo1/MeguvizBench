"""Aggregate verified trials and write a closed, aggregate-only public report."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
import json
import math
from pathlib import Path
import random
import re
import shutil
from statistics import fmean
from typing import Any

from .protocol import DIMENSIONS, MODES as RUN_MODES, STATUSES as RUN_STATUSES, digest, is_token


STATUSES = tuple(sorted(RUN_STATUSES))
MODES = RUN_MODES | {"demo"}
SCORED = frozenset({"passed", "model_error", "budget_exhausted", "timeout"})
PUBLIC_SUBTYPES = frozenset({
    "android", "web", "svg", "3d", "bugfix", "local_bug", "timing_bug", "certificate", "idempotency",
})
MIN_FAMILIES = 3
BOOTSTRAP_DRAWS = 2000
SITE_FILES = ("index.html", "style.css", "app.js")
TRIAL_CONDITIONS = (
    "task_id", "family_id", "variant_id", "dimension", "subtype",
    "scorer_version", "task_version", "seed", "repeat",
)


def _uncertainty(family_means: list[float], complete: bool) -> dict:
    if not complete or len(family_means) < MIN_FAMILIES:
        return {"status": "insufficient", "lower": None, "upper": None}
    rng = random.Random(0)
    draws = sorted(fmean(rng.choices(family_means, k=len(family_means))) for _ in range(BOOTSTRAP_DRAWS))
    lower = draws[int((BOOTSTRAP_DRAWS - 1) * 0.025)]
    upper = draws[math.ceil((BOOTSTRAP_DRAWS - 1) * 0.975)]
    return {"status": "family_bootstrap", "lower": round(lower, 2), "upper": round(upper, 2)}


def _score(result: dict | None) -> float | None:
    if result is None or result["status"] not in SCORED:
        return None
    score = result["score"]
    if score is None and result["status"] != "passed":
        return 0
    if not _number(score, 100):
        raise ValueError("invalid score for scored trial")
    return score


def _summarize(trials: list[tuple[dict, dict | None]]) -> dict:
    families: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    scored = 0
    for trial, result in trials:
        variant_scores = families[trial["family_id"]][trial["variant_id"]]
        score = _score(result)
        if score is not None:
            variant_scores.append(score)
            scored += 1
    family_means = []
    for _, variants in sorted(families.items()):
        variant_means = [fmean(scores) for scores in variants.values() if scores]
        if variant_means:
            family_means.append(fmean(variant_means))
    complete = bool(trials) and scored == len(trials)
    return {
        "score": round(fmean(family_means), 2) if family_means else None,
        "scored_trials": scored,
        "planned_trials": len(trials),
        "scored_families": len(family_means),
        "planned_families": len(families),
        "coverage": round(scored / len(trials), 6) if trials else None,
        "uncertainty": _uncertainty(family_means, complete),
    }


def _aggregate_measurements(attempts: list[dict], key: str) -> tuple[float | None, int]:
    values = [attempt[key] for attempt in attempts if attempt[key] is not None]
    if any(not _number(value) for value in values):
        raise ValueError("invalid trial measurement")
    unknown = len(attempts) - len(values)
    return (round(math.fsum(values), 8) if values and not unknown else None, unknown)


def _report_row(plan: dict, trials: list[dict], attempts_by_trial: dict[str, list[dict]]) -> dict:
    first = trials[0]
    config_fields = ("model_id", "agent_id", "config_digest")
    for trial in trials:
        if any(trial[field] != first[field] for field in config_fields):
            raise ValueError("configuration mixes model or agent settings")
    pairs = []
    attempts = []
    for trial in trials:
        history = attempts_by_trial.get(trial["trial_id"], [])
        attempts.extend(history)
        pairs.append((trial, max(history, key=lambda result: result["attempt"], default=None)))

    statuses = Counter(result["status"] if result else "missing" for _, result in pairs)
    dimensions = {
        dim: _summarize([(trial, result) for trial, result in pairs if trial["dimension"] == dim])
        for dim in DIMENSIONS
    }
    subtypes = sorted({trial["subtype"] for trial in trials if trial.get("subtype") in PUBLIC_SUBTYPES})
    task_types = {
        subtype: _summarize([(trial, result) for trial, result in pairs if trial.get("subtype") == subtype])
        for subtype in subtypes
    }
    scored = sum(dimension["scored_trials"] for dimension in dimensions.values())
    complete = scored == len(trials)
    enough_families = all(dimension["scored_families"] >= MIN_FAMILIES for dimension in dimensions.values())
    weights = plan["score_weights"]
    if not isinstance(weights, dict) or set(weights) != set(DIMENSIONS) or any(
        not _number(weight) or weight <= 0 for weight in weights.values()
    ):
        raise ValueError("invalid frozen dimension weights")
    composite = None
    if complete and enough_families:
        composite = round(
            sum(dimensions[dim]["score"] * weights[dim] for dim in DIMENSIONS) / sum(weights.values()), 2
        )
    conditions = {
        "protocol_version": plan["protocol_version"],
        "taskset_id": plan["taskset_id"],
        "taskset_version": plan["taskset_version"],
        "budget_id": plan["budget_id"],
        "budget_digest": plan["budget_digest"],
        "trial_microusd": plan["trial_microusd"],
        "tools_profile": plan["tools_profile"],
        "environment": plan["environment"],
        "engine_digest": plan.get("engine_digest"),
        "score_weights": weights,
        "trials": sorted(
            ([trial.get(field) for field in TRIAL_CONDITIONS] for trial in trials),
            key=lambda item: json.dumps(item, ensure_ascii=False, separators=(",", ":")),
        ),
    }
    cost, unknown_cost = _aggregate_measurements(attempts, "cost_usd")
    duration, unknown_duration = _aggregate_measurements(attempts, "duration_seconds")
    return {
        "run_id": plan["run_id"],
        "mode": plan["mode"],
        "config_id": first["config_id"],
        "config_digest": first["config_digest"],
        "model_id": first["model_id"],
        "agent_id": first["agent_id"],
        "protocol_version": plan["protocol_version"],
        "taskset_id": plan["taskset_id"],
        "taskset_version": plan["taskset_version"],
        "budget_id": plan["budget_id"],
        "tools_profile": plan["tools_profile"],
        "cohort": digest(conditions),
        "state": "complete" if complete else "provisional",
        "planned_trials": len(trials),
        "scored_trials": scored,
        "attempts": len(attempts),
        "success_rate": round(statuses["passed"] / scored, 6) if scored else None,
        "failure_types": {status: statuses[status] for status in STATUSES},
        "attempt_statuses": dict(Counter(attempt["status"] for attempt in attempts)),
        "cost_usd": cost,
        "unknown_cost_attempts": unknown_cost,
        "duration_seconds": duration,
        "unknown_duration_attempts": unknown_duration,
        "dimensions": dimensions,
        "task_types": task_types,
        "composite_score": composite,
    }


def build_public_report(plans: Iterable[dict], results: Iterable[dict]) -> dict:
    """Project trusted plans and trial metadata into a disclosure-safe aggregate."""
    expected = {}
    grouped = []
    run_ids = set()
    for plan in plans:
        run_id = plan["run_id"]
        if run_id in run_ids:
            raise ValueError("duplicate run")
        run_ids.add(run_id)
        configurations: dict[str, list[dict]] = defaultdict(list)
        families = {}
        repeats = set()
        for trial in plan["expected_trials"]:
            trial_id = trial["trial_id"]
            dimension = trial["dimension"]
            if (trial_id in expected or dimension not in DIMENSIONS
                    or families.setdefault(trial["family_id"], dimension) != dimension):
                raise ValueError("duplicate trial or invalid task dimension")
            repetition = (trial["config_id"], trial["family_id"], trial["variant_id"], trial["repeat"])
            if repetition in repeats:
                raise ValueError("duplicate planned repeat")
            repeats.add(repetition)
            expected[trial_id] = plan
            configurations[trial["config_id"]].append(trial)
        if not configurations:
            raise ValueError("empty run plan")
        grouped.extend((plan, trials) for trials in configurations.values())

    attempts_by_trial: dict[str, list[dict]] = defaultdict(list)
    attempt_ids = set()
    attempt_numbers = set()
    for result in results:
        trial_id = result["trial_id"]
        attempt = result["attempt"]
        plan = expected.get(trial_id)
        if (plan is None or result["run_id"] != plan["run_id"] or result["mode"] != plan["mode"]
                or result["protocol_version"] != plan["protocol_version"] or result["status"] not in STATUSES
                or type(attempt) is not int or attempt < 1 or result["attempt_id"] in attempt_ids
                or (trial_id, attempt) in attempt_numbers):
            raise ValueError("trial result mismatches its plan or duplicates an attempt")
        attempt_ids.add(result["attempt_id"])
        attempt_numbers.add((trial_id, attempt))
        attempts_by_trial[trial_id].append(result)
    rows = [_report_row(plan, trials, attempts_by_trial) for plan, trials in grouped]
    provisional_runs = {row["run_id"] for row in rows if row["state"] == "provisional"}
    for row in rows:
        row["batch_state"] = "provisional" if row["run_id"] in provisional_runs else "complete"
        if row["batch_state"] == "provisional":
            row["composite_score"] = None
    rows.sort(key=lambda row: (row["run_id"], row["config_id"]))
    report = {"schema_version": "1.0", "rows": rows}
    validate_public_report(report)
    return report


def _number(value: Any, maximum: float = math.inf) -> bool:
    if type(value) is int:
        return 0 <= value <= min(maximum, 2 ** 53 - 1)
    return type(value) is float and 0 <= value <= maximum and math.isfinite(value)


def _integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:+/-]{0,127}", value) is not None


def _hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _nullable(check):
    return lambda value: value is None or check(value)


def _exact(value: Any, shape: dict, field: str) -> None:
    if not isinstance(value, dict) or value.keys() != shape.keys():
        raise ValueError(f"unexpected fields in {field}")
    for key, check in shape.items():
        if not check(value[key]):
            raise ValueError(f"invalid public field {field}.{key}")


_SCORE = _nullable(lambda value: _number(value, 100))
_RATE = _nullable(lambda value: _number(value, 1))
_MEASUREMENT = _nullable(_number)


def _validate_summary(summary: dict) -> bool:
    _exact(summary, {
        "score": _SCORE,
        "scored_trials": _integer,
        "planned_trials": _integer,
        "scored_families": _integer,
        "planned_families": _integer,
        "coverage": _RATE,
        "uncertainty": lambda value: isinstance(value, dict),
    }, "task summary")
    uncertainty = summary["uncertainty"]
    _exact(uncertainty, {
        "status": lambda value: value in ("insufficient", "family_bootstrap"),
        "lower": _SCORE,
        "upper": _SCORE,
    }, "uncertainty")
    scored, planned = summary["scored_trials"], summary["planned_trials"]
    if (scored > planned or summary["scored_families"] > min(summary["planned_families"], scored)
            or summary["planned_families"] > planned or bool(scored) != (summary["score"] is not None)
            or summary["coverage"] != (round(scored / planned, 6) if planned else None)):
        raise ValueError("inconsistent task summary")
    lower, upper = uncertainty["lower"], uncertainty["upper"]
    if uncertainty["status"] == "family_bootstrap":
        if scored != planned or summary["scored_families"] < MIN_FAMILIES or lower is None or upper is None or lower > upper:
            raise ValueError("inconsistent confidence interval")
    elif lower is not None or upper is not None:
        raise ValueError("insufficient evidence cannot have a confidence interval")
    return True


def _validate_dimensions(value: dict) -> bool:
    _exact(value, dict.fromkeys(DIMENSIONS, _validate_summary), "dimensions")
    return True


def _validate_task_types(value: Any) -> bool:
    return isinstance(value, dict) and set(value) <= PUBLIC_SUBTYPES and all(_validate_summary(item) for item in value.values())


def _validate_statuses(value: dict) -> bool:
    _exact(value, dict.fromkeys(STATUSES, _integer), "failure types")
    return True


def _validate_attempt_statuses(value: Any) -> bool:
    return isinstance(value, dict) and set(value) <= RUN_STATUSES and all(_integer(count) for count in value.values())


def validate_public_report(payload: dict) -> None:
    """Reject extra fields, non-finite numbers and inconsistent public rows."""
    _exact(payload, {
        "schema_version": lambda value: value == "1.0",
        "rows": lambda value: isinstance(value, list),
    }, "report")
    keys = set()
    provisional_runs = set()
    for row in payload["rows"]:
        _exact(row, {
            "run_id": _identifier,
            "mode": lambda value: isinstance(value, str) and value in MODES,
            "config_id": is_token,
            "config_digest": _hash,
            "model_id": _identifier,
            "agent_id": _identifier,
            "protocol_version": _identifier,
            "taskset_id": _identifier,
            "taskset_version": _identifier,
            "budget_id": _identifier,
            "tools_profile": _identifier,
            "cohort": _hash,
            "state": lambda value: value in ("complete", "provisional"),
            "batch_state": lambda value: value in ("complete", "provisional"),
            "planned_trials": _integer,
            "scored_trials": _integer,
            "attempts": _integer,
            "success_rate": _RATE,
            "failure_types": _validate_statuses,
            "attempt_statuses": _validate_attempt_statuses,
            "cost_usd": _MEASUREMENT,
            "unknown_cost_attempts": _integer,
            "duration_seconds": _MEASUREMENT,
            "unknown_duration_attempts": _integer,
            "dimensions": _validate_dimensions,
            "task_types": _validate_task_types,
            "composite_score": _SCORE,
        }, "public row")
        key = row["run_id"], row["config_id"]
        planned, scored = row["planned_trials"], row["scored_trials"]
        statuses = row["failure_types"]
        if (
            key in keys or not planned or not 0 <= scored <= planned
            or row["state"] != ("complete" if scored == planned else "provisional")
            or sum(statuses.values()) != planned or sum(statuses[status] for status in SCORED) != scored
            or row["success_rate"] != (round(statuses["passed"] / scored, 6) if scored else None)
            or sum(value["planned_trials"] for value in row["dimensions"].values()) != planned
            or sum(value["scored_trials"] for value in row["dimensions"].values()) != scored
            or row["attempts"] < planned - statuses["missing"]
            or sum(row["attempt_statuses"].values()) != row["attempts"]
        ):
            raise ValueError("inconsistent public row")
        for metric, unknown in (("cost_usd", "unknown_cost_attempts"), ("duration_seconds", "unknown_duration_attempts")):
            if row[unknown] > row["attempts"] or (row[metric] is None) != (row[unknown] > 0 or not row["attempts"]):
                raise ValueError("inconsistent public measurement")
        if row["composite_score"] is not None and (
            row["batch_state"] != "complete"
            or any(value["scored_families"] < MIN_FAMILIES for value in row["dimensions"].values())
        ):
            raise ValueError("public composite lacks complete dimension coverage")
        if row["state"] == "provisional":
            provisional_runs.add(row["run_id"])
        keys.add(key)
    if any(row["batch_state"] != ("provisional" if row["run_id"] in provisional_runs else "complete")
           for row in payload["rows"]):
        raise ValueError("inconsistent batch state")


def publish_site(payload: dict, web_dir: Path, output_dir: Path) -> None:
    """Write a fresh Pages tree using only checked-in assets and validated data."""
    validate_public_report(payload)
    web_dir, output_dir = Path(web_dir).resolve(), Path(output_dir).resolve()
    if web_dir == output_dir or (output_dir.exists() and any(output_dir.iterdir())):
        raise ValueError("site output must be a new or empty directory")
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    for name in SITE_FILES:
        source = web_dir / name
        if not source.is_file() or source.is_symlink():
            raise ValueError("missing checked-in site asset")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in SITE_FILES:
        shutil.copyfile(web_dir / name, output_dir / name)
    (output_dir / "data.json").write_text(encoded, encoding="utf-8")
    (output_dir / ".nojekyll").touch()
