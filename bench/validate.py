#!/usr/bin/env python3
"""Validate the benchmark itself.

A hidden test that a correct solution cannot pass would make every score
meaningless, so each task ships a reference implementation here and this script
asserts the hidden test goes green against it. It also asserts the SEED files fail
their test, which proves a "fix" task actually has the bug it claims.

    python3 bench/validate.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bench.tasks import TASKS  # noqa: E402

REFERENCE = {
    "iso_duration": {"solution.py": r'''
import re

_RE = re.compile(
    r'^(?P<sign>-)?P(?!$)'
    r'(?:(?P<Y>\d+(?:\.\d+)?)Y)?'
    r'(?:(?P<M>\d+(?:\.\d+)?)M)?'
    r'(?:(?P<W>\d+(?:\.\d+)?)W)?'
    r'(?:(?P<D>\d+(?:\.\d+)?)D)?'
    r'(?:T(?!$)'
    r'(?:(?P<h>\d+(?:\.\d+)?)H)?'
    r'(?:(?P<m>\d+(?:\.\d+)?)M)?'
    r'(?:(?P<s>\d+(?:\.\d+)?)S)?'
    r')?$'
)
_MUL = {"Y": 365 * 86400.0, "M": 30 * 86400.0, "W": 7 * 86400.0, "D": 86400.0,
        "h": 3600.0, "m": 60.0, "s": 1.0}


def parse_duration(s):
    if not isinstance(s, str):
        raise ValueError("duration must be a string")
    m = _RE.match(s.strip())
    if not m:
        raise ValueError(f"invalid ISO-8601 duration: {s!r}")
    parts = {k: v for k, v in m.groupdict().items() if k != "sign" and v is not None}
    if not parts:
        raise ValueError(f"duration has no components: {s!r}")
    total = sum(float(v) * _MUL[k] for k, v in parts.items())
    return -total if m.group("sign") else total
'''},
    "roman": {"solution.py": r'''
_PAIRS = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
          (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
_VALID = None


def to_roman(n):
    if isinstance(n, bool) or not isinstance(n, int):
        raise ValueError("n must be an int")
    if not 1 <= n <= 3999:
        raise ValueError("n out of range 1..3999")
    out = []
    for v, sym in _PAIRS:
        while n >= v:
            out.append(sym)
            n -= v
    return "".join(out)


def from_roman(s):
    global _VALID
    if not isinstance(s, str) or not s:
        raise ValueError("empty numeral")
    if _VALID is None:
        _VALID = {to_roman(i): i for i in range(1, 4000)}
    try:
        return _VALID[s]
    except KeyError:
        raise ValueError(f"malformed numeral: {s!r}")
'''},
    "interval_merge": {"solution.py": r'''
def merge(intervals):
    items = []
    for iv in intervals or []:
        s, e = iv[0], iv[1]
        if s > e:
            raise ValueError(f"start > end: {iv!r}")
        items.append([s, e])
    items.sort(key=lambda x: (x[0], x[1]))
    out = []
    for s, e in items:
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out
'''},
    "lru": {"solution.py": r'''
from collections import OrderedDict


class LRU:
    def __init__(self, capacity):
        if capacity < 0:
            raise ValueError("capacity must be >= 0")
        self.capacity = capacity
        self._d = OrderedDict()

    def get(self, key):
        if key not in self._d:
            return None
        self._d.move_to_end(key)
        return self._d[key]

    def put(self, key, value):
        if self.capacity == 0:
            return
        self._d[key] = value
        self._d.move_to_end(key)
        while len(self._d) > self.capacity:
            self._d.popitem(last=False)

    def __len__(self):
        return len(self._d)
'''},
    "semver": {"solution.py": r'''
import re

_RE = re.compile(r'^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.\-]+))?(?:\+([0-9A-Za-z.\-]+))?$')


def _parse(v):
    if not isinstance(v, str):
        raise ValueError("version must be a string")
    m = _RE.match(v.strip())
    if not m:
        raise ValueError(f"invalid semver: {v!r}")
    core = tuple(int(x) for x in m.group(1, 2, 3))
    pre = m.group(4).split(".") if m.group(4) else None
    return core, pre


def _cmp_pre(a, b):
    if a is None and b is None:
        return 0
    if a is None:
        return 1
    if b is None:
        return -1
    for x, y in zip(a, b):
        xn, yn = x.isdigit(), y.isdigit()
        if xn and yn:
            if int(x) != int(y):
                return -1 if int(x) < int(y) else 1
        elif xn != yn:
            return -1 if xn else 1
        elif x != y:
            return -1 if x < y else 1
    if len(a) == len(b):
        return 0
    return -1 if len(a) < len(b) else 1


def compare(a, b):
    ca, pa = _parse(a)
    cb, pb = _parse(b)
    if ca != cb:
        return -1 if ca < cb else 1
    return _cmp_pre(pa, pb)
'''},
    "expr_eval": {"solution.py": r'''
import re

_TOK = re.compile(r'\s*(\d+\.\d+|\.\d+|\d+|[()+\-*/])')


def _lex(s):
    toks, i = [], 0
    while i < len(s):
        if s[i].isspace():
            i += 1
            continue
        m = _TOK.match(s, i)
        if not m:
            raise ValueError(f"bad character at {i}: {s[i]!r}")
        toks.append(m.group(1))
        i = m.end()
    return toks


class _P:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        v = self.peek()
        self.i += 1
        return v

    def expr(self):
        v = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            r = self.term()
            v = v + r if op == "+" else v - r
        return v

    def term(self):
        v = self.unary()
        while self.peek() in ("*", "/"):
            op = self.take()
            r = self.unary()
            if op == "*":
                v = v * r
            else:
                if r == 0:
                    raise ZeroDivisionError("division by zero")
                v = v / r
        return v

    def unary(self):
        if self.peek() == "-":
            self.take()
            return -self.unary()
        if self.peek() == "+":
            self.take()
            return self.unary()
        return self.atom()

    def atom(self):
        tok = self.take()
        if tok is None:
            raise ValueError("unexpected end of expression")
        if tok == "(":
            v = self.expr()
            if self.take() != ")":
                raise ValueError("missing )")
            return v
        try:
            return float(tok)
        except (TypeError, ValueError):
            raise ValueError(f"unexpected token {tok!r}")


def evaluate(s):
    if not isinstance(s, str):
        raise ValueError("expression must be a string")
    toks = _lex(s)
    if not toks:
        raise ValueError("empty expression")
    p = _P(toks)
    v = p.expr()
    if p.i != len(toks):
        raise ValueError("trailing tokens")
    return float(v)
'''},
    "jsonpath": {"solution.py": r'''
import re

_STEP = re.compile(r'^[A-Za-z_][\w\-]*$')
_IDX = re.compile(r'^\[(-?\d+)\]$')
_MISSING = object()


def _tokens(path):
    if not isinstance(path, str) or not path.strip():
        raise ValueError("empty path")
    out = []
    for part in path.split("."):
        if part == "":
            raise ValueError(f"malformed path: {path!r}")
        head, brackets = part, []
        if "[" in part:
            head = part[:part.index("[")]
            rest = part[part.index("["):]
            for chunk in re.findall(r'\[[^\]]*\]', rest):
                m = _IDX.match(chunk)
                if not m:
                    raise ValueError(f"malformed index {chunk!r} in {path!r}")
                brackets.append(int(m.group(1)))
            if "".join(re.findall(r'\[[^\]]*\]', rest)) != rest:
                raise ValueError(f"malformed path: {path!r}")
        if head:
            if not _STEP.match(head):
                raise ValueError(f"malformed key {head!r} in {path!r}")
            out.append(head)
        elif not brackets:
            raise ValueError(f"malformed path: {path!r}")
        out.extend(brackets)
    return out


def get(obj, path, default=None):
    cur = obj
    for step in _tokens(path):
        if isinstance(step, int):
            if not isinstance(cur, (list, tuple)):
                return default
            try:
                cur = cur[step]
            except IndexError:
                return default
        else:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(step, _MISSING)
            if cur is _MISSING:
                return default
    return cur
'''},
    "wrap": {"solution.py": r'''
def wrap(text, width):
    if not isinstance(width, int) or width < 1:
        raise ValueError("width must be >= 1")
    if not text or not text.strip():
        return []
    out = []
    paras = text.split("\n\n")
    for pi, para in enumerate(paras):
        if pi:
            out.append("")
        words, line = para.split(), ""
        for w in words:
            while len(w) > width:
                if line:
                    out.append(line)
                    line = ""
                out.append(w[:width])
                w = w[width:]
            if not line:
                line = w
            elif len(line) + 1 + len(w) <= width:
                line += " " + w
            else:
                out.append(line)
                line = w
        if line:
            out.append(line)
    return out
'''},
    "fix_pagination": {"paginate.py": r'''
def page_items(items, page, per_page):
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page must be >= 1")
    start = (page - 1) * per_page
    return items[start:start + per_page]


def total_pages(n, per_page):
    if per_page < 1:
        raise ValueError("per_page must be >= 1")
    return (n + per_page - 1) // per_page
'''},
    "fix_multifile_stats": {
        "stats.py": r'''
def median(values):
    vs = sorted(values)
    if not vs:
        raise ValueError("median of empty sequence")
    n = len(vs)
    mid = n // 2
    if n % 2:
        return vs[mid]
    return (vs[mid - 1] + vs[mid]) / 2


def percentile(values, p):
    vs = sorted(values)
    if not vs:
        raise ValueError("percentile of empty sequence")
    p = max(0, min(100, p))
    idx = int(round((len(vs) - 1) * p / 100))
    return vs[idx]
''',
        "report.py": r'''
from stats import median, percentile


def summarize(samples):
    return {"n": len(samples), "median": median(samples), "p90": percentile(samples, 90)}
''',
    },
    "fix_state_machine": {"orders.py": r'''
ALLOWED = {
    "new": ["paid", "cancelled"],
    "paid": ["shipped", "refunded"],
    "shipped": ["delivered"],
}

TERMINAL = ["cancelled", "refunded", "delivered"]


class Order:
    def __init__(self):
        self.state = "new"
        self._history = ["new"]

    def transition(self, to):
        if to not in ALLOWED.get(self.state, []):
            raise ValueError(f"illegal transition {self.state} -> {to}")
        self.state = to
        self._history.append(to)
        return self.state

    def history(self):
        return list(self._history)

    def is_terminal(self):
        return self.state in TERMINAL
'''},
    "fix_csv_parser": {"csvlite.py": r'''
def parse(text):
    if text == "":
        return []
    rows, row, field = [], [], ""
    i, n, in_q = 0, len(text), False
    while i < n:
        c = text[i]
        if in_q:
            if c == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field += '"'
                    i += 2
                    continue
                in_q = False
            else:
                field += c
        else:
            if c == '"':
                in_q = True
            elif c == ",":
                row.append(field)
                field = ""
            elif c == "\n":
                row.append(field)
                rows.append(row)
                row, field = [], ""
            elif c == "\r":
                pass
            else:
                field += c
        i += 1
    if field or row:
        row.append(field)
        rows.append(row)
    return rows
'''},
}


def check(task, files, expect_pass, what):
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        for name, body in files.items():
            target = d / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body.lstrip("\n"))
        (d / "_check.py").write_text(task["test"])
        p = subprocess.run([sys.executable, "_check.py"], cwd=d,
                           capture_output=True, text=True, timeout=120)
    ok = p.returncode == 0 and "OK" in p.stdout
    if ok == expect_pass:
        return True, ""
    tail = ((p.stderr or "") + (p.stdout or "")).strip().splitlines()
    return False, (f"{what}: expected {'PASS' if expect_pass else 'FAIL'}, got "
                   f"{'PASS' if ok else 'FAIL'}" + (f" :: {tail[-1][:160]}" if tail else ""))


def main():
    bad = []
    for t in TASKS:
        tid = t["id"]
        # Newer suites keep the reference beside the task so the two cannot drift.
        ref = t.get("reference") or REFERENCE.get(tid)
        if not ref:
            bad.append(f"{tid}: NO reference implementation — test is unvalidated")
            continue
        ok, msg = check(t, ref, True, f"{tid} reference")
        print(f"  {'ok  ' if ok else 'BAD '} {tid:<22} reference solution passes its hidden test")
        if not ok:
            bad.append(msg)
        # A fix task must actually be broken to start with, or it scores free passes.
        if t.get("seed"):
            ok2, msg2 = check(t, t["seed"], False, f"{tid} seed")
            print(f"  {'ok  ' if ok2 else 'BAD '} {tid:<22} buggy seed fails its hidden test")
            if not ok2:
                bad.append(msg2)
    print()
    if bad:
        print("BENCHMARK IS NOT TRUSTWORTHY:")
        for b in bad:
            print("  -", b)
        return 1
    print(f"all {len(TASKS)} tasks validated — hidden tests are correct and the "
          f"fix tasks are genuinely broken")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
