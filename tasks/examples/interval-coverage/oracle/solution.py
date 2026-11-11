import json
import sys


def covered_length(window, ranges):
    start, end = window
    total = 0
    frontier = start
    for left, right in sorted(ranges):
        left = max(left, start, frontier)
        right = min(right, end)
        if right > left:
            total += right - left
            frontier = right
    return total


request = json.load(sys.stdin)
json.dump(covered_length(request["window"], request["ranges"]), sys.stdout)
