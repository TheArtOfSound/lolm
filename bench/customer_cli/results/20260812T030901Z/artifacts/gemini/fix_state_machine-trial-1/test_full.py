
from orders import Order

def test_full_flow():
    # Test all terminal states
    for terminal in ["cancelled", "refunded", "delivered"]:
        order = Order()
        if terminal == "cancelled":
            order.transition("cancelled")
        elif terminal == "refunded":
            order.transition("paid")
            order.transition("refunded")
        elif terminal == "delivered":
            order.transition("paid")
            order.transition("shipped")
            order.transition("delivered")
        
        assert order.is_terminal()
        try:
            order.transition("new")
        except ValueError:
            pass
        else:
            assert False, f"Should not be able to transition from {terminal}"
            
    print("Terminal state tests passed")

if __name__ == "__main__":
    test_full_flow()
