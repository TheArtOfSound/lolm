import app
# Test that they are importable from app
from app import save_order, load_order, price, report, delete_order, all_orders

items = [{"qty": 2, "unit": 10.0}]
save_order("2", items)
assert load_order("2") == items
assert price(items) == 21.6
r = report("2")
assert "21.6" in r
assert delete_order("2") == True
print("Re-export check passed!")
