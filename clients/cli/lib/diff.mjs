// Copyright (c) 2026 Qira LLC. All rights reserved.
/**
 * Reconstruct sandbox files from the unified diffs the API streams.
 *
 * `file_changed` events carry a unified diff rather than the file body, so `--save`
 * has to replay them. Two honesty rules, because writing a corrupted file to a
 * user's disk is worse than writing nothing:
 *
 *   1. The server truncates each diff to 2500 chars. A clipped diff is detected and
 *      rejected rather than half-applied.
 *   2. Every hunk's context and removal lines must match the current content
 *      exactly. Any mismatch fails the file instead of guessing.
 */

/** Apply one unified diff to `current`. Returns {ok, text, reason}. */
export function applyUnifiedDiff(current, diff) {
  if (typeof diff !== "string" || diff.length === 0) {
    return { ok: false, text: current, reason: "empty diff" };
  }
  const lines = diff.split("\n");
  // A complete diff from difflib ends with a full line; a clipped one usually does
  // not, and its final hunk will be short. Both are caught below by hunk math.
  const src = current.length ? current.split("\n") : [];
  // difflib keeps the trailing newline on the last line, so an exact split leaves a
  // trailing "" element. Track it and restore it at the end.
  const hadTrailingNewline = current.endsWith("\n");
  if (hadTrailingNewline) src.pop();

  const out = [];
  let srcIdx = 0;
  let i = 0;
  let sawHunk = false;

  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("--- ") || line.startsWith("+++ ")) { i++; continue; }
    const m = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(line);
    if (!m) { i++; continue; }
    sawHunk = true;
    const oldStart = parseInt(m[1], 10);
    const oldCount = m[2] === undefined ? 1 : parseInt(m[2], 10);
    const newCount = m[4] === undefined ? 1 : parseInt(m[4], 10);
    // difflib uses 1-based starts; a pure creation hunk reports start 0.
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
      // A trailing "" from the final split is not a diff line.
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
      } else if (l.startsWith("\\ No newline")) {
        // positional marker only
      } else {
        // Anything else means the diff was clipped mid-line.
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
  return { ok: true, text: out.join("\n") + (out.length ? "\n" : ""), reason: "" };
}

/**
 * Replay a sequence of {path, diff} events into final file contents.
 * Returns {files: Map<path,text>, failed: Map<path,reason>}.
 */
export function replayFileChanges(changes) {
  const files = new Map();
  const failed = new Map();
  for (const { path, diff } of changes) {
    if (!path) continue;
    if (failed.has(path)) continue;          // already unreliable — do not compound
    const current = files.get(path) ?? "";
    const res = applyUnifiedDiff(current, diff);
    if (res.ok) files.set(path, res.text);
    else { failed.set(path, res.reason); files.delete(path); }
  }
  return { files, failed };
}
