from collections import defaultdict

class Ledger:
    def __init__(self):
        self._transactions = []
        self._next_id = 1

    def post(self, description, entries):
        if not isinstance(entries, list) or len(entries) < 2:
            raise ValueError("Entries must be a list of at least two items.")

        total = 0
        processed_entries = []
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise ValueError("Each entry must be a (account, amount) pair.")
            
            account, amount = entry
            
            if not isinstance(amount, int) or isinstance(amount, bool):
                raise ValueError("Amount must be an integer (cents).")
                
            total += amount
            processed_entries.append({'account': account, 'amount': amount})

        if total != 0:
            raise ValueError("Entries must sum to zero.")

        txn_id = self._next_id
        for entry in processed_entries:
            self._transactions.append({
                'id': txn_id,
                'description': description,
                'account': entry['account'],
                'amount': entry['amount']
            })
        
        self._next_id += 1
        return txn_id

    def balance(self, account):
        total = 0
        for entry in self._transactions:
            if entry['account'] == account:
                total += entry['amount']
        return total

    def accounts(self):
        seen = set()
        for entry in self._transactions:
            seen.add(entry['account'])
        return sorted(list(seen))

    def history(self, account=None):
        if account is None:
            return list(self._transactions)
        return [entry for entry in self._transactions if entry['account'] == account]

    def reverse(self, txn_id):
        txn_entries = [entry for entry in self._transactions if entry['id'] == txn_id]
        if not txn_entries:
            raise KeyError(f"Transaction ID {txn_id} not found.")

        reversed_entries = [(entry['account'], -entry['amount']) for entry in txn_entries]
        return self.post(f"Reversal of {txn_id}", reversed_entries)
