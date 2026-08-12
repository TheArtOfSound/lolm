"""Pagination helpers used by the reports endpoint."""
import math


def page_items(items, page, per_page):
    """Return the slice of `items` on 1-indexed `page`."""
    if page < 1 or per_page < 1:
        raise ValueError("Page and per_page must be >= 1")
    start = (page - 1) * per_page
    return items[start:start + per_page]


def total_pages(n, per_page):
    """How many pages `n` items need."""
    if per_page < 1:
        raise ValueError("per_page must be >= 1")
    if n == 0:
        return 0
    return math.ceil(n / per_page)
