#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Run a generated HTML app in REAL headless Chromium and measure whether it
actually works — not whether the code merely exists.

This is what the visual builder was missing: it could not tell a working game
from a dead one, so it shipped blank canvases as "fully working." Here we load
the HTML, watch the canvas, and check three things a real game must do:

  renders  — the canvas draws real, non-uniform content (a blank/one-color
             canvas is the classic "blank maze box" failure)
  animates — the frame changes over ~1s WITHOUT input (the game loop is alive;
             a raycaster with no requestAnimationFrame never redraws)
  responds — the frame changes AFTER arrow/WASD/space input (controls are wired)

Plus JS console/page errors. A game is "working" when it renders AND (animates
OR responds) AND has no fatal errors. Standalone so it can run out-of-process
(no event-loop conflict with uvicorn): reads an HTML file path, prints a JSON
verdict on stdout.

Usage:  python3 scripts/visual_verify.py <html_file> [--wait 1500]
"""
import json
import sys

# A per-canvas signature computed IN the page: colour count (blank detection)
# plus a sampled-pixel hash (change detection). Works for 2d canvases (raycasters,
# snake, tetris, pong — the overwhelming majority); falls back to a marker for
# WebGL/tainted contexts so the caller can use screenshot diffing instead.
_SIG_JS = r"""
() => {
  const c = document.querySelector('canvas');
  if (!c) return {canvas:false};
  const info = {canvas:true, w:c.width, h:c.height};
  try {
    const g = c.getContext('2d');
    if (g) {
      const d = g.getImageData(0, 0, c.width, c.height).data;
      const colors = new Set();
      let h = 2166136261 >>> 0;
      for (let i = 0; i < d.length; i += 41) {
        colors.add((d[i] << 16) | (d[i+1] << 8) | d[i+2]);
        h = ((h ^ d[i]) * 16777619) >>> 0;
      }
      info.colors = colors.size;
      info.hash = h;
      return info;
    }
  } catch (e) { info.tainted = true; }
  info.colors = null;   // webgl / tainted → use screenshot fallback
  return info;
}
"""

_KEYS = ["ArrowUp", "ArrowRight", "ArrowDown", "ArrowLeft", "w", "a", "s", "d", " "]


def verify(html: str, wait_ms: int = 1500) -> dict:
    from playwright.sync_api import sync_playwright
    out = {"working": False, "renders": False, "animates": False, "responds": False,
           "has_canvas": False, "console_errors": [], "reasons": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(args=[
            "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
            "--disable-software-rasterizer"])
        page = browser.new_page(viewport={"width": 800, "height": 600})
        errs = []
        page.on("console", lambda m: errs.append(m.text[:200]) if m.type == "error" else None)
        page.on("pageerror", lambda e: errs.append(str(e)[:200]))

        import base64
        def screenshot_sig():
            try:
                png = page.screenshot(type="png")
                # size is a cheap blankness proxy; hash detects change
                return {"canvas": True, "colors": None, "hash": hash(png) & 0xffffffff,
                        "png_bytes": len(png)}
            except Exception:
                return {"canvas": False}

        def probe():
            try:
                s = page.evaluate(_SIG_JS)
            except Exception:
                s = {"canvas": False}
            if s.get("canvas") and s.get("colors") is None:
                fb = screenshot_sig()          # webgl/tainted → screenshot fallback
                fb["w"], fb["h"] = s.get("w"), s.get("h")
                return fb
            return s

        try:
            page.set_content(html, wait_until="load", timeout=9000)
        except Exception as exc:
            out["reasons"].append(f"the page failed to load: {str(exc)[:120]}")
            out["console_errors"] = errs[:6]
            browser.close()
            return out

        page.wait_for_timeout(450)             # let init/first frame run
        s1 = probe()
        out["has_canvas"] = bool(s1.get("canvas"))
        if not out["has_canvas"]:
            # DOM/website build: "working" = visible body content + no fatal errors
            text = (page.inner_text("body") or "").strip() if page.query_selector("body") else ""
            has_content = len(text) > 8 or bool(page.query_selector("svg, img, button, input, table"))
            out["renders"] = has_content
            out["animates"] = out["responds"] = has_content   # n/a for static pages
            out["console_errors"] = errs[:6]
            out["working"] = has_content and not errs
            if not has_content:
                out["reasons"].append("no <canvas> and the page has no visible content")
            browser.close()
            return out

        # Blank-canvas check (the #1 failure): a real scene has many colours.
        if s1.get("colors") is not None:
            out["renders"] = s1["colors"] > 2
            if not out["renders"]:
                out["reasons"].append(
                    f"the canvas is BLANK — only {s1['colors']} colour(s) drawn "
                    "(nothing is being painted; check the draw/projection math)")
        else:                                   # screenshot fallback (webgl)
            out["renders"] = s1.get("png_bytes", 0) > 3500
            if not out["renders"]:
                out["reasons"].append("the canvas appears blank (near-empty frame)")

        # Animation check: does it change over ~1s with NO input? (loop alive)
        page.wait_for_timeout(max(200, wait_ms - 450))
        s2 = probe()
        out["animates"] = (s2.get("hash") != s1.get("hash"))

        # Response check: change after arrow/WASD/space input? (controls wired)
        page.evaluate("() => { try{window.focus();}catch(e){} }")
        for k in _KEYS:
            try:
                page.keyboard.down(k); page.wait_for_timeout(40); page.keyboard.up(k)
            except Exception:
                pass
            page.wait_for_timeout(30)
        page.wait_for_timeout(200)
        s3 = probe()
        out["responds"] = (s3.get("hash") != s2.get("hash"))

        if not out["animates"] and not out["responds"]:
            out["reasons"].append(
                "the game is FROZEN — the frame never changed on its own or after "
                "arrow/WASD/space input (no animation loop, or controls aren't wired)")
        elif not out["responds"]:
            out["reasons"].append(
                "controls do nothing — the frame didn't change after arrow/WASD/space "
                "(attach keydown to window and update state on it)")

        out["console_errors"] = errs[:6]
        if errs:
            out["reasons"].append(f"JS error(s): {errs[0][:120]}")

        out["working"] = bool(out["renders"] and (out["animates"] or out["responds"])
                              and not any("SyntaxError" in e or "is not defined" in e
                                          or "is not a function" in e for e in errs))
        browser.close()
    return out


if __name__ == "__main__":
    path = sys.argv[1]
    wait = 1500
    if "--wait" in sys.argv:
        wait = int(sys.argv[sys.argv.index("--wait") + 1])
    html = open(path, encoding="utf-8").read()
    try:
        print(json.dumps(verify(html, wait)))
    except Exception as exc:
        print(json.dumps({"working": False, "error": str(exc)[:200],
                          "reasons": [f"verifier crashed: {str(exc)[:120]}"]}))
