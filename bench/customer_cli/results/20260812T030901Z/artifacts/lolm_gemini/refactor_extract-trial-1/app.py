"""Order tool: storage, pricing, and reporting all in one file."""
import json
from storage import save_order, load_order, delete_order, all_orders
from pricing import price

def report(order_id, tier="basic"):
    items = load_order(order_id)
    if items is None:
        return json.dumps({"error": "not found"})
    return json.dumps({"order": order_id, "total": price(items, tier)}, sort_keys=True)
