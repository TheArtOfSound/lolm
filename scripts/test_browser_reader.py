#!/usr/bin/env python3
"""Smoke-test the LOLM-NFET browser reader."""

from __future__ import annotations

import argparse
import json

from local_ui.browser_reader_client import launch_browser_reader


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="https://example.com")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    browser = launch_browser_reader(headless=args.headless)
    try:
        nav = browser.navigate(args.url)
        text = browser.text()
        print(json.dumps({"navigate": nav, "text": text}, indent=2, ensure_ascii=False))
    finally:
        browser.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
