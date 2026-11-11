"""Command-line entry point for planning, running, rescoring and publishing."""

import argparse
from pathlib import Path
from subprocess import SubprocessError
import shutil
import sys
import time
import uuid

from .archive import PrivateArchive, assert_claim, plan_path, trial_path
from .execution import ensure_workspace, grade_submission, restore_interrupted, result_path, run_trial, validate_bundle
from .grading import docker_prepare
from .protocol import BenchError, PUBLIC_TASKSETS, ROOT, batches, create_plan, encoded, identifier, load_tasks, read_json, require, taskset_tasks, verify_plan, write_json
from .reporting import build_public_report, publish_site, validate_public_report
from .transport import OpenAITransport


def check_public_boundary(plan, results):
    marker = "PRIVATE-CANARY-" + uuid.uuid4().hex
    probe = [dict(record, private_marker=marker) for record in results]
    report = build_public_report([dict(plan, private_marker=marker)], probe)
    require(marker.encode() not in encoded(report), "private_marker_in_public_report")
    try:
        validate_public_report(dict(report, private_marker=marker))
    except ValueError:
        return report
    raise BenchError("public_report_accepted_unlisted_field")


def check_docker_boundary(image):
    import tempfile

    from .execution import materialize
    from .grading import CandidateEnvironment

    ensure_workspace()
    docker_prepare(image)
    with tempfile.TemporaryDirectory(prefix="boundary-", dir=ROOT / ".bench") as directory:
        root = Path(directory).resolve()
        candidate = root / "candidate"
        candidate.mkdir()
        (root / "private-answer.txt").write_text("PRIVATE-ANSWER-" + uuid.uuid4().hex, encoding="utf-8")
        materialize(candidate, {"solution.py": (
            "import json, os\n"
            "from pathlib import Path\n"
            "readable = Path('/private-answer.txt').exists() or Path('../private-answer.txt').exists()\n"
            "secret_names = ('OPENAI_API_KEY','BENCH_TASKS_TOKEN','BENCH_EVIDENCE_TOKEN','GITHUB_TOKEN')\n"
            "sentinel = Path('/tmp/prior-run-state')\n"
            "fresh = not sentinel.exists()\n"
            "sentinel.write_text('new state')\n"
            "print(json.dumps({'clean': fresh and not readable and not Path('/var/run/docker.sock').exists()"
            " and not any(name in os.environ for name in secret_names)}))\n"
        )})
        env = CandidateEnvironment("docker", image, candidate, "solution.py", time.monotonic() + 25)
        require(env.run({}) == {"clean": True}, "docker_boundary_probe_failed")
        require(env.run({}) == {"clean": True}, "docker_state_reset_probe_failed")


def loaded_plan(args):
    plan = read_json(args.plan)
    return plan, verify_plan(plan, getattr(args, "private_tasks", None))


def collect_results(plan, tasks, directory):
    require(directory.is_dir(), "results_directory_missing")
    records = []
    for trial in plan["expected_trials"]:
        task = tasks[trial["task_id"]]
        prior = None
        for attempt in range(1, plan["budget"]["retries"] + 2):
            path = result_path(directory, trial, attempt)
            if not path.is_file():
                continue
            record = validate_bundle(plan, trial, task, attempt, read_json(path))
            if attempt > 1:
                require(prior is not None and prior["status"] == "api_error"
                        and record["retry_of"] == prior["attempt_id"]
                        and (record["retry_reason"] in {"http_429", "http_502", "http_503", "http_504"}
                             or (record["status"] == "missing" and record["retry_reason"] == "interrupted_retry")),
                        "invalid_retry_history")
            records.append(record)
            prior = record
    return records


def self_check(args):
    ensure_workspace()
    tasks = taskset_tasks(args.taskset)
    run_key = args.run_key or f"{args.taskset}-self-check"
    plan = create_plan(args.taskset, "controls", "zero", 1, "platform_validation", run_key, args.backend, tasks)
    families = len({task.spec["family_id"] for task in tasks.values()})
    if args.taskset == "public-six":
        require(len(tasks) == families == 6, "public_six_families_required")
    if args.backend == "docker":
        check_docker_boundary(plan["environment"])
    write_json(args.output / "plan.json", plan)
    attempts = []
    control_scores = []
    for trial in plan["expected_trials"]:
        task = tasks[trial["task_id"]]
        record = run_trial(plan, trial, task, args.output / "evidence")
        if trial["model_id"] == "oracle":
            require(record["status"] == "passed" and record["score"] == 100, "oracle_control_failed")
        else:
            require(record["status"] == "model_error" and record["score"] is not None
                    and record["score"] <= task.spec["wrong_max_score"], "wrong_control_not_rejected")
        attempts.append(record)
        control_scores.append({"task": trial["task_id"], "fixture": trial["model_id"], "score": record["score"],
                               "raw_score": record["grade"]["raw_score"]})
    for task in tasks.values():
        if args.taskset == "public-six" and task.spec["dimension"] != "maintenance_architecture":
            continue
        status, grade, _, _ = grade_submission(task, task.fixture("starter"), args.backend, plan["environment"], time.monotonic() + 180)
        require(status == "model_error" and grade is not None and grade["score"] < 100, "starter_bug_not_rejected")
        control_scores.append({"task": task.spec["task_id"], "fixture": "starter", "score": grade["score"],
                               "raw_score": grade["raw_score"]})
    require(collect_results(plan, tasks, args.output / "evidence") == attempts, "evidence_recalculation_failed")
    report = check_public_boundary(plan, attempts)
    write_json(args.output / "checks.json", {"backend": args.backend, "scores": control_scores, "docker_boundary": args.backend == "docker"})
    publish_site(report, ROOT / "web", args.output / "site")
    print(f"platform_validation: {families} families, {len(attempts)} control trials")


def run(args):
    if args.command == "doctor":
        status = {name: shutil.which(name) is not None for name in ("docker", "harbor", "git", "uv", "node")}
        status["python"] = sys.version.split()[0]
        print(encoded(status).decode())
        return
    if args.command == "validate":
        tasks = taskset_tasks(args.taskset or ("private" if args.private_tasks else "public-six"), args.private_tasks)
        print(f"validated_tasks={len(tasks)}")
        return
    if args.command == "self-check":
        self_check(args)
        return
    if args.command == "plan":
        tasks = taskset_tasks(args.taskset, args.private_tasks)
        plan = create_plan(args.taskset, args.models, args.budget, args.repeats, args.mode, args.run_key, args.backend, tasks)
        write_json(args.output, plan)
        print(f"planned_trials={len(plan['expected_trials'])}")
        return
    if args.command == "matrix":
        plan = read_json(args.plan)
        groups = batches(plan)
        require(groups, "empty_matrix")
        if args.batch_count:
            print(len(groups))
        else:
            require(0 <= args.batch < len(groups), "unknown_matrix_batch")
            print(encoded({"include": [{"trial_id": identifier(trial["trial_id"])} for trial in groups[args.batch]]}).decode())
        return
    if args.command in {"public-validate", "site"}:
        report = read_json(args.input) if args.input else build_public_report([], [])
        validate_public_report(report)
        if args.command == "site":
            publish_site(report, ROOT / "web", args.output)
        return
    if args.command == "harbor-smoke":
        from .harbor import smoke

        smoke(args.output)
        return
    if args.command == "archived-plan":
        archive = PrivateArchive.from_environment()
        plan = archive.get(plan_path({"run_id": args.run_id}))
        require(plan is not None, "archived_plan_unavailable")
        verify_plan(plan, args.private_tasks)
        write_json(args.output, plan)
        return
    plan, tasks = loaded_plan(args)
    if args.command == "claim":
        require(plan["mode"] != "platform_validation", "claim_requires_paid_mode")
        OpenAITransport.from_environment()
        archive = PrivateArchive.from_environment()
        check_public_boundary(plan, [])
        check_docker_boundary(plan["environment"])
        archive.create(plan_path(plan), plan)
    elif args.command == "trial":
        require(plan["backend"] == args.backend, "backend_plan_mismatch")
        trial = next((trial for trial in plan["expected_trials"] if trial["trial_id"] == args.trial_id), None)
        require(trial is not None, "unknown_trial")
        archive = PrivateArchive.from_environment() if args.archive else None
        record = run_trial(plan, trial, tasks[trial["task_id"]], args.output, archive)
        print(record["status"])
    elif args.command == "restore":
        archive = PrivateArchive.from_environment()
        assert_claim(archive, plan)
        restored = 0
        args.output.mkdir(parents=True, exist_ok=True)
        for trial in plan["expected_trials"]:
            for attempt in range(1, plan["budget"]["retries"] + 2):
                bundle = archive.get(trial_path(plan, trial, f"attempt-{attempt}"))
                if bundle is None:
                    reservation = archive.get(trial_path(plan, trial, f"reservation-{attempt}"))
                    if reservation is not None:
                        bundle = restore_interrupted(plan, trial, tasks[trial["task_id"]], attempt, reservation)
                        write_json(result_path(args.output, trial, attempt), bundle)
                    break
                validate_bundle(plan, trial, tasks[trial["task_id"]], attempt, bundle)
                write_json(result_path(args.output, trial, attempt), bundle)
                restored += 1
        print(f"restored_attempts={restored}")
    elif args.command == "publish":
        records = collect_results(plan, tasks, args.results)
        report = check_public_boundary(plan, records)
        if args.previous:
            previous = read_json(args.previous)
            validate_public_report(previous)
            report["rows"] = [row for row in previous["rows"] if row["run_id"] != plan["run_id"]] + report["rows"]
        publish_site(report, ROOT / "web", args.output)
    elif args.command in {"rescore", "regrade"}:
        trial = next((trial for trial in plan["expected_trials"] if trial["trial_id"] == args.trial_id), None)
        require(trial is not None, "unknown_trial")
        require(1 <= args.attempt <= plan["budget"]["retries"] + 1, "unknown_attempt")
        original = tasks[trial["task_id"]]
        bundle = read_json(args.evidence)
        record = validate_bundle(plan, trial, original, args.attempt, bundle)
        if args.command == "rescore":
            write_json(args.output, {"attempt_id": record["attempt_id"], "scorer_digest": record["scorer_digest"], "grade": record["grade"]})
        else:
            task = load_tasks(args.scorers, original.spec["status"]).get(trial["task_id"])
            require(task is not None and task.spec["scorer_version"] == args.scorer_version
                    and task.files == original.files and bundle["submission"] is not None,
                    "regrade_requires_compatible_task_and_submission")
            ensure_workspace()
            require(plan["backend"] == "docker", "regrade_requires_docker_plan")
            docker_prepare(plan["environment"])
            status, grade, observations, cases = grade_submission(
                task, bundle["submission"], "docker", plan["environment"], time.monotonic() + plan["budget"]["wall_seconds"],
            )
            write_json(args.output, {"attempt_id": record["attempt_id"], "status": status,
                                     "scorer_version": task.spec["scorer_version"], "scorer_digest": task.scorer_digest,
                                     "grade": grade, "observations": observations, "cases": cases})


def parser():
    cli = argparse.ArgumentParser(prog="meguvizbench")
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    validate = commands.add_parser("validate")
    validate.add_argument("--taskset", choices=[*PUBLIC_TASKSETS, "private"])
    validate.add_argument("--private-tasks", type=Path)
    check = commands.add_parser("self-check")
    check.add_argument("--output", type=Path, required=True)
    check.add_argument("--backend", choices=["local", "docker"], default="docker")
    check.add_argument("--taskset", choices=PUBLIC_TASKSETS, default="public-six")
    check.add_argument("--run-key")
    plan = commands.add_parser("plan")
    plan.add_argument("--taskset", choices=[*PUBLIC_TASKSETS, "private"], required=True)
    plan.add_argument("--models", required=True)
    plan.add_argument("--budget", required=True)
    plan.add_argument("--repeats", type=int, required=True)
    plan.add_argument("--mode", required=True)
    plan.add_argument("--run-key", required=True)
    plan.add_argument("--backend", choices=["local", "docker"], default="docker")
    plan.add_argument("--output", type=Path, required=True)
    plan.add_argument("--private-tasks", type=Path)
    matrix = commands.add_parser("matrix")
    matrix.add_argument("--plan", type=Path, required=True)
    option = matrix.add_mutually_exclusive_group()
    option.add_argument("--batch", type=int, default=0)
    option.add_argument("--batch-count", action="store_true")
    for name in ("claim", "trial", "restore", "publish", "rescore", "regrade"):
        command = commands.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--private-tasks", type=Path)
        if name != "claim":
            command.add_argument("--output", type=Path, required=True)
        if name in {"trial", "rescore", "regrade"}:
            command.add_argument("--trial-id", required=True)
        if name == "trial":
            command.add_argument("--backend", choices=["local", "docker"], default="docker")
            command.add_argument("--archive", action="store_true")
        if name == "publish":
            command.add_argument("--results", type=Path, required=True)
            command.add_argument("--previous", type=Path)
        if name in {"rescore", "regrade"}:
            command.add_argument("--evidence", type=Path, required=True)
            command.add_argument("--attempt", type=int, default=1)
        if name == "regrade":
            command.add_argument("--scorers", type=Path, required=True)
            command.add_argument("--scorer-version", required=True)
    archived_plan = commands.add_parser("archived-plan")
    archived_plan.add_argument("--run-id", required=True)
    archived_plan.add_argument("--private-tasks", type=Path)
    archived_plan.add_argument("--output", type=Path, required=True)
    site = commands.add_parser("site")
    site.add_argument("--input", type=Path)
    site.add_argument("--output", type=Path, required=True)
    check_public = commands.add_parser("public-validate")
    check_public.add_argument("--input", type=Path, required=True)
    harbor = commands.add_parser("harbor-smoke")
    harbor.add_argument("--output", type=Path, required=True)
    return cli


def main():
    args = parser().parse_args()
    try:
        run(args)
    except BenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, IndexError, RecursionError, EOFError, SubprocessError):
        print("error: invalid_or_unavailable_input", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
