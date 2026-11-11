"""Behavioral checks using separate requests and explicit expected frame traces."""

import json


def bind(surface="panel", **changes):
    return {
        "op": "bind", "surface": surface, "generation": 1, "target": "main",
        "source": "base", "revision": 0, "effect": "frost", "rect": [2, 2, 8, 8],
        "halo": 2, "opt_in": True, "compatible": True, "cost": 4, "priority": 3,
        **changes,
    }


def frame(number, **changes):
    return {
        "op": "frame", "frame": number, "target": "main", "scene": "base",
        "viewport": [0, 0, 10, 10], "hardware": True, "native_available": True,
        "budget": 16, **changes,
    }


def receipt(number, ok, surface="panel", generation=1):
    return {"op": "receipt", "frame": number, "ok": ok, "surface": surface, "generation": generation}


def unbind(generation):
    return {"op": "unbind", "surface": "panel", "generation": generation}


def layer(path, surface="panel", probe=False, generation=1):
    return {"surface": surface, "generation": generation, "path": path, "probe": probe}


def output(number, layers=(), captures=(), used=0):
    return {"frame": number, "layers": list(layers), "captures": [list(key) for key in captures], "used": used}


def panel_sample(number, probe=False, generation=1):
    return output(number, [layer("sample", probe=probe, generation=generation)], [("base", 0)], 4)


def evaluate(artifact, run):
    def check(events, expected):
        actual = run({"events": events})
        return json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)

    return {
        "empty_protocol": check(
            [unbind(1), receipt(9, False), frame(1), frame(2, target="empty")],
            [output(1), output(2)],
        ),
        "confirmed_cutover": check(
            [bind(), frame(1), receipt(1, True), frame(2), frame(3, hardware=False), frame(4)],
            [
                panel_sample(1, probe=True), output(2, [layer("native")]),
                panel_sample(3), output(4, [layer("native")]),
            ],
        ),
        "runtime_gates": check(
            [bind(), frame(1, hardware=False), frame(2, native_available=False), frame(3)],
            [panel_sample(1), panel_sample(2), panel_sample(3, probe=True)],
        ),
        "clip_halo": check(
            [
                bind("a"), bind("b", rect=[2, 1, 8, 7]), bind("c", rect=[2, 3, 8, 9]),
                bind("d", rect=[1, 2, 7, 8]), bind("e", rect=[3, 2, 9, 8]), frame(1),
            ],
            [
                output(1, [layer("sample", "a", probe=True), *(layer("sample", name) for name in "bcde")],
                       [("base", 0)], 4),
            ],
        ),
        "semantic_gates": check(
            [
                bind("a", effect="lens"), bind("b", source="other"), bind("c", compatible=False),
                bind("d", opt_in=False), bind("e", cost=0), bind("f", effect="tint"), frame(1),
            ],
            [
                output(1, [*(layer("sample", name) for name in "abcd"), layer("flat", "e"),
                           layer("sample", "f")], [("base", 0), ("other", 0)], 8),
            ],
        ),
        "in_flight": check(
            [bind(), frame(1), frame(2), frame(3, hardware=False), frame(4), receipt(1, True), frame(5)],
            [
                panel_sample(1, probe=True), panel_sample(2), panel_sample(3), panel_sample(4),
                output(5, [layer("native")]),
            ],
        ),
        "sticky_failure": check(
            [bind(), frame(1), receipt(1, False), frame(2, hardware=False), frame(3), receipt(1, True), frame(4)],
            [panel_sample(1, probe=True), panel_sample(2), panel_sample(3), panel_sample(4)],
        ),
        "generation_isolation": check(
            [
                bind(), frame(1), bind(generation=2), frame(2),
                receipt(1, True), unbind(1), receipt(1, True, generation=2),
                frame(3), receipt(2, True, generation=2), frame(4), unbind(2),
                receipt(4, False, generation=2), frame(5),
            ],
            [
                panel_sample(1, probe=True), panel_sample(2, probe=True, generation=2),
                panel_sample(3, generation=2), output(4, [layer("native", generation=2)]), output(5),
            ],
        ),
        "late_receipts": check(
            [
                bind(), receipt(11, True), frame(12), receipt(13, False), frame(13),
                receipt(12, True), receipt(12, False), frame(14),
            ],
            [panel_sample(12, probe=True), panel_sample(13), output(14, [layer("native")])],
        ),
        "latest_native_failure": check(
            [
                bind(), frame(1), receipt(1, True), frame(2), frame(3), receipt(2, False),
                frame(4), receipt(4, False), receipt(3, True), frame(5),
            ],
            [
                panel_sample(1, probe=True), output(2, [layer("native")]), output(3, [layer("native")]),
                output(4, [layer("native")]), panel_sample(5),
            ],
        ),
        "shared_capture": check(
            [
                bind("a", opt_in=False, cost=2), bind("b", opt_in=False, cost=7),
                bind("z", opt_in=False, source="secondary", priority=1, cost=1), frame(1, budget=8),
            ],
            [output(1, [layer("sample", name) for name in "abz"], [("base", 0), ("secondary", 0)], 8)],
        ),
        "budget_priority": check(
            [
                bind("a", opt_in=False, source="large", cost=9, priority=12),
                bind("b", opt_in=False, source="shared", cost=1, priority=9),
                bind("c", opt_in=False, source="shared", cost=6, priority=-5),
                bind("d", opt_in=False, source="small", cost=3, priority=3),
                bind("e", opt_in=False, source="tiny", cost=1, priority=-1),
                frame(1, budget=6), frame(2, budget=4),
            ],
            [
                output(1, [layer("flat", "a"), layer("sample", "b"), layer("sample", "c"),
                           layer("flat", "d"), layer("flat", "e")], [("shared", 0)], 6),
                output(2, [layer("flat", "a"), layer("flat", "b"), layer("flat", "c"),
                           layer("sample", "d"), layer("sample", "e")], [("small", 0), ("tiny", 0)], 4),
            ],
        ),
        "scope_revision_order": check(
            [
                bind("c", opt_in=False, source="foo", cost=1), bind("b", opt_in=False, revision=2, cost=1),
                bind("a", opt_in=False, revision=10, cost=1),
                bind("z", target="other", opt_in=False, revision=2, cost=9, priority=100),
                frame(1, budget=3), frame(2, target="other", budget=1),
            ],
            [
                output(1, [layer("sample", name) for name in "abc"], [("base", 2), ("base", 10), ("foo", 0)], 3),
                output(2, [layer("flat", "z")]),
            ],
        ),
        "mixed_paths": check(
            [
                bind("a", cost=7), bind("b", opt_in=False, cost=2), frame(1, budget=2),
                receipt(1, True, surface="a"), frame(2, budget=2),
            ],
            [
                output(1, [layer("flat", "a", probe=True), layer("flat", "b")]),
                output(2, [layer("native", "a"), layer("sample", "b")], [("base", 0)], 2),
            ],
        ),
    }
