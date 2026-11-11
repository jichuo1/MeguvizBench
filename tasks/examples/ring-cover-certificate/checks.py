import json


SIZE = 14
TARGETS = {0, 1, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13}
FORBIDDEN = {1, 4, 6, 9, 12}


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate object key")
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError("Non-JSON constant")


def covers(switch, target):
    return (target - switch) % SIZE in {0, 1, SIZE - 1}


def evaluate(artifact, run):
    result = dict.fromkeys(
        (
            "certificate_shape", "position_domain", "unique_switches", "switch_budget", "mutual_exclusion",
            "forbidden_positions", "required_position", "target_coverage", "witness_completeness", "witness_validity",
        ),
        False,
    )
    try:
        certificate = json.loads(
            (artifact / "certificate.json").read_text(encoding="utf-8"),
            object_pairs_hook=unique_keys,
            parse_constant=invalid_constant,
        )
    except (OSError, ValueError, RecursionError):
        return result
    if (
        not isinstance(certificate, dict)
        or certificate.keys() != {"selected", "witness"}
        or not isinstance(certificate["selected"], list)
        or not isinstance(certificate["witness"], dict)
    ):
        return result

    result["certificate_shape"] = True
    selected = certificate["selected"]
    witness = certificate["witness"]
    result["switch_budget"] = len(selected) <= 5
    result["witness_completeness"] = witness.keys() == {str(target) for target in TARGETS}
    if not all(type(position) is int and 0 <= position < SIZE for position in selected):
        return result

    switches = set(selected)
    result["position_domain"] = True
    result["unique_switches"] = len(switches) == len(selected)
    result["mutual_exclusion"] = all((switch + 1) % SIZE not in switches for switch in switches)
    result["forbidden_positions"] = switches.isdisjoint(FORBIDDEN)
    result["required_position"] = 11 in switches
    result["target_coverage"] = TARGETS <= {(switch + offset) % SIZE for switch in switches for offset in (-1, 0, 1)}
    result["witness_validity"] = result["witness_completeness"] and all(
        type(witness[str(target)]) is int and witness[str(target)] in switches and covers(witness[str(target)], target)
        for target in TARGETS
    )
    return result
