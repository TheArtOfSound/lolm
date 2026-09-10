// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Produce a unified diff between two texts.
 *
 * `diff.mjs` applies diffs the API sends; this makes them, so an edit the agent
 * performs can be shown to the reader as the change it actually was rather than
 * as "wrote 1,204 bytes". Line-level LCS is exact for files of ordinary size;
 * beyond `limit` lines it falls back to trimming the common prefix and suffix,
 * which is linear and still shows the region that changed.
 */

const LIMIT = 2_000;

function splitLines(text) {
  const value = String(text ?? "");
  if (!value) return [];
  const lines = value.split("\n");
  if (value.endsWith("\n")) lines.pop();
  return lines;
}

/** Edit script as [op, line] with op in " ", "-", "+". */
function editScript(a, b) {
  if (a.length > LIMIT || b.length > LIMIT) {
    let head = 0;
    while (head < a.length && head < b.length && a[head] === b[head]) head += 1;
    let tail = 0;
    while (tail < a.length - head && tail < b.length - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) tail += 1;
    return [
      ...a.slice(0, head).map((line) => [" ", line]),
      ...a.slice(head, a.length - tail).map((line) => ["-", line]),
      ...b.slice(head, b.length - tail).map((line) => ["+", line]),
      ...a.slice(a.length - tail).map((line) => [" ", line]),
    ];
  }
  const n = a.length, m = b.length;
  const width = m + 1;
  const table = new Int32Array((n + 1) * width);
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      table[i * width + j] = a[i] === b[j]
        ? table[(i + 1) * width + j + 1] + 1
        : Math.max(table[(i + 1) * width + j], table[i * width + j + 1]);
    }
  }
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push([" ", a[i]]); i += 1; j += 1; }
    else if (table[(i + 1) * width + j] >= table[i * width + j + 1]) { out.push(["-", a[i]]); i += 1; }
    else { out.push(["+", b[j]]); j += 1; }
  }
  while (i < n) out.push(["-", a[i++]]);
  while (j < m) out.push(["+", b[j++]]);
  return out;
}

/**
 * @returns a unified diff string, or "" when the texts are identical.
 * Output is capped at `maxLines`; the cap is reported on the last line.
 */
export function unifiedDiff(before, after, { path = "", context = 3, maxLines = 400 } = {}) {
  const a = splitLines(before);
  const b = splitLines(after);
  const script = editScript(a, b);
  if (!script.some(([op]) => op !== " ")) return "";

  const hunks = [];
  let index = 0;
  while (index < script.length) {
    if (script[index][0] === " ") { index += 1; continue; }
    const start = Math.max(0, index - context);
    let end = index;
    let quiet = 0;
    while (end < script.length && quiet <= context * 2) {
      quiet = script[end][0] === " " ? quiet + 1 : 0;
      end += 1;
    }
    end = Math.min(script.length, end - Math.max(0, quiet - context));
    hunks.push(script.slice(start, end));
    index = end;
  }

  const lines = [];
  if (path) lines.push(`--- a/${path}`, `+++ b/${path}`);
  let oldLine = 1, newLine = 1, cursor = 0;
  for (const hunk of hunks) {
    // Advance the counters through the unchanged stretch before this hunk.
    const hunkStart = script.indexOf(hunk[0], cursor);
    for (let k = cursor; k < hunkStart; k += 1) {
      if (script[k][0] !== "+") oldLine += 1;
      if (script[k][0] !== "-") newLine += 1;
    }
    cursor = hunkStart + hunk.length;
    const oldCount = hunk.filter(([op]) => op !== "+").length;
    const newCount = hunk.filter(([op]) => op !== "-").length;
    lines.push(`@@ -${oldLine},${oldCount} +${newLine},${newCount} @@`);
    for (const [op, line] of hunk) {
      lines.push(`${op}${line}`);
      if (op !== "+") oldLine += 1;
      if (op !== "-") newLine += 1;
    }
  }
  if (lines.length > maxLines) {
    const hidden = lines.length - maxLines;
    return `${lines.slice(0, maxLines).join("\n")}\n… ${hidden} more line(s)`;
  }
  return lines.join("\n");
}

/** Counts a caller can show without parsing the text. */
export function diffStats(diff) {
  let added = 0, removed = 0;
  for (const line of String(diff || "").split("\n")) {
    if (line.startsWith("+++") || line.startsWith("---")) continue;
    if (line.startsWith("+")) added += 1;
    else if (line.startsWith("-")) removed += 1;
  }
  return { added, removed };
}
