"""Harder agent tasks: multi-file repair, refactors, packages, and real CLIs.

These extend `bench.tasks` with work that a single-file code completion cannot
fake. Each entry carries its own `reference` implementation so `bench/validate.py`
can prove the hidden test is passable and that every seeded bug is really broken.

Same hard rules as the base suite: stdlib only, no network, no pip, no input(),
and every hidden test finishes well inside the grader timeout.
"""

from __future__ import annotations

HARD_TASKS = [
    # ── multi-file repair ───────────────────────────────────────────────────
    {
        "id": "fix_cache_ttl",
        "tier": "fix",
        "task": (
            "cache.py holds a TTLCache and service.py is a read-through cache in front of a "
            "loader. Both are wrong. Fix them so: an entry is expired when now - stored_at >= ttl "
            "(exactly at the ttl it is already expired); reading an expired key removes it and "
            "returns None; reading a live key makes it most-recently-used; set() purges expired "
            "entries first and only then evicts the least-recently-used entry while the cache is "
            "over capacity; clear() empties the cache; and len(cache) is the number of stored "
            "entries. In service.py, lookup(key, loader, now=None) must return the cached value "
            "on a hit and otherwise call loader(key) exactly once and store the result, stats() "
            "must return {'hits': int, 'misses': int}, and reset() must empty both the cache and "
            "the counters without touching TTLCache internals. Keep both file names, the class "
            "name TTLCache, and every existing function name."
        ),
        "seed": {
            "cache.py": '''"""Tiny TTL + LRU cache."""
import time


class TTLCache:
    def __init__(self, capacity, ttl):
        self.capacity = capacity
        self.ttl = ttl
        self._data = {}

    def set(self, key, value, now=None):
        now = time.time() if now is None else now
        self._data[key] = (value, now)
        if len(self._data) > self.capacity:
            self._data.pop(next(iter(self._data)))

    def get(self, key, now=None):
        now = time.time() if now is None else now
        if key not in self._data:
            return None
        value, stamp = self._data[key]
        if now - stamp > self.ttl:
            return None
        return value

    def __len__(self):
        return len(self._data)
''',
            "service.py": '''"""Read-through cache in front of a loader."""
from cache import TTLCache

_CACHE = TTLCache(capacity=2, ttl=10)


def lookup(key, loader, now=None):
    hit = _CACHE.get(key, now=now)
    if hit is not None:
        return hit
    value = loader(key)
    _CACHE.set(key, value, now=now)
    return value
''',
        },
        "reference": {
            "cache.py": '''"""Tiny TTL + LRU cache."""
import time
from collections import OrderedDict


class TTLCache:
    def __init__(self, capacity, ttl):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self.ttl = ttl
        self._data = OrderedDict()

    def _clock(self, now):
        return time.time() if now is None else now

    def _expired(self, stamp, now):
        return now - stamp >= self.ttl

    def _purge(self, now):
        for key in [k for k, (_, stamp) in self._data.items() if self._expired(stamp, now)]:
            del self._data[key]

    def set(self, key, value, now=None):
        now = self._clock(now)
        self._data[key] = (value, now)
        self._data.move_to_end(key)
        self._purge(now)
        while len(self._data) > self.capacity:
            self._data.popitem(last=False)

    def get(self, key, now=None):
        now = self._clock(now)
        if key not in self._data:
            return None
        value, stamp = self._data[key]
        if self._expired(stamp, now):
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def clear(self):
        self._data.clear()

    def __len__(self):
        return len(self._data)
''',
            "service.py": '''"""Read-through cache in front of a loader."""
from cache import TTLCache

_CACHE = TTLCache(capacity=2, ttl=10)
_STATS = {"hits": 0, "misses": 0}


def lookup(key, loader, now=None):
    hit = _CACHE.get(key, now=now)
    if hit is not None:
        _STATS["hits"] += 1
        return hit
    _STATS["misses"] += 1
    value = loader(key)
    _CACHE.set(key, value, now=now)
    return value


def stats():
    return dict(_STATS)


def reset():
    _CACHE.clear()
    _STATS["hits"] = 0
    _STATS["misses"] = 0
''',
        },
        "test": r"""
import cache as C, service as S

c = C.TTLCache(capacity=2, ttl=10)
c.set('a', 1, now=0)
assert c.get('a', now=9) == 1
assert c.get('a', now=10) is None, 'now - stored_at >= ttl must count as expired'
assert len(c) == 0, 'an expired entry must be dropped when it is read'

c = C.TTLCache(capacity=2, ttl=100)
c.set('a', 1, now=0)
c.set('b', 2, now=1)
assert c.get('a', now=2) == 1
c.set('c', 3, now=3)
assert c.get('b', now=4) is None, 'the least-recently-used entry must be evicted'
assert c.get('a', now=4) == 1
assert c.get('c', now=4) == 3
assert len(c) == 2, len(c)

c = C.TTLCache(capacity=2, ttl=5)
c.set('x', 1, now=0)
c.set('y', 2, now=0)
c.set('z', 3, now=10)
assert len(c) == 1 and c.get('z', now=10) == 3, len(c)
c.clear()
assert len(c) == 0

S.reset()
calls = []
def loader(k):
    calls.append(k)
    return k.upper()
assert S.lookup('a', loader, now=0) == 'A'
assert S.lookup('a', loader, now=1) == 'A'
assert calls == ['a'], calls
assert S.stats() == {'hits': 1, 'misses': 1}, S.stats()
assert S.lookup('a', loader, now=100) == 'A'
assert calls == ['a', 'a'], calls
assert S.stats() == {'hits': 1, 'misses': 2}, S.stats()
S.reset()
assert S.stats() == {'hits': 0, 'misses': 0}, S.stats()
print('OK')
""",
    },
    {
        "id": "fix_argsplit",
        "tier": "fix",
        "task": (
            "lexer.py splits a command line into arguments and runner.py turns that into a "
            "program plus arguments. The splitter is a naive space split and is wrong. Fix "
            "split_args(line) so: runs of whitespace separate arguments and leading/trailing "
            "whitespace is ignored; double quotes group text and understand the escapes "
            "backslash-doublequote and backslash-backslash; single quotes group text completely "
            "literally with no escapes inside; outside quotes a backslash escapes the next "
            "character; quotes may start and end mid-argument so x\"y\"z is one argument xyz; "
            "an empty quoted string produces an empty argument; and an unbalanced quote or a "
            "trailing lone backslash raises ValueError. Fix parse_command(line) so it returns "
            "{'program': ..., 'args': [...]} and raises ValueError for an empty or "
            "whitespace-only line instead of crashing. Keep both file names and both function "
            "names."
        ),
        "seed": {
            "lexer.py": '''"""Split a command line into arguments."""


def split_args(line):
    out = []
    for part in line.split(" "):
        if part:
            out.append(part.strip('"'))
    return out
''',
            "runner.py": '''"""Turn a command line into a program plus arguments."""
from lexer import split_args


def parse_command(line):
    parts = split_args(line)
    return {"program": parts[0], "args": parts[1:]}
''',
        },
        "reference": {
            "lexer.py": r'''"""Split a command line into arguments."""


def split_args(line):
    args, current, started = [], [], False
    index, length = 0, len(line)
    while index < length:
        char = line[index]
        if char.isspace():
            if started:
                args.append("".join(current))
                current, started = [], False
            index += 1
        elif char == "'":
            started = True
            index += 1
            while index < length and line[index] != "'":
                current.append(line[index])
                index += 1
            if index >= length:
                raise ValueError("unbalanced single quote")
            index += 1
        elif char == '"':
            started = True
            index += 1
            while index < length and line[index] != '"':
                if line[index] == "\\" and index + 1 < length and line[index + 1] in ('"', "\\"):
                    current.append(line[index + 1])
                    index += 2
                else:
                    current.append(line[index])
                    index += 1
            if index >= length:
                raise ValueError("unbalanced double quote")
            index += 1
        elif char == "\\":
            if index + 1 >= length:
                raise ValueError("trailing backslash")
            current.append(line[index + 1])
            started = True
            index += 2
        else:
            current.append(char)
            started = True
            index += 1
    if started:
        args.append("".join(current))
    return args
''',
            "runner.py": '''"""Turn a command line into a program plus arguments."""
from lexer import split_args


def parse_command(line):
    parts = split_args(line)
    if not parts:
        raise ValueError("empty command line")
    return {"program": parts[0], "args": parts[1:]}
''',
        },
        "test": r"""
import lexer as L, runner as R

assert L.split_args('a b  c') == ['a', 'b', 'c']
assert L.split_args('  a   ') == ['a']
assert L.split_args('') == []
assert L.split_args('git commit -m "fix the bug"') == ['git', 'commit', '-m', 'fix the bug']
assert L.split_args("echo 'hello world'") == ['echo', 'hello world']
assert L.split_args('a "" b') == ['a', '', 'b'], L.split_args('a "" b')
assert L.split_args(r'say "he said \"hi\""') == ['say', 'he said "hi"'], L.split_args(r'say "he said \"hi\""')
assert L.split_args(r'a\ b') == ['a b'], L.split_args(r'a\ b')
assert L.split_args("'no \\ escapes'") == ['no \\ escapes'], L.split_args("'no \\ escapes'")
assert L.split_args('x"y"z') == ['xyz'], L.split_args('x"y"z')

def bad(fn, *a):
    try:
        fn(*a)
    except ValueError:
        return
    except Exception as e:
        raise AssertionError(f'expected ValueError, got {type(e).__name__}')
    raise AssertionError(f'{a!r} should raise ValueError')

bad(L.split_args, 'a "unbalanced')
bad(L.split_args, "a 'unbalanced")
bad(L.split_args, 'trailing \\')
assert R.parse_command('git commit -m "x y"') == {'program': 'git', 'args': ['commit', '-m', 'x y']}
bad(R.parse_command, '   ')
bad(R.parse_command, '')
print('OK')
""",
    },
    {
        "id": "fix_retry",
        "tier": "fix",
        "task": (
            "retry.py provides a retry decorator that is wrong: it swallows every exception "
            "type, sleeps with the real clock, and does not report how many attempts it made. "
            "Rewrite it as retry(attempts=3, on=(Exception,), sleep=time.sleep, delay=0) so it "
            "calls the wrapped function at most `attempts` times in total; retries only when the "
            "raised exception is an instance of one of `on` and lets anything else propagate "
            "immediately; re-raises the final exception once the attempts are exhausted; calls "
            "sleep(delay * 2 ** index) between attempts with index starting at 0; exposes "
            "wrapper.calls as the number of invocations made during the most recent call; "
            "raises ValueError at decoration time when attempts is below 1; and preserves the "
            "wrapped function's __name__ and __doc__. Keep the file name and the name retry."
        ),
        "seed": {
            "retry.py": '''"""Retry helper."""
import time


def retry(attempts=3, on=(Exception,), delay=0):
    def wrap(fn):
        def inner(*args, **kwargs):
            for _ in range(attempts - 1):
                try:
                    return fn(*args, **kwargs)
                except Exception:
                    time.sleep(delay)
            return fn(*args, **kwargs)
        return inner
    return wrap
''',
        },
        "reference": {
            "retry.py": '''"""Retry helper."""
import functools
import time


def retry(attempts=3, on=(Exception,), sleep=time.sleep, delay=0):
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            inner.calls = 0
            last = None
            for index in range(attempts):
                inner.calls += 1
                try:
                    return fn(*args, **kwargs)
                except on as error:
                    last = error
                    if index < attempts - 1:
                        sleep(delay * 2 ** index)
            raise last

        inner.calls = 0
        return inner

    return wrap
''',
        },
        "test": r"""
import retry as R

calls = {'n': 0}
slept = []

@R.retry(attempts=3, on=(ValueError,), sleep=slept.append, delay=1)
def flaky():
    'docstring'
    calls['n'] += 1
    if calls['n'] < 3:
        raise ValueError('boom')
    return 'ok'

assert flaky() == 'ok'
assert calls['n'] == 3, calls
assert slept == [1, 2], slept
assert flaky.calls == 3, flaky.calls
assert flaky.__name__ == 'flaky', flaky.__name__
assert flaky.__doc__ == 'docstring', flaky.__doc__

seen = {'v': 0}

@R.retry(attempts=5, on=(ValueError,), sleep=lambda s: None)
def wrong():
    seen['v'] += 1
    raise KeyError('nope')

try:
    wrong()
except KeyError:
    pass
else:
    raise AssertionError('an exception outside `on` must propagate')
assert seen['v'] == 1, seen

count = {'v': 0}

@R.retry(attempts=2, on=(ValueError,), sleep=lambda s: None)
def always():
    count['v'] += 1
    raise ValueError('fail ' + str(count['v']))

try:
    always()
except ValueError as e:
    assert str(e) == 'fail 2', str(e)
else:
    raise AssertionError('exhausted attempts must re-raise the last error')
assert count['v'] == 2, count

try:
    R.retry(attempts=0)
except ValueError:
    pass
else:
    raise AssertionError('attempts < 1 must raise ValueError')
print('OK')
""",
    },
    {
        "id": "fix_date_range",
        "tier": "fix",
        "task": (
            "dates.py builds date ranges and is wrong. Fix daterange(start, end, step_days=1) so "
            "the range includes both endpoints when they land on the step; step_days must be a "
            "non-zero int and anything else (including 0, a float, or a bool) raises ValueError; "
            "a positive step with start > end returns []; a negative step walks backwards and is "
            "inclusive, and a negative step with start < end returns []. Fix "
            "business_days(start, end, holidays=()) so it returns the inclusive-range dates that "
            "are Monday to Friday and are not in holidays. Keep the file name and both function "
            "names."
        ),
        "seed": {
            "dates.py": '''"""Inclusive date ranges."""
from datetime import timedelta


def daterange(start, end, step_days=1):
    out = []
    current = start
    while current < end:
        out.append(current)
        current += timedelta(days=step_days)
    return out


def business_days(start, end):
    return [d for d in daterange(start, end) if d.weekday() < 5]
''',
        },
        "reference": {
            "dates.py": '''"""Inclusive date ranges."""
from datetime import timedelta


def daterange(start, end, step_days=1):
    if isinstance(step_days, bool) or not isinstance(step_days, int) or step_days == 0:
        raise ValueError("step_days must be a non-zero integer")
    out = []
    current = start
    if step_days > 0:
        while current <= end:
            out.append(current)
            current += timedelta(days=step_days)
    else:
        while current >= end:
            out.append(current)
            current += timedelta(days=step_days)
    return out


def business_days(start, end, holidays=()):
    blocked = set(holidays)
    return [d for d in daterange(start, end) if d.weekday() < 5 and d not in blocked]
''',
        },
        "test": r"""
from datetime import date
import dates as D

assert D.daterange(date(2026, 1, 1), date(2026, 1, 4)) == [
    date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 4)]
assert D.daterange(date(2026, 1, 1), date(2026, 1, 1)) == [date(2026, 1, 1)]
assert D.daterange(date(2026, 1, 1), date(2026, 1, 6), 2) == [
    date(2026, 1, 1), date(2026, 1, 3), date(2026, 1, 5)]
assert D.daterange(date(2026, 1, 4), date(2026, 1, 1), -1) == [
    date(2026, 1, 4), date(2026, 1, 3), date(2026, 1, 2), date(2026, 1, 1)]
assert D.daterange(date(2026, 1, 4), date(2026, 1, 1)) == []
assert D.daterange(date(2026, 1, 1), date(2026, 1, 4), -1) == []

def bad(*a):
    try:
        D.daterange(*a)
    except ValueError:
        return
    except Exception as e:
        raise AssertionError(f'expected ValueError, got {type(e).__name__}')
    raise AssertionError(f'{a!r} should raise ValueError')

bad(date(2026, 1, 1), date(2026, 1, 4), 0)
bad(date(2026, 1, 1), date(2026, 1, 4), 1.5)
bad(date(2026, 1, 1), date(2026, 1, 4), True)

# 2026-01-01 is a Thursday.
assert D.business_days(date(2026, 1, 1), date(2026, 1, 7)) == [
    date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
assert D.business_days(date(2026, 1, 1), date(2026, 1, 7), holidays={date(2026, 1, 2)}) == [
    date(2026, 1, 1), date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
print('OK')
""",
    },
    # ── refactors that must not change behaviour ────────────────────────────
    {
        "id": "refactor_shapes",
        "tier": "refactor",
        "task": (
            "shapes.py dispatches on a shape 'kind' with a chain of if/elif in two places. "
            "Refactor it onto a registry without changing the results of area(shape) or "
            "perimeter(shape) for circle, rect, and square. Add "
            "register(kind, area_fn, perimeter_fn) which registers or replaces a kind and "
            "returns None, and kinds() which returns the sorted list of registered kind names. "
            "Add a built-in 'triangle' kind taking sides a, b, and c that uses Heron's formula "
            "for area and a+b+c for perimeter, raising ValueError when the sides cannot form a "
            "triangle with positive area. An unknown kind must raise a ValueError whose message "
            "contains the kind name. Keep the file name shapes.py and the function names area "
            "and perimeter."
        ),
        "seed": {
            "shapes.py": '''"""Area and perimeter for a few shapes."""
import math


def area(shape):
    kind = shape["kind"]
    if kind == "circle":
        return math.pi * shape["r"] ** 2
    elif kind == "rect":
        return shape["w"] * shape["h"]
    elif kind == "square":
        return shape["side"] ** 2
    else:
        raise ValueError("unknown shape")


def perimeter(shape):
    kind = shape["kind"]
    if kind == "circle":
        return 2 * math.pi * shape["r"]
    elif kind == "rect":
        return 2 * (shape["w"] + shape["h"])
    elif kind == "square":
        return 4 * shape["side"]
    else:
        raise ValueError("unknown shape")
''',
        },
        "reference": {
            "shapes.py": '''"""Area and perimeter for a few shapes, dispatched through a registry."""
import math

_REGISTRY = {}


def register(kind, area_fn, perimeter_fn):
    _REGISTRY[kind] = (area_fn, perimeter_fn)
    return None


def kinds():
    return sorted(_REGISTRY)


def _lookup(shape):
    kind = shape["kind"]
    if kind not in _REGISTRY:
        raise ValueError(f"unknown shape kind: {kind}")
    return _REGISTRY[kind]


def area(shape):
    return _lookup(shape)[0](shape)


def perimeter(shape):
    return _lookup(shape)[1](shape)


def _triangle_area(shape):
    a, b, c = shape["a"], shape["b"], shape["c"]
    if min(a, b, c) <= 0 or a + b <= c or a + c <= b or b + c <= a:
        raise ValueError(f"sides {a}, {b}, {c} cannot form a triangle")
    s = (a + b + c) / 2
    return math.sqrt(s * (s - a) * (s - b) * (s - c))


def _triangle_perimeter(shape):
    _triangle_area(shape)
    return shape["a"] + shape["b"] + shape["c"]


register("circle", lambda s: math.pi * s["r"] ** 2, lambda s: 2 * math.pi * s["r"])
register("rect", lambda s: s["w"] * s["h"], lambda s: 2 * (s["w"] + s["h"]))
register("square", lambda s: s["side"] ** 2, lambda s: 4 * s["side"])
register("triangle", _triangle_area, _triangle_perimeter)
''',
        },
        "test": r"""
import math
import shapes as S

assert abs(S.area({'kind': 'circle', 'r': 2}) - math.pi * 4) < 1e-9
assert S.area({'kind': 'rect', 'w': 3, 'h': 4}) == 12
assert S.area({'kind': 'square', 'side': 5}) == 25
assert abs(S.perimeter({'kind': 'circle', 'r': 2}) - 4 * math.pi) < 1e-9
assert S.perimeter({'kind': 'rect', 'w': 3, 'h': 4}) == 14
assert S.perimeter({'kind': 'square', 'side': 5}) == 20
assert abs(S.area({'kind': 'triangle', 'a': 3, 'b': 4, 'c': 5}) - 6.0) < 1e-9
assert S.perimeter({'kind': 'triangle', 'a': 3, 'b': 4, 'c': 5}) == 12

for shape in ({'kind': 'triangle', 'a': 1, 'b': 2, 'c': 10},
              {'kind': 'triangle', 'a': 0, 'b': 1, 'c': 1},
              {'kind': 'triangle', 'a': 1, 'b': 2, 'c': 3}):
    try:
        S.area(shape)
    except ValueError:
        pass
    else:
        raise AssertionError(f'{shape} has no positive area and must raise ValueError')

try:
    S.area({'kind': 'blob'})
except ValueError as e:
    assert 'blob' in str(e), str(e)
else:
    raise AssertionError('an unknown kind must raise ValueError naming the kind')

assert S.kinds() == ['circle', 'rect', 'square', 'triangle'], S.kinds()
assert S.register('hexagon', lambda s: 6 * s['side'], lambda s: 6 * s['side']) is None
assert S.area({'kind': 'hexagon', 'side': 2}) == 12
assert S.perimeter({'kind': 'hexagon', 'side': 2}) == 12
assert 'hexagon' in S.kinds()
print('OK')
""",
    },
    {
        "id": "refactor_extract",
        "tier": "refactor",
        "task": (
            "app.py mixes storage, pricing, and reporting in one module. Split it into three "
            "files without breaking any caller. Create storage.py owning the order dictionary "
            "and providing save_order, load_order, plus new delete_order(order_id) returning "
            "True when it removed something and False otherwise, and all_orders() returning the "
            "known order ids. Create pricing.py owning TAX, TIERS, and price(items, tier='basic'), "
            "and change price so an unknown tier raises a ValueError whose message contains the "
            "tier name instead of silently applying no discount. Leave app.py with report plus "
            "re-exports so that save_order, load_order, price, and report all remain importable "
            "from app. No order storage may remain in app.py: app must not define a module-level "
            "_DB. Keep the existing function names and the rounding behaviour of price."
        ),
        "seed": {
            "app.py": '''"""Order tool: storage, pricing, and reporting all in one file."""
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
''',
        },
        "reference": {
            "storage.py": '''"""Order storage."""

_DB = {}


def save_order(order_id, items):
    _DB[order_id] = list(items)
    return order_id


def load_order(order_id):
    return _DB.get(order_id)


def delete_order(order_id):
    return _DB.pop(order_id, None) is not None


def all_orders():
    return list(_DB)
''',
            "pricing.py": '''"""Order pricing."""

TAX = 0.08
TIERS = {"basic": 0.0, "silver": 0.05, "gold": 0.1}


def price(items, tier="basic"):
    if tier not in TIERS:
        raise ValueError(f"unknown pricing tier: {tier}")
    subtotal = sum(i["qty"] * i["unit"] for i in items)
    discount = subtotal * TIERS[tier]
    return round((subtotal - discount) * (1 + TAX), 2)
''',
            "app.py": '''"""Order reporting. Storage and pricing live in their own modules."""
import json

from pricing import price
from storage import load_order, save_order

__all__ = ["save_order", "load_order", "price", "report"]


def report(order_id, tier="basic"):
    items = load_order(order_id)
    if items is None:
        return json.dumps({"error": "not found"})
    return json.dumps({"order": order_id, "total": price(items, tier)}, sort_keys=True)
''',
        },
        "test": r"""
import json
import app, pricing, storage

assert app.save_order('o1', [{'qty': 2, 'unit': 10.0}]) == 'o1'
assert storage.load_order('o1') == [{'qty': 2, 'unit': 10.0}]
assert app.load_order('o1') == [{'qty': 2, 'unit': 10.0}]
assert pricing.price([{'qty': 2, 'unit': 10.0}]) == 21.6, pricing.price([{'qty': 2, 'unit': 10.0}])
assert app.price([{'qty': 2, 'unit': 10.0}], 'gold') == 19.44, app.price([{'qty': 2, 'unit': 10.0}], 'gold')
assert json.loads(app.report('o1')) == {'order': 'o1', 'total': 21.6}
assert json.loads(app.report('nope')) == {'error': 'not found'}

storage.save_order('o2', [])
assert sorted(storage.all_orders()) == ['o1', 'o2'], storage.all_orders()
assert storage.delete_order('o2') is True
assert storage.delete_order('o2') is False
assert sorted(storage.all_orders()) == ['o1']

try:
    pricing.price([{'qty': 1, 'unit': 1.0}], 'platinum')
except ValueError as e:
    assert 'platinum' in str(e), str(e)
else:
    raise AssertionError('an unknown tier must raise ValueError')

assert not hasattr(app, '_DB'), 'order storage must live in storage.py only'
assert pricing.TAX == 0.08 and 'gold' in pricing.TIERS
print('OK')
""",
    },
    # ── make the failing test pass ──────────────────────────────────────────
    {
        "id": "tdd_matrix",
        "tier": "tdd",
        "task": (
            "test_matrix.py exists and fails because matrix.py does not. Create matrix.py with a "
            "Matrix class so that `python3 test_matrix.py` prints OK. Do not modify or delete "
            "test_matrix.py. Beyond what that file checks, Matrix must also: work for "
            "non-square shapes, expose shape as a (rows, cols) tuple and T as the transpose, "
            "support * with an int or float as scalar multiplication and with a Matrix as matrix "
            "multiplication, compare equal only to another Matrix with the same values, and "
            "raise ValueError for ragged rows, for an empty matrix, for adding mismatched "
            "shapes, and for multiplying when the inner dimensions disagree."
        ),
        "seed": {
            "test_matrix.py": '''"""Run me with: python3 test_matrix.py"""
from matrix import Matrix

a = Matrix([[1, 2], [3, 4]])
b = Matrix([[5, 6], [7, 8]])
assert (a + b) == Matrix([[6, 8], [10, 12]])
assert (a * b) == Matrix([[19, 22], [43, 50]])
assert (a * 2) == Matrix([[2, 4], [6, 8]])
assert a.T == Matrix([[1, 3], [2, 4]])
assert a.shape == (2, 2)
assert Matrix.identity(2) == Matrix([[1, 0], [0, 1]])
print("OK")
''',
        },
        "reference": {
            "test_matrix.py": '''"""Run me with: python3 test_matrix.py"""
from matrix import Matrix

a = Matrix([[1, 2], [3, 4]])
b = Matrix([[5, 6], [7, 8]])
assert (a + b) == Matrix([[6, 8], [10, 12]])
assert (a * b) == Matrix([[19, 22], [43, 50]])
assert (a * 2) == Matrix([[2, 4], [6, 8]])
assert a.T == Matrix([[1, 3], [2, 4]])
assert a.shape == (2, 2)
assert Matrix.identity(2) == Matrix([[1, 0], [0, 1]])
print("OK")
''',
            "matrix.py": '''"""Small dense matrix type."""


class Matrix:
    def __init__(self, rows):
        rows = [list(row) for row in rows]
        if not rows or not rows[0]:
            raise ValueError("a matrix needs at least one row and one column")
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            raise ValueError("all rows must have the same length")
        self.rows = rows

    @property
    def shape(self):
        return (len(self.rows), len(self.rows[0]))

    @property
    def T(self):
        return Matrix([list(column) for column in zip(*self.rows)])

    @classmethod
    def identity(cls, n):
        if n < 1:
            raise ValueError("identity size must be >= 1")
        return cls([[1 if i == j else 0 for j in range(n)] for i in range(n)])

    def __eq__(self, other):
        return isinstance(other, Matrix) and self.rows == other.rows

    def __add__(self, other):
        if not isinstance(other, Matrix):
            raise TypeError("can only add a Matrix to a Matrix")
        if self.shape != other.shape:
            raise ValueError(f"shape mismatch: {self.shape} + {other.shape}")
        return Matrix([[x + y for x, y in zip(r1, r2)] for r1, r2 in zip(self.rows, other.rows)])

    def __mul__(self, other):
        if isinstance(other, (int, float)) and not isinstance(other, bool):
            return Matrix([[x * other for x in row] for row in self.rows])
        if not isinstance(other, Matrix):
            raise TypeError("can only multiply by a Matrix or a number")
        if self.shape[1] != other.shape[0]:
            raise ValueError(f"shape mismatch: {self.shape} * {other.shape}")
        columns = list(zip(*other.rows))
        return Matrix([[sum(x * y for x, y in zip(row, column)) for column in columns] for row in self.rows])

    def __repr__(self):
        return f"Matrix({self.rows!r})"
''',
        },
        "test": r"""
import pathlib
from matrix import Matrix

seed = pathlib.Path('test_matrix.py')
assert seed.exists(), 'test_matrix.py must not be deleted'
assert 'Matrix.identity(2)' in seed.read_text(), 'test_matrix.py must not be weakened'

a = Matrix([[1, 2], [3, 4]])
b = Matrix([[5, 6], [7, 8]])
assert (a + b) == Matrix([[6, 8], [10, 12]])
assert (a * b) == Matrix([[19, 22], [43, 50]])
assert (a * 2) == Matrix([[2, 4], [6, 8]])
assert a.T == Matrix([[1, 3], [2, 4]])
assert a.shape == (2, 2)
assert Matrix.identity(2) == Matrix([[1, 0], [0, 1]])

r = Matrix([[1, 2, 3], [4, 5, 6]])
s = Matrix([[7, 8], [9, 10], [11, 12]])
assert (r * s) == Matrix([[58, 64], [139, 154]]), (r * s)
assert r.shape == (2, 3) and r.T.shape == (3, 2)
assert (a * 1.5) == Matrix([[1.5, 3.0], [4.5, 6.0]])
assert (a == [[1, 2], [3, 4]]) is False
assert (a == Matrix([[1, 2], [3, 4]])) is True

def bad(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return
    except Exception as e:
        raise AssertionError(f'expected {exc.__name__}, got {type(e).__name__}')
    raise AssertionError(f'expected {exc.__name__}')

bad(lambda: Matrix([[1, 2], [3]]))
bad(lambda: Matrix([]))
bad(lambda: a + r)
bad(lambda: a * s)
print('OK')
""",
    },
    # ── real command line programs ──────────────────────────────────────────
    {
        "id": "cli_wordfreq",
        "tier": "cli",
        "task": (
            "Create wordfreq.py, a command line program run as "
            "`python3 wordfreq.py [-n N] FILE`. A word is a maximal run of the characters a-z, "
            "0-9, and apostrophe after lowercasing the text, with apostrophes stripped from the "
            "start and end of each word and empty results discarded. Print the top N words as "
            "`word<TAB>count`, one per line, ordered by descending count and then alphabetically "
            "for ties. N defaults to 10. Exit 0 on success, printing nothing for an empty file. "
            "Print a message to stderr and exit 2 for a missing FILE argument, an unreadable "
            "file, a non-integer N, or any unrecognised argument. Write nothing to stdout on "
            "error."
        ),
        "reference": {
            "wordfreq.py": r'''#!/usr/bin/env python3
"""Top-N word frequencies for a text file."""
import re
import sys
from collections import Counter

WORD = re.compile(r"[a-z0-9']+")
USAGE = "usage: wordfreq.py [-n N] FILE"


def tokenize(text):
    words = []
    for raw in WORD.findall(text.lower()):
        word = raw.strip("'")
        if word:
            words.append(word)
    return words


def top_words(text, n):
    counts = Counter(tokenize(text))
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:n]


def main(argv):
    n, path, index = 10, None, 0
    while index < len(argv):
        argument = argv[index]
        if argument == "-n":
            index += 1
            if index >= len(argv):
                print(USAGE, file=sys.stderr)
                return 2
            try:
                n = int(argv[index])
            except ValueError:
                print(USAGE, file=sys.stderr)
                return 2
        elif argument.startswith("-") or path is not None:
            print(USAGE, file=sys.stderr)
            return 2
        else:
            path = argument
        index += 1
    if path is None:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        print(f"wordfreq.py: cannot read {path}", file=sys.stderr)
        return 2
    for word, count in top_words(text, n):
        print(f"{word}\t{count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
''',
        },
        "test": r"""
import pathlib
import subprocess
import sys

pathlib.Path('sample.txt').write_text("the quick brown fox. The QUICK fox! don't don't stop\n")
pathlib.Path('empty.txt').write_text('')

def run(args, expect):
    r = subprocess.run([sys.executable, 'wordfreq.py'] + args, capture_output=True, text=True, timeout=30)
    assert r.returncode == expect, (args, r.returncode, r.stdout[:200], r.stderr[:200])
    return r

r = run(['-n', '3', 'sample.txt'], 0)
assert r.stdout == "don't\t2\nfox\t2\nquick\t2\n", repr(r.stdout)
r = run(['sample.txt'], 0)
assert len(r.stdout.splitlines()) == 6, r.stdout
assert r.stdout.splitlines()[-1] == 'stop\t1', r.stdout
r = run(['empty.txt'], 0)
assert r.stdout == '', repr(r.stdout)

for args in ([], ['missing.txt'], ['-n', 'x', 'sample.txt'], ['-n'], ['--bogus', 'sample.txt']):
    r = run(args, 2)
    assert r.stdout == '', (args, repr(r.stdout))
    assert r.stderr.strip() != '', args
print('OK')
""",
    },
    {
        "id": "cli_csvstat",
        "tier": "cli",
        "task": (
            "Create csvstat.py, a command line program run as "
            "`python3 csvstat.py --column NAME [--precision N]` that reads a CSV with a header "
            "row from standard input. Print one JSON object to stdout with the keys count, min, "
            "max, mean, and sum for the named column, where mean is rounded to N decimal places "
            "(default 4). Blank cells are skipped rather than treated as errors. Exit 0 on "
            "success; exit 2 for a missing --column, a non-integer --precision, or an "
            "unrecognised argument; exit 3 when the column is not in the header; exit 4 when a "
            "non-blank cell in that column is not a number; and exit 5 when the column has no "
            "usable values. Every error must print a message to stderr and nothing to stdout."
        ),
        "reference": {
            "csvstat.py": '''#!/usr/bin/env python3
"""Summary statistics for one column of a CSV read from stdin."""
import csv
import json
import sys

USAGE = "usage: csvstat.py --column NAME [--precision N]"


def main(argv):
    column, precision, index = None, 4, 0
    while index < len(argv):
        if argv[index] == "--column" and index + 1 < len(argv):
            column = argv[index + 1]
            index += 2
            continue
        if argv[index] == "--precision" and index + 1 < len(argv):
            try:
                precision = int(argv[index + 1])
            except ValueError:
                print(USAGE, file=sys.stderr)
                return 2
            index += 2
            continue
        print(USAGE, file=sys.stderr)
        return 2
    if column is None:
        print(USAGE, file=sys.stderr)
        return 2

    reader = csv.DictReader(sys.stdin)
    if not reader.fieldnames or column not in reader.fieldnames:
        print(f"csvstat.py: no such column: {column}", file=sys.stderr)
        return 3
    values = []
    for row in reader:
        raw = (row.get(column) or "").strip()
        if not raw:
            continue
        try:
            values.append(float(raw))
        except ValueError:
            print(f"csvstat.py: not a number: {raw}", file=sys.stderr)
            return 4
    if not values:
        print(f"csvstat.py: column {column} has no values", file=sys.stderr)
        return 5
    total = sum(values)
    print(json.dumps({
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": round(total / len(values), precision),
        "sum": total,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
''',
        },
        "test": r"""
import json
import subprocess
import sys

CSV = "name,score,note\na,1,x\nb,2,y\nc,6,z\n"

def run(args, stdin, expect):
    r = subprocess.run([sys.executable, 'csvstat.py'] + args, input=stdin,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == expect, (args, r.returncode, r.stdout[:200], r.stderr[:200])
    return r

out = json.loads(run(['--column', 'score'], CSV, 0).stdout)
assert out['count'] == 3, out
assert out['min'] == 1 and out['max'] == 6 and out['sum'] == 9, out
assert abs(out['mean'] - 3.0) < 1e-9, out

out = json.loads(run(['--column', 'score', '--precision', '1'], "name,score\na,1\nb,2\n", 0).stdout)
assert out['mean'] == 1.5, out

out = json.loads(run(['--column', 'score'], "name,score\na,\nb,4\n", 0).stdout)
assert out['count'] == 1 and out['sum'] == 4, out

for args, stdin, code in ((['--column', 'nope'], CSV, 3),
                          (['--column', 'note'], CSV, 4),
                          ([], CSV, 2),
                          (['--bogus', '1'], CSV, 2),
                          (['--column', 'score', '--precision', 'x'], CSV, 2),
                          (['--column', 'score'], "name,score\n", 5)):
    r = run(args, stdin, code)
    assert r.stdout == '', (args, repr(r.stdout))
    assert r.stderr.strip() != '', args
print('OK')
""",
    },
    {
        "id": "pkg_calc",
        "tier": "package",
        "task": (
            "Build a Python package named calc in the current directory so that "
            "`python3 -m calc \"1+2*3\"` prints 7. Create calc/__init__.py exporting "
            "evaluate, calc/ops.py with add, sub, mul, and div where div raises "
            "ZeroDivisionError for a zero divisor, and a calc/__main__.py entry point. "
            "evaluate(expression) must parse and compute the expression itself with correct "
            "precedence, parentheses, unary minus and plus, and integer and decimal literals, "
            "returning an int when the arithmetic is exact integer arithmetic and a float when "
            "division or a decimal literal is involved. It must raise ValueError for a malformed "
            "expression. No file in the package may call eval or exec. The entry point exits 0 "
            "on success, prints usage to stderr and exits 2 when the argument count is not "
            "exactly one, and prints the error to stderr and exits 3 for a bad expression or a "
            "division by zero."
        ),
        "reference": {
            "calc/__init__.py": '''"""Tiny calculator package."""
from .parser import evaluate

__all__ = ["evaluate"]
''',
            "calc/ops.py": '''"""Arithmetic primitives."""


def add(a, b):
    return a + b


def sub(a, b):
    return a - b


def mul(a, b):
    return a * b


def div(a, b):
    if b == 0:
        raise ZeroDivisionError("division by zero")
    return a / b
''',
            "calc/parser.py": r'''"""Recursive-descent expression parser. No eval, no exec."""
import re

from .ops import add, div, mul, sub

_TOKEN = re.compile(r"\s*(?:(\d+\.\d+|\d+)|(.))")


def _tokens(text):
    out, position = [], 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if not match or match.end() == position:
            break
        position = match.end()
        number, symbol = match.group(1), match.group(2)
        if number is not None:
            out.append(float(number) if "." in number else int(number))
        elif symbol is not None:
            if symbol not in "+-*/()":
                raise ValueError(f"unexpected character: {symbol!r}")
            out.append(symbol)
    if text[position:].strip():
        raise ValueError(f"unexpected input: {text[position:]!r}")
    return out


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.position = 0

    def peek(self):
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self):
        value = self.peek()
        self.position += 1
        return value

    def expression(self):
        value = self.term()
        while self.peek() in ("+", "-"):
            value = add(value, self.term()) if self.take() == "+" else sub(value, self.term())
        return value

    def term(self):
        value = self.unary()
        while self.peek() in ("*", "/"):
            value = mul(value, self.unary()) if self.take() == "*" else div(value, self.unary())
        return value

    def unary(self):
        if self.peek() == "-":
            self.take()
            return -self.unary()
        if self.peek() == "+":
            self.take()
            return self.unary()
        return self.atom()

    def atom(self):
        token = self.take()
        if token == "(":
            value = self.expression()
            if self.take() != ")":
                raise ValueError("missing closing parenthesis")
            return value
        if isinstance(token, (int, float)):
            return token
        raise ValueError(f"unexpected token: {token!r}")


def evaluate(expression):
    tokens = _tokens(str(expression))
    if not tokens:
        raise ValueError("empty expression")
    parser = _Parser(tokens)
    value = parser.expression()
    if parser.position != len(tokens):
        raise ValueError("trailing input in expression")
    return value
''',
            "calc/__main__.py": '''"""Entry point for `python3 -m calc EXPRESSION`."""
import sys

from . import evaluate


def main(argv):
    if len(argv) != 1:
        print("usage: python3 -m calc EXPRESSION", file=sys.stderr)
        return 2
    try:
        result = evaluate(argv[0])
    except (ValueError, ZeroDivisionError) as error:
        print(f"calc: {error}", file=sys.stderr)
        return 3
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
''',
        },
        "test": r"""
import pathlib
import subprocess
import sys

from calc import evaluate
from calc.ops import add, div, mul, sub

assert evaluate('1+2*3') == 7, evaluate('1+2*3')
assert evaluate('(1+2)*3') == 9
assert evaluate('-4 + 2') == -2
assert evaluate('7/2') == 3.5
assert evaluate('2*(3+4)-5') == 9
assert evaluate('2.5*2') == 5.0
assert evaluate('-(3-5)') == 2

source = ''.join(p.read_text() for p in sorted(pathlib.Path('calc').rglob('*.py')))
assert 'eval(' not in source and 'exec(' not in source, 'the package must not call eval or exec'

assert add(1, 2) == 3 and sub(5, 2) == 3 and mul(3, 4) == 12 and div(9, 3) == 3.0
try:
    div(1, 0)
except ZeroDivisionError:
    pass
else:
    raise AssertionError('div by zero must raise ZeroDivisionError')

for expression in ('1+', '', '(1+2', '1 2 +', '3 $ 4'):
    try:
        evaluate(expression)
    except ValueError:
        pass
    else:
        raise AssertionError(f'{expression!r} must raise ValueError')

def run(args, expect):
    r = subprocess.run([sys.executable, '-m', 'calc'] + args, capture_output=True, text=True, timeout=30)
    assert r.returncode == expect, (args, r.returncode, r.stdout[:200], r.stderr[:200])
    return r

assert run(['1+2*3'], 0).stdout.strip() == '7', run(['1+2*3'], 0).stdout
assert run(['7/2'], 0).stdout.strip() == '3.5'
run([], 2)
run(['1', '2'], 2)
run(['1+'], 3)
run(['1/0'], 3)
print('OK')
""",
    },
    # ── implementation with exacting semantics ──────────────────────────────
    {
        "id": "json_patch",
        "tier": "impl",
        "task": (
            "Create jsonpatch.py defining apply_patch(doc, ops) which applies a list of RFC 6902 "
            "operations to doc and returns a new document, never mutating the input. Support the "
            "ops add, remove, replace, move, copy, and test, with JSON pointer paths including "
            "the escapes ~1 for a slash and ~0 for a tilde, and the array token '-' meaning "
            "append. Operations apply in order. Raise ValueError for a failed test op, a path "
            "that does not exist for remove/replace/test, an out-of-range array index, a path "
            "that does not start with a slash, a malformed operation, and an unsupported op "
            "name."
        ),
        "reference": {
            "jsonpatch.py": '''"""Minimal RFC 6902 JSON Patch."""
import copy


def _unescape(token):
    return token.replace("~1", "/").replace("~0", "~")


def _split(pointer):
    if not isinstance(pointer, str):
        raise ValueError("path must be a string")
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"invalid JSON pointer: {pointer!r}")
    return [_unescape(part) for part in pointer.split("/")[1:]]


def _index(container, token, allow_end=False):
    if token == "-":
        if not allow_end:
            raise ValueError("'-' is only valid when adding to an array")
        return len(container)
    if not token.isdigit() or (len(token) > 1 and token[0] == "0"):
        raise ValueError(f"invalid array index: {token!r}")
    value = int(token)
    limit = len(container) if allow_end else len(container) - 1
    if value > limit:
        raise ValueError(f"array index out of range: {token!r}")
    return value


def _resolve(doc, tokens):
    node = doc
    for token in tokens:
        if isinstance(node, list):
            node = node[_index(node, token)]
        elif isinstance(node, dict):
            if token not in node:
                raise ValueError(f"path not found: {token!r}")
            node = node[token]
        else:
            raise ValueError(f"cannot descend into {type(node).__name__}")
    return node


def _parent(doc, tokens):
    if not tokens:
        raise ValueError("this operation requires a non-root path")
    return _resolve(doc, tokens[:-1]), tokens[-1]


def _add(doc, tokens, value):
    if not tokens:
        return value
    parent, token = _parent(doc, tokens)
    if isinstance(parent, list):
        parent.insert(_index(parent, token, allow_end=True), value)
    elif isinstance(parent, dict):
        parent[token] = value
    else:
        raise ValueError(f"cannot add to {type(parent).__name__}")
    return doc


def _remove(doc, tokens):
    parent, token = _parent(doc, tokens)
    if isinstance(parent, list):
        return parent.pop(_index(parent, token))
    if isinstance(parent, dict):
        if token not in parent:
            raise ValueError(f"path not found: {token!r}")
        return parent.pop(token)
    raise ValueError(f"cannot remove from {type(parent).__name__}")


def apply_patch(doc, ops):
    result = copy.deepcopy(doc)
    for position, op in enumerate(ops):
        if not isinstance(op, dict) or "op" not in op or "path" not in op:
            raise ValueError(f"operation {position} is malformed")
        kind = op["op"]
        tokens = _split(op["path"])
        if kind == "add":
            if "value" not in op:
                raise ValueError(f"operation {position} needs a value")
            result = _add(result, tokens, copy.deepcopy(op["value"]))
        elif kind == "remove":
            _remove(result, tokens)
        elif kind == "replace":
            if "value" not in op:
                raise ValueError(f"operation {position} needs a value")
            if not tokens:
                result = copy.deepcopy(op["value"])
                continue
            _resolve(result, tokens)
            _remove(result, tokens)
            result = _add(result, tokens, copy.deepcopy(op["value"]))
        elif kind == "move":
            source = _split(op.get("from", ""))
            if tokens[:len(source)] == source and len(tokens) > len(source):
                raise ValueError("cannot move a location into itself")
            result = _add(result, tokens, _remove(result, source))
        elif kind == "copy":
            value = copy.deepcopy(_resolve(result, _split(op.get("from", ""))))
            result = _add(result, tokens, value)
        elif kind == "test":
            if _resolve(result, tokens) != op.get("value"):
                raise ValueError(f"test failed at {op['path']}")
        else:
            raise ValueError(f"unsupported op: {kind!r}")
    return result
''',
        },
        "test": r"""
from jsonpatch import apply_patch

base = {'a': 1, 'b': {'c': [1, 2, 3]}, 'x/y': 'esc'}
snapshot = {'a': 1, 'b': {'c': [1, 2, 3]}, 'x/y': 'esc'}

out = apply_patch(base, [{'op': 'replace', 'path': '/a', 'value': 9}])
assert out['a'] == 9, out
assert base == snapshot, 'the input document must not be mutated'

assert apply_patch(base, [{'op': 'add', 'path': '/d', 'value': 4}])['d'] == 4
assert apply_patch(base, [{'op': 'add', 'path': '/b/c/-', 'value': 4}])['b']['c'] == [1, 2, 3, 4]
assert apply_patch(base, [{'op': 'add', 'path': '/b/c/0', 'value': 0}])['b']['c'] == [0, 1, 2, 3]
assert 'a' not in apply_patch(base, [{'op': 'remove', 'path': '/a'}])
assert apply_patch(base, [{'op': 'remove', 'path': '/b/c/1'}])['b']['c'] == [1, 3]

moved = apply_patch(base, [{'op': 'move', 'from': '/a', 'path': '/b/a'}])
assert moved['b']['a'] == 1 and 'a' not in moved, moved
copied = apply_patch(base, [{'op': 'copy', 'from': '/a', 'path': '/a2'}])
assert copied['a2'] == 1 and copied['a'] == 1, copied
assert apply_patch(base, [{'op': 'test', 'path': '/a', 'value': 1}]) == base
assert apply_patch(base, [{'op': 'test', 'path': '/x~1y', 'value': 'esc'}]) == base
assert base == snapshot

def bad(ops):
    try:
        apply_patch(base, ops)
    except ValueError:
        return
    except Exception as e:
        raise AssertionError(f'expected ValueError, got {type(e).__name__}: {e}')
    raise AssertionError(f'{ops} should raise ValueError')

bad([{'op': 'test', 'path': '/a', 'value': 2}])
bad([{'op': 'remove', 'path': '/nope'}])
bad([{'op': 'replace', 'path': '/nope', 'value': 1}])
bad([{'op': 'add', 'path': '/b/c/99', 'value': 1}])
bad([{'op': 'remove', 'path': '/b/c/99'}])
bad([{'op': 'frobnicate', 'path': '/a'}])
bad([{'op': 'add', 'path': 'a', 'value': 1}])
bad([{'op': 'add', 'path': '/z'}])
bad(['nope'])
bad([{'op': 'add', 'path': '/z', 'value': 1}, {'op': 'test', 'path': '/z', 'value': 2}])

chained = apply_patch(base, [
    {'op': 'add', 'path': '/z', 'value': 1},
    {'op': 'test', 'path': '/z', 'value': 1},
    {'op': 'replace', 'path': '/z', 'value': 5},
])
assert chained['z'] == 5, chained
print('OK')
""",
    },
    {
        "id": "graph_topo",
        "tier": "impl",
        "task": (
            "Create topo.py defining toposort(graph) and a CycleError exception. graph maps a "
            "node to the list of nodes it depends on, so dependencies come first in the output. "
            "Nodes that appear only as a dependency are still part of the graph. The order must "
            "be deterministic: whenever several nodes are ready, take the smallest one. "
            "toposort({}) is []. When the graph has a cycle, raise CycleError, which must be a "
            "subclass of ValueError and must carry a .cycle attribute holding the cycle as a "
            "list of nodes that starts and ends with the same node."
        ),
        "reference": {
            "topo.py": '''"""Deterministic topological sort."""
import heapq


class CycleError(ValueError):
    def __init__(self, cycle):
        super().__init__("cycle detected: " + " -> ".join(str(node) for node in cycle))
        self.cycle = cycle


def _find_cycle(graph, remaining):
    node = min(remaining)
    path, seen = [], set()
    while node not in seen:
        seen.add(node)
        path.append(node)
        following = sorted(dep for dep in graph.get(node, []) if dep in remaining)
        if not following:
            break
        node = following[0]
    if node in path:
        return path[path.index(node):] + [node]
    return path


def toposort(graph):
    nodes = set(graph)
    for dependencies in graph.values():
        nodes.update(dependencies)
    incoming = {node: 0 for node in nodes}
    dependents = {node: [] for node in nodes}
    for node, dependencies in graph.items():
        for dependency in dependencies:
            dependents[dependency].append(node)
            incoming[node] += 1
    ready = [node for node, count in incoming.items() if count == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        node = heapq.heappop(ready)
        order.append(node)
        for dependent in sorted(dependents[node]):
            incoming[dependent] -= 1
            if incoming[dependent] == 0:
                heapq.heappush(ready, dependent)
    if len(order) != len(nodes):
        raise CycleError(_find_cycle(graph, nodes - set(order)))
    return order
''',
        },
        "test": r"""
from topo import CycleError, toposort

assert issubclass(CycleError, ValueError)
assert toposort({}) == []
g = {'app': ['lib', 'util'], 'lib': ['util'], 'util': []}
assert toposort(g) == ['util', 'lib', 'app'], toposort(g)
assert toposort({'z': [], 'a': [], 'm': []}) == ['a', 'm', 'z']
assert toposort({'a': ['b']}) == ['b', 'a'], toposort({'a': ['b']})
assert toposort({'d': ['b', 'c'], 'b': ['a'], 'c': ['a'], 'a': []}) == ['a', 'b', 'c', 'd']

try:
    toposort({'a': ['b'], 'b': ['c'], 'c': ['a']})
except CycleError as e:
    assert isinstance(e.cycle, list), e.cycle
    assert e.cycle[0] == e.cycle[-1], e.cycle
    assert set(e.cycle) == {'a', 'b', 'c'}, e.cycle
else:
    raise AssertionError('a cycle must raise CycleError')

try:
    toposort({'a': ['a']})
except CycleError as e:
    assert set(e.cycle) == {'a'}, e.cycle
    assert e.cycle[0] == e.cycle[-1], e.cycle
else:
    raise AssertionError('a self loop must raise CycleError')
print('OK')
""",
    },
    {
        "id": "config_merge",
        "tier": "impl",
        "task": (
            "Create config.py defining merge(base, override, list_strategy='replace') which deep "
            "merges two configuration dictionaries and returns a new one without mutating "
            "either input. Nested dicts merge key by key. Lists follow list_strategy: 'replace' "
            "takes the override list, 'append' concatenates base then override, and 'unique' "
            "concatenates and then drops later duplicates while keeping first-seen order. Any "
            "other strategy raises a ValueError mentioning the strategy. A value of None on "
            "either side is always replaceable. int and float mix freely, but bool does not "
            "count as a number. Any other type conflict raises a ValueError whose message "
            "contains the dotted path to the conflict."
        ),
        "reference": {
            "config.py": '''"""Deep configuration merge."""
import copy

STRATEGIES = ("replace", "append", "unique")


def _numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _merge(base, override, strategy, path):
    if isinstance(base, dict) and isinstance(override, dict):
        out = copy.deepcopy(base)
        for key, value in override.items():
            here = f"{path}.{key}" if path else str(key)
            out[key] = _merge(base[key], value, strategy, here) if key in base else copy.deepcopy(value)
        return out
    if isinstance(base, list) and isinstance(override, list):
        if strategy == "replace":
            return copy.deepcopy(override)
        combined = copy.deepcopy(base) + copy.deepcopy(override)
        if strategy == "append":
            return combined
        seen, unique = set(), []
        for item in combined:
            marker = repr(item)
            if marker not in seen:
                seen.add(marker)
                unique.append(item)
        return unique
    if base is None or override is None or type(base) is type(override):
        return copy.deepcopy(override)
    if _numeric(base) and _numeric(override):
        return copy.deepcopy(override)
    raise ValueError(
        f"type conflict at {path or '<root>'}: {type(base).__name__} vs {type(override).__name__}"
    )


def merge(base, override, list_strategy="replace"):
    if list_strategy not in STRATEGIES:
        raise ValueError(f"unknown list strategy: {list_strategy!r}")
    return _merge(base, override, list_strategy, "")
''',
        },
        "test": r"""
from config import merge

base = {'a': 1, 'b': {'c': 2, 'd': [1, 2]}, 'e': 'x', 'n': None}
snapshot = {'a': 1, 'b': {'c': 2, 'd': [1, 2]}, 'e': 'x', 'n': None}
out = merge(base, {'b': {'c': 3, 'z': 9}, 'f': True})
assert out == {'a': 1, 'b': {'c': 3, 'd': [1, 2], 'z': 9}, 'e': 'x', 'n': None, 'f': True}, out
assert base == snapshot, 'inputs must not be mutated'

assert merge({'d': [1, 2]}, {'d': [3]})['d'] == [3]
assert merge({'d': [1, 2]}, {'d': [3]}, list_strategy='append')['d'] == [1, 2, 3]
assert merge({'d': [1, 2]}, {'d': [2, 3]}, list_strategy='unique')['d'] == [1, 2, 3]
assert merge({'n': None}, {'n': 5})['n'] == 5
assert merge({'n': 5}, {'n': None})['n'] is None
assert merge({'a': 1}, {'a': 2.5})['a'] == 2.5
assert merge({}, {'a': {'b': 1}}) == {'a': {'b': 1}}

def failure(b, o, **kw):
    try:
        merge(b, o, **kw)
    except ValueError as e:
        return str(e)
    raise AssertionError('expected ValueError')

assert 'b.c' in failure({'b': {'c': 1}}, {'b': {'c': [1]}}), failure({'b': {'c': 1}}, {'b': {'c': [1]}})
assert 'strategy' in failure({}, {}, list_strategy='nope').lower()
assert failure({'a': 1}, {'a': True}), 'bool is not a number'
print('OK')
""",
    },
    {
        "id": "bank_ledger",
        "tier": "impl",
        "task": (
            "Create ledger.py defining a Ledger class that keeps a double-entry book in integer "
            "cents. post(description, entries) takes a list of (account, amount) pairs, requires "
            "at least two entries whose amounts are plain ints that sum to zero, and returns a "
            "transaction id counting up from 1. A rejected post must raise ValueError and leave "
            "every balance unchanged; a bool is not a valid amount. balance(account) returns the "
            "signed total for that account and 0 for an unknown one. accounts() returns the "
            "sorted list of accounts seen so far. history(account=None) returns one dict per "
            "posted entry in post order, each with the keys id, description, account, and "
            "amount, filtered to a single account when one is given. reverse(txn_id) posts the "
            "exact inverse of that transaction and returns the new id, raising KeyError for an "
            "unknown id."
        ),
        "reference": {
            "ledger.py": '''"""Double-entry ledger in integer cents."""


class Ledger:
    def __init__(self):
        self._entries = []
        self._next_id = 1

    def post(self, description, entries):
        rows = list(entries)
        if len(rows) < 2:
            raise ValueError("a transaction needs at least two entries")
        for account, amount in rows:
            if isinstance(amount, bool) or not isinstance(amount, int):
                raise ValueError(f"amount for {account!r} must be an integer number of cents")
        if sum(amount for _, amount in rows) != 0:
            raise ValueError("entries must sum to zero")
        txn = self._next_id
        self._next_id += 1
        for account, amount in rows:
            self._entries.append({
                "id": txn,
                "description": description,
                "account": account,
                "amount": amount,
            })
        return txn

    def balance(self, account):
        return sum(row["amount"] for row in self._entries if row["account"] == account)

    def accounts(self):
        return sorted({row["account"] for row in self._entries})

    def history(self, account=None):
        return [dict(row) for row in self._entries if account is None or row["account"] == account]

    def reverse(self, txn_id):
        rows = [row for row in self._entries if row["id"] == txn_id]
        if not rows:
            raise KeyError(txn_id)
        return self.post(
            f"reversal of {txn_id}",
            [(row["account"], -row["amount"]) for row in rows],
        )
''',
        },
        "test": r"""
import ledger as L

book = L.Ledger()
assert book.balance('cash') == 0
assert book.accounts() == []

t1 = book.post('sale', [('cash', 1000), ('revenue', -1000)])
assert t1 == 1, t1
assert book.balance('cash') == 1000 and book.balance('revenue') == -1000
assert book.balance('nope') == 0
assert book.accounts() == ['cash', 'revenue'], book.accounts()

t2 = book.post('refund', [('cash', -250), ('revenue', 250)])
assert t2 == 2 and book.balance('cash') == 750, book.balance('cash')

rows = book.history('cash')
assert [r['amount'] for r in rows] == [1000, -250], rows
assert rows[0]['description'] == 'sale' and rows[0]['id'] == 1, rows[0]
assert set(rows[0]) == {'id', 'description', 'account', 'amount'}, rows[0]
assert len(book.history()) == 4, len(book.history())

t3 = book.reverse(1)
assert t3 == 3, t3
assert book.balance('cash') == -250, book.balance('cash')
assert book.balance('revenue') == 250, book.balance('revenue')

def bad(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return
    except Exception as e:
        raise AssertionError(f'expected {exc.__name__}, got {type(e).__name__}')
    raise AssertionError(f'expected {exc.__name__}')

bad(lambda: book.post('bad', [('cash', 1), ('revenue', 1)]))
bad(lambda: book.post('bad', [('cash', 0)]))
bad(lambda: book.post('bad', [('cash', 1.5), ('revenue', -1.5)]))
bad(lambda: book.post('bad', [('cash', True), ('revenue', -1)]))
bad(lambda: book.reverse(99), KeyError)
assert book.balance('cash') == -250, 'a rejected post must not change balances'
assert len(book.history()) == 6, len(book.history())
print('OK')
""",
    },
]
