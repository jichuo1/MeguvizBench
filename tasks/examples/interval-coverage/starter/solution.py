import json
import sys


def covered_length(window, ranges):
    start, end = window
    return sum(max(0, min(end, right) - max(start, left)) for left, right in ranges)


request = json.load(sys.stdin)
json.dump(covered_length(request["window"], request["ranges"]), sys.stdout)
