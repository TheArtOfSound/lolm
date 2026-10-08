// Copyright (c) 2026 Qira LLC
// SPDX-License-Identifier: AGPL-3.0-or-later
import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const BRIDGE = resolve(dirname(fileURLToPath(import.meta.url)), "chatgpt-readonly-mcp.mjs");
function session() {
  const child = spawn(process.execPath, [BRIDGE], { stdio: ["pipe", "pipe", "pipe"] });
  const lines = createInterface({ input: child.stdout });
  const pending = new Map();
  lines.on("line", line => {
    let msg; try { msg = JSON.parse(line); } catch { return; }
    const res = pending.get(msg.id);
    if (res) { pending.delete(msg.id); res(msg); }
  });
  let id = 0;
  function call(method, params = {}) {
    return new Promise((resolvePromise, reject) => {
      const n = ++id;
      const deadline = setTimeout(() => { pending.delete(n); reject(new Error("Timeout " + method)); }, 7000);
      pending.set(n, msg => { clearTimeout(deadline); resolvePromise(msg); });
      child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: n, method, params }) + "\n");
    });
  }
  return { child, call, close: () => { child.stdin.end(); child.kill(); lines.close(); } };
}
test("MCP initializes, exposes exactly four restricted functions", async () => {
  const s = session();
  try {
    const init = await s.call("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "test", version: "1.0" } });
    assert.equal(init.result?.serverInfo?.name, "qira-lolm-readonly");
    assert.equal(init.result?.protocolVersion, "2024-11-05");
    const listed = await s.call("tools/list");
    const names = listed.result.tools.map(t => t.name);
    assert.deepEqual(names, ["lolm_bridge_info", "lolm_diagnostics", "lolm_nfet_status", "lolm_nfet_check"]);
    for (const tool of listed.result.tools) {
      assert.equal(tool.annotations.destructiveHint, false);
      assert.equal(tool.annotations.readOnlyHint, true);
      assert.ok(!/shell|exec|deploy|file_write|memory_add/.test(tool.name));
    }
  } finally { s.close(); }
});
test("MCP rejects unknown methods and arbitrary local operations", async () => {
  const s = session();
  try {
    const no = await s.call("tools/call", { name: "shell.execute", arguments: { command: "echo unsafe" } });
    assert.equal(no.result.isError, true);
    const info = await s.call("tools/call", { name: "lolm_bridge_info", arguments: {} });
    assert.equal(info.result.isError, false);
    const parsed = JSON.parse(info.result.content[0].text);
    assert.equal(parsed.bridge_readonly, true);
    assert.equal(parsed.shell_access, false);
    assert.equal(parsed.file_write_access, false);
    const invalid = await s.call("tools/call", { name: "lolm_nfet_status", arguments: { command: "ls" } });
    assert.equal(invalid.result.isError, true);
    const badText = await s.call("tools/call", { name: "lolm_nfet_check", arguments: { text: "x".repeat(1401) } });
    assert.equal(badText.result.isError, true);
    const noMethod = await s.call("terminal/exec", { command: "echo unsafe" });
    assert.equal(noMethod.error.code, -32601);
  } finally { s.close(); }
});
