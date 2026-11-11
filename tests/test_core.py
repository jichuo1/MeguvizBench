from io import BytesIO
import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path

from meguvizbench.archive import PrivateArchive, pack, unpack
from meguvizbench.grading import bounded_process, minimal_env, score_observations
from meguvizbench.harbor import stage_svg_package
from meguvizbench.protocol import BenchError, batches, checked_relative, create_plan, encoded, presets, taskset_tasks
from meguvizbench.transport import BudgetExhausted, OpenAITransport, model_request, parse_submission, reserve, submission_prompt


class Response:
    def __init__(self, status, body):
        self.status = status
        self.data = BytesIO(encoded(body))

    def getheader(self, key):
        return "offline-receipt" if key == "x-request-id" else None

    def read(self, count):
        return self.data.read(count)

    def read1(self, count):
        return self.read(count)


class FakeConnection:
    def __init__(self, fixture, requests, host, timeout):
        self.fixture = fixture
        self.requests = requests
        self.host = host
        self.sock = None

    def request(self, method, path, body, headers):
        self.requests.append((self.host, method, path, body))
        self.response = self.fixture(method, path, body)

    def getresponse(self):
        return self.response

    def close(self):
        pass


class PlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = taskset_tasks("public-six")
        cls.model = presets()["models"]["pilot-two"][1]
        cls.budget = presets()["budgets"]["pilot"]

    def test_submission_is_exact_bounded_utf8_data(self):
        for path in ("../score.json", "a/../../x", "C:/outside", "a\\b", "con.txt", "file."):
            with self.subTest(path=path), self.assertRaises(BenchError):
                checked_relative(path)
        for text in ('{"solution.py":"","reward.json":"100"}', '{"solution.py":"","solution.py":"second"}'):
            with self.subTest(text=text), self.assertRaises(BenchError):
                parse_submission(text, ["solution.py"])

    def test_rubric_keeps_partial_credit_and_gates_performance(self):
        spec = {
            "rubric": [
                {"id": "core", "points": 30, "category": "correctness"},
                {"id": "other", "points": 60, "category": "structure"},
                {"id": "speed", "points": 10, "category": "performance"},
            ],
            "caps": [{"requires": ["core"], "max_score": 45}],
        }
        grade = score_observations(spec, {"core": False, "other": True, "speed": True})
        self.assertEqual((60, 45, "blocked"), (grade["raw_score"], grade["score"], grade["criteria"][2]["outcome"]))
        pending = score_observations(spec, {"core": True, "other": None, "speed": True})
        self.assertEqual((None, 40), (pending["score"], pending["measured_points"]))

    def test_paid_planning_and_dispatch_bounds(self):
        plan = create_plan("public-six", "pilot-two", "pilot", 2, "pilot", "pilot-plan", "docker", self.tasks)
        trials = plan["expected_trials"]
        self.assertEqual(len(trials), 24)
        self.assertEqual(trials[0]["seed"], trials[12]["seed"])
        self.assertNotEqual(trials[0]["trial_id"], trials[12]["trial_id"])
        self.assertLessEqual(len(trials) * plan["trial_microusd"], plan["budget"]["total_microusd"])
        with self.assertRaises(BenchError):
            create_plan("public-six", "pilot-two", "zero", 2, "pilot", "zero", "docker", self.tasks)
        with self.assertRaises(BenchError):
            create_plan("public-six", "pilot-two", "pilot", 2, "pilot", "local", "local", self.tasks)
        with self.assertRaises(BenchError):
            create_plan("public-challenges", "pilot-two", "pilot", 2, "pilot", "advanced", "docker", self.tasks)
        self.assertEqual([128, 128, 128, 48], list(map(len, batches({"expected_trials": list(range(432))}))))

    def test_transport_records_usage_and_limits_unknown_failures(self):
        task = self.tasks["svg-sync-badge"]
        prompt = submission_prompt(task)
        body = encoded(model_request(self.model, prompt, self.budget["output_tokens"]))
        self.assertNotIn(task.fixture("oracle")["badge.svg"].encode(), body)
        with self.assertRaises(BudgetExhausted):
            reserve(self.model, body, self.budget, 1, 2)
        limit = reserve(self.model, body, self.budget, 250000, 2)
        actual = {"model": self.model["model_id"], "choices": [{"finish_reason": "stop",
                  "message": {"content": '{"badge.svg":"offline"}'}}],
                  "usage": {"prompt_tokens": 1000, "completion_tokens": 40,
                            "prompt_tokens_details": {"cached_tokens": 200}}}
        requests = []

        def connection(status, payload):
            return lambda host, timeout: FakeConnection(lambda *_: Response(status, payload), requests, host, timeout)

        transport = OpenAITransport("offline-key", connection(200, actual))
        success = transport.complete(body, self.model, time.monotonic() + 5, limit)
        self.assertEqual(("received", 2120), (success.status, success.cost))
        self.assertEqual(("api.openai.com", "POST", "/v1/chat/completions"), requests[0][:3])
        failure = OpenAITransport("offline-key", connection(429, {})).complete(body, self.model, time.monotonic() + 5, limit)
        self.assertEqual(("api_error", None, True), (failure.status, failure.cost, failure.retryable))
        malformed = OpenAITransport("offline-key", connection(200, {"choices": []})).complete(
            body, self.model, time.monotonic() + 5, limit,
        )
        self.assertEqual(("api_error", None), (malformed.status, malformed.cost))

    def test_archive_rest_contract_is_private_create_only_and_recoverable(self):
        objects = {}
        requests = []
        path = "runs/run-123456789012345678901234/plan.json.gz"
        source = {"private": "synthetic-answer-canary", "trial_id": "example"}

        def service(method, url, body):
            if url == "/repos/example/evidence":
                return Response(200, {"private": True, "visibility": "private", "full_name": "example/evidence"})
            if method == "PUT":
                if url in objects:
                    return Response(422, {})
                from meguvizbench.protocol import decode
                decoded = decode(body)
                self.assertNotIn("sha", decoded)
                objects[url] = decoded["content"]
                return Response(201, {})
            return Response(200, {"encoding": "base64", "content": objects[url], "type": "file"})

        archive = PrivateArchive("example/evidence", "offline-token",
                                 lambda host, timeout: FakeConnection(service, requests, host, timeout))
        archive.create(path, source)
        self.assertEqual(archive.get(path), source)
        with self.assertRaisesRegex(BenchError, "archive_record_already_exists"):
            archive.create(path, {"replace": "would corrupt evidence"})
        tampered = pack({"data": "a"})
        self.assertEqual(unpack(tampered), {"data": "a"})
        with self.assertRaises((ValueError, OSError, EOFError)):
            unpack(tampered[:-5])
        public = lambda host, timeout: FakeConnection(
            lambda *_: Response(200, {"private": False, "visibility": "public"}), requests, host, timeout,
        )
        with self.assertRaisesRegex(BenchError, "evidence_repository_must_be_private"):
            PrivateArchive("example/evidence", "offline-token", public)

    def test_process_deadline(self):
        output = bounded_process([sys.executable, "-c", "import time; time.sleep(2)"], b"", None, minimal_env(), 0.05)
        self.assertEqual(output.status, "timeout")

    def test_harbor_package_fixes_separate_verifier_and_explicit_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "svg-sync-badge"
            stage_svg_package(output)
            config = tomllib.loads((output / "task.toml").read_text(encoding="utf-8"))
            self.assertEqual(config["verifier"]["environment_mode"], "separate")
            self.assertEqual(config["artifacts"][0]["source"], "/app/badge.svg")
            self.assertEqual(config["environment"]["network_mode"], "no-network")


if __name__ == "__main__":
    unittest.main()
