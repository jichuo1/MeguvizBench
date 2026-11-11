"""Reference frame coordinator."""

import json
import sys
from dataclasses import dataclass


@dataclass
class Binding:
    spec: dict
    state: str = "cold"
    awaiting_frame: int | None = None

    def eligible(self, frame):
        layer = self.spec
        if self.state == "failed" or not all((
            frame["hardware"], frame["native_available"], layer["opt_in"], layer["compatible"],
            layer["effect"] == "frost", layer["cost"] > 0, layer["source"] == frame["scene"],
        )):
            return False
        left, top, right, bottom = layer["rect"]
        outer_left, outer_top, outer_right, outer_bottom = frame["viewport"]
        halo = layer["halo"]
        return (
            outer_left <= left - halo and outer_top <= top - halo
            and right + halo <= outer_right and bottom + halo <= outer_bottom
        )

    def accept(self, event):
        if self.awaiting_frame != event["frame"]:
            return
        self.awaiting_frame = None
        self.state = "confirmed" if event["ok"] else "failed"


def allocate(groups, budget):
    queue = []
    for key, layers in groups.items():
        cost = max(layer["cost"] for layer in layers)
        priority = max(layer["priority"] for layer in layers)
        queue.append((-priority, key, cost))
    available = budget
    captures = []
    for _, key, cost in sorted(queue):
        if cost <= available:
            available -= cost
            captures.append(key)
    return captures, budget - available


def render(frame, bindings):
    outputs = {}
    groups = {}
    for surface, binding in sorted(bindings.items()):
        layer = binding.spec
        if layer["target"] != frame["target"]:
            continue
        output = {"surface": surface, "generation": layer["generation"], "path": "flat", "probe": False}
        outputs[surface] = output
        if binding.eligible(frame):
            if binding.state == "confirmed":
                output["path"] = "native"
                binding.awaiting_frame = frame["frame"]
                continue
            if binding.awaiting_frame is None:
                binding.awaiting_frame = frame["frame"]
                output["probe"] = True
        if layer["cost"] > 0:
            key = (layer["source"], layer["revision"])
            groups.setdefault(key, []).append(layer)
    captures, used = allocate(groups, frame["budget"])
    for key in captures:
        for layer in groups[key]:
            outputs[layer["surface"]]["path"] = "sample"
    return {"frame": frame["frame"], "layers": list(outputs.values()), "captures": captures, "used": used}


def coordinate(events):
    bindings = {}
    output = []
    for event in events:
        operation = event["op"]
        if operation == "bind":
            bindings[event["surface"]] = Binding(event)
        elif operation == "frame":
            output.append(render(event, bindings))
        else:
            surface = event["surface"]
            binding = bindings.get(surface)
            if binding is None or binding.spec["generation"] != event["generation"]:
                continue
            if operation == "unbind":
                del bindings[surface]
            else:
                binding.accept(event)
    return output


if __name__ == "__main__":
    print(json.dumps(coordinate(json.load(sys.stdin)["events"])))
