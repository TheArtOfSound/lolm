from ledger import Ledger

def test():
    ledger = Ledger()
    
    # Check balance returns 0 for unknown account
    assert ledger.balance("Unknown") == 0
    
    # Test valid post
    txn1 = ledger.post("Initial", [("A", 100), ("B", -100)])
    assert txn1 == 1
    
    # Test history filtering
    assert ledger.history("A") == [{"id": 1, "description": "Initial", "account": "A", "amount": 100}]
    assert ledger.history("C") == []
    
    # Test invalid amount (bool) again more strictly
    try:
        ledger.post("Bad", [("A", 1), ("B", -1.0)])
    except ValueError:
        pass
    else:
        assert False, "Should have raised ValueError for float"
        
    print("Additional tests passed")

if __name__ == "__main__":
    test()
