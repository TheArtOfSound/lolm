class Ledger:
    def __init__(self):
        self._entries = []
        self._next_id = 1
        self._accounts = set()

    def post(self, description, entries):
        if not isinstance(entries, list) or len(entries) < 2:
            raise ValueError("At least two entries are required.")
        
        total = 0
        for account, amount in entries:
            if not isinstance(amount, int) or isinstance(amount, bool):
                raise ValueError("Amount must be an integer.")
            total += amount
            
        if total != 0:
            raise ValueError("Entries must sum to zero.")
            
        txn_id = self._next_id
        for account, amount in entries:
            self._entries.append({
                "id": txn_id,
                "description": description,
                "account": account,
                "amount": amount
            })
            self._accounts.add(account)
            
        self._next_id += 1
        return txn_id

    def balance(self, account):
        total = 0
        for entry in self._entries:
            if entry["account"] == account:
                total += entry["amount"]
        return total

    def accounts(self):
        return sorted(list(self._accounts))

    def history(self, account=None):
        if account is None:
            return self._entries.copy()
        return [e for e in self._entries if e["account"] == account]

    def reverse(self, txn_id):
        txn_entries = [e for e in self._entries if e["id"] == txn_id]
        if not txn_entries:
            raise KeyError(f"Transaction ID {txn_id} not found.")
            
        # Create inverse entries
        inverse_entries = [(e["account"], -e["amount"]) for e in txn_entries]
        return self.post(f"Reversal of {txn_id}", inverse_entries)
