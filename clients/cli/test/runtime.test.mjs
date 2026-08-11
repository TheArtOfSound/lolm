// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ToolRegistry } from "../lib/runtime/registry.mjs";
import { PermissionPolicy, classifyCommand } from "../lib/runtime/permissions.mjs";
import { RunStore } from "../lib/runtime/runs.mjs";
import { ProcessManager } from "../lib/runtime/processes.mjs";

test("registry validates schemas, aliases provider names, and wraps results", async () => {
  const registry = new ToolRegistry({ permissionPolicy: new PermissionPolicy({ mode: "developer" }) });
  registry.register({
    name: "demo.echo",
    aliases: ["echo"],
    description: "Echo text.",
    risk: "read",
    inputSchema: { type: "object", required: ["text"], properties: { text: { type: "string", minLength: 1 } }, additionalProperties: false },
    execute: async ({ text }) => ({ text }),
  });
  assert.equal(registry.providerDefinitions()[0].function.name, "demo__echo");
  assert.deepEqual((await registry.execute({ name: "echo", arguments: { text: "hello" } })).result, { text: "hello" });
  const invalid = await registry.execute({ name: "demo__echo", arguments: {} });
  assert.equal(invalid.ok, false);
  assert.equal(invalid.error.code, "INVALID_TOOL_ARGUMENTS");
});

test("permission modes and command classification distinguish safe, remote, and catastrophic operations", async () => {
  assert.equal(classifyCommand("npm test").approval, "auto");
  assert.equal(classifyCommand("git push origin main").risk, "external");
  assert.equal(classifyCommand("rm -rf /").blocked, true);
  const registry = new ToolRegistry({ permissionPolicy: new PermissionPolicy({ mode: "readonly" }) });
  registry.register({ name: "demo.write", description: "Write.", risk: "write", inputSchema: { type: "object", additionalProperties: false }, execute: async () => true });
  const result = await registry.execute({ name: "demo.write", arguments: {} });
  assert.equal(result.error.code, "APPROVAL_REQUIRED");
});

test("run store persists redacted structured events and can resume", async () => {
  const root = await mkdtemp(join(tmpdir(), "lolm-runs-"));
  const store = new RunStore({ root });
  const run = await store.create({ prompt: "test", apiKey: "must-not-leak" });
  await store.append(run.id, { type: "provider.request", data: { token: "hidden", message: "ok" } });
  await store.finish(run.id, "failed", { error: "planned" });
  const shown = await store.show(run.id);
  assert.equal(shown.meta.status, "failed");
  assert.equal(shown.events.at(-2).data.token, "[redacted]");
  assert.equal((await store.list())[0].id, run.id);
  assert.equal((await store.resume(run.id)).meta.status, "running");
  const raw = await readFile(join(root, run.id, "events.jsonl"), "utf8");
  assert.doesNotMatch(raw, /must-not-leak|hidden/);
});

test("process manager tracks background process output and exit status", async () => {
  const manager = new ProcessManager();
  const started = manager.spawn([process.execPath, "-e", "setTimeout(() => console.log('ready'), 20)"], { shell: false });
  assert.match(started.id, /^proc_/);
  const completed = await manager.wait(started.id, 2_000);
  assert.equal(completed.status, "completed");
  assert.match(completed.stdout, /ready/);
  manager.close();
});
