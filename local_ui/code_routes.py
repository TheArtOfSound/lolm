# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Public agentic-coding endpoint — the 70B drives the isolated sandbox in a loop.

POST /api/demo/code/run streams the real write→run→read→fix loop (code_agent) over a
fresh bwrap-jailed sandbox, driven by the frontier model. Public + rate-limited; every
command is isolated (no host FS/net) exactly like the public sandbox. The model only
proposes JSON actions — the loop is the sole thing that touches the sandbox.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# The out-of-process runtime verifier: loads generated HTML in real headless
# Chromium and reports whether it actually renders/animates/responds. Run as a
# subprocess so Playwright never touches the uvicorn event loop.
_VERIFY_SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "visual_verify.py")


def _static_html_lint(html: str) -> Dict[str, Any]:
    """Heuristic verify when Chromium/Playwright is unavailable.

    Never claims ``working=True`` (only a real browser can). When the HTML looks
    like a blank canvas / dead loop, returns ``working=False`` so the build loop
    still retries instead of shipping dead UI. Clear reasons surface in the
    receipt so users know what was checked.
    """
    h = html or ""
    low = h.lower()
    reasons: List[str] = []
    has_canvas = "<canvas" in low
    has_script = "<script" in low
    has_raf = any(x in low for x in (
        "requestanimationframe", "setinterval(", "settimeout(",
    ))
    has_keys = any(x in low for x in (
        "keydown", "keyup", "pointerdown", "touchstart", "mousedown",
    ))
    draw_hints = any(x in low for x in (
        "fillrect", "strokerect", "beginpath", "fillstyle", "strokestyle",
        "getimagedata", "drawimage", "filltext", "arc(", "lineto",
    ))
    if len(h.strip()) < 80:
        reasons.append("static lint: HTML too short to be a real app")
    if has_canvas and not draw_hints:
        reasons.append("static lint: canvas present but no draw calls (likely blank)")
    if has_canvas and not has_raf:
        reasons.append("static lint: no animation/timer loop detected")
    if has_canvas and not has_keys and "game" in low:
        reasons.append("static lint: game-like canvas without input handlers")
    if not has_script and has_canvas:
        reasons.append("static lint: canvas without any <script>")
    # working=False forces rebuild; working=None means "unknown — ship best effort"
    if reasons:
        return {
            "working": False, "renders": bool(has_canvas and draw_hints),
            "animates": has_raf, "responds": has_keys, "console_errors": [],
            "reasons": reasons, "static_lint": True, "unavailable": True,
            "note": "browser verifier unavailable — static lint rejected this build",
        }
    ok_structure = (has_canvas and draw_hints and has_raf) or (has_script and len(h) > 400)
    return {
        "working": None,
        "renders": bool(has_canvas and draw_hints) if has_canvas else ("<body" in low),
        "animates": has_raf,
        "responds": has_keys,
        "console_errors": [],
        "reasons": (["static lint: structure looks ok (browser verify unavailable)"]
                    if ok_structure else
                    ["static lint: browser verifier unavailable — could not confirm interactivity"]),
        "static_lint": True,
        "unavailable": True,
        "note": "shipped without Chromium confirm — install Playwright for hard verify",
    }


def _verify_html(html: str, wait_ms: int = 1400, timeout: int = 55) -> Dict[str, Any]:
    """Run the HTML in a real browser. When Playwright is missing, fall back to
    static lint so blank canvases still trigger auto-retry (never silent ship)."""
    if not os.path.exists(_VERIFY_SCRIPT):
        return _static_html_lint(html)
    path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write(html)
            path = f.name
        r = subprocess.run([sys.executable, _VERIFY_SCRIPT, path, "--wait", str(wait_ms)],
                           capture_output=True, text=True, timeout=timeout)
        line = (r.stdout or "").strip().splitlines()[-1] if (r.stdout or "").strip() else ""
        if not line:
            lint = _static_html_lint(html)
            lint["reasons"] = (lint.get("reasons") or []) + [
                "browser verifier returned no verdict — used static lint"]
            return lint
        verdict = json.loads(line)
        # If browser says blank/broken, keep that; if unavailable-shaped, merge lint.
        if verdict.get("working") is None and verdict.get("unavailable"):
            lint = _static_html_lint(html)
            if lint.get("working") is False:
                return lint
        return verdict
    except Exception as exc:
        lint = _static_html_lint(html)
        lint["reasons"] = (lint.get("reasons") or []) + [
            f"browser verifier error: {str(exc)[:120]}"]
        return lint
    finally:
        if path:
            try:
                os.unlink(path)
            except Exception:
                pass

def _verdict_score(v: Dict[str, Any]) -> int:
    """Rank candidates so we keep the best when none is fully working."""
    if not v:
        return -1
    return (4 * int(bool(v.get("renders"))) + 2 * int(bool(v.get("animates")))
            + 2 * int(bool(v.get("responds"))) - len(v.get("console_errors") or []))


def _verify_all(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Verify several HTML candidates CONCURRENTLY — each _verify_html spawns its
    own Chromium subprocess, so threads just overlap the I/O wait. Each result is
    the candidate annotated with the extracted 'html' and its 'verdict'."""
    if not candidates:
        return []
    from concurrent.futures import ThreadPoolExecutor

    def _one(cand: Dict[str, Any]) -> Dict[str, Any]:
        html = _extract_html(cand.get("text") or "")
        if not html or len(html) < 60:
            return {**cand, "html": html or "", "verdict": {
                "working": False, "renders": False,
                "reasons": [cand.get("error") or "the model returned no usable HTML"]}}
        return {**cand, "html": html, "verdict": _verify_html(html)}

    with ThreadPoolExecutor(max_workers=min(4, len(candidates))) as ex:
        return list(ex.map(_one, candidates))

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from local_ui.code_agent import CodeAgent
from local_ui import code_receipts as code_receipt_ledger
from local_ui.sandbox import Sandbox, _HAS_BWRAP

class CodeTask(BaseModel):
    task: str
    max_steps: int = 18
    # Optional prior chat turns so coding continues the conversation (switch-from-Claude UX)
    history: Optional[List[Dict[str, str]]] = None


class VisualTask(BaseModel):
    task: str


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _seal_visual_receipt(task: str, done: Dict[str, Any]) -> Dict[str, Any]:
    """Hash-chain a visual build into the shared receipt ledger (audit trail)."""
    import hashlib
    v = done.get("verdict") or {}
    core = {
        "kind": "visual_build",
        "task": (task or "")[:400],
        "verified": bool(done.get("verified")),
        "verifier_ran": bool(done.get("verifier_ran")),
        "attempts": done.get("attempts"),
        "mode": done.get("mode"),
        "winner": done.get("winner"),
        "bytes": done.get("bytes"),
        "working": v.get("working"),
        "renders": v.get("renders"),
        "animates": v.get("animates"),
        "responds": v.get("responds"),
        "reasons": (v.get("reasons") or [])[:8],
        "static_lint": bool(v.get("static_lint")),
        "ts": int(time.time()),
        "ok": bool(done.get("verified")),
        "verdict": "verified" if done.get("verified") else (
            "unverified" if done.get("verifier_ran") is False or v.get("working") is None
            else "failed"),
    }
    # Do not store full HTML in the ledger (can be large); store content hash only.
    html = done.get("html") or ""
    core["html_sha"] = hashlib.sha256(html.encode("utf-8")).hexdigest()[:24] if html else ""
    core["receipt_sha"] = hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    try:
        sealed = code_receipt_ledger.append(core, source="api.demo.code.visual.build")
    except Exception:
        sealed = core
    return sealed


def _emit_visual_done(done: Dict[str, Any], task: str):
    """Yield done + visual_receipt events; always attach receipt_sha on done."""
    sealed = _seal_visual_receipt(task, done)
    payload = dict(done)
    payload["receipt_sha"] = sealed.get("receipt_sha") or sealed.get("ledger_sha")
    payload["ledger_sha"] = sealed.get("ledger_sha")
    yield _sse("done", payload)
    yield _sse("visual_receipt", sealed)


def _extract_html(raw: str) -> Optional[str]:
    """Pull a complete HTML document out of the model's reply (tolerates fences/prose)."""
    if not raw:
        return None
    t = raw.strip()
    if "```" in t:
        import re
        m = re.search(r"```(?:html)?\s*(.*?)```", t, re.DOTALL | re.IGNORECASE)
        if m and ("<" in m.group(1)):
            t = m.group(1).strip()
    low = t.lower()
    start = low.find("<!doctype")
    if start < 0:
        start = low.find("<html")
    if start < 0:
        # bare fragment (just <canvas>/<script>…) → wrap into a minimal dark document
        if "<" in t and ("<script" in low or "<canvas" in low or "<div" in low or "<svg" in low):
            return ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                    "<style>html,body{margin:0;height:100%;background:#0a0c10;color:#e2e8f0;"
                    "font-family:system-ui}</style></head><body>" + t + "</body></html>")
        return None
    end = low.rfind("</html>")
    return t[start:end + 7] if end > start else t[start:]


# Per-type implementation recipes — a proven spec for the common asks so the one-shot
# build comes out right instead of a vague approximation.
_VISUAL_RECIPES = [
    (re.compile(r"\bsnake\b", re.I),
     "SNAKE: ~22x22 cell grid; snake = array of {x,y} segments; food at a random empty cell; arrow/WASD set "
     "direction (ignore a direct 180° reversal); advance on a ~110ms timer (unshift new head, pop tail unless it "
     "ate food → grow + new food + score++); game-over on wall or self collision, show score + 'press R to "
     "restart'. Rounded cells with a 1px gap; head a brighter shade. CRITICAL: test self-collision and "
     "food-on-snake by COORDINATES — snake.some(s => s.x===head.x && s.y===head.y) — never snake.includes(head) "
     "(object identity is always false, so the snake would pass through itself and food spawn on it)."),
    (re.compile(r"\b(raycast|fps|first[- ]?person|wolfenstein|doom)\b", re.I),
     "RAYCASTER (true first-person 3D): a 2D integer wall map (1=wall,0=empty); player {x,y,angle}. Each frame: "
     "clear, fill ceiling (top half, dark blue-grey) and floor (bottom half, dark grey); then for every screen "
     "column x: compute the ray angle across a ~66° FOV, DDA-step through the grid to the first wall, take the "
     "PERPENDICULAR distance (multiply by cos(rayAngle−playerAngle) to remove fisheye), wallHeight = "
     "screenH/dist, draw a vertical wall strip centered vertically, shaded by distance and darker on N/S faces — "
     "use a BRIGHT base wall color so it's clearly visible. WASD moves with wall collision, ←/→ rotate. Start the "
     "player in an open cell."),
    (re.compile(r"\bpong\b", re.I),
     "PONG: left paddle = player (mouse or W/S), right paddle = AI tracking the ball; ball with vx,vy bounces off "
     "top/bottom and paddles (add spin from paddle motion + hit position); score when it passes a paddle, reset "
     "to center; dashed center line + big scores."),
    (re.compile(r"\b(breakout|brick.?breaker|arkanoid)\b", re.I),
     "BREAKOUT: a grid of colored bricks; paddle (mouse/arrows); ball bounces off walls/paddle/bricks (remove "
     "brick + score on hit, reflect angle by where it hits the paddle); lose when the ball drops below the "
     "paddle; win when bricks are cleared; restart key."),
    (re.compile(r"\btetris\b", re.I),
     "TETRIS: a 10x20 grid; the 7 tetrominoes with rotation states; the current piece falls on a timer; arrows "
     "move/rotate (with collision + simple wall-kick), down = soft drop, space = hard drop; lock into the grid "
     "when it can't fall, clear full rows + score, spawn the next piece, game-over if a spawn collides."),
    (re.compile(r"\bflappy\b", re.I),
     "FLAPPY: a bird with gravity; click/space sets an upward velocity; scrolling pipe pairs with a gap; score on "
     "passing a pipe; game-over on pipe/ground collision + restart."),
    (re.compile(r"\b(platformer|jump.?and.?run)\b", re.I),
     "PLATFORMER: player with gravity + horizontal velocity; left/right move, up/space jump only when grounded; "
     "AABB collision against an array of platform rects (resolve vertical then horizontal); a camera that "
     "follows; collectibles + score."),
    (re.compile(r"\basteroids\b", re.I),
     "ASTEROIDS: a ship that rotates (←/→) and thrusts (↑) with momentum + screen wrap; space fires bullets; "
     "asteroids drift and split into smaller ones when shot; score + lives."),
    (re.compile(r"\b(space ?invaders|invaders)\b", re.I),
     "SPACE INVADERS: a grid of aliens stepping side-to-side and dropping at the edges; a player cannon (arrows) "
     "firing upward; bullets remove aliens + score; aliens occasionally fire back; win on clear, lose if they "
     "reach the bottom."),
    (re.compile(r"\b(plasma|shader|fragment shader|glsl)\b", re.I),
     "PLASMA/SHADER (2D canvas, per-pixel): build an ImageData of a modest buffer (e.g. 220x220) scaled by CSS to "
     "fill the screen; each frame, for every pixel compute v = sin(x*0.04+t) + sin(y*0.04+t) + "
     "sin((x+y)*0.04+t) + sin(hypot(x-cx,y-cy)*0.04+t), map v to a vivid HSL color, write RGBA, then putImageData. "
     "Animate t. Smooth and colorful — not a flat fill."),
    (re.compile(r"\b(mandelbrot|julia|fractal)\b", re.I),
     "FRACTAL (per-pixel ImageData): map each pixel to a complex c in the view rectangle; iterate z = z² + c up to "
     "~120 iterations until |z|>2; color by (smoothed) iteration count with a vivid palette; never-escaping "
     "points are black. Optionally animate a slow zoom toward a detailed point."),
    (re.compile(r"\b(particles?|fireworks|starfield|confetti|boids|flocking)\b", re.I),
     "PARTICLES: an array of particles with position + velocity (+ life for fireworks/confetti); update and draw "
     "each on a slightly-faded canvas (semi-transparent black overlay for trails); spawn continuously or on "
     "click; bright additive colors. Starfield = stars with a z depth moving toward the camera, perspective-"
     "projected, wrapping when they pass. Boids = steer by separation + alignment + cohesion."),
    (re.compile(r"\b(game of life|cellular automat)\b", re.I),
     "GAME OF LIFE: a cell grid; each tick apply Conway's rules (a live cell with 2–3 live neighbors survives; a "
     "dead cell with exactly 3 becomes live); draw live cells; click to toggle, space to play/pause, R to reseed "
     "randomly."),
    (re.compile(r"\b(rotating cube|3d cube|wireframe|spinning cube|rubik)\b", re.I),
     "3D CUBE: 8 cube vertices; each frame rotate them on x/y/z (sin/cos), apply a simple perspective projection "
     "(sx = x*f/(z+d)), draw the 12 edges; smooth continuous rotation; optionally depth-shade."),
    (re.compile(r"\bclock\b", re.I),
     "CLOCK: a canvas analog clock — face + hour ticks + hour/minute/second hands from new Date(), redrawn every "
     "frame; clean, centered, scales to the canvas."),
    (re.compile(r"\b(landing page|web ?site|web ?page|portfolio|dashboard)\b", re.I),
     "WEBPAGE: a polished single page — a hero (headline + subtext + a CTA button), a few feature cards, a footer; "
     "modern CSS (system font, a tasteful gradient/accent, rounded cards, hover states, responsive flex/grid). "
     "Make it look designed and complete, never a blank page."),
]


def _visual_recipe(task: str) -> str:
    for rx, rec in _VISUAL_RECIPES:
        if rx.search(task or ""):
            return rec
    return ""


def register_code_routes(app: Any, root: str,
                         chat_fn: Optional[Callable[[List[Dict[str, str]]], str]],
                         runs_per_min: int = 6,
                         stream_fn: Optional[Callable[..., Any]] = None,
                         gen_many_fn: Optional[Callable[..., List[Dict[str, Any]]]] = None,
                         usage_fn: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
    rate: Dict[str, List[float]] = {}

    def _ip(req: Request) -> str:
        fwd = req.headers.get("x-forwarded-for", "")
        return (fwd.split(",")[0].strip() if fwd else (req.client.host if req.client else "?"))

    def _quota_deny(request: Request, kind: str):
        """Usage-tier gate: None when allowed, else the 402 response."""
        if usage_fn is None:
            return None
        q = usage_fn(request, kind)
        if q.get("allowed"):
            return None
        return JSONResponse({"error": q.get("error", "daily limit reached"),
                             "upgrade": True, "tier": q.get("tier"), "used": q.get("used"),
                             "limit": q.get("limit"), "tiers": q.get("tiers")}, status_code=402)

    @app.get("/api/demo/code/health")
    def code_health():
        return {"enabled": bool(_HAS_BWRAP and chat_fn is not None),
                "isolated": True, "runs_per_min": runs_per_min,
                "note": "the 70B writes code, runs it in a bwrap jail, reads the failure, "
                        "and fixes it — every command isolated (no host FS/network)",
                "receipts": code_receipt_ledger.stats()}

    @app.get("/api/demo/code/receipts")
    def code_receipts_tail(limit: int = 20, kind: str = ""):
        """Public audit window: recent sealed code/visual receipts (hash-chained)."""
        lim = max(1, min(int(limit or 20), 50))
        # Empty-ledger UX: seed labeled demos so /receipts.html shows the format.
        # Also seal one real selftest receipt (live sandbox run) when missing.
        try:
            code_receipt_ledger.ensure_demo_seed()
        except Exception:
            pass
        try:
            code_receipt_ledger.ensure_selftest_receipt()
        except Exception:
            pass
        rows = code_receipt_ledger.tail(max(lim, 50))
        want = (kind or "").strip().lower()
        # Strip bulky stdout tails for the list view; full sha remains.
        slim = []
        for r in rows:
            rkind = (r.get("kind") or (
                "visual_build" if "visual" in str(r.get("source") or "") else "code_agent"
            ))
            if want in ("code", "code_agent") and "visual" in str(rkind):
                continue
            if want in ("visual", "visual_build") and "visual" not in str(rkind):
                continue
            slim.append({
                "ledger_sha": r.get("ledger_sha"),
                "prev_ledger_sha": r.get("prev_ledger_sha"),
                "receipt_sha": r.get("receipt_sha"),
                "kind": rkind,
                "task": (r.get("task") or "")[:160],
                "verdict": r.get("verdict"),
                "ok": r.get("ok"),
                "files": r.get("files") or [],
                "green_runs": r.get("green_runs"),
                "failed_runs": r.get("failed_runs"),
                "verifies": r.get("verifies"),
                "attempts": r.get("attempts"),
                "html_sha": r.get("html_sha"),
                "ts": r.get("ledger_ts") or r.get("ts"),
                "source": r.get("source"),
                "demo": bool(r.get("demo")),
                "selftest": bool(r.get("selftest")),
            })
        slim = slim[-lim:]
        return {"receipts": slim, "stats": code_receipt_ledger.stats()}

    @app.post("/api/demo/code/run")
    def code_run(req: CodeTask, request: Request):
        if not (_HAS_BWRAP and chat_fn is not None):
            return JSONResponse({"error": "agentic code execution unavailable on this host"},
                                status_code=503)
        ip = _ip(request)
        now = time.time()
        rate[ip] = [t for t in rate.get(ip, []) if now - t < 60]
        if len(rate[ip]) >= runs_per_min:
            return JSONResponse({"error": f"rate limit {runs_per_min} code runs/min"},
                                status_code=429)
        rate[ip].append(now)
        deny = _quota_deny(request, "runs")
        if deny is not None:
            return deny
        task = (req.task or "").strip()[:2000]
        if not task:
            return JSONResponse({"error": "empty task"}, status_code=400)

        # Ledger lives next to sandboxes under the code root's parent runs/ if possible.
        try:
            code_receipt_ledger.init(Path(root).resolve().parent / "code_receipts"
                                     if Path(root).name == "pub_sandboxes"
                                     else Path(root).resolve().parent)
        except Exception:
            code_receipt_ledger.init()

        sb = Sandbox(root)
        # Wrap chat_fn to inject conversation history for multi-turn coding sessions
        hist = getattr(req, "history", None) or []
        hist_lines = []
        if isinstance(hist, list):
            for t in hist[-8:]:
                if not isinstance(t, dict):
                    continue
                role = "user" if t.get("role") == "user" else "assistant"
                content = str(t.get("content") or "").strip()
                if content:
                    hist_lines.append(f"{role}: {content[:500]}")
        base_chat = chat_fn

        def _chat_with_history(msgs: List[Dict[str, str]]) -> str:
            out: List[Dict[str, str]] = []
            for x in msgs:
                content = str(x.get("content") or "")
                if (
                    hist_lines
                    and x.get("role") == "user"
                    and content.startswith("TASK:")
                    and "CONVERSATION SO FAR" not in content
                ):
                    content = (
                        "CONVERSATION SO FAR (coding session):\n"
                        + "\n".join(hist_lines)
                        + "\n\n"
                        + content
                    )
                out.append({"role": x.get("role", "user"), "content": content})
            try:
                return base_chat(out, max_new_tokens=2400)  # type: ignore[call-arg]
            except TypeError:
                return base_chat(out)

        # Simple print/hello tasks don't need 18 steps — finish faster for switchers.
        tlow = task.lower()
        simple = (
            len(task) < 120
            and any(k in tlow for k in ("print ", "hello", "fizz", "prime", "factorial", "fib"))
            and "game" not in tlow and "server" not in tlow
        )
        step_cap = 10 if simple else 22
        agent = CodeAgent(sb, _chat_with_history,
                          max_steps=min(max(req.max_steps, 1), step_cap), isolated=True)

        def gen():
            try:
                yield _sse("agent_note", {"text": "LOLM Code — multi-file agentic loop (run → fix → verify)"})
                for ev in agent.run(task):
                    if ev.get("event") == "code_receipt":
                        try:
                            sealed = code_receipt_ledger.append(ev.get("data") or {},
                                                                source="api.demo.code.run")
                            # stream the ledger-chained row (still includes trail)
                            yield _sse("code_receipt", sealed)
                            continue
                        except Exception as lexc:
                            # never fail the user stream on ledger IO
                            note = {"text": f"receipt ledger write skipped: {lexc}"[:160]}
                            yield _sse("agent_note", note)
                    yield _sse(ev["event"], ev["data"])
            except Exception as exc:
                yield _sse("error", {"error": str(exc)[:200]})
            finally:
                try:
                    sb.destroy()
                except Exception:
                    pass

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    _VISUAL_SYSTEM = (
            "You build ONE complete, self-contained HTML document that implements the "
            "user's visual or interactive task. Output ONLY the HTML — start with "
            "<!DOCTYPE html> and nothing before it, no prose, no markdown fences.\n"
            "RULES:\n"
            "- Inline ALL CSS in <style> and ALL JavaScript in <script>. One file.\n"
            "- NO external resources: no CDNs, no <script src=URL>, no <img src=URL>, no "
            "fetch/XHR, no imports, no web fonts. They are BLOCKED by the sandbox.\n"
            "- Use <canvas> or DOM + vanilla JS. Make it ACTUALLY WORK and be playable: "
            "wire keyboard/mouse handlers, a requestAnimationFrame (or timer) loop, score, "
            "and a short on-screen controls hint.\n"
            "- START ALREADY RUNNING and in a PLAYABLE state. NEVER show 'Game Over', a "
            "blank screen, or a paused/start menu on load — the game must be live and "
            "moving the instant it loads (the player presses keys to play, not to start). "
            "Initialize gameOver=false and put the player/snake/ship safely mid-field with "
            "room ahead.\n"
            "- Attach keydown/keyup listeners to `window` (window.addEventListener('keydown',…)) "
            "and call window.focus() on load so keys register immediately. preventDefault on "
            "arrow keys/space so the page doesn't scroll.\n"
            "- Key checks MUST be case-insensitive: use e.key.toLowerCase()==='r' (NOT "
            "e.key==='R'), and accept BOTH arrow keys and WASD for movement. The restart key "
            "must actually reset ALL state (score, position, gameOver=false) and resume the "
            "loop.\n"
            "- TOUCH CONTROLS (phones have NO keyboard — the game must be fully playable by "
            "touch too): add touchstart/touchmove listeners on the canvas with "
            "e.preventDefault() (and CSS touch-action:none on the canvas). Directional games "
            "(snake, tetris moves) = SWIPE detection (compare touchstart→touchend deltas, "
            "pick the dominant axis). Paddle games (pong, breakout) = drag: paddle follows "
            "touchmove X/Y. Tap = the primary action (flap, shoot, rotate, toggle). Update "
            "the on-screen controls hint to mention both (e.g. 'arrows/WASD or swipe').\n"
            "- Be FORGIVING at the start: place the player/snake centered with lots of empty "
            "space ahead, use a calm initial speed, and don't end the game in the first second. "
            "It should be fun to play, not instantly lose.\n"
            "- RENDER WHAT THE USER ACTUALLY ASKED FOR, completely — not a simplified "
            "placeholder or a schematic. For a first-person / FPS / raycaster, draw the "
            "3D VIEW the player sees: cast a ray per screen column and draw each wall as a "
            "vertical strip whose height is inversely proportional to its distance (fisheye-"
            "corrected) — NOT a 2D top-down map. For 3D, project points to 2D yourself. For "
            "a shader/plasma effect, write per-pixel ImageData. Implement the real math.\n"
            "- FIT THE VISIBLE AREA WITHOUT SCROLLING. The whole app must be visible at "
            "once. Center everything with flexbox (body{margin:0;height:100vh;display:flex;"
            "flex-direction:column;align-items:center;justify-content:center;overflow:hidden}). "
            "Size a game canvas to a fixed square that fits, e.g. const S=Math.min("
            "window.innerWidth,window.innerHeight)-20; canvas.width=canvas.height=S — NEVER "
            "set the canvas taller than the viewport (don't use window.innerHeight for height "
            "while innerWidth for width, or content scrolls off-screen). Dark, clean styling.\n"
            "- CORRECTNESS — these bugs RUN but play WRONG; do not make them:\n"
            "  • Comparing objects/cells: arrays of {x,y} (snake segments, grid cells, pieces) DON'T match "
            "with .includes(obj) / .indexOf(obj) / === — those test object IDENTITY, never value, so they "
            "are ALWAYS false. To ask 'is this cell occupied?' use arr.some(p => p.x===cell.x && p.y===cell.y). "
            "Snake self-collision AND food-not-on-snake MUST use this coordinate check (or the snake passes "
            "through itself and food spawns under it).\n"
            "  • Spawn pickups/food on a VERIFIED-empty cell: re-roll while it coincides with the body/walls "
            "using that same coordinate check.\n"
            "  • Update game state THEN test collisions THEN draw, so what's on screen matches the logic.\n"
            "  • Keep every index/coordinate in range and every entity inside the play area.\n"
            "Make it fun, correct, and complete — actually play a few moves in your head and confirm the "
            "win/lose/score/collision rules truly fire."
    )

    def _visual_messages(task: str) -> List[Dict[str, str]]:
        """The one visual-builder prompt, shared by every visual route."""
        recipe = _visual_recipe(task)
        guide = (f"\n\nIMPLEMENTATION GUIDE — follow this approach:\n{recipe}\n" if recipe else "")
        return [{"role": "system", "content": _VISUAL_SYSTEM},
                {"role": "user", "content": f"TASK: {task}{guide}\n\nReturn the full, complete HTML document now."}]

    def _visual_fix_messages(task: str, prev_html: str, reasons: List[str]) -> List[Dict[str, str]]:
        """Regeneration prompt after a REAL browser found the build broken — the
        exact failures are handed back so the model fixes those, not guesses."""
        problems = "\n".join(f"  - {r}" for r in reasons[:6]) or "  - it did not work when run"
        user = (
            f"TASK: {task}\n\n"
            "Your previous HTML was RUN in a real browser and it DID NOT WORK. A verifier "
            "found these exact problems:\n" + problems + "\n\n"
            "Rewrite the WHOLE document to fix them. Most common causes: the draw loop never "
            "runs (add requestAnimationFrame and actually call it), the projection/draw math "
            "paints nothing (a raycaster MUST compute per-column wall distance and draw a "
            "vertical slice scaled by 1/distance), or keydown isn't wired to state. Make sure "
            "something is VISIBLY drawn every frame and the frame changes on movement.\n\n"
            "PREVIOUS (BROKEN) HTML:\n" + prev_html[:9000] + "\n\n"
            "Return the full corrected HTML document now, starting with <!DOCTYPE html>.")
        return [{"role": "system", "content": _VISUAL_SYSTEM},
                {"role": "user", "content": user}]

    @app.post("/api/demo/code/visual/stream")
    def code_visual_stream(req: VisualTask, request: Request):
        """STREAMING visual builder — same prompt/recipes as the blocking route, but
        the code is streamed token-by-token as SSE while it's being written, and the
        finished document is emitted the instant the stream ends:
          start → chunk{text}* → html{html,bytes} → done   (error{...} on failure)
        The blocking POST /api/demo/code/visual stays as the fallback."""
        if stream_fn is None or chat_fn is None:
            return JSONResponse({"error": "streaming builder unavailable — use /api/demo/code/visual"},
                                status_code=503)
        ip = _ip(request)
        now = time.time()
        rate[ip] = [t for t in rate.get(ip, []) if now - t < 60]
        if len(rate[ip]) >= runs_per_min:
            return JSONResponse({"error": f"rate limit {runs_per_min} builds/min"}, status_code=429)
        rate[ip].append(now)
        deny = _quota_deny(request, "visual")
        if deny is not None:
            return deny
        task = (req.task or "").strip()[:2000]
        if not task:
            return JSONResponse({"error": "empty task"}, status_code=400)
        msgs = _visual_messages(task)

        def gen():
            yield _sse("start", {"task": task[:140]})
            full, buf = [], []
            buf_len = 0
            try:
                for piece in stream_fn(msgs, 3600):
                    full.append(piece)
                    buf.append(piece)
                    buf_len += len(piece)
                    if buf_len >= 160:            # coalesce tiny deltas; keep event volume sane
                        yield _sse("chunk", {"text": "".join(buf)})
                        buf, buf_len = [], 0
                if buf:
                    yield _sse("chunk", {"text": "".join(buf)})
            except Exception as exc:
                yield _sse("error", {"error": f"stream failed: {exc}"[:200]})
                return
            raw = "".join(full)
            html = _extract_html(raw)
            if not html or len(html) < 60:
                yield _sse("error", {"error": "the model did not return a usable HTML app — try rephrasing"})
                return
            yield _sse("html", {"html": html, "bytes": len(html)})
            yield _sse("done", {})

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/demo/code/visual")
    def code_visual(req: VisualTask, request: Request):
        """Build a COMPLETE self-contained HTML app for a visual/interactive task.

        The browser is the safe visual runtime: the returned HTML runs in a
        sandboxed iframe (allow-scripts only — no network, no parent access), so a
        game/animation/UI is actually playable, not just printed as text.
        """
        if chat_fn is None:
            return JSONResponse({"error": "visual builder unavailable on this host"},
                                status_code=503)
        ip = _ip(request)
        now = time.time()
        rate[ip] = [t for t in rate.get(ip, []) if now - t < 60]
        if len(rate[ip]) >= runs_per_min:
            return JSONResponse({"error": f"rate limit {runs_per_min} builds/min"},
                                status_code=429)
        rate[ip].append(now)
        deny = _quota_deny(request, "visual")
        if deny is not None:
            return deny
        task = (req.task or "").strip()[:2000]
        if not task:
            return JSONResponse({"error": "empty task"}, status_code=400)

        msgs = _visual_messages(task)
        try:
            raw = chat_fn(msgs, max_new_tokens=3600)
        except TypeError:
            raw = chat_fn(msgs)          # chat_fn without a token arg (tests)
        except Exception as exc:
            return JSONResponse({"error": f"generation failed: {exc}"[:200]}, status_code=502)
        html = _extract_html(raw)
        if not html or len(html) < 60:
            return JSONResponse({"error": "the model did not return a usable HTML app — try rephrasing"},
                                status_code=502)
        return {"html": html, "bytes": len(html)}

    def _gen_html(msgs: List[Dict[str, str]]) -> Optional[str]:
        try:
            raw = chat_fn(msgs, max_new_tokens=3600)
        except TypeError:
            raw = chat_fn(msgs)
        return _extract_html(raw)

    @app.post("/api/demo/code/visual/build")
    def code_visual_build(req: VisualTask, request: Request):
        """AUTONOMOUS visual builder — the one that actually WORKS. It generates the
        app, RUNS it in real headless Chromium, and if it's broken (blank canvas,
        dead loop, unwired controls) it feeds the exact failure back to the model and
        rebuilds — up to a few times — until the browser confirms it renders,
        animates, and responds. Streams honest progress the whole way:
          attempt{n,of} → verifying{n} → verdict{n,working,renders,animates,responds,reasons}
          → (loop) → done{html,bytes,verified,attempts,verdict}
        Never claims success it hasn't seen; if it can't reach a working build it
        returns the best attempt and says so.
        """
        if chat_fn is None:
            return JSONResponse({"error": "visual builder unavailable on this host"}, status_code=503)
        ip = _ip(request)
        now = time.time()
        rate[ip] = [t for t in rate.get(ip, []) if now - t < 60]
        if len(rate[ip]) >= runs_per_min:
            return JSONResponse({"error": f"rate limit {runs_per_min} builds/min"}, status_code=429)
        rate[ip].append(now)
        deny = _quota_deny(request, "visual")
        if deny is not None:
            return deny
        task = (req.task or "").strip()[:2000]
        if not task:
            return JSONResponse({"error": "empty task"}, status_code=400)
        max_tries = 4

        # Three independent frontier brains for the ensemble race (two keys).
        ROUND1 = ["zai-glm-4.7", "openai/gpt-oss-120b", "meta-llama/llama-4-scout-17b-16e-instruct"]

        def gen():
            best_html: Optional[str] = None
            best_verdict: Dict[str, Any] = {}
            best_model: Optional[str] = None
            attempts = 0
            # Fan out to N brains only for a HARD build (a known recipe) — easy asks
            # (a clock, a landing page) don't need 3x the cost; they take the single path.
            ensemble = bool(gen_many_fn) and bool(_visual_recipe(task))

            def consider(html, verdict, model):
                nonlocal best_html, best_verdict, best_model
                if best_html is None or _verdict_score(verdict) > _verdict_score(best_verdict):
                    best_html, best_verdict, best_model = html, verdict, model

            # ── ROUND 1 (ensemble): race 3 independent brains, verify EACH in a real
            #    browser, keep the one the browser confirms works ("brains in unison"). ──
            if ensemble:
                attempts = 1
                yield _sse("attempt", {"n": 1, "of": 3, "mode": "ensemble", "models": ROUND1})
                try:
                    cands = gen_many_fn(_visual_messages(task), ROUND1) or []
                except Exception:
                    cands = []
                if cands:
                    yield _sse("verifying", {"n": 1, "count": len(cands)})
                    for cnd in _verify_all(cands):
                        v = cnd["verdict"]
                        consider(cnd["html"], v, cnd.get("model"))
                        yield _sse("candidate", {"model": cnd.get("model"), "provider": cnd.get("provider"),
                                   "working": v.get("working"), "renders": v.get("renders"),
                                   "animates": v.get("animates"), "responds": v.get("responds"),
                                   "bytes": len(cnd.get("html") or ""), "reasons": v.get("reasons", [])})
                    if best_verdict.get("working") or best_verdict.get("working") is None:
                        done_payload = {
                            "html": best_html or "", "bytes": len(best_html or ""),
                            "verified": bool(best_verdict.get("working")),
                            "verifier_ran": best_verdict.get("working") is not None,
                            "attempts": attempts, "winner": best_model, "mode": "ensemble",
                            "verdict": best_verdict,
                        }
                        yield from _emit_visual_done(done_payload, task)
                        return
                else:
                    ensemble = False           # fan-out unavailable → single-model path

            # ── SINGLE-MODEL loop: fresh if nothing yet, else FIX the best so far. ──
            msgs = (_visual_messages(task) if best_html is None
                    else _visual_fix_messages(task, best_html, best_verdict.get("reasons", [])))
            cap = 2 if best_html is not None else max_tries      # ensemble already spent a round
            for _ in range(cap):
                attempts += 1
                yield _sse("attempt", {"n": attempts, "of": max_tries,
                                       "mode": "fix" if best_html is not None else "single"})
                try:
                    html = _gen_html(msgs)
                except Exception as exc:
                    yield _sse("error", {"error": f"generation failed: {exc}"[:160]})
                    if best_html is None:
                        return
                    break
                if not html or len(html) < 60:
                    yield _sse("attempt_note", {"n": attempts, "note": "no usable HTML — retrying"})
                    continue
                yield _sse("verifying", {"n": attempts})
                v = _verify_html(html)
                yield _sse("verdict", {"n": attempts, "working": v.get("working"),
                                       "renders": v.get("renders"), "animates": v.get("animates"),
                                       "responds": v.get("responds"), "reasons": v.get("reasons", [])})
                consider(html, v, best_model or "cloud")
                if v.get("working") or v.get("working") is None:
                    break
                msgs = _visual_fix_messages(task, html, v.get("reasons", []))
            done_payload = {
                "html": best_html or "", "bytes": len(best_html or ""),
                "verified": bool(best_verdict.get("working")),
                "verifier_ran": best_verdict.get("working") is not None,
                "attempts": attempts, "winner": best_model,
                "mode": "ensemble" if ensemble else "single", "verdict": best_verdict,
            }
            yield from _emit_visual_done(done_payload, task)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
