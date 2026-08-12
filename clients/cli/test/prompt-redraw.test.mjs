// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Background output must not corrupt the line the reader is typing on.
 *
 * The controller finishing its load, or a tool reporting in, arrives while
 * readline owns the prompt line. Writing straight to stdout there lands on top
 * of the prompt — the defect that printed a status line inside the input box.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { createConsoleSurface, caps, GUTTER, inputPrompt, spread, rule, stripAnsi } from "../lib/tui.mjs";

/** Capture stdout while a body runs. */
function capture(body) {
  const chunks = [];
  const original = process.stdout.write.bind(process.stdout);
  process.stdout.write = (chunk) => { chunks.push(String(chunk)); return true; };
  try { body(); } finally { process.stdout.write = original; }
  return chunks.join("");
}

function surfaceWithFakeReadline() {
  const redraws = [];
  const surface = createConsoleSurface({ version: "test", provider: "P", model: "M", nfet: "on" });
  surface.attach({ prompt: (preserve) => redraws.push(preserve) });
  return { surface, redraws };
}

test("output while the prompt is live erases it and repaints it", () => {
  const { surface, redraws } = surfaceWithFakeReadline();
  surface.setPromptLive(true);
  const out = capture(() => surface.tool("Local NFET quality controller ready"));
  assert.match(out, /\x1b\[2K/, "the prompt line must be erased before writing over it");
  assert.ok(out.includes("Local NFET quality controller ready"));
  assert.deepEqual(redraws, [true], "readline must repaint the prompt, preserving typed input");
});

test("output with no live prompt writes plainly", () => {
  const { surface, redraws } = surfaceWithFakeReadline();
  surface.setPromptLive(false);
  const out = capture(() => surface.tool("no prompt on screen"));
  assert.ok(out.includes("no prompt on screen"));
  assert.deepEqual(redraws, [], "nothing to repaint when the reader is not at a prompt");
});

test("the prompt and its rule are one coherent block", () => {
  const prompt = inputPrompt();
  if (caps.plain) {
    assert.equal(prompt, "\nYou: ");
    return;
  }
  const plain = stripAnsi(prompt);
  assert.match(plain, /YOU/, "the reader's turn is labelled");
  assert.ok(plain.trimEnd().endsWith("›"), "the caret is the last thing before the cursor");
});

test("spread pins a detail to the right edge without overlapping", () => {
  const line = stripAnsi(spread("left", "right", 40));
  assert.ok(line.length <= 40, `"${line}" must fit the width`);
  assert.ok(line.startsWith("left") && line.endsWith("right"));
  // A line too narrow for both must still not lose either side.
  const tight = stripAnsi(spread("aaaaaaaaaa", "bbbbbbbbbb", 12));
  assert.ok(tight.includes("aaaaaaaaaa") && tight.includes("bbbbbbbbbb"));
});

test("a labelled rule fills the width exactly once", () => {
  const line = stripAnsi(rule("YOU"));
  assert.ok(line.startsWith(GUTTER), "a rule hangs off the shared gutter");
  assert.match(line.slice(GUTTER.length), /^[-─] YOU [-─]+$/, `unexpected rule shape: ${line}`);
  assert.ok(line.length <= caps.width, "a rule must never wrap");
  assert.equal(stripAnsi(rule()).length, stripAnsi(line).length, "labelled and plain rules align");
});
