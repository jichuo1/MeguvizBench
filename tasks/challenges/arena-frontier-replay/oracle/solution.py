import json
import sys

from arena import Arena


def main():
    request = json.load(sys.stdin)
    arena = Arena(request["pages"])
    events = [arena.dispatch(command) for command in request["ops"]]
    json.dump({"events": events}, sys.stdout)


if __name__ == "__main__":
    main()
