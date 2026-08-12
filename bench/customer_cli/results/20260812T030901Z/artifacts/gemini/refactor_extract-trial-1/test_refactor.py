import json
import app
import storage
import pricing

def test_everything():
    items = [{"qty": 2, "unit": 10.0}]
    storage.save_order("o1", items)
    
    assert storage.load_order("o1") == items
    assert storage.all_orders() == ["o1"]
    
    # Check pricing
    assert pricing.price(items, tier="basic") == 21.6 # 20 * 1.08
    assert pricing.price(items, tier="silver") == 20.52 # (20 * 0.95) * 1.08
    
    try:
        pricing.price(items, tier="platinum")
    except ValueError as e:
        assert str(e) == "Unknown tier: platinum"
    else:
        assert False, "Should have raised ValueError"
        
    # Check app.report
    report = app.report("o1")
    assert json.loads(report) == {"order": "o1", "total": 21.6}
    
    assert storage.delete_order("o1") is True
    assert storage.delete_order("o1") is False
    assert storage.all_orders() == []
    
    assert json.loads(app.report("o1")) == {"error": "not found"}

if __name__ == "__main__":
    test_everything()
    print("Tests passed")
