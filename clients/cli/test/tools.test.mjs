// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createAgentToolbox } from "../lib/tools/index.mjs";
import { createToolRunner } from "../lib/tools.mjs";

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

test("fs.search works on a machine with no ripgrep installed", async () => {
  const root = await workspace("search");
  await mkdir(join(root, "pkg"), { recursive: true });
  await writeFile(join(root, "pkg", "app.py"), "import os\nNEEDLE = 1\n");
  await writeFile(join(root, "notes.md"), "NEEDLE in prose\n");
  const toolbox = createAgentToolbox({ cwd: root, mode: "trusted" });
  const search = async (args) => {
    const call = await toolbox.registry.execute({ name: "fs.search", arguments: args });
    assert.equal(call.ok, true, JSON.stringify(call.error));
    return call.result;
  };
  // Force the fallback rather than depending on whether this host has `rg`.
  const original = process.env.PATH;
  process.env.PATH = join(root, "no-such-bin");
  try {
    const all = await search({ query: "NEEDLE" });
    assert.equal(all.engine, "builtin");
    assert.deepEqual(all.matches.slice().sort(), ["notes.md:1:NEEDLE in prose", "pkg/app.py:2:NEEDLE = 1"]);
    assert.deepEqual((await search({ query: "NEEDLE", glob: "*.py" })).matches, ["pkg/app.py:2:NEEDLE = 1"]);
    assert.deepEqual((await search({ query: "NEEDLE = 1", fixed: true })).matches, ["pkg/app.py:2:NEEDLE = 1"]);
    assert.deepEqual((await search({ query: "absent" })).matches, []);
  } finally {
    process.env.PATH = original;
    await toolbox.close();
  }
});

test("agent runner removes provider tool-envelope metadata before strict validation", async () => {
  const root = await workspace("envelope");
  const runner = createToolRunner({ cwd: root, yes: true, mode: "trusted" });
  try {
    const result = await runner.execute({
      name: "fs__write",
      arguments: { path: "solution.py", content: "VALUE = 7\n", tool: "fs.write" },
    });
    assert.equal(result.ok, true);
    assert.equal(await readFile(join(root, "solution.py"), "utf8"), "VALUE = 7\n");
    const listed = await runner.execute({ name: "fs__list", arguments: { path: "", depth: 1 } });
    assert.equal(listed.ok, true);
    assert.ok(listed.entries.some((entry) => entry.path === "solution.py"));
  } finally { await runner.close(); }
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

test("fs.patch accepts text pasted back from an fs.inspect preview", async () => {
  const root = await workspace("patch-numbered");
  await writeFile(join(root, "app.py"), "def main():\n    return 1\n");
  const toolbox = createAgentToolbox({ cwd: root, mode: "trusted" });
  const preview = await toolbox.registry.execute({ name: "fs.inspect", arguments: { path: "app.py" } });
  assert.match(preview.result.preview, /^1: def main\(\):/);
  // The model pastes the numbered preview lines straight into old_text.
  const patch = await toolbox.registry.execute({
    name: "fs.patch",
    arguments: { path: "app.py", old_text: "2:     return 1", new_text: "    return 2" },
  });
  assert.equal(patch.ok, true, JSON.stringify(patch.error));
  assert.equal(await readFile(join(root, "app.py"), "utf8"), "def main():\n    return 2\n");
  // Genuinely absent text must still fail, and say why.
  const missing = await toolbox.registry.execute({
    name: "fs.patch",
    arguments: { path: "app.py", old_text: "nowhere", new_text: "x" },
  });
  assert.equal(missing.ok, false);
  assert.equal(missing.error.code, "PATCH_CONTEXT_MISSING");
  await toolbox.close();
});

test("fs.inspect pages a long file from an explicit start line", async () => {
  const root = await workspace("inspect-range");
  await writeFile(join(root, "long.txt"), Array.from({ length: 300 }, (_, i) => `line ${i + 1}`).join("\n"));
  const toolbox = createAgentToolbox({ cwd: root, mode: "trusted" });
  const page = await toolbox.registry.execute({ name: "fs.inspect", arguments: { path: "long.txt", line_start: 150, lines: 3 } });
  assert.equal(page.ok, true, JSON.stringify(page.error));
  assert.equal(page.result.preview, "150: line 150\n151: line 151\n152: line 152");
  assert.equal(page.result.total_lines, 300);
  assert.equal(page.result.truncated, true);
  await toolbox.close();
});
