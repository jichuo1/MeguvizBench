import json
import sys

from watchdog import Watchdog


def main():
    request = json.load(sys.stdin)
    watchdog = Watchdog(request)
    actions = [watchdog.handle(event) for event in request["events"]]
    result = {
        "state": watchdog.state,
        "reason": watchdog.reason,
        "attempts": watchdog.attempts,
        "actions": actions,
    }
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
