// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

function safe(value) { return String(value).toLowerCase().replace(/[^a-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "tool"; }

export async function readMcpConfig(root) {
  const merged = { mcpServers: {} };
  for (const path of [join(homedir(), ".lolm", "mcp.json"), join(resolve(root), ".mcp.json")]) {
    try { Object.assign(merged.mcpServers, JSON.parse(await readFile(path, "utf8")).mcpServers || {}); } catch {}
  }
  return merged;
}

class McpClient {
  constructor(name, spec, root) {
    this.name = name; this.spec = spec; this.root = root; this.child = null; this.buffer = ""; this.nextId = 1; this.pending = new Map(); this.stderr = "";
  }

  async start() {
    if (this.child) return;
    this.child = spawn(this.spec.command, this.spec.args || [], { cwd: this.spec.cwd ? resolve(this.root, this.spec.cwd) : this.root, env: { ...process.env, ...(this.spec.env || {}) }, stdio: ["pipe", "pipe", "pipe"] });
    this.child.stdout.on("data", (chunk) => this.consume(chunk.toString()));
    this.child.stderr.on("data", (chunk) => { this.stderr = `${this.stderr}${chunk}`.slice(-32_000); });
    this.child.on("exit", (code) => { for (const { reject } of this.pending.values()) reject(Object.assign(new Error(`MCP server ${this.name} exited ${code}: ${this.stderr.trim()}`), { code: "MCP_SERVER_EXITED" })); this.pending.clear(); this.child = null; });
    await this.request("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "lolm-cli", version: "1.2.0" } });
    this.notify("notifications/initialized", {});
  }

  consume(text) {
    this.buffer += text;
    while (true) {
      const index = this.buffer.indexOf("\n"); if (index < 0) break;
      const line = this.buffer.slice(0, index).trim(); this.buffer = this.buffer.slice(index + 1); if (!line) continue;
      let message; try { message = JSON.parse(line); } catch { continue; }
      if (message.id == null || !this.pending.has(message.id)) continue;
      const pending = this.pending.get(message.id); this.pending.delete(message.id); clearTimeout(pending.timer);
      if (message.error) pending.reject(Object.assign(new Error(message.error.message || "MCP request failed."), { code: "MCP_ERROR", data: message.error.data }));
      else pending.resolve(message.result);
    }
  }

  request(method, params, timeoutMs = 30_000) {
    return new Promise((resolvePromise, reject) => {
      const id = this.nextId++;
      const timer = setTimeout(() => { this.pending.delete(id); reject(Object.assign(new Error(`MCP ${this.name} timed out during ${method}.`), { code: "MCP_TIMEOUT" })); }, timeoutMs);
      this.pending.set(id, { resolve: resolvePromise, reject, timer });
      this.child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
    });
  }

  notify(method, params) { this.child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method, params })}\n`); }
  close() { if (this.child) this.child.kill("SIGTERM"); this.child = null; }
}

export class McpManager {
  constructor({ root, registry }) { this.root = resolve(root); this.registry = registry; this.clients = []; this.status = []; }

  async connectEnabled({ includeDisabled = false } = {}) {
    const config = await readMcpConfig(this.root); const results = [];
    for (const [name, spec] of Object.entries(config.mcpServers || {})) {
      if (spec.enabled !== true && !includeDisabled) { results.push({ name, enabled: false, connected: false }); continue; }
      const client = new McpClient(name, spec, this.root);
      try {
        await client.start(); const listed = await client.request("tools/list", {}); const tools = listed?.tools || [];
        for (const remote of tools) {
          const canonical = `mcp.${safe(name)}_${safe(remote.name)}`;
          const risk = spec.risks?.[remote.name] || "external";
          this.registry.register({
            name: canonical, description: `${remote.description || remote.name} [MCP server: ${name}]`, risk, approval: risk === "read" ? "auto" : "confirm",
            inputSchema: remote.inputSchema || { type: "object" },
            execute: async (args) => client.request("tools/call", { name: remote.name, arguments: args }, Number(spec.timeout_ms || 120_000)),
          });
        }
        this.clients.push(client); results.push({ name, enabled: true, connected: true, tools: tools.map((tool) => tool.name) });
      } catch (error) { client.close(); results.push({ name, enabled: true, connected: false, error: error.message }); }
    }
    this.status = results; return results;
  }

  close() { for (const client of this.clients) client.close(); this.clients = []; }
}
