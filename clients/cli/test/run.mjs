// Copyright (c) 2026 Qira LLC. All rights reserved.
/**
 * Tests for the CLI's risky part: reconstructing sandbox files from the streamed
 * unified diffs. Writing a corrupted file to a user's disk is worse than writing
 * nothing, so the applier has to refuse anything it cannot verify.
 *
 *   node test/run.mjs
 */

import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { promisify } from "node:util";
import assert from "node:assert/strict";
import { applyUnifiedDiff, replayFileChanges } from "../lib/diff.mjs";

const run = promisify(execFile);
const here = dirname(fileURLToPath(import.meta.url));
const BIN = join(here, "..", "bin", "lolm.mjs");

let pass = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// ── the applier ──────────────────────────────────────────────────────────────

test("creates a new file from a creation hunk", () => {
  const diff = [
    "--- a/solution.py", "+++ b/solution.py", "@@ -0,0 +1,3 @@",
    "+def f():", "+    return 42", "+print(f())", "",
  ].join("\n");
  const r = applyUnifiedDiff("", diff);
  assert.equal(r.ok, true, r.reason);
  assert.equal(r.text, "def f():\n    return 42\nprint(f())\n");
});

test("applies an edit against matching context", () => {
  const before = "def f():\n    return 41\nprint(f())\n";
  const diff = [
    "--- a/s.py", "+++ b/s.py", "@@ -1,3 +1,3 @@",
    " def f():", "-    return 41", "+    return 42", " print(f())", "",
  ].join("\n");
  const r = applyUnifiedDiff(before, diff);
  assert.equal(r.ok, true, r.reason);
  assert.equal(r.text, "def f():\n    return 42\nprint(f())\n");
});

test("refuses a diff whose context does not match", () => {
  const diff = [
    "--- a/s.py", "+++ b/s.py", "@@ -1,2 +1,2 @@",
    " def g():", "-    return 1", "+    return 2", "",
  ].join("\n");
  const r = applyUnifiedDiff("def f():\n    return 1\n", diff);
  assert.equal(r.ok, false);
  assert.match(r.reason, /context mismatch/);
});

test("refuses a truncated diff instead of half-applying it", () => {
  // The API clips diffs at 2500 chars; the hunk header promises more than arrives.
  const diff = [
    "--- a/s.py", "+++ b/s.py", "@@ -0,0 +1,5 @@",
    "+line one", "+line two",   // header said 5, only 2 present
  ].join("\n");
  const r = applyUnifiedDiff("", diff);
  assert.equal(r.ok, false);
  assert.match(r.reason, /truncated|incomplete/);
});

test("refuses garbage and empty input", () => {
  assert.equal(applyUnifiedDiff("", "").ok, false);
  assert.equal(applyUnifiedDiff("", "not a diff at all").ok, false);
  assert.match(applyUnifiedDiff("", "not a diff at all").reason, /no hunks/);
});

test("preserves lines after the final hunk", () => {
  const before = "a\nb\nc\nd\n";
  const diff = ["@@ -1,2 +1,2 @@", " a", "-b", "+B", ""].join("\n");
  const r = applyUnifiedDiff(before, diff);
  assert.equal(r.ok, true, r.reason);
  assert.equal(r.text, "a\nB\nc\nd\n");
});

// ── replay across a whole run ────────────────────────────────────────────────

test("replays create-then-edit into the final content", () => {
  const create = ["@@ -0,0 +1,2 @@", "+x = 1", "+print(x)", ""].join("\n");
  const edit = ["@@ -1,2 +1,2 @@", "-x = 1", "+x = 2", " print(x)", ""].join("\n");
  const { files, failed } = replayFileChanges([
    { path: "a.py", diff: create },
    { path: "a.py", diff: edit },
  ]);
  assert.equal(failed.size, 0);
  assert.equal(files.get("a.py"), "x = 2\nprint(x)\n");
});

test("a failed file is reported, not written with partial content", () => {
  const create = ["@@ -0,0 +1,1 @@", "+ok = 1", ""].join("\n");
  const bad = ["@@ -0,0 +1,9 @@", "+only one line"].join("\n");
  const { files, failed } = replayFileChanges([
    { path: "good.py", diff: create },
    { path: "bad.py", diff: bad },
  ]);
  assert.equal(files.has("good.py"), true);
  assert.equal(files.has("bad.py"), false, "must not write a file it could not verify");
  assert.equal(failed.has("bad.py"), true);
});

test("once a file fails, later diffs for it stay rejected", () => {
  const bad = ["@@ -0,0 +1,9 @@", "+one"].join("\n");
  const create = ["@@ -0,0 +1,1 @@", "+x = 1", ""].join("\n");
  const { files, failed } = replayFileChanges([
    { path: "f.py", diff: bad },
    { path: "f.py", diff: create },
  ]);
  assert.equal(files.has("f.py"), false, "a compounded file is not trustworthy");
  assert.equal(failed.has("f.py"), true);
});

// ── the binary itself ───────────────────────────────────────────────────────

test("--version prints just the version", async () => {
  const { stdout } = await run(process.execPath, [BIN, "--version"]);
  assert.match(stdout.trim(), /^\d+\.\d+\.\d+$/);
});

test("--help lists the commands", async () => {
  const { stdout } = await run(process.execPath, [BIN, "--help"]);
  for (const cmd of ["code", "ask", "build", "receipts", "status", "memory"]) {
    assert.ok(stdout.includes(cmd), `help should mention ${cmd}`);
  }
});

test("no args prints help rather than erroring", async () => {
  const { stdout } = await run(process.execPath, [BIN]);
  assert.ok(stdout.includes("USAGE"));
});

test("an unknown command exits 2 with a usable message", async () => {
  await assert.rejects(
    run(process.execPath, [BIN, "frobnicate"]),
    (e) => e.code === 2 && /unknown command/.test(e.stderr),
  );
});

test("code with no task exits 2 instead of calling the API", async () => {
  await assert.rejects(
    run(process.execPath, [BIN, "code"]),
    (e) => e.code === 2 && /what should it build/.test(e.stderr),
  );
});

test("an unknown flag exits 2", async () => {
  await assert.rejects(
    run(process.execPath, [BIN, "status", "--nope"]),
    (e) => e.code === 2 && /unknown flag/.test(e.stderr),
  );
});

// ── run ─────────────────────────────────────────────────────────────────────

for (const [name, fn] of tests) {
  try {
    await fn();
    console.log(`  ✓ ${name}`);
    pass++;
  } catch (e) {
    console.error(`  ✗ ${name}\n    ${e.message}`);
    process.exitCode = 1;
  }
}
console.log(`\n${pass}/${tests.length} passed`);
