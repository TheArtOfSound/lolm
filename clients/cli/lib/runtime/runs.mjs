// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import { appendFile, mkdir, readFile, readdir, rename, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { randomUUID } from "node:crypto";

const SECRET_KEY = /(?:api[-_]?key|authorization|cookie|password|secret|token)/i;
const MAX_EVENT_STRING = 64 * 1024;

function redact(value, key = "") {
  if (SECRET_KEY.test(key)) return "[redacted]";
  if (typeof value === "string") return value.length > MAX_EVENT_STRING ? `${value.slice(0, MAX_EVENT_STRING)}\n[truncated]` : value;
  if (Array.isArray(value)) return value.map((item) => redact(item));
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([childKey, item]) => [childKey, redact(item, childKey)]));
  return value;
}

async function atomicJson(path, value) {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  await rename(temporary, path);
}

function runId() {
  return `run_${new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14)}_${randomUUID().slice(0, 8)}`;
}

export class RunStore {
  constructor({ root = process.env.LOLM_RUNS_DIR || join(homedir(), ".lolm", "runs") } = {}) {
    this.root = root;
  }

  paths(id) {
    const directory = join(this.root, id);
    return { directory, meta: join(directory, "run.json"), events: join(directory, "events.jsonl") };
  }

  async create(input = {}) {
    const id = runId();
    const now = new Date().toISOString();
    const meta = redact({
      id,
      status: "running",
      created_at: now,
      updated_at: now,
      prompt: input.prompt || "",
      command: input.command || null,
      cwd: input.cwd || process.cwd(),
      mode: input.mode || "standard",
      provider: input.provider || null,
      model: input.model || null,
    });
    const paths = this.paths(id);
    await mkdir(paths.directory, { recursive: true, mode: 0o700 });
    await atomicJson(paths.meta, meta);
    await this.append(id, { type: "run.started", data: meta });
    return meta;
  }

  async append(id, event) {
    const paths = this.paths(id);
    const row = redact({ id: randomUUID(), at: new Date().toISOString(), ...event });
    await mkdir(paths.directory, { recursive: true, mode: 0o700 });
    await appendFile(paths.events, `${JSON.stringify(row)}\n`, { mode: 0o600 });
    return row;
  }

  async update(id, changes) {
    const current = await this.readMeta(id);
    const next = redact({ ...current, ...changes, id, updated_at: new Date().toISOString() });
    await atomicJson(this.paths(id).meta, next);
    return next;
  }

  async finish(id, status = "completed", result = {}) {
    const meta = await this.update(id, { status, finished_at: new Date().toISOString(), ...result });
    await this.append(id, { type: `run.${status}`, data: result });
    return meta;
  }

  async readMeta(id) {
    return JSON.parse(await readFile(this.paths(id).meta, "utf8"));
  }

  async show(id) {
    const meta = await this.readMeta(id);
    let events = [];
    try {
      const text = await readFile(this.paths(id).events, "utf8");
      events = text.split("\n").filter(Boolean).map((line) => JSON.parse(line));
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
    return { meta, events };
  }

  async list({ limit = 20 } = {}) {
    await mkdir(this.root, { recursive: true, mode: 0o700 });
    const entries = await readdir(this.root, { withFileTypes: true });
    const rows = [];
    for (const entry of entries) {
      if (!entry.isDirectory() || !entry.name.startsWith("run_")) continue;
      try { rows.push(await this.readMeta(entry.name)); } catch {}
    }
    return rows.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))).slice(0, limit);
  }

  async resume(id) {
    const run = await this.show(id);
    if (run.meta.status === "running") return run;
    const previousStatus = run.meta.status;
    run.meta = await this.update(id, { status: "running", resumed_at: new Date().toISOString() });
    await this.append(id, { type: "run.resumed", data: { previous_status: previousStatus } });
    return run;
  }

  eventSink(id) {
    return (event) => this.append(id, { type: event.type, data: event });
  }
}
