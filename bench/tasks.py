"""Objective coding benchmark for the LOLM code agent.

Every task names an EXACT output path and function signature, so a hidden test
written independently of the agent can import and score it. The hidden test is
written into the sandbox only AFTER the agent finishes, so it cannot be read,
weakened, or deleted by the agent — the failure mode that makes self-reported
"green runs" worthless.

Rules every task respects (they mirror the real sandbox's hard limits):
  - stdlib only, no network, no pip
  - must run and exit well inside the run timeout
  - no interactive input

`seed` pre-populates the sandbox with existing (buggy) files. Those tasks are the
closest analogue to what people actually use Claude Code for: change working code
without breaking it.
"""

from __future__ import annotations

TASKS = [
    # ── pure implementation, edge-case heavy ────────────────────────────────
    {
        "id": "iso_duration",
        "tier": "impl",
        "task": (
            "Create solution.py defining parse_duration(s) -> float that converts an "
            "ISO-8601 duration string to total seconds as a float. Support the date part "
            "(Y=365 days, M=30 days, W=7 days, D) and the time part after 'T' (H, M, S), "
            "fractional seconds, and a leading '-' meaning the whole duration is negative. "
            "Examples: 'P3DT4H5M6S' -> 273906.0, 'PT0.5S' -> 0.5, 'P1Y' -> 31536000.0, "
            "'-PT5M' -> -300.0, 'PT1H' -> 3600.0. "
            "Raise ValueError for input that is not a valid duration, including '', 'P', "
            "'hello', and '3D' (no leading P). "
            "Do not add test cases of your own beyond the examples given."
        ),
        "test": """
import solution as S
def bad(s):
    try:
        S.parse_duration(s)
    except ValueError:
        return True
    except Exception as e:
        raise AssertionError(f"{s!r} raised {type(e).__name__}, expected ValueError")
    raise AssertionError(f"{s!r} should have raised ValueError")

assert abs(S.parse_duration('P3DT4H5M6S') - 273906.0) < 1e-6, S.parse_duration('P3DT4H5M6S')
assert abs(S.parse_duration('PT0.5S') - 0.5) < 1e-9, S.parse_duration('PT0.5S')
assert abs(S.parse_duration('P1Y') - 31536000.0) < 1e-6, S.parse_duration('P1Y')
assert abs(S.parse_duration('-PT5M') + 300.0) < 1e-9, S.parse_duration('-PT5M')
assert abs(S.parse_duration('PT1H') - 3600.0) < 1e-9, S.parse_duration('PT1H')
assert abs(S.parse_duration('P1W') - 604800.0) < 1e-6, S.parse_duration('P1W')
assert abs(S.parse_duration('PT0S')) < 1e-9
for s in ('', 'P', 'hello', '3D'):
    bad(s)
print('OK')
""",
    },
    {
        "id": "roman",
        "tier": "impl",
        "task": (
            "Create solution.py defining to_roman(n) -> str and from_roman(s) -> int for "
            "standard Roman numerals covering 1 through 3999, using the usual subtractive "
            "forms (IV, IX, XL, XC, CD, CM). to_roman must raise ValueError for anything "
            "outside 1..3999 and for non-integers. from_roman must accept uppercase input "
            "and raise ValueError for malformed numerals such as 'IIII', 'VV', 'IC', '', "
            "and 'ABC'. The two must round-trip for every value in 1..3999."
        ),
        "test": """
import solution as S
for n in range(1, 4000):
    r = S.to_roman(n)
    assert S.from_roman(r) == n, (n, r, S.from_roman(r))
assert S.to_roman(4) == 'IV'
assert S.to_roman(9) == 'IX'
assert S.to_roman(40) == 'XL'
assert S.to_roman(1994) == 'MCMXCIV', S.to_roman(1994)
assert S.to_roman(3999) == 'MMMCMXCIX', S.to_roman(3999)
def bad(fn, v):
    try:
        fn(v)
    except ValueError:
        return
    except Exception as e:
        raise AssertionError(f"{v!r} raised {type(e).__name__}, expected ValueError")
    raise AssertionError(f"{v!r} should raise ValueError")
for v in (0, 4000, -1):
    bad(S.to_roman, v)
for v in ('IIII', 'VV', 'IC', '', 'ABC'):
    bad(S.from_roman, v)
print('OK')
""",
    },
    {
        "id": "interval_merge",
        "tier": "impl",
        "task": (
            "Create solution.py defining merge(intervals) that takes a list of "
            "[start, end] pairs (unsorted, possibly overlapping, ints or floats) and "
            "returns a new sorted list of merged [start, end] pairs. Intervals that only "
            "touch at an endpoint merge into one. An empty input returns an empty list. "
            "Raise ValueError if any interval has start > end. Do not mutate the input."
        ),
        "test": """
import solution as S
assert S.merge([]) == []
assert S.merge([[1, 3]]) == [[1, 3]]
assert S.merge([[1, 3], [2, 6], [8, 10], [15, 18]]) == [[1, 6], [8, 10], [15, 18]]
assert S.merge([[1, 4], [4, 5]]) == [[1, 5]]
assert S.merge([[5, 6], [1, 2]]) == [[1, 2], [5, 6]]
assert S.merge([[1, 10], [2, 3], [4, 5]]) == [[1, 10]]
src = [[3, 4], [1, 2]]
snapshot = [list(x) for x in src]
S.merge(src)
assert src == snapshot, f"input was mutated: {src} != {snapshot}"
try:
    S.merge([[5, 1]])
except ValueError:
    pass
else:
    raise AssertionError('start > end must raise ValueError')
print('OK')
""",
    },
    {
        "id": "lru",
        "tier": "impl",
        "task": (
            "Create solution.py defining a class LRU(capacity) implementing a "
            "least-recently-used cache with get(key) returning the value or None when "
            "absent, and put(key, value). Both get and put count as a use. When the cache "
            "is over capacity, evict the least recently used entry. Expose len(cache) as "
            "the number of live entries. LRU(0) must accept puts without storing anything. "
            "Raise ValueError for a negative capacity."
        ),
        "test": """
import solution as S
c = S.LRU(2)
c.put('a', 1); c.put('b', 2)
assert c.get('a') == 1
c.put('c', 3)                     # 'b' is LRU -> evicted
assert c.get('b') is None, 'b should have been evicted'
assert c.get('a') == 1 and c.get('c') == 3
assert len(c) == 2, len(c)
c.put('a', 99)
assert c.get('a') == 99
z = S.LRU(0)
z.put('x', 1)
assert z.get('x') is None and len(z) == 0
try:
    S.LRU(-1)
except ValueError:
    pass
else:
    raise AssertionError('negative capacity must raise ValueError')
big = S.LRU(3)
for i, k in enumerate('abc'):
    big.put(k, i)
big.get('a')                      # 'b' now LRU
big.put('d', 3)
assert big.get('b') is None, 'b should be evicted after a was refreshed'
assert big.get('a') == 0 and big.get('c') == 2 and big.get('d') == 3
print('OK')
""",
    },
    {
        "id": "semver",
        "tier": "impl",
        "task": (
            "Create solution.py defining compare(a, b) -> int that compares two semantic "
            "version strings, returning -1, 0, or 1. Follow semver precedence: compare "
            "major, minor, patch numerically; a version WITH a prerelease is lower than "
            "the same version without one; prerelease identifiers compare dot-separated, "
            "numeric identifiers numerically and lower than alphanumeric ones. Build "
            "metadata after '+' is ignored entirely. Raise ValueError on malformed input "
            "like '1.2', 'x.y.z', and ''."
        ),
        "test": """
import solution as S
assert S.compare('1.0.0', '1.0.1') == -1
assert S.compare('1.0.1', '1.0.0') == 1
assert S.compare('1.0.0', '1.0.0') == 0
assert S.compare('2.0.0', '1.9.9') == 1
assert S.compare('1.0.0-alpha', '1.0.0') == -1
assert S.compare('1.0.0', '1.0.0-alpha') == 1
assert S.compare('1.0.0-alpha', '1.0.0-alpha.1') == -1
assert S.compare('1.0.0-alpha.1', '1.0.0-alpha.beta') == -1
assert S.compare('1.0.0-alpha.beta', '1.0.0-beta') == -1
assert S.compare('1.0.0-beta.2', '1.0.0-beta.11') == -1
assert S.compare('1.0.0-rc.1', '1.0.0') == -1
assert S.compare('1.0.0+build1', '1.0.0+build2') == 0
assert S.compare('1.0.0+x', '1.0.0') == 0
for bad_in in ('1.2', 'x.y.z', ''):
    try:
        S.compare(bad_in, '1.0.0')
    except ValueError:
        continue
    raise AssertionError(f'{bad_in!r} must raise ValueError')
print('OK')
""",
    },
    {
        "id": "expr_eval",
        "tier": "impl",
        "task": (
            "Create solution.py defining evaluate(s) -> float, an arithmetic expression "
            "evaluator supporting + - * / and parentheses, unary minus, integer and decimal "
            "literals, and arbitrary whitespace. Standard precedence and left associativity. "
            "Division by zero must raise ZeroDivisionError. Malformed input such as '1 +', "
            "'(1', '', and '2 ** 3' must raise ValueError. Do not use eval or exec."
        ),
        "test": """
import solution as S, pathlib
src = pathlib.Path('solution.py').read_text()
assert 'eval(' not in src.replace('evaluate(', ''), 'must not use eval'
assert 'exec(' not in src, 'must not use exec'
assert abs(S.evaluate('1+2*3') - 7) < 1e-9
assert abs(S.evaluate('(1+2)*3') - 9) < 1e-9
assert abs(S.evaluate('-4 + 2') + 2) < 1e-9
assert abs(S.evaluate('10 / 4') - 2.5) < 1e-9
assert abs(S.evaluate('2*(3+4)-5') - 9) < 1e-9
assert abs(S.evaluate('  7  ') - 7) < 1e-9
assert abs(S.evaluate('1.5*2') - 3.0) < 1e-9
assert abs(S.evaluate('8/2/2') - 2.0) < 1e-9
assert abs(S.evaluate('-(3+2)') + 5) < 1e-9
try:
    S.evaluate('1/0')
except ZeroDivisionError:
    pass
else:
    raise AssertionError('1/0 must raise ZeroDivisionError')
for bad_in in ('1 +', '(1', '', '2 ** 3'):
    try:
        S.evaluate(bad_in)
    except ValueError:
        continue
    except ZeroDivisionError:
        raise AssertionError(f'{bad_in!r} wrong exception')
    raise AssertionError(f'{bad_in!r} must raise ValueError')
print('OK')
""",
    },
    {
        "id": "jsonpath",
        "tier": "impl",
        "task": (
            "Create solution.py defining get(obj, path, default=None) that reads a nested "
            "value out of dicts and lists using a dotted path with bracket indices, e.g. "
            "'a.b', 'items[0].name', 'x[1][2]'. Negative indices work like Python's. "
            "Return default when any step is missing, the index is out of range, or the "
            "type does not support the step — never raise for a missing path. Raise "
            "ValueError for a malformed path such as '', 'a..b', or 'a[x]'."
        ),
        "test": """
import solution as S
d = {'a': {'b': 7}, 'items': [{'name': 'x'}, {'name': 'y'}], 'x': [[0, 1, 2], [3, 4, 5]]}
assert S.get(d, 'a.b') == 7
assert S.get(d, 'items[0].name') == 'x'
assert S.get(d, 'items[1].name') == 'y'
assert S.get(d, 'items[-1].name') == 'y'
assert S.get(d, 'x[1][2]') == 5
assert S.get(d, 'a.zz') is None
assert S.get(d, 'a.zz', 'fb') == 'fb'
assert S.get(d, 'items[9].name', 'fb') == 'fb'
assert S.get(d, 'a.b.c', 'fb') == 'fb'
assert S.get(d, 'nope[0]', 'fb') == 'fb'
for bad_in in ('', 'a..b', 'a[x]'):
    try:
        S.get(d, bad_in)
    except ValueError:
        continue
    raise AssertionError(f'{bad_in!r} must raise ValueError')
print('OK')
""",
    },
    {
        "id": "wrap",
        "tier": "impl",
        "task": (
            "Create solution.py defining wrap(text, width) -> list[str] that word-wraps "
            "text to at most `width` characters per line. Split on whitespace; never leave "
            "trailing spaces; a single word longer than width is hard-broken across lines. "
            "A blank line in the input separates paragraphs and must be preserved as an "
            "empty string in the output. Empty text returns an empty list. Raise ValueError "
            "when width < 1. Do not use the textwrap module."
        ),
        "test": """
import solution as S, pathlib
src = pathlib.Path('solution.py').read_text()
assert 'textwrap' not in src, 'must not use textwrap'
assert S.wrap('', 10) == []
assert S.wrap('hello world', 20) == ['hello world']
out = S.wrap('the quick brown fox jumps', 10)
assert all(len(x) <= 10 for x in out), out
assert ' '.join(out).split() == 'the quick brown fox jumps'.split(), out
assert all(x == x.rstrip() for x in out), out
long = S.wrap('abcdefghijkl', 5)
assert long == ['abcde', 'fghij', 'kl'], long
para = S.wrap('one two\\n\\nthree four', 20)
assert '' in para, para
assert para[0].startswith('one') and para[-1].startswith('three'), para
try:
    S.wrap('x', 0)
except ValueError:
    pass
else:
    raise AssertionError('width < 1 must raise ValueError')
print('OK')
""",
    },

    # ── change existing code without breaking it (the Claude Code use case) ──
    {
        "id": "fix_pagination",
        "tier": "fix",
        "task": (
            "The file paginate.py has bugs. page_items(items, page, per_page) is meant to "
            "return the 1-indexed page slice, and total_pages(n, per_page) the number of "
            "pages. Right now page_items returns the wrong slice (it is off by one page) "
            "and total_pages truncates instead of rounding up, so a partial last page is "
            "lost. Read paginate.py, fix both functions in place, and keep the existing "
            "signatures and module name exactly as they are. page 1 must return the first "
            "per_page items; a page past the end returns an empty list; total_pages(0, n) "
            "is 0. Raise ValueError for page < 1 or per_page < 1."
        ),
        "seed": {
            "paginate.py": '''"""Pagination helpers used by the reports endpoint."""


def page_items(items, page, per_page):
    """Return the slice of `items` on 1-indexed `page`."""
    start = page * per_page
    return items[start:start + per_page]


def total_pages(n, per_page):
    """How many pages `n` items need."""
    return n // per_page
''',
        },
        "test": """
import paginate as P
xs = list(range(10))
assert P.page_items(xs, 1, 3) == [0, 1, 2], P.page_items(xs, 1, 3)
assert P.page_items(xs, 2, 3) == [3, 4, 5], P.page_items(xs, 2, 3)
assert P.page_items(xs, 4, 3) == [9], P.page_items(xs, 4, 3)
assert P.page_items(xs, 5, 3) == [], P.page_items(xs, 5, 3)
assert P.total_pages(10, 3) == 4, P.total_pages(10, 3)
assert P.total_pages(9, 3) == 3, P.total_pages(9, 3)
assert P.total_pages(0, 3) == 0, P.total_pages(0, 3)
assert P.total_pages(1, 3) == 1, P.total_pages(1, 3)
for args in ((xs, 0, 3), (xs, 1, 0)):
    try:
        P.page_items(*args)
    except ValueError:
        continue
    raise AssertionError(f'{args} must raise ValueError')
print('OK')
""",
    },
    {
        "id": "fix_multifile_stats",
        "tier": "fix",
        "task": (
            "This project has two files. stats.py provides median and percentile; report.py "
            "uses them. Both have bugs: median returns the wrong value for an even-length "
            "input (it must average the two middle values) and crashes on an empty list "
            "instead of raising ValueError; percentile(values, p) uses the wrong index and "
            "does not clamp p to 0..100. report.py's summarize must return a dict with keys "
            "'n', 'median', and 'p90'. Read both files, fix stats.py, and make report.py's "
            "summarize correct. Keep both module names and all existing function names. "
            "Do not delete either file."
        ),
        "seed": {
            "stats.py": '''"""Small statistics helpers (no third-party deps)."""


def median(values):
    vs = sorted(values)
    return vs[len(vs) // 2]


def percentile(values, p):
    vs = sorted(values)
    idx = int(len(vs) * p / 100)
    return vs[idx]
''',
            "report.py": '''"""Summarize a batch of latency samples."""

from stats import median, percentile


def summarize(samples):
    return {"n": len(samples), "median": median(samples)}
''',
        },
        "test": """
import stats as St, report as R
assert St.median([1, 2, 3]) == 2
assert St.median([1, 2, 3, 4]) == 2.5, St.median([1, 2, 3, 4])
assert St.median([5]) == 5
try:
    St.median([])
except ValueError:
    pass
else:
    raise AssertionError('median([]) must raise ValueError')
xs = list(range(1, 101))
assert St.percentile(xs, 0) == 1, St.percentile(xs, 0)
assert St.percentile(xs, 100) == 100, St.percentile(xs, 100)
assert St.percentile(xs, 150) == 100, 'p must clamp at 100'
assert St.percentile(xs, -5) == 1, 'p must clamp at 0'
assert St.percentile([10], 50) == 10
out = R.summarize([1, 2, 3, 4])
assert set(out) == {'n', 'median', 'p90'}, out
assert out['n'] == 4 and out['median'] == 2.5, out
print('OK')
""",
    },
    {
        "id": "fix_state_machine",
        "tier": "fix",
        "task": (
            "orders.py implements an order state machine that is wrong. Legal transitions "
            "are: new -> paid, new -> cancelled, paid -> shipped, paid -> refunded, "
            "shipped -> delivered. Nothing may leave the terminal states cancelled, "
            "refunded, or delivered. Read orders.py and fix the Order class so transition(to) "
            "performs a legal move and raises ValueError with the current and target state "
            "in the message for an illegal one, history() returns the full ordered list of "
            "states starting with 'new', and is_terminal() is correct. Keep the class name "
            "Order and the method names as they are."
        ),
        "seed": {
            "orders.py": '''"""Order lifecycle."""

ALLOWED = {
    "new": ["paid"],
    "paid": ["shipped"],
    "shipped": ["delivered"],
}

TERMINAL = ["delivered"]


class Order:
    def __init__(self):
        self.state = "new"
        self._history = []

    def transition(self, to):
        self.state = to
        self._history.append(to)
        return self.state

    def history(self):
        return self._history

    def is_terminal(self):
        return self.state in TERMINAL
''',
        },
        "test": """
import orders as O
o = O.Order()
assert o.state == 'new' and o.history() == ['new'], o.history()
o.transition('paid'); o.transition('shipped'); o.transition('delivered')
assert o.history() == ['new', 'paid', 'shipped', 'delivered'], o.history()
assert o.is_terminal()
for to in ('paid', 'shipped', 'new'):
    try:
        o.transition(to)
    except ValueError as e:
        assert 'delivered' in str(e) and to in str(e), f'message must name both states: {e}'
    else:
        raise AssertionError('terminal state must not transition')
c = O.Order(); c.transition('cancelled')
assert c.is_terminal() and c.history() == ['new', 'cancelled'], c.history()
r = O.Order(); r.transition('paid'); r.transition('refunded')
assert r.is_terminal(), 'refunded is terminal'
b = O.Order()
try:
    b.transition('shipped')
except ValueError as e:
    assert 'new' in str(e) and 'shipped' in str(e), e
else:
    raise AssertionError('new -> shipped is illegal')
assert b.state == 'new', 'a rejected transition must not change state'
assert b.history() == ['new'], b.history()
print('OK')
""",
    },
    {
        "id": "fix_csv_parser",
        "tier": "fix",
        "task": (
            "csvlite.py has a hand-rolled CSV parser that mishandles quotes. parse(text) "
            "must return a list of rows, each a list of field strings. It has to handle "
            "quoted fields containing commas, doubled quotes (\"\") meaning one literal "
            "quote inside a quoted field, empty fields, and a trailing newline (which must "
            "not produce an extra empty row). Read csvlite.py and fix parse in place. Keep "
            "the module name and the function name parse. Do not import the csv module."
        ),
        "seed": {
            "csvlite.py": '''"""Minimal CSV reader (we cannot use the stdlib csv module here)."""


def parse(text):
    rows = []
    for line in text.split("\\n"):
        rows.append(line.split(","))
    return rows
''',
        },
        # ''' delimited: this test's own source contains a "" pair next to a quote,
        # which would close a """ string early.
        "test": '''
import csvlite as C, pathlib
src = pathlib.Path('csvlite.py').read_text()
assert 'import csv' not in src, 'must not import csv'
assert C.parse('a,b\\n1,2') == [['a', 'b'], ['1', '2']]
assert C.parse('a,b\\n1,2\\n') == [['a', 'b'], ['1', '2']], 'trailing newline must not add a row'
assert C.parse('"x,y",z') == [['x,y', 'z']], C.parse('"x,y",z')
q = 'he said ' + chr(34) + 'hi' + chr(34)
doubled = '"he said ""hi""",z'
assert C.parse(doubled) == [[q, 'z']], C.parse(doubled)
assert C.parse('a,,c') == [['a', '', 'c']]
assert C.parse('') == [] or C.parse('') == [['']], C.parse('')
assert C.parse('"multi\\nline",b') == [['multi\\nline', 'b']], C.parse('"multi\\nline",b')
print('OK')
''',
    },
]


from bench.tasks_hard import HARD_TASKS  # noqa: E402

TASKS = TASKS + HARD_TASKS


def by_id(task_id: str):
    for t in TASKS:
        if t["id"] == task_id:
            return t
    raise KeyError(task_id)
