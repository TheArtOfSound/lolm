// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createAgentToolbox } from "../lib/tools/index.mjs";

async function workspace(label) { return mkdtemp(join(tmpdir(), `lolm-tools-${label}-`)); }

test("agent toolbox exposes typed first-class tool families", async () => {
  const root = await workspace("catalog");
  const toolbox = createAgentToolbox({ cwd: root, mode: "trusted" });
  const names = toolbox.registry.list().map((tool) => tool.name);
  for (const name of ["terminal.exec", "terminal.spawn", "fs.patch", "git.status", "github.prList", "cloudflare.deploy", "browser.inspect", "computer.observe"]) assert.ok(names.includes(name), name);
  assert.ok(names.length >= 60);
  assert.ok(toolbox.registry.list().every((tool) => tool.inputSchema && tool.risk));
  await toolbox.close();
});

test("filesystem tools inspect, patch, and search exact local content", async () => {
  const root = await workspace("filesystem");
  await writeFile(join(root, "hello.txt"), "alpha\nbeta\n");
  const toolbox = createAgentToolbox({ cwd: root, mode: "trusted" });
  const patch = await toolbox.registry.execute({ name: "fs.patch", arguments: { path: "hello.txt", old_text: "beta", new_text: "gamma" } });
  assert.equal(patch.ok, true);
  assert.equal(await readFile(join(root, "hello.txt"), "utf8"), "alpha\ngamma\n");
  const search = await toolbox.registry.execute({ name: "fs.search", arguments: { query: "gamma" } });
  assert.match(search.result.matches[0], /hello\.txt:2:gamma/);
  const inspect = await toolbox.registry.execute({ name: "fs.inspect", arguments: { path: "hello.txt" } });
  assert.match(inspect.result.preview, /2: gamma/);
  await toolbox.close();
});

test("terminal tools execute foreground commands and preserve background process IDs", async () => {
  const root = await workspace("terminal");
  const toolbox = createAgentToolbox({ cwd: root, mode: "trusted" });
  const foreground = await toolbox.registry.execute({ name: "terminal.exec", arguments: { command: `${JSON.stringify(process.execPath)} -e "console.log('verified')"` } });
  assert.equal(foreground.ok, true);
  assert.match(foreground.result.stdout, /verified/);
  const background = await toolbox.registry.execute({ name: "terminal.spawn", arguments: { command: `${JSON.stringify(process.execPath)} -e "setTimeout(() => {}, 5000)"` } });
  assert.match(background.result.id, /^proc_/);
  assert.equal((await toolbox.registry.execute({ name: "terminal.status", arguments: { process_id: background.result.id } })).result.status, "running");
  await toolbox.registry.execute({ name: "terminal.kill", arguments: { process_id: background.result.id } });
  await toolbox.close();
});

test("filesystem reads outside the trusted workspace are denied by default", async () => {
  const root = await workspace("scope");
  const toolbox = createAgentToolbox({ cwd: root, mode: "trusted" });
  const result = await toolbox.registry.execute({ name: "fs.read", arguments: { path: join(tmpdir(), "outside.txt") } });
  assert.equal(result.ok, false);
  assert.equal(result.error.code, "OUTSIDE_WORKSPACE");
  await toolbox.close();
});

test("enabled local plugins contribute typed tools through the registry", async () => {
  const root = await workspace("plugin");
  const plugin = join(root, "plugin"); await mkdir(plugin);
  await writeFile(join(plugin, "lolm-plugin.json"), JSON.stringify({ name: "test-plugin", version: "1.0.0", main: "index.mjs", enabled: true }));
  await writeFile(join(plugin, "index.mjs"), `export function register(registry) { registry.register({ name: "test.echo", description: "Echo plugin text.", risk: "read", inputSchema: { type: "object", required: ["text"], properties: { text: { type: "string" } }, additionalProperties: false }, execute: async ({ text }) => ({ text }) }); }`);
  const previous = process.env.LOLM_PLUGIN_PATH; process.env.LOLM_PLUGIN_PATH = plugin;
  const toolbox = createAgentToolbox({ cwd: root, mode: "trusted" });
  try {
    const status = await toolbox.loadExtensions();
    assert.equal(status.plugins[0].loaded, true);
    assert.deepEqual((await toolbox.registry.execute({ name: "test.echo", arguments: { text: "hello" } })).result, { text: "hello" });
  } finally {
    if (previous === undefined) delete process.env.LOLM_PLUGIN_PATH; else process.env.LOLM_PLUGIN_PATH = previous;
    await toolbox.close();
  }
});

test("enabled MCP servers contribute callable tools through the same registry", async () => {
  const root = await workspace("mcp");
  const server = join(root, "server.mjs");
  await writeFile(server, `import readline from "node:readline";
const rl = readline.createInterface({ input: process.stdin });
const send = (value) => process.stdout.write(JSON.stringify(value) + "\\n");
rl.on("line", (line) => { const message = JSON.parse(line); if (message.id == null) return;
  if (message.method === "initialize") send({ jsonrpc: "2.0", id: message.id, result: { protocolVersion: "2024-11-05", capabilities: { tools: {} }, serverInfo: { name: "test", version: "1" } } });
  else if (message.method === "tools/list") send({ jsonrpc: "2.0", id: message.id, result: { tools: [{ name: "echo", description: "Echo MCP text.", inputSchema: { type: "object", required: ["text"], properties: { text: { type: "string" } }, additionalProperties: false } }] } });
  else if (message.method === "tools/call") send({ jsonrpc: "2.0", id: message.id, result: { content: [{ type: "text", text: message.params.arguments.text }] } });
});`);
  await writeFile(join(root, ".mcp.json"), JSON.stringify({ mcpServers: { test: { enabled: true, command: process.execPath, args: [server], risks: { echo: "read" } } } }));
  const toolbox = createAgentToolbox({ cwd: root, mode: "trusted" });
  try {
    const status = await toolbox.loadExtensions();
    assert.equal(status.mcp[0].connected, true);
    const result = await toolbox.registry.execute({ name: "mcp.test_echo", arguments: { text: "from mcp" } });
    assert.equal(result.result.content[0].text, "from mcp");
  } finally { await toolbox.close(); }
});
