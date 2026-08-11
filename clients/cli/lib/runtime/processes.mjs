// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import { spawn as spawnChild } from "node:child_process";
import { randomUUID } from "node:crypto";

const MAX_OUTPUT = 256 * 1024;

function capped(current, addition) {
  const value = `${current}${addition}`;
  return value.length > MAX_OUTPUT ? value.slice(-MAX_OUTPUT) : value;
}

function processView(record) {
  return {
    id: record.id,
    command: record.command,
    cwd: record.cwd,
    status: record.status,
    pid: record.child.pid || null,
    started_at: record.startedAt,
    finished_at: record.finishedAt || null,
    exit_code: record.exitCode,
    signal: record.signal,
    stdout: record.stdout,
    stderr: record.stderr,
  };
}

export class ProcessManager {
  constructor() {
    this.processes = new Map();
  }

  spawn(command, { cwd = process.cwd(), env = {}, shell = true } = {}) {
    const id = `proc_${randomUUID().slice(0, 10)}`;
    const child = shell
      ? spawnChild(process.platform === "win32" ? "cmd.exe" : (process.env.SHELL || "/bin/sh"), process.platform === "win32" ? ["/d", "/s", "/c", command] : ["-lc", command], { cwd, env: { ...process.env, ...env }, stdio: "pipe" })
      : spawnChild(command[0], command.slice(1), { cwd, env: { ...process.env, ...env }, stdio: "pipe" });
    const record = {
      id, child, command: Array.isArray(command) ? command.join(" ") : command, cwd,
      status: "running", startedAt: new Date().toISOString(), finishedAt: null,
      exitCode: null, signal: null, stdout: "", stderr: "",
    };
    this.processes.set(id, record);
    child.stdout.on("data", (data) => { record.stdout = capped(record.stdout, data.toString()); });
    child.stderr.on("data", (data) => { record.stderr = capped(record.stderr, data.toString()); });
    child.on("error", (error) => { record.stderr = capped(record.stderr, `${error.message}\n`); });
    child.on("close", (code, signal) => {
      record.status = code === 0 ? "completed" : "failed";
      record.exitCode = code;
      record.signal = signal;
      record.finishedAt = new Date().toISOString();
    });
    return processView(record);
  }

  status(id) {
    const record = this.processes.get(id);
    if (!record) throw Object.assign(new Error(`Unknown process: ${id}`), { code: "UNKNOWN_PROCESS" });
    return processView(record);
  }

  list() {
    return [...this.processes.values()].map(processView);
  }

  stdin(id, input, { close = false } = {}) {
    const record = this.processes.get(id);
    if (!record) throw Object.assign(new Error(`Unknown process: ${id}`), { code: "UNKNOWN_PROCESS" });
    if (record.status !== "running" || !record.child.stdin.writable) throw Object.assign(new Error(`Process ${id} is not accepting input.`), { code: "PROCESS_NOT_RUNNING" });
    record.child.stdin.write(input);
    if (close) record.child.stdin.end();
    return processView(record);
  }

  kill(id, signal = "SIGTERM") {
    const record = this.processes.get(id);
    if (!record) throw Object.assign(new Error(`Unknown process: ${id}`), { code: "UNKNOWN_PROCESS" });
    if (record.status === "running") record.child.kill(signal);
    return processView(record);
  }

  async wait(id, timeoutMs = 30_000) {
    const record = this.processes.get(id);
    if (!record) throw Object.assign(new Error(`Unknown process: ${id}`), { code: "UNKNOWN_PROCESS" });
    if (record.status !== "running") return processView(record);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(Object.assign(new Error(`Process ${id} timed out.`), { code: "PROCESS_TIMEOUT" })), timeoutMs);
      record.child.once("close", () => { clearTimeout(timer); resolve(); });
    });
    return processView(record);
  }

  close() {
    for (const record of this.processes.values()) if (record.status === "running") record.child.kill("SIGTERM");
  }
}
