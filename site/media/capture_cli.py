#!/usr/bin/env python3
"""Capture a REAL `lolm` CLI session with timing, for the homepage demo.

Runs the command under a pty so the CLI emits its normal colours and behaves exactly
as it does in a terminal, and records every output chunk with the wall-clock offset it
actually arrived at. The result is a faithful recording of a real run — nothing is
scripted, retimed, or re-enacted. If the agent takes a wrong turn, that is what the
video shows.

    python3 site/media/capture_cli.py --out site/media/cli-session.json -- \
        node clients/cli/bin/lolm.mjs code "..." --save /tmp/demo

Output: {"cols":N,"rows":N,"started":iso,"argv":[...],"chunks":[[t,text],...]}
"""

from __future__ import annotations

import argparse
import json
import os
import pty
import select
import sys
import time
from pathlib import Path


def capture(argv, cols=100, rows=30, idle_cap=2.5):
    """Run argv under a pty, returning timestamped output chunks.

    idle_cap compresses dead air: a real run can sit silent for 20s waiting on a
    model, which is honest but unwatchable. Gaps longer than idle_cap are clamped to
    it, and the compression is recorded so the page can say so.
    """
    pid, fd = pty.fork()
    if pid == 0:                                  # child
        os.environ["COLUMNS"], os.environ["LINES"] = str(cols), str(rows)
        os.environ["FORCE_COLOR"] = "1"
        os.execvp(argv[0], argv)
    chunks, t0, last = [], time.time(), time.time()
    compressed = 0.0
    try:
        while True:
            r, _, _ = select.select([fd], [], [], 60)
            if not r:
                break
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            now = time.time()
            gap = now - last
            if gap > idle_cap:
                compressed += gap - idle_cap
            last = now
            t = round(now - t0 - compressed, 3)
            chunks.append([t, data.decode("utf-8", "replace")])
            sys.stdout.write(data.decode("utf-8", "replace"))
            sys.stdout.flush()
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
    return chunks, round(compressed, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--cols", type=int, default=100)
    ap.add_argument("--rows", type=int, default=30)
    ap.add_argument("--idle-cap", type=float, default=2.5)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    argv = [x for x in a.cmd if x != "--"]
    if not argv:
        raise SystemExit("give a command after --")
    chunks, compressed = capture(argv, a.cols, a.rows, a.idle_cap)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "cols": a.cols, "rows": a.rows,
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "argv": argv,
        "idle_compressed_s": compressed,
        "duration_s": chunks[-1][0] if chunks else 0,
        "chunks": chunks,
    }, ensure_ascii=False))
    print(f"\n[capture] {len(chunks)} chunks, {out.stat().st_size} bytes, "
          f"{chunks[-1][0] if chunks else 0}s playback "
          f"({compressed}s of model wait compressed) -> {out}")


if __name__ == "__main__":
    main()
