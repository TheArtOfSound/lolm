// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import { spawn } from "node:child_process";
import { isAbsolute, relative, resolve } from "node:path";

export const MAX_OUTPUT = 256 * 1024;
export const MAX_READ = 2 * 1024 * 1024;
export const SKIP_DIRECTORIES = new Set([".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__"]);

export function resolveUserPath(root, value = ".") {
  return resolve(root, String(value || "."));
}

export function isOutside(root, path) {
  const value = relative(resolve(root), resolve(path));
  return value.startsWith("..") || isAbsolute(value);
}

export function assertReadablePath(root, path, context = {}) {
  if (isOutside(root, path) && !context.allowOutside) {
    throw Object.assign(new Error(`Path is outside the trusted workspace: ${path}`), { code: "OUTSIDE_WORKSPACE" });
  }
}

export function pathClassification(root, values, { destructive = false } = {}) {
  const paths = values.filter(Boolean).map((value) => resolveUserPath(root, value));
  if (paths.some((path) => isOutside(root, path))) return { risk: "external", approval: "explicit", reason: "This action writes outside the trusted workspace." };
  if (destructive) return { risk: "write", approval: "confirm", reason: "This action deletes or overwrites workspace content." };
  return { risk: "write", approval: "confirm", reason: "This action changes workspace content." };
}

export function runFile(command, args = [], { cwd = process.cwd(), env = {}, timeoutMs = 120_000, input } = {}) {
  return new Promise((resolvePromise) => {
    const child = spawn(command, args, { cwd, env: { ...process.env, ...env }, stdio: [input === undefined ? "ignore" : "pipe", "pipe", "pipe"] });
    let stdout = "", stderr = "", timedOut = false, settled = false;
    const cap = (current, chunk) => `${current}${chunk}`.slice(-MAX_OUTPUT);
    child.stdout.on("data", (chunk) => { stdout = cap(stdout, chunk); });
    child.stderr.on("data", (chunk) => { stderr = cap(stderr, chunk); });
    if (input !== undefined) child.stdin.end(input);
    const timer = setTimeout(() => { timedOut = true; child.kill("SIGTERM"); }, Math.max(250, timeoutMs));
    const finish = (value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolvePromise(value);
    };
    child.on("close", (code, signal) => finish({ ok: code === 0 && !timedOut, exit_code: code, signal, timed_out: timedOut, stdout, stderr }));
    child.on("error", (error) => finish({ ok: false, error: error.message, code: error.code, timed_out: timedOut, stdout, stderr }));
  });
}

export function commandResult(result, label) {
  if (result.ok) return result;
  const message = result.timed_out ? `${label} timed out.` : result.error || result.stderr.trim() || `${label} exited with code ${result.exit_code}.`;
  throw Object.assign(new Error(message), { code: result.timed_out ? "COMMAND_TIMEOUT" : "COMMAND_FAILED", result });
}

export function objectSchema(properties = {}, required = []) {
  return { type: "object", properties, required, additionalProperties: false };
}

export function truncate(value, limit = MAX_OUTPUT) {
  const text = String(value ?? "");
  return text.length > limit ? `${text.slice(0, limit)}\n[truncated]` : text;
}
