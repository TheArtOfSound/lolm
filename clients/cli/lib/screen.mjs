// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** A full-screen frame compositor.
 *
 * The console draws whole frames: a fixed header, a scrolling transcript, and a
 * bordered input pinned to the bottom. Repainting every row on every keystroke
 * flickers badly over SSH, so a frame is diffed against the last one and only
 * the rows that actually changed are rewritten.
 */
import { stripAnsi } from "./tui.mjs";

const ALT_ON = "\x1b[?1049h";
const ALT_OFF = "\x1b[?1049l";
const HIDE = "\x1b[?25l";
const SHOW = "\x1b[?25h";
const CLEAR = "\x1b[2J\x1b[H";

/** Truncate to a column budget without cutting an escape sequence in half. */
export function fit(value, columns) {
  const text = String(value ?? "");
  if (stripAnsi(text).length <= columns) return text;
  let out = "";
  let width = 0;
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === "\x1b") {
      const end = text.indexOf("m", index);
      if (end === -1) break;
      out += text.slice(index, end + 1);
      index = end;
      continue;
    }
    if (width >= columns - 1) { out += "…"; break; }
    out += text[index];
    width += 1;
  }
  return `${out}\x1b[0m`;
}

export function createScreen({ output = process.stdout, alternate = true } = {}) {
  let previous = [];
  let open = false;

  const size = () => ({
    rows: Math.max(8, output.rows || 24),
    columns: Math.max(40, output.columns || 80),
  });

  return {
    size,
    open() {
      if (open) return;
      open = true;
      previous = [];
      output.write((alternate ? ALT_ON : "") + CLEAR + HIDE);
    },
    close() {
      if (!open) return;
      open = false;
      previous = [];
      output.write(SHOW + (alternate ? ALT_OFF : ""));
    },
    /** Force the next draw to repaint everything (after a resize or Ctrl+L). */
    invalidate() {
      previous = [];
      if (open) output.write(CLEAR);
    },
    /**
     * @param lines   one string per terminal row, already fitted to width
     * @param cursor  {row, column}, zero-indexed, or null to hide the cursor
     */
    draw(lines, cursor = null) {
      if (!open) return;
      const { rows } = size();
      const frame = lines.slice(0, rows);
      let out = HIDE;
      for (let row = 0; row < rows; row += 1) {
        const next = frame[row] ?? "";
        if (previous[row] === next) continue;
        out += `\x1b[${row + 1};1H\x1b[2K${next}`;
      }
      previous = frame;
      if (cursor) out += `\x1b[${cursor.row + 1};${cursor.column + 1}H${SHOW}`;
      output.write(out);
    },
  };
}
