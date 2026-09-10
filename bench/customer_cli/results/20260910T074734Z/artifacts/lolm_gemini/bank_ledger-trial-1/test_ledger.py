from ledger import Ledger

def test():
    ledger = Ledger()
    
    # Test valid post
    txn1 = ledger.post("Initial", [("A", 100), ("B", -100)])
    assert txn1 == 1
    assert ledger.balance("A") == 100
    assert ledger.balance("B") == -100
    assert ledger.accounts() == ["A", "B"]
    
    # Test invalid post (non-zero sum)
    try:
        ledger.post("Bad", [("A", 100), ("B", -50)])
    except ValueError:
        pass
    else:
        assert False, "Should have raised ValueError"
    
    assert ledger.balance("A") == 100
    
    # Test invalid post (bool)
    try:
        ledger.post("Bad", [("A", True), ("B", -True)])
    except ValueError:
        pass
    else:
        assert False, "Should have raised ValueError"
        
    # Test history
    history = ledger.history()
    assert len(history) == 2
    assert history[0]["id"] == 1
    
    # Test reverse
    txn2 = ledger.reverse(1)
    assert txn2 == 2
    assert ledger.balance("A") == 0
    assert ledger.balance("B") == 0
    
    print("Tests passed")

if __name__ == "__main__":
    test()
