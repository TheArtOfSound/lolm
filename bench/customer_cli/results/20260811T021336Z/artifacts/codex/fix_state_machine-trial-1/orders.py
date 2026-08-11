"""Order lifecycle."""

ALLOWED = {
    "new": ["paid"],
    "paid": ["shipped"],
    "shipped": ["delivered"],
}

TERMINAL = ["delivered"]


class Order:
    def __init__(self):
        self.state = "new"
        self._history = []

    def transition(self, to):
        self.state = to
        self._history.append(to)
        return self.state

    def history(self):
        return self._history

    def is_terminal(self):
        return self.state in TERMINAL
