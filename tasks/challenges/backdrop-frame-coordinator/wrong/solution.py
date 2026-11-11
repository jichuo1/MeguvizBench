"""A plausible coordinator that treats submitted probes as confirmed immediately."""

import json
import sys


def coordinate(events):
    bindings = {}
    tried = set()
    results = []
    for event in events:
        operation = event["op"]
        if operation == "bind":
            bindings[event["surface"]] = event
        elif operation == "unbind":
            layer = bindings.get(event["surface"])
            if layer and layer["generation"] == event["generation"]:
                del bindings[event["surface"]]
        elif operation == "frame":
            layers = []
            groups = {}
            for surface, layer in sorted(bindings.items()):
                if layer["target"] != event["target"]:
                    continue
                key = (layer["source"], layer["revision"])
                output = {"surface": surface, "generation": layer["generation"], "path": "flat", "probe": False}
                layers.append(output)
                left, top, right, bottom = layer["rect"]
                a, b, c, d = event["viewport"]
                h = layer["halo"]
                eligible = all((
                    event["hardware"], event["native_available"], layer["opt_in"], layer["compatible"],
                    layer["effect"] == "frost", layer["cost"] > 0, layer["source"] == event["scene"],
                    a <= left - h, b <= top - h, right + h <= c, bottom + h <= d,
                ))
                generation = (surface, layer["generation"])
                if eligible and generation in tried:
                    output["path"] = "native"
                    continue
                if eligible:
                    output["probe"] = True
                    tried.add(generation)
                if layer["cost"] > 0:
                    groups.setdefault(key, []).append((layer, output))
            captures = []
            used = 0
            ordering = sorted(groups, key=lambda key: (-max(x[0]["priority"] for x in groups[key]), key))
            for key in ordering:
                cost = max(layer["cost"] for layer, _ in groups[key])
                if used + cost <= event["budget"]:
                    captures.append(key)
                    used += cost
                    for _, output in groups[key]:
                        output["path"] = "sample"
            results.append({"frame": event["frame"], "layers": layers, "captures": captures, "used": used})
    return results


if __name__ == "__main__":
    print(json.dumps(coordinate(json.load(sys.stdin)["events"])))
