DIGEST = "sample-green"
OTHER = "sample-amber"


def event(t, op, **data):
    return {"t": t, "op": op, **data}


def probe(t, remote="missing", local=DIGEST):
    return event(t, "probe", local=local, remote=remote)


def advance(t, phase, count, attempt=1):
    return event(t, "progress", phase=phase, count=count, attempt=attempt)


def exited(t, attempt=1):
    return event(t, "exit", attempt=attempt)


def confirmed(t, attempt=1, digest=DIGEST):
    return event(t, "confirmed", attempt=attempt, digest=digest)


def evaluate(artifact, run):
    def check(events, state, attempts, actions, reason=None, **config):
        request = {
            "digest": DIGEST,
            "size": 12,
            "stall": 10,
            "backoff": 3,
            "max_attempts": 3,
            "events": events,
            **config,
        }
        trace = [[] for _ in events]
        for index, op, attempt in actions:
            trace[index].append({"op": op, "attempt": attempt})
        expected = {"state": state, "reason": reason, "attempts": attempts, "actions": trace}
        actual = run(request)
        return actual == expected and type(actual["attempts"]) is int and all(
            type(action["attempt"]) is int for row in actual["actions"] for action in row
        )

    return {
        "entry_and_init": check([], "await_probe", 0, []) and check(
            [event(1, "tick"), probe(2)], "running", 1, [(1, "start", 1)],
        ),
        "probe_dedup": check(
            [probe(0, DIGEST), probe(3), event(9, "cancel")], "succeeded", 0, [], "verified",
        ),
        "probe_outage": check(
            [probe(0, "unavailable"), probe(9), exited(12), probe(16, "unavailable"), probe(18, DIGEST)],
            "succeeded", 1, [(1, "start", 1)], "verified",
        ),
        "progress_hwm": check(
            [probe(0), advance(3, "transfer", 4), advance(5, "transfer", 4), advance(6, "transfer", 3),
             advance(7, "encode", 9), event(8, "tick"), event(12, "tick"), event(13, "tick")],
            "draining", 1, [(0, "start", 1), (7, "stop", 1)],
        ) and check(
            [probe(0), advance(6, "encode", 7), advance(14, "verify", 0), event(23, "tick"), event(24, "tick")],
            "draining", 1, [(0, "start", 1), (4, "stop", 1)],
        ),
        "invalid_progress": check(
            [probe(0), advance(1, "transfer", True), advance(2, "transfer", 13), advance(3, "transfer", -1),
             advance(4, "transfer", 4.5), advance(5, "transfer", "5"), event(10, "tick")],
            "draining", 1, [(0, "start", 1), (6, "stop", 1)],
        ),
        "deadline_order": check(
            [probe(0), advance(10, "transfer", 1), event(19, "tick"), event(20, "tick")],
            "draining", 1, [(0, "start", 1), (3, "stop", 1)],
        ) and check(
            [probe(0), advance(11, "transfer", 4), event(30, "tick")],
            "draining", 1, [(0, "start", 1), (1, "stop", 1)],
        ) and check(
            [probe(0), exited(10), probe(13)],
            "running", 2, [(0, "start", 1), (2, "start", 2)],
        ),
        "readback_gating": check(
            [probe(0), advance(1, "transfer", 12), advance(2, "verify", 12), event(3, "tick")],
            "running", 1, [(0, "start", 1)],
        ) and check(
            [probe(0), confirmed(1, digest=OTHER)], "failed", 1, [(0, "start", 1)], "remote_conflict",
        ) and check(
            [probe(0), confirmed(1)], "succeeded", 1, [(0, "start", 1)], "verified",
        ),
        "reap_barrier": check(
            [probe(0), event(10, "tick"), probe(15), confirmed(15), event(16, "tick"), exited(18), probe(21)],
            "running", 2, [(0, "start", 1), (1, "stop", 1), (6, "start", 2)],
        ),
        "backoff": check(
            [probe(0), exited(2), probe(4, local=OTHER), probe(5)],
            "running", 2, [(0, "start", 1), (3, "start", 2)],
        ) and check(
            [probe(0), exited(2), probe(2)], "running", 2, [(0, "start", 1), (2, "start", 2)], backoff=0,
        ),
        "stale_generation": check(
            [probe(0), exited(2), probe(5), advance(11, "verify", 12), exited(12), confirmed(13), event(15, "tick")],
            "draining", 2, [(0, "start", 1), (2, "start", 2), (6, "stop", 2)],
        ) and check(
            [probe(0), advance(1, "verify", 8), exited(2), probe(5), advance(14, "encode", 1, attempt=2), event(15, "tick")],
            "running", 2, [(0, "start", 1), (3, "start", 2)],
        ),
        "digest_identity": check(
            [probe(0), exited(2), probe(5, DIGEST, local=OTHER)], "failed", 1, [(0, "start", 1)], "digest_changed",
        ) and check(
            [probe(0, OTHER)], "failed", 0, [], "remote_conflict",
        ),
        "bounded_attempts": check(
            [probe(0), exited(1), probe(4), exited(6, attempt=2), probe(9)],
            "failed", 2, [(0, "start", 1), (2, "start", 2)], "attempts_exhausted", max_attempts=2,
        ) and check(
            [probe(0), exited(1), probe(4, DIGEST)], "succeeded", 1, [(0, "start", 1)], "verified", max_attempts=1,
        ),
        "cancellation": check(
            [probe(0), event(10, "cancel"), exited(11), probe(20)],
            "cancelled", 1, [(0, "start", 1), (1, "stop", 1)], "cancelled",
        ) and check(
            [probe(0), event(10, "tick"), event(10, "cancel"), confirmed(10)],
            "cancelled", 1, [(0, "start", 1), (1, "stop", 1)], "cancelled",
        ),
    }
