def evaluate(artifact, run):
    def check(events, expected):
        result = run({"events": events})
        return (
            isinstance(result, list)
            and all(isinstance(item, list) and len(item) == 2 and type(item[0]) is int for item in result)
            and result == expected
        )

    return {
        "no_early_alert": check([["set", 0, "a", True], ["tick", 4]], []),
        "exact_threshold": check([["set", 0, "a", True], ["tick", 5]], [[5, "a"]]),
        "repeat_true": check([["set", 0, "a", True], ["set", 3, "a", True], ["tick", 5]], [[5, "a"]]),
        "one_per_activation": check([["set", 0, "a", True], ["tick", 5], ["tick", 10]], [[5, "a"]]),
        "cancel_pending": check([["set", 0, "a", True], ["set", 4, "a", False], ["tick", 8]], []),
        "restart_after_clear": check(
            [["set", 0, "a", True], ["tick", 5], ["set", 6, "a", False], ["set", 7, "a", True], ["tick", 11], ["tick", 12]],
            [[5, "a"], [12, "a"]],
        ),
        "independent_sensors": check(
            [["set", 0, "a", True], ["set", 1, "b", True], ["set", 2, "a", False], ["tick", 5], ["tick", 6]],
            [[6, "b"]],
        ),
        "stable_order": check([["set", 0, "z", True], ["set", 0, "a", True], ["tick", 5]], [[5, "a"], [5, "z"]]),
        "same_timestamp": check(
            [["set", 0, "a", True], ["set", 0, "b", True], ["set", 5, "b", False], ["tick", 5], ["set", 5, "a", False]],
            [[5, "a"]],
        ),
        "tick_only": check([["tick", 0], ["set", 1, "a", False], ["tick", 10]], []),
    }
