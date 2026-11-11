"""Append-only, bounded evidence objects in a dedicated private repository."""

import base64
import gzip
from http.client import HTTPSConnection
import io
import os
import re
import time

from .protocol import BenchError, decode, digest, encoded, require, sha

MAX_PACKED = 700 * 1024
MAX_UNPACKED = 4 * 1024 * 1024
SLUG = re.compile(r"[a-zA-Z0-9-]{1,39}/[a-zA-Z0-9_.-]{1,100}\Z")
PATH = re.compile(r"runs/run-[a-f0-9]{24}/(?:plan|trial-[a-f0-9]{24}/(?:claim|reservation-[12]|attempt-[12]))\.json\.gz\Z")


def pack(value):
    body = encoded({"sha256": digest(value), "data": value})
    require(len(body) <= MAX_UNPACKED, "archive_object_unpacked_limit")
    compressed = gzip.compress(body, mtime=0)
    require(len(compressed) <= MAX_PACKED, "archive_object_packed_limit")
    return compressed


def unpack(data):
    require(len(data) <= MAX_PACKED, "archive_object_packed_limit")
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        body = stream.read(MAX_UNPACKED + 1)
    require(len(body) <= MAX_UNPACKED, "archive_object_unpacked_limit")
    record = decode(body)
    require(type(record) is dict and set(record) == {"sha256", "data"}, "invalid_archive_wrapper")
    require(digest(record["data"]) == record["sha256"], "archive_checksum_mismatch")
    return record["data"]


class PrivateArchive:
    def __init__(self, repo, token, connection=HTTPSConnection):
        require(repo and SLUG.fullmatch(repo) and repo.split("/")[1] not in {".", ".."} and token, "missing_private_archive_configuration")
        self.repo = repo
        self.token = token
        self.connection = connection
        self.assert_private()

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("BENCH_EVIDENCE_REPO"), os.environ.get("BENCH_EVIDENCE_TOKEN"))

    def request(self, method, path, body=None):
        conn = self.connection("api.github.com", timeout=20)
        try:
            conn.request(method, "/repos/" + self.repo + path, body=body, headers={
                "Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "meguvizbench", "Content-Type": "application/json",
            })
            response = conn.getresponse()
            data = response.read(2 * 1024 * 1024 + 1)
            require(len(data) <= 2 * 1024 * 1024, "archive_response_too_large")
            if response.status in {200, 201}:
                return response.status, decode(data)
            return response.status, None
        except (OSError, UnicodeError) as exc:
            raise BenchError("archive_transport_error") from exc
        finally:
            conn.close()

    def assert_private(self):
        status, repo = self.request("GET", "")
        require(status == 200 and repo.get("private") is True and repo.get("visibility") == "private"
                and repo.get("full_name", "").lower() == self.repo.lower(), "evidence_repository_must_be_private")

    def get(self, path):
        require(PATH.fullmatch(path), "invalid_archive_path")
        status, record = self.request("GET", "/contents/" + path)
        if status == 404:
            return None
        require(status == 200 and record.get("type") == "file" and record.get("encoding") == "base64", "archive_read_failed")
        data = base64.b64decode("".join(record["content"].split()), validate=True)
        return unpack(data)

    def create(self, path, value):
        require(PATH.fullmatch(path), "invalid_archive_path")
        self.assert_private()
        body = encoded({"message": "chore(evidence): append benchmark record",
                        "content": base64.b64encode(pack(value)).decode("ascii")})
        for retry in range(4):
            # No sha is provided. An existing file is never updated.
            status, _ = self.request("PUT", "/contents/" + path, body)
            if status == 201:
                return
            if status not in {409, 422}:
                break
            require(self.get(path) is None, "archive_record_already_exists")
            time.sleep(0.25 * (retry + 1))
        raise BenchError("archive_write_failed")


def plan_path(plan):
    return f"runs/{plan['run_id']}/plan.json.gz"


def trial_path(plan, trial, name):
    return f"runs/{plan['run_id']}/{trial['trial_id']}/{name}.json.gz"


def assert_claim(archive, plan):
    claim = archive.get(plan_path(plan))
    require(claim is not None and digest(claim) == digest(plan), "frozen_plan_claim_mismatch")
