// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import test from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { createServer } from "node:http";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { createPdf } from "../lib/pdf.mjs";
import { PROVIDERS, resolveRuntime } from "../lib/config.mjs";

const exec = promisify(execFile);
const here = dirname(fileURLToPath(import.meta.url));
const bin = join(here, "..", "bin", "lolm.mjs");

async function temp(name) { return mkdtemp(join(tmpdir(), `lolm-${name}-`)); }

function startServer(handler) {
  return new Promise((resolvePromise) => {
    const server = createServer(async (req, res) => {
      let body = "";
      for await (const chunk of req) body += chunk;
      const payload = body ? JSON.parse(body) : {};
      const result = await handler(req, payload);
      res.writeHead(result.status || 200, { "content-type": "application/json" });
      res.end(JSON.stringify(result.body));
    });
    server.listen(0, "127.0.0.1", () => resolvePromise(server));
  });
}

function address(server) { return `http://127.0.0.1:${server.address().port}/v1`; }

test("provider catalog includes frontier, aggregator, local, and custom paths", () => {
  for (const name of ["openai", "anthropic", "google", "xai", "openrouter", "groq", "ollama", "custom"]) {
    assert.ok(PROVIDERS[name], name);
  }
  const runtime = resolveRuntime({ provider: "custom", providers: { custom: { baseUrl: "http://127.0.0.1:9999/v1", model: "mine", apiKey: "secret" } } });
  assert.equal(runtime.protocol, "openai");
  assert.equal(runtime.model, "mine");
  assert.equal(runtime.keySource, "config");
});

test("help and version describe the local open-source command surface", async () => {
  const help = await exec(process.execPath, [bin, "--help"], { env: { ...process.env, NO_COLOR: "1" } });
  assert.match(help.stdout, /local intelligence/i);
  assert.match(help.stdout, /lolm "update yourself"/);
  assert.match(help.stdout, /nfet status\|test/);
  const version = await exec(process.execPath, [bin, "--version"]);
  assert.equal(version.stdout.trim(), "1.0.0");
});

test("JSON providers output is one stable document", async () => {
  const root = await temp("providers");
  const result = await exec(process.execPath, [bin, "providers", "--json"], {
    env: { ...process.env, LOLM_CONFIG: join(root, "config.json") },
  });
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.ok, true);
  assert.ok(payload.providers.length >= 10);
  assert.equal(result.stderr, "");
});

test("OpenAI-compatible ask works without any LOLM hosted credential", async (t) => {
  const server = await startServer((_req, payload) => ({
    body: { choices: [{ message: { role: "assistant", content: `local answer from ${payload.model}` } }], usage: { total_tokens: 7 } },
  }));
  t.after(() => server.close());
  const root = await temp("ask");
  const result = await exec(process.execPath, [bin, "ask", "hello", "--provider", "custom", "--base-url", address(server), "--model", "test-model", "--api-key", "test", "--no-nfet", "--json"], {
    env: { ...process.env, LOLM_CONFIG: join(root, "config.json") },
  });
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.ok, true);
  assert.equal(payload.response, "local answer from test-model");
  assert.equal(payload.provider, "custom");
});

test("code tool loop writes locally and reports exact path", async (t) => {
  let calls = 0;
  const server = await startServer((_req, payload) => {
    calls++;
    if (!payload.messages.some((message) => message.role === "tool")) {
      return { body: { choices: [{ message: { role: "assistant", content: null, tool_calls: [{ id: "c1", type: "function", function: { name: "write_file", arguments: JSON.stringify({ path: "hello.html", content: "<!doctype html><title>Hello</title>" }) } }] } }] } };
    }
    return { body: { choices: [{ message: { role: "assistant", content: "Created hello.html locally." } }] } };
  });
  t.after(() => server.close());
  const root = await temp("code");
  const result = await exec(process.execPath, [bin, "code", "create hello.html", "--cwd", root, "--yes", "--provider", "custom", "--base-url", address(server), "--model", "test", "--api-key", "test", "--no-nfet", "--json"]);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.ok, true);
  assert.equal(payload.changes.length, 1);
  assert.equal(await readFile(join(root, "hello.html"), "utf8"), "<!doctype html><title>Hello</title>");
  assert.equal(calls, 2);
});

test("PDF writer creates a valid multi-object PDF", async () => {
  const root = await temp("pdf");
  const out = join(root, "report.pdf");
  const result = await createPdf("# Report\n\n- one\n- two\n\nA useful paragraph.", out);
  const body = await readFile(out);
  assert.equal(body.subarray(0, 5).toString(), "%PDF-");
  assert.match(body.toString("ascii"), /\/Type \/Catalog/);
  assert.ok(result.bytes > 500);
});

test("natural PDF request routes to local PDF creation", async (t) => {
  const server = await startServer(() => ({ body: { choices: [{ message: { role: "assistant", content: "# Local report\n\nMade by LOLM." } }] } }));
  t.after(() => server.close());
  const root = await temp("natural-pdf");
  const out = join(root, "made.pdf");
  const result = await exec(process.execPath, [bin, "make", "me", "a", "PDF", "about", "LOLM", "--out", out, "--yes", "--provider", "custom", "--base-url", address(server), "--model", "test", "--api-key", "test", "--no-nfet", "--json"]);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.kind, "pdf");
  assert.equal(payload.path, out);
  assert.equal((await readFile(out)).subarray(0, 5).toString(), "%PDF-");
});
