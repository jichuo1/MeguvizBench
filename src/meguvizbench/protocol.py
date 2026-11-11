"""Strict task and run contracts, with content-addressed plans."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import platform
import re

from . import PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parents[2]
DIMENSIONS = (
    "frontend_graphics", "systems_performance", "algorithms_data", "backend_consistency",
    "maintenance_architecture", "math_science", "research_evidence", "computer_use",
)
CAPABILITIES = {"shell", "browser", "desktop_gui", "android", "blender", "physical_device", "gpu"}
CRITERION_CATEGORIES = {"correctness", "regression", "structure", "constraint", "render", "visual", "performance"}
MODES = {"platform_validation", "pilot", "official"}
STATUSES = {
    "passed", "model_error", "budget_exhausted", "timeout", "unsupported_configuration",
    "environment_error", "api_error", "verifier_error", "cancelled", "missing", "review_pending",
}
TOKEN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}\Z")
FILE_PART = re.compile(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,79}\Z")
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{kind}{n}" for kind in ("COM", "LPT") for n in range(10)}
MAX_FILE = 64 * 1024
MAX_SUBMISSION = 128 * 1024
MAX_PROMPT = 48 * 1024
BATCH_SIZE = 128
PUBLIC_TASKSETS = {"public-six": "examples", "public-challenges": "challenges"}


class BenchError(ValueError):
    """Expected, user-visible failure with a stable code."""


def require(condition, code):
    if not condition:
        raise BenchError(code)


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, "duplicate_json_key")
        obj[key] = value
    return obj


def reject_constant(_value):
    raise BenchError("invalid_json_constant")


def decode(data):
    return json.loads(data, object_pairs_hook=unique_object, parse_constant=reject_constant)


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path, limit=8 * 1024 * 1024):
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, "document_too_large")
    return decode(data)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(encoded(data) + b"\n")


def fields(obj, keys, code="unexpected_fields"):
    require(type(obj) is dict and obj.keys() == set(keys.split()), code)


def is_token(value):
    return isinstance(value, str) and TOKEN.fullmatch(value) is not None and value not in {".", ".."}


def identifier(value):
    require(is_token(value), "invalid_identifier")
    return value


def checked_relative(value):
    require(isinstance(value, str) and len(value) <= 200, "invalid_submission_path")
    parts = value.split("/")
    require(
        len(parts) <= 6 and all(FILE_PART.fullmatch(part) and not part.endswith(".")
                                and part.split(".")[0].upper() not in RESERVED for part in parts),
        "invalid_submission_path",
    )
    return PurePosixPath(value)


def safe_file(root, relative, limit=MAX_FILE):
    path = root
    for part in checked_relative(relative).parts:
        path = path / part
        require(not path.is_symlink() and not path.is_junction(), "invalid_file_link")
    require(path.is_file(), "missing_file")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, "file_too_large")
    return data


def validate_submission(submission, allowed):
    require(type(submission) is dict and set(submission) == set(allowed), "submission_file_set_mismatch")
    require(all(type(value) is str for value in submission.values()), "submission_requires_utf8_text")
    sizes = [len(value.encode("utf-8")) for value in submission.values()]
    require(all(size <= MAX_FILE for size in sizes) and sum(sizes) <= MAX_SUBMISSION, "submission_too_large")
    return submission


def validate_task(spec):
    fields(spec, "task_id family_id variant_id version scorer_version dimension tags difficulty status source capabilities submission rubric caps wrong_max_score subtype")
    for key in ("task_id", "family_id", "variant_id", "version", "scorer_version"):
        identifier(spec[key])
    require(spec["dimension"] in DIMENSIONS, "invalid_dimension")
    require(spec["subtype"] is None or is_token(spec["subtype"]), "invalid_subtype")
    if spec["dimension"] == "frontend_graphics":
        require(spec["subtype"] in {"android", "web", "svg", "3d"}, "invalid_graphics_subtype")
    require(spec["difficulty"] in {"D1", "D2", "D3", "D4", "D5"}, "invalid_difficulty")
    require(spec["status"] in {"synthetic", "active"}, "invalid_task_status")
    fields(spec["source"], "project revision exposure")
    require(all(isinstance(x, str) and 0 < len(x) <= 300 for x in spec["source"].values()), "invalid_source")
    for key in ("tags", "capabilities"):
        values = spec[key]
        require(type(values) is list and all(is_token(x) for x in values), "invalid_task_labels")
        require(len(values) == len(set(values)), "duplicate_task_label")
    require(set(spec["capabilities"]) <= CAPABILITIES, "invalid_capability")
    files = spec["submission"]
    fields(files, "files entrypoint")
    require(type(files["files"]) is list and 1 <= len(files["files"]) <= 12, "invalid_file_list")
    paths = [str(checked_relative(path)).lower() for path in files["files"]]
    require(len(set(paths)) == len(paths), "duplicate_submission_path")
    require(not any(path.startswith(other + "/") for path in paths for other in paths), "overlapping_submission_paths")
    require(files["entrypoint"] is None or (files["entrypoint"] == "solution.py" and "solution.py" in files["files"]), "invalid_entrypoint")
    require(type(spec["rubric"]) is list and 1 <= len(spec["rubric"]) <= 100, "invalid_rubric")
    ids = set()
    total = 0
    for item in spec["rubric"]:
        fields(item, "id points evidence method failure category")
        key = identifier(item["id"])
        require(key not in ids, "duplicate_criterion")
        require(type(item["points"]) is int and 1 <= item["points"] <= 100, "invalid_points")
        require(all(type(item[name]) is str and item[name].strip() for name in ("evidence", "method", "failure", "category")), "missing_criterion_detail")
        require(item["category"] in CRITERION_CATEGORIES, "unknown_criterion_category")
        ids.add(key)
        total += item["points"]
    require(total == 100, "rubric_total_must_be_100")
    require(type(spec["caps"]) is list, "invalid_caps")
    for cap in spec["caps"]:
        fields(cap, "requires max_score")
        require(type(cap["requires"]) is list and bool(cap["requires"]) and set(cap["requires"]) <= ids, "invalid_cap_checks")
        require(type(cap["max_score"]) is int and 0 <= cap["max_score"] < 100, "invalid_cap_score")
    require(type(spec["wrong_max_score"]) is int and 0 <= spec["wrong_max_score"] < 100, "invalid_wrong_score")


@dataclass(frozen=True)
class Task:
    path: Path
    spec: dict
    prompt: str
    content_digest: str
    scorer_digest: str

    @property
    def files(self):
        return self.spec["submission"]["files"]

    def fixture(self, name):
        require(name in {"starter", "oracle", "wrong"}, "unknown_fixture")
        directory = self.path / name
        require(directory.is_dir() and not directory.is_symlink() and not directory.is_junction(), "invalid_fixture_directory")
        return validate_submission({path: safe_file(directory, path).decode("utf-8") for path in self.files}, self.files)


def load_tasks(root, status):
    require(root.is_dir() and not root.is_symlink() and not root.is_junction(), "task_root_unavailable")
    tasks = {}
    variants = set()
    family_dimensions = {}
    for path in sorted(root.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        require(not path.is_symlink() and not path.is_junction(), "invalid_task_link")
        spec = decode(safe_file(path, "task.json"))
        validate_task(spec)
        require(spec["status"] == status and spec["task_id"] == path.name and path.name not in tasks, "invalid_task_identity")
        family, variant = spec["family_id"], spec["variant_id"]
        require((family, variant) not in variants, "duplicate_family_variant")
        require(family_dimensions.setdefault(family, spec["dimension"]) == spec["dimension"], "mixed_family_dimensions")
        variants.add((family, variant))
        prompt = safe_file(path, "prompt.md", MAX_PROMPT).decode("utf-8")
        scorer_digest = sha(safe_file(path, "checks.py"))
        task = Task(path, spec, prompt, "", scorer_digest)
        fixtures = {name: task.fixture(name) for name in ("starter", "oracle", "wrong")}
        tasks[path.name] = Task(path, spec, prompt, digest([spec, prompt, scorer_digest, fixtures]), scorer_digest)
    require(0 < len(tasks) <= 100, "invalid_task_count")
    return tasks


def presets():
    config = read_json(ROOT / "configs" / "presets.json")
    models = config["models"]
    known = {model["id"]: model for model in models["pilot-two"]}
    for key in ("luna-only", "terra-only"):
        models[key] = [known[config_id] for config_id in models[key]]
    return config


def taskset_tasks(taskset, private_tasks=None):
    if taskset in PUBLIC_TASKSETS:
        require(private_tasks is None, "private_root_for_public_taskset")
        return load_tasks(ROOT / "tasks" / PUBLIC_TASKSETS[taskset], "synthetic")
    require(taskset == "private" and private_tasks is not None, "private_taskset_unavailable")
    return load_tasks(private_tasks, "active")


def environment(backend):
    if backend == "docker":
        return presets()["image"]
    require(backend == "local", "unknown_backend")
    return f"local-{platform.system().lower()}-{platform.machine().lower()}-python-{platform.python_version()}"


def create_plan(taskset, models, budget, repeats, mode, run_key, backend, tasks):
    require(mode in MODES and type(repeats) is int and 1 <= repeats <= 8, "invalid_plan_mode_or_repeats")
    identifier(run_key)
    config = presets()
    require(models in config["models"] and budget in config["budgets"], "unknown_preset")
    profile = config["budgets"][budget]
    if mode == "platform_validation":
        require(taskset in PUBLIC_TASKSETS and models == "controls" and budget == "zero", "invalid_control_plan")
    else:
        require(models != "controls" and profile["total_microusd"] > 0 and backend == "docker", "paid_plan_requires_positive_budget_and_docker")
        require((mode, taskset) in {("pilot", "public-six"), ("official", "private")}, "invalid_paid_taskset")
    run_id = "run-" + digest(run_key)[:24]
    taskset_version = digest({key: task.content_digest for key, task in tasks.items()})
    engine_digest = digest({path.name: sha(path.read_bytes()) for path in sorted(Path(__file__).parent.glob("*.py"))})
    expected = []
    for model in config["models"][models]:
        for task in tasks.values():
            for repeat in range(1, repeats + 1):
                spec = task.spec
                seed = int(digest([taskset_version, spec["task_id"], repeat])[:8], 16)
                trial_id = "trial-" + digest([run_id, model["id"], spec["task_id"], repeat])[:24]
                expected.append({
                    "trial_id": trial_id, "task_id": spec["task_id"], "family_id": spec["family_id"],
                    "variant_id": spec["variant_id"], "dimension": spec["dimension"], "tags": spec["tags"],
                    "difficulty": spec["difficulty"], "subtype": spec["subtype"],
                    "scorer_version": spec["scorer_version"], "task_version": spec["version"],
                    "model_id": model["model_id"], "agent_id": model["agent_id"], "config_id": model["id"],
                    "config_digest": digest(model), "seed": seed, "repeat": repeat,
                })
    quota = min(profile["trial_microusd"], profile["total_microusd"] // len(expected))
    require(mode == "platform_validation" or quota > 0, "insufficient_trial_budget")
    return {
        "protocol_version": PROTOCOL_VERSION, "mode": mode, "run_id": run_id, "run_key": run_key,
        "taskset_id": taskset, "taskset_version": taskset_version, "models_id": models,
        "budget_id": budget, "budget_digest": digest(profile), "budget": profile, "trial_microusd": quota,
        "repeats": repeats, "backend": backend, "environment": environment(backend), "engine_digest": engine_digest,
        "tools_profile": "no-network-json-stdin-v1", "score_weights": dict.fromkeys(DIMENSIONS, 1),
        "expected_trials": expected,
    }


def verify_plan(plan, private_tasks=None):
    keys = "protocol_version mode run_id run_key taskset_id taskset_version models_id budget_id budget_digest budget trial_microusd repeats backend environment engine_digest tools_profile score_weights expected_trials"
    fields(plan, keys, "invalid_run_spec")
    tasks = taskset_tasks(plan["taskset_id"], private_tasks)
    expected = create_plan(
        plan["taskset_id"], plan["models_id"], plan["budget_id"], plan["repeats"],
        plan["mode"], plan["run_key"], plan["backend"], tasks,
    )
    require(encoded(plan) == encoded(expected), "plan_does_not_match_frozen_configuration")
    return tasks


def batches(plan):
    trials = plan["expected_trials"]
    return [trials[start:start + BATCH_SIZE] for start in range(0, len(trials), BATCH_SIZE)]
