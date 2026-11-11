import json
import sys


def collect_alerts(events):
    starts = {}
    emitted = set()
    alerts = []
    for event in events:
        operation, time, *details = event
        if operation == "set":
            sensor, active = details
            if active:
                starts.setdefault(sensor, time)
            else:
                starts.pop(sensor, None)
                emitted.discard(sensor)
        else:
            for sensor in sorted(starts.keys() - emitted):
                if time - starts[sensor] >= 5:
                    alerts.append([time, sensor])
                    emitted.add(sensor)
    return alerts


json.dump(collect_alerts(json.load(sys.stdin)["events"]), sys.stdout)
