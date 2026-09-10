import app
from storage import all_orders, delete_order

# Test data
items = [{"qty": 2, "unit": 10.0}] # 20.0, no discount: 20 * 1.08 = 21.6
app.save_order("1", items)

# Test report
r = app.report("1", "basic")
print(f"Report: {r}")
assert "21.6" in r

# Test storage delete
assert app.delete_order("1") == True
assert app.load_order("1") is None
assert app.delete_order("1") == False

# Test pricing error
try:
    app.price(items, "invalid")
except ValueError as e:
    print(f"Caught expected error: {e}")
    assert "invalid" in str(e)
else:
    raise AssertionError("Should have raised ValueError")

print("All tests passed!")
