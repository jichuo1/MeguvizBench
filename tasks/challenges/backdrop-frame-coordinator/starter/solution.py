"""Implement the frame coordination policy described in prompt.md."""

import json
import sys


def coordinate(events):
    return [
        {"frame": event["frame"], "layers": [], "captures": [], "used": 0}
        for event in events
        if event["op"] == "frame"
    ]


if __name__ == "__main__":
    print(json.dumps(coordinate(json.load(sys.stdin)["events"])))
