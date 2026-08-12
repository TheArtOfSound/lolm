
_DB = {}

def save_order(order_id, items):
    _DB[order_id] = list(items)
    return order_id

def load_order(order_id):
    return _DB.get(order_id)

def delete_order(order_id):
    if order_id in _DB:
        del _DB[order_id]
        return True
    return False

def all_orders():
    return list(_DB.keys())
