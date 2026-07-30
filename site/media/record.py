#!/usr/bin/env python3
"""Record the terminal replay into web-ready video.

Points headless Chromium at render_cast.html, records the page, then transcodes to
mp4 (h264, broad support) and webm (vp9, smaller) and pulls a poster frame. Nothing is
re-enacted: the replay is driven by a cast captured off a real pty session.

    python3 site/media/record.py --cast cli-session.json --name cli-demo

Needs ffmpeg on PATH and the project's Playwright install.
"""

from __future__ import annotations

import argparse
import http.server
import json
import shutil
import socket
import subprocess
import threading
import time
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parent
W, H = 1000, 620


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(directory: Path, port: int):
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def record(cast: str, name: str, speed: float, out_dir: Path) -> Path:
    from playwright.sync_api import sync_playwright

    port = free_port()
    httpd = serve(HERE, port)
    raw_dir = out_dir / "_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--force-device-scale-factor=2"])
            ctx = browser.new_context(
                viewport={"width": W, "height": H},
                device_scale_factor=2,
                record_video_dir=str(raw_dir),
                record_video_size={"width": W, "height": H},
            )
            page = ctx.new_page()
            page.goto(f"http://127.0.0.1:{port}/render_cast.html"
                      f"?cast={cast}&speed={speed}", wait_until="load")
            page.wait_for_function("window.__castDone === true", timeout=180_000)
            path = page.video.path()
            ctx.close()            # flush the video file
            browser.close()
    finally:
        httpd.shutdown()
    return Path(path)


def transcode(src: Path, name: str, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4 = out_dir / f"{name}.mp4"
    webm = out_dir / f"{name}.webm"
    poster = out_dir / f"{name}.jpg"
    # yuv420p + faststart so it plays inline on iOS and starts before full download.
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                    "-vf", "scale=1000:-2", "-c:v", "libx264", "-preset", "slow",
                    "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    "-an", str(mp4)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                    "-vf", "scale=1000:-2", "-c:v", "libvpx-vp9", "-crf", "38",
                    "-b:v", "0", "-row-mt", "1", "-an", str(webm)], check=True)
    # Poster = the final frame, which is the receipt — the part worth seeing at rest.
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(src)],
        capture_output=True, text=True, check=True).stdout.strip())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(dur - 0.4, 0):.2f}",
                    "-i", str(src), "-frames:v", "1", "-vf", "scale=1000:-2",
                    "-q:v", "4", str(poster)], check=True)
    return {"mp4": mp4, "webm": webm, "poster": poster, "duration": dur}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cast", default="cli-session.json")
    ap.add_argument("--name", default="cli-demo")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--out", default=str(HERE))
    a = ap.parse_args()
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not on PATH")
    out_dir = Path(a.out)
    print(f"[record] replaying {a.cast} at {a.speed}x …")
    raw = record(a.cast, a.name, a.speed, out_dir)
    print(f"[record] raw {raw.name} ({raw.stat().st_size // 1024} KB)")
    res = transcode(raw, a.name, out_dir)
    for k in ("mp4", "webm", "poster"):
        p = res[k]
        print(f"[record] {k:<7} {p.name:<20} {p.stat().st_size // 1024:>5} KB")
    print(f"[record] duration {res['duration']:.1f}s")
    shutil.rmtree(out_dir / "_raw", ignore_errors=True)


if __name__ == "__main__":
    main()
