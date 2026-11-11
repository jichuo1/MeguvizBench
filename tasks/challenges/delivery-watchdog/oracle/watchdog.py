from progress import Progress


TERMINAL = {"succeeded", "failed", "cancelled"}


class Watchdog:
    def __init__(self, request):
        self.digest = request["digest"]
        self.size = request["size"]
        self.stall = request["stall"]
        self.backoff = request["backoff"]
        self.max_attempts = request["max_attempts"]
        self.state = "await_probe"
        self.reason = None
        self.attempts = 0
        self.deadline = 0
        self.ready_at = 0
        self.progress = None

    def action(self, op):
        return {"op": op, "attempt": self.attempts}

    def stop(self, actions):
        self.state = "draining"
        actions.append(self.action("stop"))

    def finish(self, state, reason):
        self.state = state
        self.reason = reason

    def verify(self, remote):
        if remote == self.digest:
            self.finish("succeeded", "verified")
        else:
            self.finish("failed", "remote_conflict")

    def probe(self, event, actions):
        if event["local"] != self.digest:
            self.finish("failed", "digest_changed")
            return
        remote = event["remote"]
        if remote == "unavailable":
            return
        if remote != "missing":
            self.verify(remote)
            return
        if self.attempts == self.max_attempts:
            self.finish("failed", "attempts_exhausted")
            return
        self.attempts += 1
        self.state = "running"
        self.deadline = event["t"] + self.stall
        self.progress = Progress(self.size)
        actions.append(self.action("start"))

    def handle(self, event):
        actions = []
        if self.state in TERMINAL:
            return actions
        now = event["t"]
        op = event["op"]
        if op == "cancel":
            if self.state == "running":
                self.stop(actions)
            self.finish("cancelled", "cancelled")
            return actions

        if self.state == "running" and now > self.deadline:
            self.stop(actions)

        if op == "probe":
            if self.state == "await_probe" or (self.state == "backoff" and now >= self.ready_at):
                self.probe(event, actions)
        elif event.get("attempt") == self.attempts:
            if op == "exit" and self.state in {"running", "draining"}:
                self.state = "backoff"
                self.ready_at = now + self.backoff
            elif self.state == "running":
                if op == "confirmed":
                    self.verify(event["digest"])
                elif op == "progress" and self.progress.advance(event["phase"], event["count"]):
                    self.deadline = now + self.stall

        if self.state == "running" and now == self.deadline:
            self.stop(actions)
        return actions
