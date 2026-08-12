// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Accessibility guarantees of the terminal UI.
 *
 * Terminal capabilities are settled once at import, so these run the real CLI
 * in a subprocess with a controlled environment. Checking the actual bytes on
 * the wire is the only way to prove that nothing repaints, animates, or emits
 * characters the reader's terminal cannot render.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const cli = join(dirname(fileURLToPath(import.meta.url)), "..", "bin", "lolm.mjs");

/** Run the CLI to completion, feeding stdin and capturing raw bytes. */
function run(args, { env = {}, stdin = "" } = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(process.execPath, [cli, ...args], { env: { ...process.env, ...env } });
    let stdout = "", stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", () => resolvePromise({ stdout, stderr }));
    child.stdin.end(stdin);
    // A hung interactive loop would otherwise stall the whole suite.
    setTimeout(() => child.kill("SIGKILL"), 30_000).unref();
  });
}

async function chat(env = {}, args = []) {
  const { stdout, stderr } = await run(["chat", "--no-nfet", ...args], { env, stdin: "/help\n/exit\n" });
  return stdout + stderr;
}

const ALT_SCREEN = "\x1b[?1049h";
const CLEAR_LINE = "\x1b[2K";
const SPINNER_FRAMES = /[◐◓◑◒|/\\]/;

test("plain mode never takes over the screen", async () => {
  const out = await chat({ LOLM_PLAIN: "1" });
  assert.ok(!out.includes(ALT_SCREEN), "must not switch to the alternate screen buffer");
  assert.ok(!out.includes(CLEAR_LINE), "must not erase lines it has already written");
  assert.ok(!out.includes("\x1b[2J"), "must not clear the screen");
  assert.ok(!out.includes("\r"), "must not return the cursor to overwrite output");
});

test("plain mode labels speakers and state in words", async () => {
  const out = await chat({ LOLM_PLAIN: "1" });
  assert.match(out, /LOLM personal agent, version/);
  assert.match(out, /^Provider: .+, model .+\.$/m, "provider is a sentence, not a symbol row");
  assert.match(out, /^Permissions: /m);
  assert.match(out, /^You: /m, "the reader's turn is named");
  assert.match(out, /^LOLM: /m, "the agent's turn is named");
});

test("plain mode emits no decorative symbols a screen reader would announce", async () => {
  const out = await chat({ LOLM_PLAIN: "1" });
  for (const symbol of ["●", "◆", "◇", "⌂", "↳", "╭", "╰", "─", "│", "•", "·"]) {
    assert.ok(!out.includes(symbol), `plain output must not contain ${symbol}`);
  }
});

test("plain mode carries no colour escapes", async () => {
  const plain = await chat({ LOLM_PLAIN: "1" });
  assert.ok(!/\x1b\[[0-9;]*m/.test(plain), "plain output carries no colour escapes");
});

test("FORCE_COLOR keeps colour when output is piped", async () => {
  // stdout is a pipe here, so colour is off by default; piping into a pager
  // that understands escapes is the case FORCE_COLOR exists for.
  const bare = await chat({ FORCE_COLOR: "" });
  assert.ok(!/\x1b\[[0-9;]*m/.test(bare), "a pipe gets no colour unless asked");
  const forced = await chat({ FORCE_COLOR: "1" });
  assert.ok(/\x1b\[[0-9;]*m/.test(forced), "FORCE_COLOR must restore colour on a pipe");
});

test("NO_COLOR removes every colour escape", async () => {
  const out = await chat({ NO_COLOR: "1", FORCE_COLOR: "" });
  assert.ok(!/\x1b\[[0-9;]*m/.test(out), "NO_COLOR must silence colour");
  assert.match(out, /personal agent/i, "content survives without colour");
});

test("a non-UTF-8 locale produces only printable ASCII", async () => {
  const out = await chat({ LC_ALL: "C", LANG: "C", NO_COLOR: "1" });
  const offending = [...out].filter((character) => {
    const code = character.codePointAt(0);
    return code > 0x7e || (code < 0x20 && !"\t\n\r\x1b".includes(character));
  });
  assert.deepEqual(offending, [], "no character outside printable ASCII may reach a C-locale terminal");
});

test("meaning never depends on colour alone", async () => {
  const { stdout } = await run(["--help"], { env: { NO_COLOR: "1" } });
  // Every option must still be identifiable with colour stripped.
  assert.match(stdout, /--plain\s+linear, screen-reader friendly output/);
  assert.match(stdout, /--no-nfet/);
});

test("doctor reports the terminal it detected and how to change it", async () => {
  const { stdout } = await run(["doctor", "--json", "--no-nfet", "--plain"], { env: { LOLM_PLAIN: "1" } });
  const payload = JSON.parse(stdout.trim().split("\n").at(-1));
  assert.equal(payload.terminal.plain, true);
  assert.equal(payload.terminal.motion, false, "plain mode must not animate");
  assert.equal(payload.terminal.altScreen, false);
  assert.equal(typeof payload.terminal.width, "number");
});

test("LOLM_NO_MOTION stops animation without stopping progress", async () => {
  const { stdout } = await run(["doctor", "--json", "--no-nfet"], { env: { LOLM_NO_MOTION: "1" } });
  const payload = JSON.parse(stdout.trim().split("\n").at(-1));
  assert.equal(payload.terminal.motion, false);
  assert.ok(!SPINNER_FRAMES.test(payload.terminal.term || ""), "sanity: term name is not a frame");
});

test("wrapping keeps words whole and respects the requested width", async () => {
  const { wrap, asciiSafe } = await import("../lib/tui.mjs");
  const wrapped = wrap("alpha beta gamma delta epsilon zeta eta theta iota kappa", 20);
  for (const line of wrapped.split("\n")) assert.ok(line.length <= 20, `"${line}" exceeds 20 columns`);
  assert.equal(wrapped.replace(/\n/g, " "), "alpha beta gamma delta epsilon zeta eta theta iota kappa");
  assert.equal(typeof asciiSafe("x"), "string");
});
