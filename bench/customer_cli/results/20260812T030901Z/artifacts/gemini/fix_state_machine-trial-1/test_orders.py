
from orders import Order

def test_transitions():
    order = Order()
    
    # Valid transitions
    order.transition("paid")
    assert order.state == "paid"
    order.transition("shipped")
    assert order.state == "shipped"
    order.transition("delivered")
    assert order.state == "delivered"
    assert order.is_terminal()
    print("Valid transitions test passed")

    # Invalid transitions
    order2 = Order()
    try:
        order2.transition("shipped")
    except ValueError as e:
        print(f"Caught expected error: {e}")
    else:
        print("Failed to raise ValueError for invalid transition")

    # History
    order3 = Order()
    order3.transition("paid")
    assert order3.history() == ["new", "paid"]
    print("History test passed")

if __name__ == "__main__":
    test_transitions()
