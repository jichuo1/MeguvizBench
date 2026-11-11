import json
import sys


def collect_alerts(events):
    starts = {}
    alerts = []
    for event in events:
        operation, time, *details = event
        if operation == "set":
            sensor, active = details
            if active:
                starts[sensor] = time
            else:
                starts.pop(sensor, None)
        else:
            for sensor, started in starts.items():
                if time - started > 5:
                    alerts.append([time, sensor])
    return alerts


json.dump(collect_alerts(json.load(sys.stdin)["events"]), sys.stdout)
