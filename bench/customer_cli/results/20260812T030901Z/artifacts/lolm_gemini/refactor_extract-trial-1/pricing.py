
TAX = 0.08
TIERS = {"basic": 0.0, "silver": 0.05, "gold": 0.1}

def price(items, tier="basic"):
    if tier not in TIERS:
        raise ValueError(f"Unknown tier: {tier}")
    subtotal = sum(i["qty"] * i["unit"] for i in items)
    discount = subtotal * TIERS.get(tier, 0.0)
    return round((subtotal - discount) * (1 + TAX), 2)
