"""Order lifecycle."""

# Legal transitions:
# new -> paid, new -> cancelled
# paid -> shipped, paid -> refunded
# shipped -> delivered

ALLOWED = {
    "new": ["paid", "cancelled"],
    "paid": ["shipped", "refunded"],
    "shipped": ["delivered"],
    "cancelled": [],
    "refunded": [],
    "delivered": []
}

TERMINAL = ["cancelled", "refunded", "delivered"]


class Order:
    def __init__(self):
        self.state = "new"
        self._history = ["new"]

    def transition(self, to):
        if to not in ALLOWED.get(self.state, []):
            raise ValueError(f"Illegal transition from {self.state} to {to}")
        self.state = to
        self._history.append(to)
        return self.state

    def history(self):
        return self._history

    def is_terminal(self):
        return self.state in TERMINAL
