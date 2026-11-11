from dataclasses import dataclass


@dataclass
class Page:
    base: int
    capacity: int
    cursor: int = 0


@dataclass
class Owner:
    live: bool = True
    pins: int = 0


def status(name):
    return {"status": name}


def valid_shape(size, alignment):
    return (
        type(size) is int and size > 0 and type(alignment) is int
        and 1 <= alignment <= 256 and alignment & (alignment - 1) == 0
    )


class Arena:
    def __init__(self, pages):
        self.pages = [Page(*page) for page in pages]
        self.owners = {}
        self.frontier = None

    def dispatch(self, command):
        operation, *args = command
        return getattr(self, operation)(*args)

    def alloc(self, owner_id, size, alignment):
        if not valid_shape(size, alignment):
            return status("invalid_shape")
        if owner_id in self.owners:
            return status("in_use")
        start = 0
        if self.frontier is not None:
            old_size, old_alignment, bound = self.frontier
            if size >= old_size and alignment >= old_alignment:
                start = bound
        for index in range(start, len(self.pages)):
            page = self.pages[index]
            padding = -(page.base + page.cursor) % alignment
            offset = page.cursor + padding
            end = offset + size
            if end <= page.capacity:
                page.cursor = end
                self.owners[owner_id] = Owner()
                self.frontier = size, alignment, index
                return {"status": "ok", "page": index, "offset": offset, "scan_from": start}
        self.frontier = size, alignment, len(self.pages)
        return {"status": "no_space", "scan_from": start}

    def pin(self, owner_id):
        owner = self.owners.get(owner_id)
        if owner is None:
            return status("unknown")
        if not owner.live:
            return status("not_live")
        owner.pins += 1
        return status("ok")

    def release(self, owner_id):
        owner = self.owners.get(owner_id)
        if owner is None:
            return status("unknown")
        if not owner.live:
            return status("not_live")
        owner.live = False
        if not owner.pins:
            del self.owners[owner_id]
        return status("ok")

    def unpin(self, owner_id):
        owner = self.owners.get(owner_id)
        if owner is None:
            return status("unknown")
        if not owner.pins:
            return status("not_pinned")
        owner.pins -= 1
        if not owner.live and not owner.pins:
            del self.owners[owner_id]
        return status("ok")

    def reset(self):
        if self.owners:
            return status("busy")
        for page in self.pages:
            page.cursor = 0
        self.frontier = None
        return status("ok")

    def append(self, base, capacity):
        self.pages.append(Page(base, capacity))
        return status("ok")

    def inspect(self):
        live = sum(owner.live for owner in self.owners.values())
        return {
            "status": "ok",
            "cursors": [page.cursor for page in self.pages],
            "live": live,
            "retiring": len(self.owners) - live,
            "pins": sum(owner.pins for owner in self.owners.values()),
        }
