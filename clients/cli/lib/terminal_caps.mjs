// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** What this terminal and this reader can actually handle.
 *
 * Every presentation decision in the CLI reads from here rather than checking
 * `isTTY` at the call site, so one detection is responsible for whether output
 * animates, repaints, uses colour, or uses characters outside ASCII.
 */
import { stdout as output, stdin as input } from "node:process";

const OFF = /^(0|false|off|no)$/i;
const ON = /^(1|true|on|yes)$/i;

function flag(name) {
  const value = process.env[name];
  if (value === undefined || value === "") return null;
  if (OFF.test(value)) return false;
  if (ON.test(value)) return true;
  return true;
}

/** A reader on a screen reader wants linear text, not a repainting canvas. */
function wantsPlain() {
  // Capabilities are settled at import time, before argv is parsed, so the flag
  // is read straight from the command line to avoid a one-command lag.
  if (process.argv.includes("--plain")) return true;
  for (const name of ["LOLM_PLAIN", "LOLM_SCREEN_READER", "ACCESSIBLE", "A11Y"]) {
    const value = flag(name);
    if (value !== null) return value;
  }
  // Terminals that announce themselves as non-visual, and the classic
  // "dumb" terminal, get the linear treatment without being asked.
  if (process.env.TERM === "dumb") return true;
  return false;
}

function supportsUnicode() {
  const forced = flag("LOLM_ASCII");
  if (forced === true) return false;
  if (forced === false) return true;
  const locale = process.env.LC_ALL || process.env.LC_CTYPE || process.env.LANG || "";
  // An explicitly non-UTF-8 locale is a reliable "this will render as noise".
  if (locale && !/utf-?8/i.test(locale)) return false;
  if (process.platform === "win32") {
    return Boolean(process.env.WT_SESSION || process.env.TERM_PROGRAM || /^UTF-?8$/i.test(process.env.LOLM_CODEPAGE || ""));
  }
  return true;
}

function supportsColor(plain) {
  const forced = flag("FORCE_COLOR");
  if (forced !== null) return forced;
  if (process.env.NO_COLOR !== undefined && process.env.NO_COLOR !== "") return false;
  if (process.env.TERM === "dumb") return false;
  // Colour on a screen reader is at best ignored and at worst spoken.
  if (plain) return false;
  return Boolean(output.isTTY);
}

export function detectCapabilities(env = process.env) {
  const plain = wantsPlain();
  const tty = Boolean(output.isTTY);
  const color = supportsColor(plain);
  const unicode = supportsUnicode();
  const motionFlag = flag("LOLM_NO_MOTION");
  // Animation is only ever a nicety. Anything that reads the screen aloud, or
  // records it, is better served by a line that appears once and stays put.
  const motion = motionFlag === true ? false : plain || !tty ? false : motionFlag === false ? true : true;
  const altScreen = tty && !plain && flag("LOLM_NO_ALT_SCREEN") !== true;
  return {
    plain,
    tty,
    color,
    unicode,
    motion,
    altScreen,
    interactive: Boolean(input.isTTY && tty),
    width: Math.max(40, Math.min(120, output.columns || (plain ? 80 : 80))),
    term: env.TERM || "",
    program: env.TERM_PROGRAM || "",
    multiplexer: env.TMUX ? "tmux" : /screen/.test(env.TERM || "") ? "screen" : "",
  };
}

/** Why each capability resolved the way it did, for `lolm doctor`. */
export function explainCapabilities(caps) {
  return [
    ["Output mode", caps.plain ? "plain (screen-reader friendly)" : "rich", caps.plain
      ? "Linear append-only text: no alternate screen, no repainting, no animation."
      : "Set LOLM_PLAIN=1 for linear, screen-reader friendly output."],
    ["Colour", caps.color ? "on" : "off", caps.color
      ? "NO_COLOR=1 turns it off; meaning is never carried by colour alone."
      : "FORCE_COLOR=1 turns it on."],
    ["Motion", caps.motion ? "animated" : "static", caps.motion
      ? "LOLM_NO_MOTION=1 replaces spinners with periodic static lines."
      : "Progress is reported as occasional static lines."],
    ["Characters", caps.unicode ? "Unicode" : "ASCII only", caps.unicode
      ? "LOLM_ASCII=1 restricts output to ASCII."
      : "Locale is not UTF-8, so box-drawing and symbols are replaced."],
    ["Alternate screen", caps.altScreen ? "in use" : "not used", caps.altScreen
      ? "LOLM_NO_ALT_SCREEN=1 keeps output in the normal scrollback."
      : "Output stays in your scrollback and can be selected and copied."],
    ["Width", `${caps.width} columns`, "Text is wrapped to fit rather than relying on terminal soft-wrap."],
  ];
}
