// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Keeps one loaded NFET bridge alive across CLI invocations.
 *
 * Loading the 4B backbone costs ~90s. Paying that on every `lolm run` made the
 * controller too expensive to leave on. This process owns a single bridge and
 * lends it to any client that connects, so the load is paid once per machine.
 *
 * Requests are serialised: the bridge is one stdin/stdout pair and one model, so
 * only one decision can be in flight. Each connection gets its own bridge
 * session, keeping rolling policy state isolated between callers.
 */
import { createServer } from "node:net";
import { spawn } from "node:child_process";
import { unlink } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import readline from "node:readline";
import { randomUUID } from "node:crypto";

const IDLE_EXIT_MS = Number(process.env.LOLM_NFET_IDLE_MS || 30 * 60_000);

function parseArgs(argv) {
  const out = {};
  for (let index = 0; index < argv.length; index += 2) {
    if (argv[index]?.startsWith("--")) out[argv[index].slice(2)] = argv[index + 1];
  }
  return out;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const { socket, python, root, profile, device, checkpoint, backend } = args;
  if (!socket || !python || !root) throw new Error("nfet daemon needs --socket, --python, and --root");

  // LOLM_NFET_BRIDGE swaps the bridge script; the tests use it to stand in a
  // stub so they need not load a 4B model to check the plumbing.
  const bridge = process.env.LOLM_NFET_BRIDGE || fileURLToPath(new URL("nfet_bridge.py", import.meta.url));
  const child = spawn(python, [
    bridge,
    "--root", root, "--profile", profile, "--device", device,
    "--checkpoint", checkpoint, "--backend", backend,
  ], {
    cwd: root,
    env: { ...process.env, PYTHONPATH: [root, process.env.PYTHONPATH].filter(Boolean).join(":"), LOLM_TEST_NO_BOOT: "1" },
    stdio: ["pipe", "pipe", "pipe"],
  });

  let stderr = "";
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => { stderr = `${stderr}${chunk}`.slice(-4000); });

  const pending = [];
  const lines = readline.createInterface({ input: child.stdout });
  lines.on("line", (line) => {
    let payload;
    try { payload = JSON.parse(line); } catch { return; }
    pending.shift()?.(payload);
  });

  const ready = await new Promise((resolvePromise, reject) => {
    pending.push(resolvePromise);
    child.once("exit", (code) => reject(new Error(`NFET bridge exited ${code}: ${stderr.trim()}`)));
    child.once("error", reject);
  });
  if (ready.event !== "ready") throw new Error(ready.error || "NFET bridge did not become ready");

  // One model, one pipe: a queue is the honest representation of that limit.
  let working = Promise.resolve();
  const ask = (request) => {
    const turn = working.then(() => new Promise((resolvePromise) => {
      pending.push(resolvePromise);
      child.stdin.write(`${JSON.stringify(request)}\n`);
    }));
    working = turn.catch(() => {});
    return turn;
  };

  let clients = 0;
  let idleTimer;
  const armIdle = () => {
    clearTimeout(idleTimer);
    if (clients > 0) return;
    idleTimer = setTimeout(() => { shutdown(0); }, IDLE_EXIT_MS);
  };

  let closing = false;
  async function shutdown(code) {
    if (closing) return;
    closing = true;
    try { child.stdin.write('{"op":"close"}\n'); } catch { /* already gone */ }
    child.kill("SIGTERM");
    server.close();
    await unlink(socket).catch(() => {});
    process.exit(code);
  }

  const server = createServer((connection) => {
    clients += 1;
    clearTimeout(idleTimer);
    const session = randomUUID();
    connection.setEncoding("utf8");
    const reader = readline.createInterface({ input: connection });
    reader.on("line", async (line) => {
      let request;
      try { request = JSON.parse(line); } catch { return; }
      if (request.op === "hello") {
        connection.write(`${JSON.stringify({ ...ready, event: "ready", daemon: true, pid: process.pid })}\n`);
        return;
      }
      if (request.op === "stop") {
        connection.write(`${JSON.stringify({ event: "stopping", pid: process.pid })}\n`);
        setTimeout(() => shutdown(0), 50);
        return;
      }
      try {
        const response = await ask({ ...request, session });
        connection.write(`${JSON.stringify(response)}\n`);
      } catch (error) {
        connection.write(`${JSON.stringify({ event: "fatal", error: error.message })}\n`);
      }
    });
    const done = () => {
      clients = Math.max(0, clients - 1);
      // Free this session's rolling policy state; the loaded model stays. The
      // id matters: without it the bridge frees nothing and sessions leak.
      ask({ op: "end_session", session }).catch(() => {});
      armIdle();
    };
    connection.once("close", done);
    connection.once("error", done);
  });

  // Losing the bind race means another daemon won it; that one is just as good.
  server.on("error", (error) => {
    process.stderr.write(`nfet daemon: ${error.message}\n`);
    process.exit(error.code === "EADDRINUSE" ? 0 : 1);
  });
  child.once("exit", (code) => {
    process.stderr.write(`nfet bridge exited ${code}: ${stderr.trim()}\n`);
    shutdown(1);
  });
  for (const signal of ["SIGTERM", "SIGINT", "SIGHUP"]) process.on(signal, () => shutdown(0));

  await new Promise((resolvePromise) => server.listen(socket, resolvePromise));
  process.stdout.write(`${JSON.stringify({ event: "listening", socket, pid: process.pid })}\n`);
  armIdle();
}

main().catch((error) => {
  process.stderr.write(`${JSON.stringify({ event: "fatal", error: error.message })}\n`);
  process.exit(1);
});
