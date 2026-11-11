"""Keep expected answers and score calculation on the controller."""

from dataclasses import dataclass
from pathlib import Path
from contextlib import contextmanager
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from .protocol import BenchError, ROOT, decode, encoded, require, safe_file, sha

MAX_IO = 96 * 1024
DOCKER_PLATFORM = "linux/amd64"


class EnvironmentError(BenchError):
    """The runner failed to create or start a candidate process."""


class DeadlineExceeded(BenchError):
    """The trial exceeded its wall-clock allowance."""


@dataclass(frozen=True)
class ProcessOutput:
    code: int | None
    stdout: bytes
    stderr: bytes
    status: str


def bounded_process(argv, data, cwd, env, timeout):
    with subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env,
    ) as proc:
        streams = {}

        def read(name, stream):
            streams[name] = stream.read(MAX_IO + 1)
            if len(streams[name]) > MAX_IO and proc.poll() is None:
                proc.kill()

        def send():
            try:
                proc.stdin.write(data)
                proc.stdin.close()
            except (OSError, ValueError):
                pass

        readers = [
            threading.Thread(target=read, args=("stdout", proc.stdout), daemon=True),
            threading.Thread(target=read, args=("stderr", proc.stderr), daemon=True),
        ]
        for thread in readers:
            thread.start()
        threading.Thread(target=send, daemon=True).start()
        status = "finished"
        try:
            proc.wait(timeout=max(0.01, timeout))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            status = "timeout"
        for thread in readers:
            thread.join(timeout=0.5)
        if any(len(output) > MAX_IO for output in streams.values()):
            status = "output_limit"
        return ProcessOutput(proc.returncode, streams.get("stdout", b"")[:MAX_IO],
                             streams.get("stderr", b"")[:MAX_IO], status)


def minimal_env():
    keys = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"}
    return {key: value for key, value in os.environ.items() if key.upper() in keys}


@contextmanager
def docker_env():
    with tempfile.TemporaryDirectory(prefix="docker-config-", dir=ROOT / ".bench") as directory:
        yield {**minimal_env(), "DOCKER_CONFIG": directory}


def docker_prepare(image):
    if not shutil.which("docker"):
        raise EnvironmentError("docker_cli_unavailable")
    with docker_env() as env:
        inspect = bounded_process(["docker", "image", "inspect", image], b"", None, env, 15)
        if inspect.code == 0:
            return
        pull = bounded_process(["docker", "pull", "--platform", DOCKER_PLATFORM, image], b"", None, env, 120)
        if pull.code != 0 or pull.status != "finished":
            raise EnvironmentError("docker_image_unavailable")


class CandidateEnvironment:
    capabilities = frozenset({"shell"})

    def __init__(self, backend, image, root, entrypoint, deadline):
        self.backend = backend
        self.image = image
        self.root = root
        self.entrypoint = entrypoint
        self.deadline = deadline
        self.observations = []

    def run(self, request):
        require(self.entrypoint is not None, "task_has_no_entrypoint")
        require(len(self.observations) < 96, "too_many_verifier_cases")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise DeadlineExceeded("trial_deadline_exceeded")
        data = encoded(request)
        require(len(data) <= MAX_IO, "verifier_input_limit")
        if self.backend == "docker":
            result = self.run_docker(data, remaining)
        else:
            result = bounded_process(
                [sys.executable, "-E", "-s", "-B", self.entrypoint],
                data, self.root, minimal_env(), min(5, remaining),
            )
        output = None
        status = result.status
        if status == "finished" and result.code == 0:
            try:
                output = decode(result.stdout)
            except (ValueError, UnicodeError, RecursionError):
                status = "invalid_json"
        elif status == "finished":
            status = "candidate_exit"
        self.observations.append({
            "input_sha256": sha(data), "output_sha256": sha(result.stdout),
            "status": status, "exit_code": result.code,
            "stdout_preview": result.stdout[:256].decode("utf-8", errors="replace"),
            "stderr_preview": result.stderr[:256].decode("utf-8", errors="replace"),
        })
        return output

    def run_docker(self, data, remaining):
        with docker_env() as env:
            return self.run_docker_with_env(data, remaining, env)

    def run_docker_with_env(self, data, remaining, env):
        name = "mvbench-" + uuid.uuid4().hex
        create = [
            "docker", "create", "--name", name, "--platform", DOCKER_PLATFORM,
            "--network", "none", "--user", "65534:65534", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "32", "--cpus", "1",
            "--memory", "192m", "--memory-swap", "192m", "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m", "--log-driver", "none",
            "--interactive", "--workdir", "/submission",
            "--mount", f"type=bind,source={self.root},target=/submission,readonly",
            self.image, "python", "-E", "-s", "-B", self.entrypoint,
        ]
        require("," not in str(self.root), "unsupported_docker_mount_path")
        try:
            created = bounded_process(create, b"", None, env, min(10, remaining))
            if created.code != 0 or created.status != "finished":
                raise EnvironmentError("docker_create_failed")
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise DeadlineExceeded("trial_deadline_exceeded")
            result = bounded_process(["docker", "start", "-a", "-i", name], data, None, env, min(8, remaining))
            if result.status == "finished" and result.code != 0:
                state = bounded_process(
                    ["docker", "inspect", "--format", "{{json .State}}", name], b"", None, env, 5,
                )
                if state.code != 0 or not state.stdout:
                    raise EnvironmentError("docker_state_unavailable")
                state_info = decode(state.stdout)
                if state_info["Status"] != "exited" or state_info["Error"]:
                    raise EnvironmentError("docker_start_failed")
            return result
        finally:
            bounded_process(["docker", "rm", "-f", name], b"", None, env, 5)


def evaluate(task, candidate, run):
    source = safe_file(task.path, "checks.py")
    require(sha(source) == task.scorer_digest, "scorer_changed")
    namespace = {"__name__": "trusted_meguvizbench_checks"}
    exec(compile(source, str(task.path / "checks.py"), "exec"), namespace)
    return namespace["evaluate"](Path(candidate), run)


def score_observations(spec, observations):
    rubric = spec["rubric"]
    require(type(observations) is dict and set(observations) == {item["id"] for item in rubric}, "criterion_set_mismatch")
    require(all(value is None or type(value) is bool for value in observations.values()), "invalid_observation")
    criteria = []
    raw = 0
    core = [item["id"] for item in rubric if item["category"] in {"correctness", "regression", "constraint"}]
    performance_eligible = bool(core) and all(observations[key] is True for key in core)
    for item in rubric:
        outcome = observations[item["id"]]
        blocked = item["category"] == "performance" and not performance_eligible
        awarded = item["points"] if outcome is True and not blocked else 0
        raw += awarded
        criteria.append({
            **item, "outcome": "blocked" if blocked else "passed" if outcome is True else "failed" if outcome is False else "unmeasured",
            "awarded": awarded if outcome is not None or blocked else None,
        })
    caps = [cap for cap in spec["caps"] if any(observations[key] is False for key in cap["requires"])]
    effective_cap = min((cap["max_score"] for cap in caps), default=100)
    missing = sum(item["points"] for item in criteria if item["outcome"] == "unmeasured")
    return {
        "raw_score": raw, "score": min(raw, effective_cap) if not missing else None,
        "measured_points": 100 - missing, "active_caps": caps, "criteria": criteria,
    }
