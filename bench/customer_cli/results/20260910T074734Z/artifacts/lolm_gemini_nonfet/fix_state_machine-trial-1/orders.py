class Order:
    _ALLOWED = {
        "new": ["paid", "cancelled"],
        "paid": ["shipped", "refunded"],
        "shipped": ["delivered"],
    }
    _TERMINAL = {"cancelled", "refunded", "delivered"}

    def __init__(self):
        self.state = "new"
        self._history = ["new"]

    def transition(self, to):
        if self.state in self._TERMINAL:
            raise ValueError(f"Illegal transition from {self.state} to {to}")
        
        allowed = self._ALLOWED.get(self.state, [])
        if to not in allowed:
            raise ValueError(f"Illegal transition from {self.state} to {to}")
        
        self.state = to
        self._history.append(to)
        return self.state

    def history(self):
        return list(self._history)

    def is_terminal(self):
        return self.state in self._TERMINAL
