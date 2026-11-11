"""Run isolated attempts and retain score evidence, candidate files and provider receipts."""

from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import os
import sys
import tempfile
import time

from . import PROTOCOL_VERSION
from .archive import assert_claim, trial_path
from .grading import CandidateEnvironment, DeadlineExceeded, EnvironmentError, docker_prepare, evaluate, score_observations
from .protocol import BenchError, ROOT, STATUSES, checked_relative, digest, encoded, fields, presets, require, sha, validate_submission, write_json
from .transport import BudgetExhausted, OpenAITransport, model_request, parse_submission, reserve, submission_prompt


def materialize(root, submission):
    if os.name == "posix":
        root.chmod(0o755)
    for name, contents in submission.items():
        path = root.joinpath(*checked_relative(name).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents.encode("utf-8"))
        if os.name == "posix":
            path.chmod(0o644)
            parent = path.parent
            while parent != root:
                parent.chmod(0o755)
                parent = parent.parent


def grade_status(grade):
    if grade["score"] is None:
        return "review_pending"
    return "passed" if grade["score"] == 100 else "model_error"


class PrivateTrace:
    def __init__(self):
        self.preview = ""

    def write(self, text):
        self.preview += text[:max(0, 2048 - len(self.preview))]
        return len(text)

    def flush(self):
        pass


def grade_submission(task, submission, backend, image, deadline):
    validate_submission(submission, task.files)
    with tempfile.TemporaryDirectory(prefix="candidate-", dir=ROOT / ".bench") as directory:
        root = Path(directory).resolve()
        materialize(root, submission)
        env = CandidateEnvironment(backend, image, root, task.spec["submission"]["entrypoint"], deadline)
        observations = None
        grade = None
        trace = PrivateTrace()
        try:
            with redirect_stdout(trace), redirect_stderr(trace):
                observations = evaluate(task, root, env.run)
            grade = score_observations(task.spec, observations)
            status = grade_status(grade)
        except DeadlineExceeded:
            status = "timeout"
        except EnvironmentError:
            status = "environment_error"
        except Exception as exc:
            # Trusted scorer exceptions are captured privately; never print candidate-derived values.
            status = "verifier_error"
            env.observations.append({"status": "verifier_error", "error": type(exc).__name__})
        if trace.preview:
            env.observations.append({"status": "private_verifier_trace", "preview": trace.preview})
        if time.monotonic() > deadline and status in {"passed", "model_error", "review_pending"}:
            grade = None
            status = "timeout"
        return status, grade, observations, env.observations


def ensure_workspace():
    path = ROOT / ".bench"
    path.mkdir(exist_ok=True)
    require(not path.is_symlink() and not path.is_junction(), "unsafe_evidence_work_directory")


def result_record(plan, trial, task, attempt, status, started, grade, submission, receipt, cost, reason):
    attempt_id = trial["trial_id"] + f"-a{attempt}"
    return {
        "protocol_version": PROTOCOL_VERSION, "run_id": plan["run_id"], "trial_id": trial["trial_id"],
        "attempt_id": attempt_id, "attempt": attempt, "mode": plan["mode"], "status": status,
        "score": grade["score"] if grade is not None else None,
        "duration_seconds": round(time.monotonic() - started, 3),
        "cost_usd": cost / 1_000_000 if cost is not None else None,
        "task": trial, "source": task.spec["source"], "task_status": task.spec["status"],
        "scorer_digest": task.scorer_digest, "task_digest": task.content_digest,
        "plan_digest": digest(plan), "taskset_version": plan["taskset_version"],
        "environment": plan["environment"], "controller_python": sys.version.split()[0],
        "budget_id": plan["budget_id"], "trial_microusd": plan["trial_microusd"],
        "calls": int(bool(receipt and receipt["called"])),
        "live_verified": bool(receipt and receipt.get("http_status") == 200 and receipt.get("usage") is not None),
        "cost_status": "unknown" if cost is None else ("estimated" if receipt and receipt["called"] else "no_api_call"),
        "submission_hashes": {path: sha(contents.encode("utf-8")) for path, contents in submission.items()} if submission is not None else None,
        "grade": grade, "retry_of": trial["trial_id"] + f"-a{attempt - 1}" if attempt > 1 else None,
        "retry_reason": reason,
        "evidence_key": trial_path(plan, trial, f"attempt-{attempt}"),
    }


def result_path(root, trial, attempt):
    return root / trial["trial_id"] / f"attempt-{attempt}.json"


def save_attempt(output, plan, trial, archive, bundle):
    attempt = bundle["result"]["attempt"]
    if archive is not None:
        archive.create(trial_path(plan, trial, f"attempt-{attempt}"), bundle)
    write_json(result_path(output, trial, attempt), bundle)


def restore_interrupted(plan, trial, task, attempt, reservation):
    fields(reservation, "request_sha256 reserved_microusd", "invalid_request_reservation")
    reserved = reservation["reserved_microusd"]
    require(type(reserved) is int and 0 < reserved <= plan["trial_microusd"], "invalid_request_reservation")
    receipt = {"called": False, "billing": "unknown", "reservation": reservation, "dispatch_state": "unknown"}
    record = result_record(plan, trial, task, attempt, "missing", time.monotonic(), None, None, receipt, None,
                           "interrupted_retry" if attempt > 1 else None)
    record["duration_seconds"] = None
    record["calls"] = None
    return {"result": record, "submission": None, "observations": None, "cases": [], "provider": receipt}


def run_trial(plan, trial, task, output, archive=None, fixture=None):
    ensure_workspace()
    paid = plan["mode"] != "platform_validation"
    require(not paid or (archive is not None and fixture is None and plan["backend"] == "docker"), "paid_trial_requires_private_archive")
    require(not paid or fixture is None, "invalid_paid_fixture")
    if paid:
        assert_claim(archive, plan)
    require(not result_path(output, trial, 1).exists(), "attempt_already_exists")
    started = time.monotonic()
    budget = plan["budget"]
    deadline = started + budget["wall_seconds"]
    backend = plan["backend"]
    image = plan["environment"]
    unsupported = not set(task.spec["capabilities"]) <= CandidateEnvironment.capabilities
    provider = None
    if paid and not unsupported:
        provider = OpenAITransport.from_environment()
    if paid:
        archive.create(trial_path(plan, trial, "claim"), {"plan_sha256": digest(plan)})
    preflight = "unsupported_configuration" if unsupported else None
    if preflight is None and backend == "docker":
        try:
            docker_prepare(image)
        except EnvironmentError:
            preflight = "environment_error"
    model = next(config for config in presets()["models"][plan["models_id"]] if config["id"] == trial["config_id"])
    remaining = plan["trial_microusd"]
    reason = None
    attempt_started = started
    for attempt in range(1, budget["retries"] + 2):
        status = preflight
        submission = grade = observations = receipt = None
        cases = []
        retryable = False
        cost = 0
        if status is None and not paid:
            submission = task.fixture(fixture or trial["model_id"])
        elif status is None:
            body = encoded(model_request(model, submission_prompt(task), budget["output_tokens"]))
            try:
                reserved = reserve(model, body, budget, remaining, budget["calls"] - attempt + 1)
                archive.create(trial_path(plan, trial, f"reservation-{attempt}"), {
                    "request_sha256": sha(body), "reserved_microusd": reserved,
                })
                reply = provider.complete(body, model, deadline, reserved)
                status, cost, receipt, retryable = reply.status, reply.cost, reply.receipt, reply.retryable
                remaining -= max(reserved, cost or 0)
                if status == "received":
                    try:
                        submission = parse_submission(reply.content, task.files)
                    except (ValueError, TypeError, UnicodeError, RecursionError):
                        status = "model_error"
            except BudgetExhausted:
                status = "budget_exhausted"
        if submission is not None:
            status, grade, observations, cases = grade_submission(task, submission, backend, image, deadline)
        record = result_record(plan, trial, task, attempt, status, attempt_started, grade, submission, receipt, cost, reason)
        bundle = {"result": record, "submission": submission, "observations": observations, "cases": cases, "provider": receipt}
        save_attempt(output, plan, trial, archive, bundle)
        if not (paid and retryable and status == "api_error" and attempt <= budget["retries"] and time.monotonic() + 2 < deadline):
            return record
        reason = f"http_{receipt['http_status']}"
        attempt_started = time.monotonic()
        time.sleep(2)
    raise BenchError("attempt_loop_invariant")


def validate_bundle(plan, trial, task, attempt, bundle):
    fields(bundle, "result submission observations cases provider", "invalid_bundle")
    record = bundle["result"]
    fields(record, "protocol_version run_id trial_id attempt_id attempt mode status score duration_seconds cost_usd task source task_status scorer_digest task_digest plan_digest taskset_version environment controller_python budget_id trial_microusd calls live_verified cost_status submission_hashes grade retry_of retry_reason evidence_key", "invalid_trial_result")
    require(record["protocol_version"] == PROTOCOL_VERSION and record["run_id"] == plan["run_id"]
            and record["trial_id"] == trial["trial_id"] and record["attempt"] == attempt
            and record["attempt_id"] == trial["trial_id"] + f"-a{attempt}" and record["mode"] == plan["mode"]
            and record["task"] == trial and record["plan_digest"] == digest(plan)
            and record["task_digest"] == task.content_digest and record["scorer_digest"] == task.scorer_digest
            and record["evidence_key"] == trial_path(plan, trial, f"attempt-{attempt}"), "bundle_identity_mismatch")
    require(record["status"] in STATUSES and (record["score"] is None or type(record["score"]) is int and 0 <= record["score"] <= 100), "invalid_trial_score")
    for key in ("duration_seconds", "cost_usd"):
        value = record[key]
        require(value is None or (type(value) in {int, float} and 0 <= value < float("inf")), "invalid_trial_measurement")
    require(record["environment"] == plan["environment"] and record["budget_id"] == plan["budget_id"]
            and record["taskset_version"] == plan["taskset_version"] and record["trial_microusd"] == plan["trial_microusd"]
            and record["source"] == task.spec["source"] and record["task_status"] == task.spec["status"], "bundle_metadata_mismatch")
    submission = bundle["submission"]
    hashes = None
    if submission is not None:
        validate_submission(submission, task.files)
        hashes = {key: sha(value.encode("utf-8")) for key, value in submission.items()}
    require(hashes == record["submission_hashes"], "submission_checksum_mismatch")
    if record["grade"] is not None:
        require(submission is not None, "grade_without_submission")
        grade = score_observations(task.spec, bundle["observations"])
        require(grade == record["grade"] and grade["score"] == record["score"]
                and grade_status(grade) == record["status"], "grade_evidence_mismatch")
    else:
        require(record["score"] is None and record["status"] not in {"passed", "review_pending"}, "score_without_grade")
    return record
