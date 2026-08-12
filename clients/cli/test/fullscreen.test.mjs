// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** The frame compositor and the input editor.
 *
 * These cover the parts a person would otherwise have to notice by eye: that a
 * redraw only rewrites rows that changed, that the cursor lands where the text
 * appears rather than where the raw string implies, and that the editing keys
 * do what their conventions promise.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { createScreen, fit } from "../lib/screen.mjs";
import { createEditor } from "../lib/editor.mjs";
import { stripAnsi } from "../lib/tui.mjs";

/** A stdout stand-in with a fixed size that records what was written. */
function fakeOutput(rows = 10, columns = 40) {
  const writes = [];
  return {
    rows, columns,
    write(chunk) { writes.push(String(chunk)); return true; },
    on() {}, off() {},
    get text() { return writes.join(""); },
    clear() { writes.length = 0; },
  };
}

test("a redraw rewrites only the rows that changed", () => {
  const output = fakeOutput();
  const screen = createScreen({ output, alternate: false });
  screen.open();
  screen.draw(["alpha", "beta", "gamma"]);
  output.clear();
  screen.draw(["alpha", "CHANGED", "gamma"]);
  const text = output.text;
  assert.ok(text.includes("CHANGED"), "the changed row is written");
  assert.ok(!text.includes("alpha"), "an unchanged row is not rewritten");
  assert.ok(!text.includes("gamma"), "an unchanged row is not rewritten");
  // Row 2 of the frame is addressed as line 2.
  assert.match(text, /\x1b\[2;1H/);
  screen.close();
});

test("invalidate forces a full repaint", () => {
  const output = fakeOutput();
  const screen = createScreen({ output, alternate: false });
  screen.open();
  screen.draw(["alpha", "beta"]);
  screen.invalidate();
  output.clear();
  screen.draw(["alpha", "beta"]);
  assert.ok(output.text.includes("alpha"), "everything is redrawn after invalidate");
  screen.close();
});

test("the alternate screen is opt-out, so output can stay in the scrollback", () => {
  const plain = fakeOutput();
  createScreen({ output: plain, alternate: false }).open();
  assert.ok(!plain.text.includes("\x1b[?1049h"));
  const alt = fakeOutput();
  createScreen({ output: alt, alternate: true }).open();
  assert.ok(alt.text.includes("\x1b[?1049h"));
});

test("fit truncates to the column budget without cutting an escape in half", () => {
  const long = "\x1b[31m" + "x".repeat(50) + "\x1b[0m";
  const cut = fit(long, 20);
  assert.ok(stripAnsi(cut).length <= 20, `too wide: ${stripAnsi(cut).length}`);
  assert.ok(cut.startsWith("\x1b[31m"), "the opening colour survives");
  assert.ok(cut.endsWith("\x1b[0m"), "the result is always closed off");
  assert.equal(fit("short", 20), "short", "content inside the budget is untouched");
});

test("editing keys follow their conventions", () => {
  const editor = createEditor();
  const type = (value) => [...value].forEach((character) => editor.key(character, { name: character }));

  type("hello world");
  assert.equal(editor.value, "hello world");

  editor.key("", { name: "w", ctrl: true });
  assert.equal(editor.value, "hello ", "ctrl+w deletes the previous word");

  editor.key("", { name: "a", ctrl: true });
  assert.equal(editor.cursor, 0, "ctrl+a goes to the start of the line");
  editor.key("", { name: "e", ctrl: true });
  assert.equal(editor.cursor, editor.value.length, "ctrl+e goes to the end");

  assert.equal(editor.key("", { name: "return" }), "submit", "plain enter submits");
  assert.equal(editor.key("", { name: "return", meta: true }), "redraw", "alt+enter does not submit");
  assert.ok(editor.value.includes("\n"), "alt+enter inserts a newline");
});

test("ctrl+c clears a draft before it quits", () => {
  const editor = createEditor();
  [..."draft"].forEach((character) => editor.key(character, { name: character }));
  assert.equal(editor.key("", { name: "c", ctrl: true }), "redraw");
  assert.equal(editor.value, "", "the first ctrl+c empties the buffer");
  assert.equal(editor.key("", { name: "c", ctrl: true }), "cancel", "the second leaves");
});

test("history recalls previous submissions from the buffer edges", () => {
  const editor = createEditor();
  editor.remember("first task");
  editor.remember("second task");
  editor.key("", { name: "up" });
  assert.equal(editor.value, "second task", "up recalls the most recent entry");
  editor.key("", { name: "up" });
  assert.equal(editor.value, "first task");
  editor.key("", { name: "down" });
  assert.equal(editor.value, "second task", "down walks back toward the draft");
});

test("control characters in a paste are stripped, newlines kept", () => {
  const editor = createEditor();
  editor.key("line one\r\nline two\x07", {});
  assert.equal(editor.value, "line one\nline two", "CRLF folds to LF and a bell is dropped");
});

test("paging keys ask the console to scroll rather than editing text", () => {
  const editor = createEditor();
  assert.equal(editor.key("", { name: "pageup" }), "scroll-up");
  assert.equal(editor.key("", { name: "pagedown" }), "scroll-down");
  assert.equal(editor.value, "", "paging never changes the buffer");
});
