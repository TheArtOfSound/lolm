// Copyright (c) 2026 Qira LLC. All rights reserved.
/**
 * Reconstruct sandbox files from the unified diffs the API streams.
 *
 * Honesty rules:
 *   1. Truncated diffs are rejected, never half-applied.
 *   2. Context and removal lines must match exactly.
 *   3. Trailing-newline semantics follow the original file and "\\ No newline"
 *      markers — never force a final newline onto a file that lacked one.
 */

/** Apply one unified diff to `current`. Returns {ok, text, reason, deleted?}. */
export function applyUnifiedDiff(current, diff) {
  if (typeof diff !== "string" || diff.length === 0) {
    return { ok: false, text: current, reason: "empty diff" };
  }
  const lines = diff.split("\n");
  const src = current.length ? current.split("\n") : [];
  // Trailing-newline policy:
  //  - new file (empty current): default ON (Unix text / difflib convention)
  //  - existing file: preserve whether it ended with \n
  //  - "\\ No newline at end of file" forces OFF
  let outHasTrailingNewline = current.length === 0 ? true : current.endsWith("\n");
  if (current.endsWith("\n") && src.length) src.pop();
  // "a\nb" (no final \n) → ["a","b"], outHasTrailingNewline=false
  // "a\nb\n" → pop trailing "" → ["a","b"], outHasTrailingNewline=true

  const out = [];
  let srcIdx = 0;
  let i = 0;
  let sawHunk = false;
  let noNewlineAtEnd = false;

  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("--- ") || line.startsWith("+++ ")) { i++; continue; }
    // Deletion of whole file sometimes appears as empty new-side
    const m = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(line);
    if (!m) { i++; continue; }
    sawHunk = true;
    const oldStart = parseInt(m[1], 10);
    const oldCount = m[2] === undefined ? 1 : parseInt(m[2], 10);
    const newCount = m[4] === undefined ? 1 : parseInt(m[4], 10);
    const target = oldCount === 0 ? oldStart : oldStart - 1;
    if (target < srcIdx || target > src.length) {
      return { ok: false, text: current, reason: `hunk start ${oldStart} out of range` };
    }
    while (srcIdx < target) out.push(src[srcIdx++]);

    i++;
    let consumedOld = 0;
    let producedNew = 0;
    while (i < lines.length && !lines[i].startsWith("@@")) {
      const l = lines[i];
      if (l === "" && i === lines.length - 1) { i++; break; }
      const tag = l[0];
      const body = l.slice(1);
      if (tag === " ") {
        if (src[srcIdx] !== body) {
          return { ok: false, text: current,
                   reason: `context mismatch at source line ${srcIdx + 1}` };
        }
        out.push(src[srcIdx++]); consumedOld++; producedNew++;
      } else if (tag === "-") {
        if (src[srcIdx] !== body) {
          return { ok: false, text: current,
                   reason: `removal mismatch at source line ${srcIdx + 1}` };
        }
        srcIdx++; consumedOld++;
      } else if (tag === "+") {
        out.push(body); producedNew++;
      } else if (l.startsWith("\\ No newline") || l.startsWith("\\ No newline at end of file")) {
        noNewlineAtEnd = true;
        outHasTrailingNewline = false;
      } else {
        return { ok: false, text: current, reason: "diff appears truncated" };
      }
      i++;
    }
    if (consumedOld !== oldCount || producedNew !== newCount) {
      return { ok: false, text: current,
               reason: `hunk incomplete (expected -${oldCount}/+${newCount}, ` +
                       `got -${consumedOld}/+${producedNew}) — diff was truncated` };
    }
  }

  if (!sawHunk) return { ok: false, text: current, reason: "no hunks in diff" };
  while (srcIdx < src.length) out.push(src[srcIdx++]);

  // Whole-file deletion: old had content, new is empty
  if (out.length === 0 && oldFileDeleted(diff)) {
    return { ok: true, text: "", reason: "", deleted: true };
  }

  if (out.length === 0) {
    return { ok: true, text: "", reason: "" };
  }
  // only append final newline when the file should have one
  const text = outHasTrailingNewline && !noNewlineAtEnd
    ? out.join("\n") + "\n"
    : out.join("\n");

  return { ok: true, text, reason: "" };
}

function oldFileDeleted(diff) {
  // Heuristic: a single hunk that removes everything and adds nothing
  return /@@ -\d+(?:,\d+)? \+0,0 @@/.test(diff) || /@@ -\d+(?:,\d+)? \+0 @@/.test(diff);
}

/**
 * Replay a sequence of {path, diff} events into final file contents.
 * Returns {files: Map<path,text>, failed: Map<path,reason>, deleted: Set<path>}.
 */
export function replayFileChanges(changes) {
  const files = new Map();
  const failed = new Map();
  const deleted = new Set();
  for (const { path, diff } of changes) {
    if (!path) continue;
    if (failed.has(path)) continue;
    const current = files.get(path) ?? "";
    const res = applyUnifiedDiff(current, diff);
    if (res.ok) {
      if (res.deleted) {
        files.delete(path);
        deleted.add(path);
      } else {
        files.set(path, res.text);
        deleted.delete(path);
      }
    } else {
      failed.set(path, res.reason);
      files.delete(path);
    }
  }
  return { files, failed, deleted };
}
