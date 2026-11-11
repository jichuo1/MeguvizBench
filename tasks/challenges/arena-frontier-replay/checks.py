import json
from random import Random


def expected_events(pages, commands):
    # Independently locate every allocation by scanning the complete page list.
    # Derive the protocol certificate from the exhaustive answer afterwards.
    locations = list(pages)
    cursors = [0] * len(locations)
    live = set()
    borrows = {}
    certificate = None
    events = []

    for operation, *args in commands:
        if operation == "alloc":
            label, size, alignment = args
            valid = (
                type(size) is int and size > 0 and type(alignment) is int
                and 1 <= alignment <= 256 and alignment.bit_count() == 1
            )
            if not valid:
                events.append({"status": "invalid_shape"})
                continue
            if label in borrows:
                events.append({"status": "in_use"})
                continue
            start = 0
            if certificate:
                minimum_size, minimum_alignment, boundary = certificate
                if not (size < minimum_size or alignment < minimum_alignment):
                    start = boundary

            eligible = []
            for index, (base, capacity) in enumerate(locations):
                current_address = base + cursors[index]
                target = (current_address + alignment - 1) // alignment * alignment
                offset = target - base
                if offset + size <= capacity:
                    eligible.append((index, offset))
            if eligible:
                index, offset = min(eligible)
                borrows[label] = 0
                live.add(label)
                cursors[index] = offset + size
                certificate = (size, alignment, index)
                events.append({"status": "ok", "page": index, "offset": offset, "scan_from": start})
            else:
                certificate = (size, alignment, len(locations))
                events.append({"status": "no_space", "scan_from": start})
            continue

        if operation == "inspect":
            events.append({
                "status": "ok", "cursors": list(cursors), "live": len(live),
                "retiring": len(borrows) - len(live), "pins": sum(borrows.values()),
            })
            continue

        result = "ok"
        if operation == "append":
            locations.append(args)
            cursors.append(0)
        elif operation == "reset":
            if borrows:
                result = "busy"
            else:
                cursors = [0] * len(locations)
                certificate = None
        else:
            label = args[0]
            if label not in borrows:
                result = "unknown"
            elif operation == "unpin":
                if borrows[label] == 0:
                    result = "not_pinned"
                else:
                    borrows[label] -= 1
                    if borrows[label] == 0 and label not in live:
                        borrows.pop(label)
            elif label not in live:
                result = "not_live"
            elif operation == "pin":
                borrows[label] += 1
            elif operation == "release":
                live.remove(label)
                if borrows[label] == 0:
                    borrows.pop(label)
        events.append({"status": result})

    return {"events": events}


def generated(seed):
    rng = Random(seed)
    pages = [[slot * 521 + rng.randrange(40), rng.randrange(16, 126)] for slot in [3, 1, 5]]
    operations = []
    names = [f"id{number}" for number in range(14)]
    next_slot = 6
    for _ in range(150):
        choice = rng.randrange(100)
        name = rng.choice(names)
        if choice < 45:
            operations.append(["alloc", name, rng.choice([1, 5, 7, 12, 16, 19, 44, 60, False]),
                               rng.choice([1, 2, 4, 8, 16, 32, 64, 3])])
        elif choice < 58:
            operations.append(["pin", name])
        elif choice < 70:
            operations.append(["release", name])
        elif choice < 84:
            operations.append(["unpin", name])
        elif choice < 91:
            operations.append(["inspect"])
        elif choice < 96:
            operations.append(["reset"])
        else:
            operations.append(["append", next_slot * 521 + rng.randrange(40), rng.randrange(16, 126)])
            next_slot += 1
    operations.append(["inspect"])
    return pages, operations


def evaluate(artifact, run):
    def check(pages, operations):
        request = {"pages": pages, "ops": operations}
        expected = expected_events(pages, operations)
        actual = run(request)
        # Comparing JSON encodings preserves the distinction between booleans and numbers.
        return json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)

    return {
        "address_alignment": check([[19, 13], [160, 31]], [
            ["alloc", "a", 3, 8], ["alloc", "b", 4, 4], ["alloc", "c", 6, 8], ["inspect"],
        ]),
        "first_fit": check([[300, 14], [10, 16], [150, 20]], [
            ["alloc", "a", 7, 1], ["alloc", "b", 7, 1], ["alloc", "c", 7, 1], ["inspect"],
        ]),
        "weaker_size": check([[0, 31], [80, 120]], [
            ["alloc", "long", 40, 4], ["alloc", "short", 16, 8], ["inspect"],
        ]),
        "weaker_alignment": check([[3, 16], [96, 96]], [
            ["alloc", "strict", 5, 16], ["alloc", "loose", 9, 4], ["inspect"],
        ]),
        "reuse_prefix": check([[0, 4], [100, 8], [256, 96], [512, 64]], [
            ["alloc", "a", 9, 4], ["alloc", "b", 9, 4], ["inspect"],
            ["alloc", "c", 12, 8], ["alloc", "d", 16, 16], ["inspect"],
        ]),
        "no_space_frontier": check([[1, 13], [80, 12]], [
            ["alloc", "large", 17, 2], ["inspect"], ["alloc", "large", 17, 2],
            ["alloc", "larger", 19, 4], ["alloc", "small", 8, 1], ["inspect"],
        ]) and check([], [["alloc", "a", 1, 1], ["inspect"]]),
        "append_after_miss": check([[0, 6]], [
            ["alloc", "a", 7, 2], ["append", 32, 8], ["alloc", "b", 7, 2],
            ["alloc", "c", 7, 2], ["append", 128, 32], ["alloc", "d", 7, 2], ["inspect"],
        ]),
        "retire_with_pins": check([[0, 112]], [
            ["alloc", "x", 9, 1], ["unpin", "x"], ["pin", "x"], ["pin", "x"],
            ["release", "x"], ["pin", "x"], ["release", "x"], ["alloc", "x", 9, 1],
            ["unpin", "x"], ["alloc", "x", 9, 1], ["inspect"], ["unpin", "x"], ["unpin", "x"],
            ["alloc", "x", 9, 1], ["inspect"],
        ]),
        "reset_barrier": check([[0, 4], [100, 72]], [
            ["alloc", "x", 9, 1], ["reset"], ["pin", "x"], ["release", "x"], ["reset"],
            ["inspect"], ["alloc", "y", 9, 1], ["unpin", "x"], ["inspect"],
        ]),
        "reset_invalidation": check([[0, 40], [96, 48]], [
            ["alloc", "warm", 32, 4], ["alloc", "b", 24, 4], ["release", "warm"], ["release", "b"],
            ["reset"], ["inspect"], ["alloc", "c", 24, 4], ["inspect"],
        ]),
        "rejected_commands": check([[0, 8], [40, 40]], [
            ["alloc", "a", 9, 2], ["alloc", "a", 2, 1], ["alloc", "a", 1, 0],
            ["alloc", "b", True, 2], ["alloc", "b", 1, True], ["alloc", "b", -1, 2],
            ["alloc", "b", 3.0, 2], ["alloc", "b", 1, 512], ["alloc", "b", 1, 3],
            ["release", "ghost"], ["pin", "ghost"], ["unpin", "ghost"], ["unpin", "a"], ["inspect"],
            ["alloc", "b", 10, 4], ["inspect"],
        ]),
        "mixed_trace": all(check(*generated(seed)) for seed in (8849, 72327)),
    }
