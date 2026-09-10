class Ledger:
    def __init__(self):
        self._transactions = []
        self._next_id = 1

    def post(self, description, entries):
        if not isinstance(entries, list) or len(entries) < 2:
            raise ValueError("Post must have at least two entries.")
        
        total = 0
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise ValueError("Entry must be a (account, amount) pair.")
            
            account, amount = entry
            
            if not isinstance(amount, int) or isinstance(amount, bool):
                raise ValueError("Amount must be an integer.")
            
            total += amount
            
        if total != 0:
            raise ValueError("Entries must sum to zero.")
        
        txn_id = self._next_id
        for account, amount in entries:
            self._transactions.append({
                "id": txn_id,
                "description": description,
                "account": account,
                "amount": amount
            })
            
        self._next_id += 1
        return txn_id

    def balance(self, account):
        total = 0
        for txn in self._transactions:
            if txn["account"] == account:
                total += txn["amount"]
        return total

    def accounts(self):
        accounts = set()
        for txn in self._transactions:
            accounts.add(txn["account"])
        return sorted(list(accounts))

    def history(self, account=None):
        if account is None:
            return list(self._transactions)
        else:
            return [txn for txn in self._transactions if txn["account"] == account]

    def reverse(self, txn_id):
        txn_entries = [txn for txn in self._transactions if txn["id"] == txn_id]
        if not txn_entries:
            raise KeyError(f"Transaction id {txn_id} not found.")
        
        # Post the inverse
        inverse_entries = [(txn["account"], -txn["amount"]) for txn in txn_entries]
        return self.post(f"Reversal of {txn_id}", inverse_entries)
