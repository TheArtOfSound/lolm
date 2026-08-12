// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Scrollback navigation, the settings panel, and clipboard routing. */
import test from "node:test";
import assert from "node:assert/strict";
import { scrollKey, searchTranscript, settingsKey, settingsModel } from "../lib/overlays.mjs";
import { osc52, copyText, backupPath } from "../lib/clipboard.mjs";

const view = { total: 100, height: 10 };

test("vim keys move the viewport the way vim does", () => {
  assert.equal(scrollKey("k", { offset: 0, ...view }).offset, 1, "k scrolls back one line");
  assert.equal(scrollKey("j", { offset: 5, ...view }).offset, 4, "j scrolls toward the tail");
  assert.equal(scrollKey("d", { offset: 20, ctrl: true, ...view }).offset, 15, "^D is half a screen");
  assert.equal(scrollKey("u", { offset: 20, ctrl: true, ...view }).offset, 25, "^U is half a screen back");
  assert.equal(scrollKey("b", { offset: 0, ...view }).offset, 10, "^B/PgUp is a full screen");
  assert.equal(scrollKey("G", { offset: 40, ...view }).offset, 0, "G returns to the live tail");
});

test("gg needs both keystrokes and goes to the oldest line", () => {
  const first = scrollKey("g", { offset: 0, ...view });
  assert.equal(first.pending, "g", "one g waits for the second");
  assert.equal(first.offset, 0, "one g alone moves nothing");
  const second = scrollKey("g", { offset: 0, ...view, pending: "g" });
  assert.equal(second.offset, 90, "gg reaches the top of the transcript");
  assert.equal(second.pending, "");
});

test("scrolling never leaves the transcript", () => {
  assert.equal(scrollKey("k", { offset: 90, ...view }).offset, 90, "cannot scroll past the oldest line");
  assert.equal(scrollKey("j", { offset: 0, ...view }).offset, 0, "cannot scroll past the newest line");
});

test("search finds the most recent match and reports its offset", () => {
  const transcript = ["alpha", "beta", "the needle here", "gamma", "delta"];
  const hit = searchTranscript(transcript, "NEEDLE");
  assert.equal(hit.index, 2, "matching ignores case");
  assert.equal(hit.offset, 2, "offset is measured back from the tail");
  assert.equal(searchTranscript(transcript, "absent"), null);
  assert.equal(searchTranscript(transcript, ""), null, "an empty query matches nothing");
});

test("search can skip past an earlier hit to find the next one", () => {
  const transcript = ["match one", "filler", "match two"];
  const first = searchTranscript(transcript, "match");
  assert.equal(first.index, 2);
  const next = searchTranscript(transcript, "match", { from: transcript.length - first.index });
  assert.equal(next.index, 0, "searching onward reaches the older match");
});

test("the settings panel moves, cycles choices, and edits free text", () => {
  const context = { provider: "Cerebras", model: "gpt-oss-120b", mode: "standard", workspace: "/tmp", nfet: "active", verbose: false };
  let state = { rows: settingsModel(context), index: 0, editing: false, buffer: "" };

  state = settingsKey("down", { ...state });
  assert.equal(state.index, 1, "j/down moves the selection");

  // Permissions is a choice row, so left/right cycles it and applies at once.
  state.index = state.rows.findIndex((row) => row.key === "mode");
  const cycled = settingsKey("right", { ...state });
  assert.equal(cycled.action, "apply");
  assert.equal(cycled.key, "mode");
  assert.notEqual(cycled.value, "standard", "the value actually changed");

  // Model is free text: enter opens an editor, typing fills it, enter applies.
  state.index = state.rows.findIndex((row) => row.key === "model");
  let editing = settingsKey("return", { ...state });
  assert.equal(editing.editing, true, "enter starts editing a text row");
  for (const character of "gpt-5") editing = settingsKey(character, { ...editing, sequence: character });
  assert.equal(editing.buffer, "gpt-5");
  const applied = settingsKey("return", { ...editing });
  assert.deepEqual([applied.action, applied.key, applied.value], ["apply", "model", "gpt-5"]);
  assert.equal(applied.editing, false, "applying closes the editor");
});

test("escape closes the panel, and cancels an edit without applying it", () => {
  const context = { provider: "P", model: "M", mode: "standard", workspace: "/tmp", nfet: "off", verbose: false };
  const rows = settingsModel(context);
  assert.equal(settingsKey("escape", { rows, index: 0, editing: false, buffer: "" }).action, "close");
  const cancelled = settingsKey("escape", { rows, index: 1, editing: true, buffer: "half-typed" });
  assert.equal(cancelled.editing, false);
  assert.equal(cancelled.action, undefined, "a cancelled edit applies nothing");
});

test("OSC 52 carries the payload and is wrapped for each multiplexer", () => {
  const bare = osc52("hello");
  assert.ok(bare.startsWith("\x1b]52;c;"), "a plain terminal gets the raw sequence");
  assert.ok(bare.includes(Buffer.from("hello").toString("base64")));

  const tmux = osc52("hello", { multiplexer: "tmux" });
  assert.ok(tmux.startsWith("\x1bPtmux;"), "tmux needs a DCS wrapper");
  assert.ok(tmux.endsWith("\x1b\\"));
  assert.ok(tmux.includes("\x1b\x1b]52"), "the inner escape is doubled for tmux");

  const screen = osc52("x".repeat(1200), { multiplexer: "screen" });
  assert.ok(screen.split("\x1bP").length > 2, "screen splits a long payload into chunks");
});

test("a copy always leaves a retrievable backup and says what it did", async () => {
  const written = [];
  const output = { write: (chunk) => { written.push(String(chunk)); return true; } };
  const result = await copyText("clipboard payload", {
    output,
    env: { LOLM_CLIPBOARD_NO_OSC52: "0", SSH_CONNECTION: "1" }, // force the remote path
  });
  assert.ok(written.join("").includes("\x1b]52;c;"), "OSC 52 is emitted when there is no local clipboard");
  assert.equal(result.confirmed, false, "OSC 52 delivery can never be confirmed");
  assert.equal(result.backup, backupPath());
  assert.match(result.note, /saved below/, "the note points at the backup");
  assert.ok(result.routes.length, "the routes used are reported");
});
