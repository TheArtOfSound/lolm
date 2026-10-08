#!/usr/bin/env node
// Copyright (c) 2026 Qira LLC
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Narrow, outbound-tunnel-only stdio MCP adapter for LOLM.
// This adapter has NO arbitrary shell, filesystem, provider-key, deployment,
// memory, or code-execution tools. Never publish it as an unauthenticated HTTP service.
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { createInterface } from "node:readline";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CLI = resolve(ROOT, "clients/cli/bin/lolm.mjs");
const MAX_TEXT = 1400;
const MAX_OUTPUT = 80_000;
const MCP_VERSION = "2024-11-05";
const READ_ONLY = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false };
const TOOLS = [
  {
    name: "lolm_bridge_info",
    description: "Report which strictly allowlisted LOLM bridge functions are available. Does not read local files or invoke LOLM.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    annotations: READ_ONLY
  },
  {
    name: "lolm_diagnostics",
    description: "Run LOLM's fixed doctor --json command and return a minimal redacted readiness summary; no shell access or local paths.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    annotations: READ_ONLY
  },
  {
    name: "lolm_nfet_status",
    description: "Read the configured LOLM-NFET model/controller availability and daemon readiness, excluding local paths and credentials.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    annotations: READ_ONLY
  },
  {
    name: "lolm_nfet_check",
    description: "Evaluate a bounded text excerpt through the existing local LOLM NFET controller. Does not authorize tool execution or changes.",
    inputSchema: {
      type: "object",
      properties: { text: { type: "string", minLength: 1, maxLength: MAX_TEXT, description: "Non-secret plan/result text to evaluate (1-1400 characters)." } },
      required: ["text"], additionalProperties: false
    },
    annotations: { ...READ_ONLY, idempotentHint: false }
  }
];

function rpcResult(id, result) {
  process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id, result }) + "\n");
}
function rpcError(id, code, message) {
  process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id, error: { code, message } }) + "\n");
}
function textResult(data, isError = false) {
  return { content: [{ type: "text", text: JSON.stringify(data) }], isError };
}
function ownsOnly(args, allowed) {
  return args && typeof args === "object" && !Array.isArray(args) &&
    Object.keys(args).every(k => allowed.includes(k));
}
function prune(result) {
  // Strictly allowlist output fields. Never forward provider configuration,
  // environment variables, filesystem paths, API keys or raw diagnostics.
  const obj = result && typeof result === "object" ? result : {};
  const nfet = obj.nfet && typeof obj.nfet === "object" ? obj.nfet : {};
  const runtime = obj.runtime && typeof obj.runtime === "object" ? obj.runtime : {};
  const service = nfet.service && typeof nfet.service === "object" ? nfet.service : {};
  const decision = nfet.decision && typeof nfet.decision === "object" ? nfet.decision : {};
  const checks = Array.isArray(obj.checks) ? obj.checks.map(x => ({
    name: typeof x?.name === "string" ? x.name.slice(0, 90) : "",
    ok: x?.ok === true,
    optional: x?.optional === true
  })).slice(0, 45) : undefined;
  const out = {
    ok: obj.ok === true,
    provider: typeof runtime.provider === "string" ? runtime.provider.slice(0, 60) : undefined,
    model: typeof runtime.model === "string" ? runtime.model.slice(0, 100) : undefined,
    nfet: {
      available: nfet.available === true,
      enabled: nfet.enabled === true,
      checkpoint_available: nfet.checkpoint_available === true,
      profile: typeof nfet.profile === "string" ? nfet.profile.slice(0, 60) : undefined,
      backend: typeof nfet.backend === "string" ? nfet.backend.slice(0, 60) : undefined,
      service_running: service.running === true || service.active === true,
      decision: typeof nfet.decision === "string" ? nfet.decision.slice(0, 100) :
                typeof decision.label === "string" ? decision.label.slice(0, 100) : undefined,
      source: typeof nfet.source === "string" ? nfet.source.slice(0, 80) : undefined,
      reason: typeof nfet.reason === "string" ? nfet.reason.slice(0, 200) : undefined
    },
    checks
  };
  return out;
}
function runLolm(args, timeoutMs = 25_000) {
  return new Promise((resolvePromise, reject) => {
    if (!existsSync(CLI)) {
      reject(new Error("LOLM CLI was not found in this checkout."));
      return;
    }
    execFile(process.execPath, [CLI, "--json", ...args], {
      cwd: ROOT, timeout: timeoutMs, maxBuffer: MAX_OUTPUT, windowsHide: true,
      env: { ...process.env, LOLM_PLAIN: "1" }
    }, (error, stdout) => {
      try {
        if (stdout.length > MAX_OUTPUT) throw Error("LOLM output exceeded bridge limit.");
        const parsed = JSON.parse(stdout.trim());
        if (!parsed || typeof parsed !== "object") throw Error("Non-object LOLM reply.");
        resolvePromise({ output: prune(parsed), exitCode: error?.code ?? 0 });
      } catch {
        reject(new Error("LOLM diagnostic returned no valid bounded JSON result."));
      }
    });
  });
}
async function callTool(name, args) {
  const allowed = TOOLS.some(t => t.name === name);
  if (!allowed) return textResult({ error: "Unknown tool. Only the four read-only LOLM operations are exposed." }, true);
  if (!ownsOnly(args, name === "lolm_nfet_check" ? ["text"] : [])) {
    return textResult({ error: "Unexpected arguments." }, true);
  }
  if (name === "lolm_bridge_info") return textResult({
    service: "Qira LOLM narrow MCP bridge", protocol: "stdio",
    bridge_readonly: true, local_cli_present: existsSync(CLI),
    available_tools: TOOLS.map(x => x.name),
    remote_endpoint: false, shell_access: false, file_write_access: false
  });
  let argv, timeoutMs;
  if (name === "lolm_diagnostics") { argv = ["doctor"]; timeoutMs = 25_000; }
  if (name === "lolm_nfet_status") { argv = ["nfet", "status"]; timeoutMs = 25_000; }
  if (name === "lolm_nfet_check") {
    if (typeof args.text !== "string" || !args.text.trim() || args.text.length > MAX_TEXT) {
      return textResult({ error: "text must be 1-1400 characters." }, true);
    }
    // The -- delimiter ensures user text is passed as a literal argument,
    // never reinterpreted as a CLI flag, even when it starts with a dash.
    argv = ["nfet", "test", "--", args.text];
    timeoutMs = 90_000;
  }
  try {
    const result = await runLolm(argv, timeoutMs);
    return textResult(result.output, !result.output.ok || result.exitCode !== 0);
  } catch (err) {
    return textResult({ ok: false, error: err.message.slice(0, 170) }, true);
  }
}
async function handle(request) {
  if (!request || request.jsonrpc !== "2.0" || typeof request.method !== "string") return;
  const { id, method, params = {} } = request;
  if (id === undefined || id === null) return; // JSON-RPC notifications are one-way.
  if (method === "initialize") return rpcResult(id, {
    protocolVersion: typeof params.protocolVersion === "string" ? params.protocolVersion : MCP_VERSION,
    capabilities: { tools: { listChanged: false } },
    serverInfo: { name: "qira-lolm-readonly", version: "0.1.0" },
    instructions: "Allowlisted read-only LOLM diagnostics and NFET text checks only. Never pass secrets or sensitive user files."
  });
  if (method === "ping") return rpcResult(id, {});
  if (method === "tools/list") return rpcResult(id, { tools: TOOLS });
  if (method === "tools/call") {
    if (typeof params?.name !== "string") return rpcError(id, -32602, "Missing tool name.");
    return rpcResult(id, await callTool(params.name, params.arguments ?? {}));
  }
  return rpcError(id, -32601, "Method not found.");
}
const reader = createInterface({ input: process.stdin, crlfDelay: Infinity, terminal: false });
for await (const line of reader) {
  if (!line.trim()) continue;
  try { await handle(JSON.parse(line)); }
  catch { /* Malformed/untrusted messages never terminate the local adapter. */ }
}
