"""Order lifecycle."""

ALLOWED = {
    "new": ["paid", "cancelled"],
    "paid": ["shipped", "refunded"],
    "shipped": ["delivered"],
}

TERMINAL = ["cancelled", "refunded", "delivered"]


class Order:
    def __init__(self):
        self.state = "new"
        # History should include the initial state
        self._history = ["new"]

    def transition(self, to):
        # Verify that the transition is allowed from the current state
        allowed_targets = ALLOWED.get(self.state, [])
        if to not in allowed_targets:
            raise ValueError(f"Illegal transition from {self.state} to {to}")
        self.state = to
        self._history.append(to)
        return self.state

    def history(self):
        # Return the ordered list of states visited
        return list(self._history)

    def is_terminal(self):
        # A state is terminal if it is listed in TERMINAL
        return self.state in TERMINAL
