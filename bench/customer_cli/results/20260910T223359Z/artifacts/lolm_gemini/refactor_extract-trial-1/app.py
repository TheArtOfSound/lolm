"""Order tool: storage, pricing, and reporting all in one file."""
import json

_DB = {}
TAX = 0.08
TIERS = {"basic": 0.0, "silver": 0.05, "gold": 0.1}


def save_order(order_id, items):
    _DB[order_id] = list(items)
    return order_id


def load_order(order_id):
    return _DB.get(order_id)


def price(items, tier="basic"):
    subtotal = sum(i["qty"] * i["unit"] for i in items)
    discount = subtotal * TIERS.get(tier, 0.0)
    return round((subtotal - discount) * (1 + TAX), 2)


def report(order_id, tier="basic"):
    items = load_order(order_id)
    if items is None:
        return json.dumps({"error": "not found"})
    return json.dumps({"order": order_id, "total": price(items, tier)}, sort_keys=True)
