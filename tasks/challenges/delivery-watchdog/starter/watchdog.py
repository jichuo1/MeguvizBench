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
        self.progress = Progress(self.size)

    def action(self, op):
        return {"op": op, "attempt": self.attempts}

    def handle(self, event):
        if self.state in TERMINAL:
            return []
        now = event["t"]
        op = event["op"]
        if op == "cancel":
            actions = [self.action("stop")] if self.state == "running" else []
            self.state = "cancelled"
            self.reason = "cancelled"
            return actions
        if op == "probe" and self.state in {"await_probe", "backoff"} and now >= self.ready_at:
            if event["remote"] == self.digest:
                self.state = "succeeded"
                self.reason = "verified"
                return []
            if self.attempts >= self.max_attempts:
                self.state = "failed"
                self.reason = "attempts_exhausted"
                return []
            self.attempts += 1
            self.state = "running"
            self.deadline = now + self.stall
            return [self.action("start")]
        if self.state == "running" and op == "progress":
            if self.progress.advance(event["phase"], event["count"]):
                self.deadline = now + self.stall
                if event["count"] == self.size:
                    self.state = "succeeded"
                    self.reason = "verified"
        elif self.state == "running" and op == "confirmed":
            self.state = "succeeded"
            self.reason = "verified"
        elif self.state == "running" and op == "exit":
            self.state = "backoff"
            self.ready_at = now + self.backoff
        if self.state == "running" and now >= self.deadline:
            self.state = "backoff"
            self.ready_at = now + self.backoff
            return [self.action("stop")]
        return []
