class Ledger:
    def __init__(self):
        self._transactions = []
        self._txn_counter = 0

    def post(self, description, entries):
        if not isinstance(entries, list) or len(entries) < 2:
            raise ValueError("Post must contain at least two entries.")

        total = 0
        formatted_entries = []
        
        for account, amount in entries:
            if not isinstance(amount, int) or isinstance(amount, bool):
                raise ValueError("Amount must be an integer.")
            total += amount
            formatted_entries.append((account, amount))
            
        if total != 0:
            raise ValueError("Entries must sum to zero.")
            
        self._txn_counter += 1
        txn_id = self._txn_counter
        
        for account, amount in formatted_entries:
            self._transactions.append({
                "id": txn_id,
                "description": description,
                "account": account,
                "amount": amount
            })
            
        return txn_id

    def balance(self, account):
        total = 0
        for entry in self._transactions:
            if entry["account"] == account:
                total += entry["amount"]
        return total

    def accounts(self):
        seen = set()
        for entry in self._transactions:
            seen.add(entry["account"])
        return sorted(list(seen))

    def history(self, account=None):
        if account is None:
            return list(self._transactions)
        return [entry for entry in self._transactions if entry["account"] == account]

    def reverse(self, txn_id):
        txn_entries = [e for e in self._transactions if e["id"] == txn_id]
        if not txn_entries:
            raise KeyError(f"Transaction {txn_id} not found.")
        
        reversal_entries = [(e["account"], -e["amount"]) for e in txn_entries]
        return self.post(f"Reversal of {txn_id}", reversal_entries)
