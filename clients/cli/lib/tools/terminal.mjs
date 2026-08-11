// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import { delimiter } from "node:path";
import { access } from "node:fs/promises";
import { constants } from "node:fs";
import { classifyCommand } from "../runtime/permissions.mjs";
import { objectSchema, resolveUserPath } from "./shared.mjs";

const SECRET = /(?:api[-_]?key|authorization|cookie|password|secret|token)/i;

function commandSchema(extra = {}) {
  return objectSchema({
    command: { type: "string", minLength: 1, maxLength: 32_000 },
    cwd: { type: "string" },
    env: { type: "object" },
    ...extra,
  }, ["command"]);
}

export function registerTerminalTools(registry, { root, processes, onAction = () => {} }) {
  registry.register({
    name: "terminal.exec", aliases: ["run_command"], description: "Run a foreground shell command and return its exit code, output, signal, and timeout state.", risk: "execute",
    classify: ({ command }) => classifyCommand(command),
    inputSchema: commandSchema({ timeout_ms: { type: "integer", minimum: 250, maximum: 600_000 } }),
    execute: async ({ command, cwd, env, timeout_ms = 120_000 }, context) => {
      const directory = resolveUserPath(root, cwd || ".");
      onAction(`${context.dryRun ? "Would run" : "Running"} ${command}`);
      const started = processes.spawn(command, { cwd: directory, env });
      try { return await processes.wait(started.id, timeout_ms); }
      catch (error) {
        processes.kill(started.id);
        return { ...processes.status(started.id), timed_out: true, error: error.message };
      }
    },
  });
  registry.register({
    name: "terminal.spawn", description: "Start a long-running command and return a persistent process ID for later status, input, or termination.", risk: "execute",
    classify: ({ command }) => {
      const base = classifyCommand(command);
      return base.approval === "auto" ? { ...base, approval: "confirm", reason: "Starting a long-running process requires confirmation." } : base;
    },
    inputSchema: commandSchema(),
    execute: async ({ command, cwd, env }) => processes.spawn(command, { cwd: resolveUserPath(root, cwd || "."), env }),
  });
  registry.register({
    name: "terminal.status", description: "Inspect one background process or list all processes started by this LOLM session.", risk: "read",
    inputSchema: objectSchema({ process_id: { type: "string" } }),
    execute: async ({ process_id }) => process_id ? processes.status(process_id) : { processes: processes.list() },
  });
  registry.register({
    name: "terminal.kill", description: "Stop a background process by its LOLM process ID.", risk: "execute", approval: "confirm",
    inputSchema: objectSchema({ process_id: { type: "string", minLength: 1 }, signal: { type: "string", enum: ["SIGTERM", "SIGINT", "SIGKILL"] } }, ["process_id"]),
    execute: async ({ process_id, signal = "SIGTERM" }) => processes.kill(process_id, signal),
  });
  registry.register({
    name: "terminal.stdin", description: "Send text to a running process and optionally close its standard input.", risk: "execute", approval: "confirm",
    inputSchema: objectSchema({ process_id: { type: "string", minLength: 1 }, input: { type: "string" }, close: { type: "boolean" } }, ["process_id", "input"]),
    execute: async ({ process_id, input, close = false }) => processes.stdin(process_id, input, { close }),
  });
  registry.register({
    name: "terminal.which", description: "Find an executable on PATH without invoking a shell.", risk: "read",
    inputSchema: objectSchema({ command: { type: "string", minLength: 1 } }, ["command"]),
    execute: async ({ command }) => {
      const extensions = process.platform === "win32" ? String(process.env.PATHEXT || ".EXE;.CMD;.BAT").split(";") : [""];
      for (const directory of String(process.env.PATH || "").split(delimiter)) {
        for (const extension of extensions) {
          const candidate = resolveUserPath(directory, `${command}${extension}`);
          try { await access(candidate, constants.X_OK); return { command, path: candidate }; } catch {}
        }
      }
      return { command, path: null };
    },
  });
  registry.register({
    name: "terminal.env", description: "Inspect selected environment variables with secret-like values redacted.", risk: "read",
    inputSchema: objectSchema({ names: { type: "array", items: { type: "string" }, maxItems: 100 } }),
    execute: async ({ names }) => {
      const selected = names?.length ? names : Object.keys(process.env).sort();
      return { env: Object.fromEntries(selected.map((name) => [name, SECRET.test(name) ? "[redacted]" : (process.env[name] ?? null)])) };
    },
  });
  registry.register({
    name: "terminal.cwd", description: "Return the trusted workspace and the agent's current working directory.", risk: "read",
    inputSchema: objectSchema(), execute: async () => ({ cwd: root, process_cwd: process.cwd() }),
  });
}
