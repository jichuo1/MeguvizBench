def evaluate(artifact, run):
    def check(window, ranges, expected):
        result = run({"window": window, "ranges": ranges})
        return type(result) is int and result == expected

    return {
        "single_span": check([0, 10], [[2, 6]], 4),
        "window_clipping": check([0, 8], [[-9, 2], [6, 14]], 4),
        "overlap_union": check([0, 8], [[1, 4], [3, 6]], 5),
        "nested_union": check([0, 12], [[1, 9], [2, 3], [5, 7]], 8),
        "unordered_disjoint": check([0, 9], [[7, 8], [0, 2], [4, 5]], 4),
        "half_open_edges": check([0, 8], [[-3, 0], [1, 3], [3, 5], [8, 10]], 4),
        "empty_input": check([0, 5], [], 0),
        "empty_window": check([4, 4], [[-3, 5], [4, 4]], 0),
        "signed_endpoints": check([-8, 1], [[-10, -6], [-4, 2]], 7),
        "large_endpoints": check([0, 10**12], [[1, 10**12 - 1]] * 1000, 10**12 - 2),
    }
