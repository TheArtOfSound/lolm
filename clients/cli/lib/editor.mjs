// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** A multi-line input buffer with the editing keys people expect.
 *
 * readline cannot do this: it owns one line, and the console needs an input box
 * that grows, wraps, and keeps a cursor the frame compositor can position. The
 * buffer is a plain string with a cursor index; everything else is derived, so
 * there is no second source of truth to keep in sync.
 */

const WORD = /[\p{L}\p{N}_]/u;

export function createEditor({ history = [] } = {}) {
  let text = "";
  let cursor = 0;
  let historyIndex = history.length;
  let draft = "";

  const lineStart = (index) => text.lastIndexOf("\n", Math.max(0, index - 1)) + 1;
  const lineEnd = (index) => {
    const next = text.indexOf("\n", index);
    return next === -1 ? text.length : next;
  };

  function wordLeft() {
    let index = cursor;
    while (index > 0 && !WORD.test(text[index - 1])) index -= 1;
    while (index > 0 && WORD.test(text[index - 1])) index -= 1;
    return index;
  }
  function wordRight() {
    let index = cursor;
    while (index < text.length && !WORD.test(text[index])) index += 1;
    while (index < text.length && WORD.test(text[index])) index += 1;
    return index;
  }
  function insert(value) {
    text = text.slice(0, cursor) + value + text.slice(cursor);
    cursor += value.length;
  }
  function remove(from, to) {
    const start = Math.max(0, Math.min(from, to));
    const end = Math.min(text.length, Math.max(from, to));
    text = text.slice(0, start) + text.slice(end);
    cursor = start;
  }
  function recall(direction) {
    if (!history.length) return false;
    if (historyIndex === history.length) draft = text;
    const next = historyIndex + direction;
    if (next < 0 || next > history.length) return false;
    historyIndex = next;
    text = next === history.length ? draft : history[next];
    cursor = text.length;
    return true;
  }

  return {
    get value() { return text; },
    get cursor() { return cursor; },
    reset() { text = ""; cursor = 0; historyIndex = history.length; draft = ""; },
    remember(value) {
      const entry = String(value || "").trim();
      if (entry && history[history.length - 1] !== entry) history.push(entry);
      historyIndex = history.length;
    },
    /**
     * Apply one keypress.
     * @returns "submit" | "cancel" | "quit" | "redraw" | "scroll-up" | "scroll-down" | null
     */
    key(sequence, info = {}) {
      const { name, ctrl, meta, shift } = info;
      if (ctrl && name === "c") return text ? (this.reset(), "redraw") : "cancel";
      if (ctrl && name === "d") return text ? null : "quit";
      if (ctrl && name === "l") return "redraw";
      if (name === "pageup") return "scroll-up";
      if (name === "pagedown") return "scroll-down";

      // Enter submits; a modified Enter inserts a newline, matching the habit
      // every chat interface has trained. Terminals that cannot distinguish
      // them still get an explicit escape hatch through Alt+Enter.
      if (name === "return" || name === "enter") {
        if (meta || shift) { insert("\n"); return "redraw"; }
        return "submit";
      }

      if (name === "backspace") {
        if (ctrl || meta) { remove(wordLeft(), cursor); return "redraw"; }
        if (cursor > 0) remove(cursor - 1, cursor);
        return "redraw";
      }
      if (name === "delete") {
        if (cursor < text.length) remove(cursor, cursor + 1);
        return "redraw";
      }
      if (ctrl && name === "w") { remove(wordLeft(), cursor); return "redraw"; }
      if (ctrl && name === "u") { remove(lineStart(cursor), cursor); return "redraw"; }
      if (ctrl && name === "k") { remove(cursor, lineEnd(cursor)); return "redraw"; }
      if (ctrl && name === "a") { cursor = lineStart(cursor); return "redraw"; }
      if (ctrl && name === "e") { cursor = lineEnd(cursor); return "redraw"; }
      if (name === "home") { cursor = lineStart(cursor); return "redraw"; }
      if (name === "end") { cursor = lineEnd(cursor); return "redraw"; }

      if (name === "left") { cursor = meta || ctrl ? wordLeft() : Math.max(0, cursor - 1); return "redraw"; }
      if (name === "right") { cursor = meta || ctrl ? wordRight() : Math.min(text.length, cursor + 1); return "redraw"; }

      if (name === "up" || name === "down") {
        const direction = name === "up" ? -1 : 1;
        const start = lineStart(cursor);
        const column = cursor - start;
        // Only step through history from the edges of the buffer, so a
        // multi-line draft can still be navigated vertically.
        if (direction === -1 && start === 0) return recall(-1) ? "redraw" : "redraw";
        if (direction === 1 && lineEnd(cursor) === text.length) return recall(1) ? "redraw" : "redraw";
        if (direction === -1) {
          const previousStart = lineStart(start - 1);
          cursor = Math.min(previousStart + column, start - 1);
        } else {
          const nextStart = lineEnd(cursor) + 1;
          cursor = Math.min(nextStart + column, lineEnd(nextStart));
        }
        return "redraw";
      }

      // Printable input, including a bracketed paste arriving as one chunk.
      if (sequence && !ctrl && !meta) {
        const clean = sequence.replace(/\r\n?/g, "\n").replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, "");
        if (clean) { insert(clean); return "redraw"; }
      }
      return null;
    },
  };
}
