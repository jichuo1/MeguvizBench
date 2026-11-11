"""Generate a public Harbor package and verify the complete oracle handoff."""

import os
import shutil
import subprocess

from .grading import minimal_env
from .protocol import BenchError, presets, read_json, require, safe_file, taskset_tasks, write_json

HARBOR_CANDIDATE_VERSION = "0.25.0"


def stage_svg_package(output):
    task = taskset_tasks("public-six")["svg-sync-badge"]
    output.mkdir(parents=True)
    solution = output / "solution"
    tests = output / "tests"
    solution.mkdir()
    tests.mkdir()
    (output / "instruction.md").write_bytes((task.prompt + "\nWrite /app/badge.svg.\n").encode("utf-8"))
    (output / "task.toml").write_bytes((
        'artifacts = [{source = "/app/badge.svg", destination = "badge.svg"}]\n'
        '[agent]\ntimeout_sec = 30.0\n'
        '[verifier]\nenvironment_mode = "separate"\ntimeout_sec = 30.0\n'
        '[environment]\nnetwork_mode = "no-network"\ncpus = 1\nmemory_mb = 512\n'
        f'docker_image = "{presets()["image"]}"\n'
    ).encode())
    (solution / "badge.svg").write_bytes(task.fixture("oracle")["badge.svg"].encode("utf-8"))
    (solution / "solve.sh").write_bytes(b"#!/bin/sh\nset -eu\nmkdir -p /app\ncp /solution/badge.svg /app/badge.svg\n")
    (tests / "checks.py").write_bytes(safe_file(task.path, "checks.py"))
    (tests / "test.sh").write_bytes(b"#!/bin/sh\nset -eu\nmkdir -p /logs/verifier\npython /tests/grade.py\n")
    (tests / "grade.py").write_bytes((
        "from pathlib import Path\n"
        "import json\n"
        "from checks import evaluate\n"
        "observed = evaluate(Path('/app'), None)\n"
        "Path('/logs/verifier/criteria.json').write_text(json.dumps(observed))\n"
        "Path('/logs/verifier/reward.txt').write_text('1' if observed and all(value is True for value in observed.values()) else '0')\n"
    ).encode())
    return task


def smoke(output):
    harbor = shutil.which("harbor")
    require(harbor, "harbor_cli_unavailable")
    require(shutil.which("docker"), "docker_cli_unavailable")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = {**minimal_env(), "HARBOR_TELEMETRY": "off"}
    if os.name != "nt":
        env["LANG"] = "C.UTF-8"
    version = subprocess.run([harbor, "--version"], capture_output=True, timeout=15, env=env, check=False)
    (output / "version.txt").write_bytes(version.stdout + version.stderr)
    require(version.returncode == 0 and HARBOR_CANDIDATE_VERSION.encode() in (version.stdout + version.stderr).split(),
            "harbor_version_mismatch")
    dataset = output / "dataset"
    task = stage_svg_package(dataset / "svg-sync-badge")
    with (output / "run.log").open("xb") as log:
        try:
            execution = subprocess.run(
                [harbor, "run", "-p", str(dataset), "-a", "oracle", "-e", "docker", "-n", "1", "-r", "0",
                 "-o", str(output / "jobs"), "--job-name", "public-svg"],
                env=env, stdout=log, stderr=log, timeout=300, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BenchError("harbor_smoke_timeout") from exc
    require(execution.returncode == 0, "harbor_smoke_failed")
    jobs = output / "jobs" / "public-svg"
    trials = [path for path in jobs.iterdir() if path.is_dir() and (path / "verifier" / "reward.txt").is_file()]
    require(len(trials) == 1, "harbor_trial_evidence_missing")
    trial = trials[0]
    reward = (trial / "verifier" / "reward.txt").read_text(encoding="utf-8").strip()
    require(reward == "1", "harbor_oracle_not_verified")
    payload = read_json(trial / "result.json")
    require(not payload.get("exception_info") and payload.get("verifier_environment_mode") == "separate",
            "harbor_trial_did_not_complete_separate_verification")
    actual = safe_file(trial, "artifacts/badge.svg").decode("utf-8")
    require(actual == task.fixture("oracle")["badge.svg"], "harbor_artifact_mismatch")
    write_json(output / "verified.json", {"harbor_version": HARBOR_CANDIDATE_VERSION, "reward": 1, "trial": trial.name})
    print("harbor_platform_validation: public SVG oracle passed")
