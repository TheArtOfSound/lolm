// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** The shared NFET service, exercised against a stub bridge.
 *
 * The real bridge loads a 4B backbone and takes about a minute, which is not
 * something a test suite can afford. Standing in a fake interpreter that speaks
 * the same JSONL protocol tests everything except the model: startup, request
 * forwarding, per-connection session isolation, and shutdown.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { connect } from "node:net";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import readline from "node:readline";
import { daemonSocketPath } from "../lib/nfet.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const daemonPath = join(here, "..", "lib", "nfet_daemon.mjs");

const STUB_BRIDGE = `
import readline from "node:readline";
const say = (v) => process.stdout.write(JSON.stringify(v) + "\\n");
// Count turns per session so a test can prove state is not shared.
const seen = new Map();
say({ event: "ready", profile: "stub", device: "cpu", backend: "stub", head_trained: true });
readline.createInterface({ input: process.stdin }).on("line", (line) => {
  const request = JSON.parse(line);
  if (request.op === "close") { say({ event: "closed" }); process.exit(0); }
  if (request.op === "end_session") { seen.delete(request.session); return say({ event: "session_ended", sessions: seen.size }); }
  const turns = (seen.get(request.session) || 0) + 1;
  seen.set(request.session, turns);
  say({ event: "decision", session_turns: turns, sessions: seen.size, text: request.text, decision: { label: "continue" } });
});
`;

async function startDaemon() {
  const root = await mkdtemp(join(tmpdir(), "lolm-nfetd-"));
  const stub = join(root, "stub-bridge.mjs");
  await writeFile(stub, STUB_BRIDGE);
  const socket = join(root, "nfet.sock");
  // Node stands in for the interpreter and LOLM_NFET_BRIDGE for the script, so
  // the daemon runs its real code path against a bridge that answers instantly.
  const child = spawn(process.execPath, [
    daemonPath, "--socket", socket, "--python", process.execPath, "--root", root,
    "--profile", "stub", "--device", "cpu", "--checkpoint", join(root, "ckpt.pt"), "--backend", "stub",
  ], { stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, LOLM_NFET_BRIDGE: stub } });
  return { root, socket, child };
}

function talk(socket) {
  const pending = [];
  const reader = readline.createInterface({ input: socket });
  reader.on("line", (line) => pending.shift()?.(JSON.parse(line)));
  return (request) => new Promise((resolvePromise) => {
    pending.push(resolvePromise);
    socket.write(`${JSON.stringify(request)}\n`);
  });
}

function open(path, deadlineMs = 15_000) {
  const stop = Date.now() + deadlineMs;
  return new Promise((resolvePromise, reject) => {
    const attempt = () => {
      const socket = connect(path);
      socket.once("connect", () => resolvePromise(socket));
      socket.once("error", () => {
        socket.destroy();
        if (Date.now() > stop) reject(new Error("daemon never listened"));
        else setTimeout(attempt, 100);
      });
    };
    attempt();
  });
}

test("one socket per model configuration", () => {
  const base = { home: "/h", python: "/p", profile: "a", device: "cpu", checkpoint: "/c", backend: "b" };
  assert.equal(daemonSocketPath(base), daemonSocketPath({ ...base }));
  for (const key of ["home", "python", "profile", "device", "checkpoint", "backend"]) {
    assert.notEqual(daemonSocketPath(base), daemonSocketPath({ ...base, [key]: "different" }),
      `${key} must not reuse another configuration's service`);
  }
});

test("the shared service isolates each connection's policy state", async (t) => {
  const { socket: path, child } = await startDaemon();
  t.after(() => child.kill("SIGKILL"));

  const first = await open(path);
  const second = await open(path);
  const askFirst = talk(first);
  const askSecond = talk(second);

  const hello = await askFirst({ op: "hello" });
  assert.equal(hello.event, "ready");
  assert.equal(hello.daemon, true);
  assert.equal(hello.head_trained, true);

  // Interleaved turns must count per connection, not globally.
  assert.equal((await askFirst({ op: "decide", text: "a1" })).session_turns, 1);
  assert.equal((await askSecond({ op: "decide", text: "b1" })).session_turns, 1);
  assert.equal((await askFirst({ op: "decide", text: "a2" })).session_turns, 2);
  const third = await askSecond({ op: "decide", text: "b2" });
  assert.equal(third.session_turns, 2);
  assert.equal(third.sessions, 2, "each connection holds exactly one session");
  assert.equal(third.text, "b2", "requests must reach the bridge unchanged");

  // Dropping a client frees its session but leaves the loaded model up.
  first.end();
  await new Promise((resolvePromise) => setTimeout(resolvePromise, 300));
  assert.equal((await askSecond({ op: "decide", text: "b3" })).sessions, 1);

  second.end();
});

test("the shared service stops on request", async (t) => {
  const { socket: path, child } = await startDaemon();
  t.after(() => child.kill("SIGKILL"));
  const socket = await open(path);
  const ask = talk(socket);
  assert.equal((await ask({ op: "hello" })).event, "ready");
  assert.equal((await ask({ op: "stop" })).event, "stopping");
  await new Promise((resolvePromise) => child.once("exit", resolvePromise));
  assert.notEqual(child.exitCode, null);
});
