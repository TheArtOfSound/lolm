// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Persistent bridge client for real local LOLM-NFET telemetry. */
import { access } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import readline from "node:readline";

const here = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(here, "../../..");

async function exists(path) {
  try { await access(path); return true; } catch { return false; }
}

export async function findNfetHome(config = {}) {
  const candidates = [
    process.env.LOLM_HOME,
    config.nfet?.home,
    packageRoot,
    process.cwd(),
    join(homedir(), "Documents", "CLI", "lolm"),
    join(homedir(), "code", "lolm"),
  ].filter(Boolean).map((value) => resolve(String(value)));
  for (const root of [...new Set(candidates)]) {
    if (await exists(join(root, "lolm", "nfet_policy.py")) && await exists(join(root, "local_ui", "server.py"))) {
      return root;
    }
  }
  return "";
}

export async function inspectNfet(config = {}) {
  const home = await findNfetHome(config);
  const nfet = config.nfet || {};
  const checkpoint = resolve(home || process.cwd(), nfet.checkpoint || "runs/nfet_controller/live_qwen4b.pt");
  const python = home && await exists(join(home, ".venv", "bin", "python"))
    ? join(home, ".venv", "bin", "python")
    : process.env.LOLM_PYTHON || "python3";
  return {
    enabled: nfet.enabled !== false,
    home,
    python,
    profile: nfet.profile || "qwen3_4b_lab",
    device: nfet.device || (process.platform === "darwin" ? "mps" : "auto"),
    checkpoint,
    checkpoint_available: await exists(checkpoint),
    backend: nfet.backend || "gru_debug",
    available: Boolean(home) && await exists(checkpoint),
  };
}

export class NfetMonitor {
  constructor(config = {}, { onStatus = () => {} } = {}) {
    this.config = config;
    this.onStatus = onStatus;
    this.child = null;
    this.lines = null;
    this.queue = [];
    this.ready = null;
    this.info = null;
  }

  async start() {
    if (this.ready) return this.ready;
    this.ready = this.#start();
    return this.ready;
  }

  async #start() {
    this.info = await inspectNfet(this.config);
    if (!this.info.enabled) return { available: false, reason: "disabled" };
    if (!this.info.home) return { available: false, reason: "LOLM source checkout not found; set LOLM_HOME" };
    if (!this.info.checkpoint_available) return { available: false, reason: `NFET checkpoint not found: ${this.info.checkpoint}` };
    const bridge = join(here, "nfet_bridge.py");
    const args = [bridge, "--root", this.info.home, "--profile", this.info.profile,
      "--device", this.info.device, "--checkpoint", this.info.checkpoint, "--backend", this.info.backend];
    this.onStatus(`Loading ${this.info.profile} NFET monitor on ${this.info.device}…`);
    this.child = spawn(this.info.python, args, {
      cwd: this.info.home,
      env: { ...process.env, PYTHONPATH: [this.info.home, process.env.PYTHONPATH].filter(Boolean).join(":"), LOLM_TEST_NO_BOOT: "1" },
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stderr = "";
    this.child.stderr.setEncoding("utf8");
    this.child.stderr.on("data", (chunk) => { stderr = `${stderr}${chunk}`.slice(-4000); });
    this.lines = readline.createInterface({ input: this.child.stdout });
    this.lines.on("line", (line) => {
      let payload;
      try { payload = JSON.parse(line); } catch { return; }
      const waiter = this.queue.shift();
      if (waiter) waiter.resolve(payload);
    });
    const fatal = new Promise((_, reject) => {
      this.child.once("error", reject);
      this.child.once("exit", (code) => reject(new Error(`NFET bridge exited ${code}: ${stderr.trim()}`)));
    });
    const ready = await Promise.race([this.#next(), fatal]);
    if (ready.event !== "ready") throw new Error(ready.error || "NFET bridge did not become ready");
    this.onStatus(`NFET ready · ${ready.profile} · trained head ${ready.head_trained ? "on" : "off"}`);
    return { available: true, ...ready };
  }

  #next() {
    return new Promise((resolvePromise, reject) => this.queue.push({ resolve: resolvePromise, reject }));
  }

  async decide(text, { reset = false, checkpoint = "work", verified = false, reuse = false, maxTokens = 1024 } = {}) {
    const ready = await this.start();
    if (!ready.available) return { available: false, reason: ready.reason };
    const response = this.#next();
    this.child.stdin.write(`${JSON.stringify({ op: "decide", text, reset, checkpoint, verified, reuse, max_tokens: maxTokens })}\n`);
    const result = await response;
    if (result.event === "error" || result.event === "fatal") throw new Error(result.error);
    return { available: true, ...result };
  }

  async close() {
    if (!this.child) return;
    try { this.child.stdin.write('{"op":"close"}\n'); } catch {}
    this.child.kill("SIGTERM");
    this.lines?.close();
    this.child = null;
  }
}
