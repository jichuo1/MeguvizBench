PHASES = {"encode": 0, "transfer": 1, "verify": 2}


class Progress:
    def __init__(self, size):
        self.size = size
        self.position = (0, 0)

    def advance(self, phase, count):
        if type(count) is not int or not 0 <= count <= self.size:
            return False
        position = (PHASES[phase], count)
        if position <= self.position:
            return False
        self.position = position
        return True
