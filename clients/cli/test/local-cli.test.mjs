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
import { documentIssues, isLolmAgentComparison } from "../lib/agent.mjs";
import { createPdf } from "../lib/pdf.mjs";
import { PROVIDERS, resolveRuntime } from "../lib/config.mjs";
import { chat } from "../lib/providers.mjs";
import { isRetryPhrase } from "../lib/session.mjs";
import { nfetSummary, stripAnsi } from "../lib/tui.mjs";

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
      res.writeHead(result.status || 200, { "content-type": "application/json", ...(result.headers || {}) });
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
  assert.match(help.stdout, /tools \[group\]/);
  assert.match(help.stdout, /run show\|resume/);
  const version = await exec(process.execPath, [bin, "--version"]);
  assert.equal(version.stdout.trim(), "1.2.1");
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
  const result = await exec(process.execPath, [bin, "ask", "tell me the selected model", "--provider", "custom", "--base-url", address(server), "--model", "test-model", "--api-key", "test", "--no-nfet", "--json"], {
    env: { ...process.env, LOLM_CONFIG: join(root, "config.json"), LOLM_LAST_TASK: join(root, "last-task.json") },
  });
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.ok, true);
  assert.equal(payload.response, "local answer from test-model");
  assert.equal(payload.provider, "custom");
  assert.match(payload.run_id, /^run_/);
  const runs = await exec(process.execPath, [bin, "runs", "--json"], { env: { ...process.env, LOLM_LAST_TASK: join(root, "last-task.json") } });
  assert.equal(JSON.parse(runs.stdout).runs[0].id, payload.run_id);
  const shown = await exec(process.execPath, [bin, "run", "show", payload.run_id, "--json"], { env: { ...process.env, LOLM_LAST_TASK: join(root, "last-task.json") } });
  assert.ok(JSON.parse(shown.stdout).run.events.some((event) => event.type === "provider.responded"));
});

test("OpenAI-compatible providers honor 429 retry-after without losing the task", async (t) => {
  let calls = 0;
  const server = await startServer(() => {
    calls++;
    if (calls === 1) return { status: 429, headers: { "retry-after": "0" }, body: { error: { message: "slow down" } } };
    return { body: { choices: [{ message: { role: "assistant", content: "recovered" } }] } };
  });
  t.after(() => server.close());
  const result = await chat({
    protocol: "openai", keyRequired: true, apiKey: "test", baseUrl: address(server), model: "test", timeoutMs: 1_000,
  }, [{ role: "user", content: "hello" }]);
  assert.equal(result.content, "recovered");
  assert.equal(calls, 2);
});

test("tools command exposes schemas and risk classes without loading a provider", async () => {
  const root = await temp("tools-command");
  const list = await exec(process.execPath, [bin, "tools", "--json"], { env: { ...process.env, LOLM_CONFIG: join(root, "missing.json") } });
  const payload = JSON.parse(list.stdout);
  assert.ok(payload.count >= 60);
  assert.ok(payload.tools.some((tool) => tool.name === "terminal.spawn" && tool.risk === "execute"));
  const inspect = await exec(process.execPath, [bin, "tools", "inspect", "fs.patch", "--json"], { env: { ...process.env, LOLM_CONFIG: join(root, "missing.json") } });
  assert.deepEqual(JSON.parse(inspect.stdout).tool.inputSchema.required, ["path", "old_text", "new_text"]);
});

test("setup validates a provider before saving and exits without unsettled top-level await", async (t) => {
  const server = await startServer(() => ({ body: { data: [{ id: "test-model" }] } }));
  t.after(() => server.close());
  const root = await temp("setup");
  const configPath = join(root, "config.json");
  const result = await exec(process.execPath, [bin, "setup", "custom", "--base-url", address(server), "--model", "test-model", "--api-key", "test-secret", "--json"], {
    env: { ...process.env, LOLM_CONFIG: configPath, LOLM_DISABLE_NATIVE_SECRETS: "1" },
  });
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.ok, true);
  assert.equal(payload.validated, true);
  assert.doesNotMatch(result.stderr, /unsettled top-level await/i);
  const saved = JSON.parse(await readFile(configPath, "utf8"));
  assert.equal(saved.provider, "custom");
  assert.equal(saved.providers.custom.model, "test-model");
});

test("setup refuses invalid credentials without changing configuration", async (t) => {
  const server = await startServer(() => ({ status: 401, body: { error: { message: "invalid credential" } } }));
  t.after(() => server.close());
  const root = await temp("setup-invalid");
  const configPath = join(root, "config.json");
  const result = await exec(process.execPath, [bin, "setup", "custom", "--base-url", address(server), "--model", "test-model", "--api-key", "bad-secret", "--json"], {
    env: { ...process.env, LOLM_CONFIG: configPath, LOLM_DISABLE_NATIVE_SECRETS: "1" },
  }).catch((error) => error);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.ok, false);
  assert.match(payload.error.message, /invalid credential/);
  await assert.rejects(readFile(configPath, "utf8"), /ENOENT/);
  assert.doesNotMatch(result.stderr, /unsettled top-level await/i);
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
  const result = await exec(process.execPath, [bin, "code", "create hello.html", "--cwd", root, "--yes", "--provider", "custom", "--base-url", address(server), "--model", "test", "--api-key", "test", "--no-nfet", "--json"], {
    env: { ...process.env, LOLM_LAST_TASK: join(root, "last-task.json") },
  });
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.ok, true);
  assert.equal(payload.changes.length, 1);
  assert.equal(await readFile(join(root, "hello.html"), "utf8"), "<!doctype html><title>Hello</title>");
  assert.equal(calls, 2);
});

test("compound HTML work stays in the agent loop instead of the artifact shortcut", async (t) => {
  const server = await startServer((_req, payload) => {
    if (!payload.messages.some((message) => message.role === "tool")) {
      return { body: { choices: [{ message: { role: "assistant", content: null, tool_calls: [
        { id: "w1", type: "function", function: { name: "fs__write", arguments: JSON.stringify({ path: "index.html", content: "<h1>Ready</h1>" }) } },
        { id: "r1", type: "function", function: { name: "terminal__exec", arguments: JSON.stringify({ command: `${JSON.stringify(process.execPath)} -e \"process.exit(0)\"` }) } },
      ] } }] } };
    }
    return { body: { choices: [{ message: { role: "assistant", content: "Created and verified index.html." } }] } };
  });
  t.after(() => server.close());
  const root = await temp("compound-html");
  const result = await exec(process.execPath, [bin, "create", "index.html", "then", "run", "a", "test", "--cwd", root, "--once", "--yes", "--provider", "custom", "--base-url", address(server), "--model", "test", "--api-key", "test", "--no-nfet", "--json"], { env: { ...process.env, LOLM_LAST_TASK: join(root, "last-task.json") } });
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.kind, undefined);
  assert.equal(payload.verified, true);
  assert.equal(await readFile(join(root, "index.html"), "utf8"), "<h1>Ready</h1>");
});

test("run routes an explicitly named file task through the write-capable agent", async (t) => {
  const server = await startServer((_req, payload) => {
    if (!payload.messages.some((message) => message.role === "tool")) {
      assert.ok(payload.tools.some((tool) => tool.function.name === "fs__write"));
      assert.ok(payload.tools.length <= 10, `expected a focused local tool set, got ${payload.tools.length}`);
      return { body: { choices: [{ message: { role: "assistant", content: null, tool_calls: [{
        id: "w1", type: "function", function: { name: "fs__write", arguments: JSON.stringify({ path: "solution.py", content: "VALUE = 7\n", tool: "fs.write" }) },
      }] } }] } };
    }
    return { body: { choices: [{ message: { role: "assistant", content: "Created solution.py." } }] } };
  });
  t.after(() => server.close());
  const root = await temp("run-named-file");
  const result = await exec(process.execPath, [bin, "run", "Create", "solution.py", "defining", "VALUE", "as", "7", "--cwd", root, "--yes", "--provider", "custom", "--base-url", address(server), "--model", "test", "--api-key", "test", "--no-nfet", "--json"], {
    env: { ...process.env, LOLM_LAST_TASK: join(root, "last-task.json") },
  });
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.ok, true);
  assert.equal(await readFile(join(root, "solution.py"), "utf8"), "VALUE = 7\n");
});

test("simple named HTML requests preserve the requested filename", async (t) => {
  const server = await startServer(() => ({ body: { choices: [{ message: { role: "assistant", content: "<!doctype html><html><title>Named</title></html>" } }] } }));
  t.after(() => server.close());
  const root = await temp("named-html");
  const result = await exec(process.execPath, [bin, "create", "an", "HTML", "file", "named", "index.html", "--cwd", root, "--once", "--yes", "--provider", "custom", "--base-url", address(server), "--model", "test", "--api-key", "test", "--no-nfet", "--json"], { env: { ...process.env, LOLM_LAST_TASK: join(root, "last-task.json") } });
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.kind, "html");
  assert.equal(payload.path, join(root, "index.html"));
});

test("PDF writer creates a valid multi-object PDF", async () => {
  const root = await temp("pdf");
  const out = join(root, "report.pdf");
  const result = await createPdf("# Report\n\n- **one:** useful\n- two\n\nA useful paragraph.", out);
  const body = await readFile(out);
  assert.equal(body.subarray(0, 5).toString(), "%PDF-");
  assert.match(body.toString("ascii"), /\/Type \/Catalog/);
  assert.doesNotMatch(body.toString("ascii"), /\*\*/);
  assert.ok(result.bytes > 500);
});

test("customer comparison documents reject framework substitutions and unsupported claims", () => {
  assert.equal(isLolmAgentComparison("Make comparisons of yourself to other agents"), true);
  assert.equal(isLolmAgentComparison("Compare LOLM with other customer coding agents"), true);
  const sources = [
    { url: "https://github.com/openai/codex" },
    { url: "https://code.claude.com/docs/en/overview" },
    { url: "https://github.com/google-gemini/gemini-cli" },
  ];
  const padded = "Useful detail. ".repeat(140);
  const bad = `# Agent comparison\n\nLangChain, AutoGPT, and ReAct are alternatives. NFET prevents malicious behavior.\n\n## Limitations\n${padded}\n\n## Sources\nhttps://github.com/openai/codex\nhttps://code.claude.com/docs/en/overview`;
  const issues = documentIssues(bad, { comparison: true, sources });
  assert.ok(issues.includes("missing Gemini CLI"));
  assert.ok(issues.includes("substituted frameworks for customer agents"));
  assert.ok(issues.includes("contains an unsupported security or competitor claim"));

  const good = `# LOLM compared with coding agents\n\n## Executive summary\nLOLM, OpenAI Codex, Anthropic Claude Code, and Google Gemini CLI have different strengths.\n\n## Capability table\n| Agent | Best fit |\n|---|---|\n| LOLM | Local-first workflows |\n| OpenAI Codex | OpenAI-integrated coding |\n| Claude Code | Anthropic-integrated coding |\n| Gemini CLI | Google-integrated coding |\n\n## Where LOLM is stronger\nProvider choice and local execution.\n\n## Where competitors are stronger\nMature ecosystems and hosted integrations.\n\n## Limitations and trade-offs\nNFET does not prevent malicious behavior. NFET can require more checking, but it does not guarantee correctness or security. ${padded}\n\n## Best fit\nChoose based on privacy, provider, and workflow needs.\n\n## Sources\n- https://github.com/openai/codex\n- https://code.claude.com/docs/en/overview\n- https://github.com/google-gemini/gemini-cli`;
  assert.deepEqual(documentIssues(good, { comparison: true, sources }), []);
});

test("natural PDF request routes to local PDF creation", async (t) => {
  const server = await startServer(() => ({ body: { choices: [{ message: { role: "assistant", content: "# Local report\n\nMade by LOLM." } }] } }));
  t.after(() => server.close());
  const root = await temp("natural-pdf");
  const out = join(root, "made.pdf");
  const result = await exec(process.execPath, [bin, "make", "me", "a", "PDF", "about", "LOLM", "--out", out, "--yes", "--provider", "custom", "--base-url", address(server), "--model", "test", "--api-key", "test", "--no-nfet", "--json"], {
    env: { ...process.env, LOLM_LAST_TASK: join(root, "last-task.json") },
  });
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.kind, "pdf");
  assert.equal(payload.path, out);
  assert.equal((await readFile(out)).subarray(0, 5).toString(), "%PDF-");
});

test("Ollama streaming keeps working while the local model produces chunks", async (t) => {
  let requestBody = "";
  const server = createServer(async (req, res) => {
    for await (const chunk of req) requestBody += chunk;
    res.writeHead(200, { "content-type": "application/x-ndjson" });
    res.write(`${JSON.stringify({ message: { content: "local " }, done: false })}\n`);
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 30));
    res.write(`${JSON.stringify({ message: { content: "stream" }, done: false })}\n`);
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 30));
    res.end(`${JSON.stringify({ message: {}, done: true, prompt_eval_count: 4, eval_count: 2 })}\n`);
  });
  await new Promise((resolvePromise) => server.listen(0, "127.0.0.1", resolvePromise));
  t.after(() => server.close());
  const tokens = [];
  const result = await chat({
    protocol: "ollama",
    keyRequired: false,
    baseUrl: `http://127.0.0.1:${server.address().port}`,
    model: "test",
    timeoutMs: 1_000,
  }, [{ role: "user", content: "hello" }], { onToken: (token) => tokens.push(token), reasoning: false, maxTokens: 321 });
  assert.equal(result.content, "local stream");
  assert.deepEqual(tokens, ["local ", "stream"]);
  assert.equal(result.usage.completion_tokens, 2);
  assert.equal(JSON.parse(requestBody).options.num_predict, 321);
});

test("natural retry restores the previous task instead of prompting with try again", async (t) => {
  const prompts = [];
  const server = await startServer((_req, payload) => {
    const last = payload.messages.filter((message) => message.role === "user").at(-1)?.content;
    prompts.push(last);
    return { body: { choices: [{ message: { role: "assistant", content: `answered: ${last}` } }] } };
  });
  t.after(() => server.close());
  const root = await temp("retry");
  const env = { ...process.env, LOLM_CONFIG: join(root, "config.json"), LOLM_LAST_TASK: join(root, "last-task.json") };
  const common = ["--provider", "custom", "--base-url", address(server), "--model", "test", "--api-key", "test", "--no-nfet", "--json"];
  await exec(process.execPath, [bin, "ask", "remember this exact request", ...common], { env });
  const retried = await exec(process.execPath, [bin, "try", "again", ...common], { env });
  assert.equal(JSON.parse(retried.stdout).response, "answered: remember this exact request");
  assert.deepEqual(prompts, ["remember this exact request", "remember this exact request"]);
  assert.equal(JSON.parse(await readFile(join(root, "last-task.json"), "utf8")).prompt, "remember this exact request");
});

test("retry language and customer NFET summaries are human-readable", () => {
  assert.equal(isRetryPhrase("try again"), true);
  assert.equal(isRetryPhrase("retry the last task"), true);
  const result = { available: true, decision: { label: "finalize", source: "verified_result" }, telemetry: { avg_entropy: 1.2, avg_hidden_drift: 3.4, avg_gate: 0.5 } };
  assert.match(stripAnsi(nfetSummary(result)), /Result checked/);
  assert.doesNotMatch(stripAnsi(nfetSummary(result)), /entropy|H 1\.2|gate 0\.5/i);
  assert.match(stripAnsi(nfetSummary(result, { verbose: true })), /H 1\.2/);
});

test("Ollama receives a local-model inactivity budget by default", () => {
  const runtime = resolveRuntime({ provider: "ollama", providers: { ollama: { model: "qwen3:14b" } } });
  assert.equal(runtime.timeoutMs, 600_000);
});
