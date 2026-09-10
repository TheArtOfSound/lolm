// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Streaming, cancellation, context compaction, plans, and diffs.
 *
 * Every provider here is a localhost server, so what is asserted is the real
 * transport and the real loop with nothing mocked but the model.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chat } from "../lib/providers.mjs";
import { compactMessages, contextSize, runAgent } from "../lib/agent.mjs";
import { createToolRunner } from "../lib/tools.mjs";
import { renderDiff, stripAnsi } from "../lib/tui.mjs";

function serve(handler) {
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (chunk) => { body += chunk; });
    req.on("end", () => handler(JSON.parse(body || "{}"), res));
  });
  return new Promise((resolvePromise) => {
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolvePromise({
        server,
        runtime: { provider: "custom", protocol: "openai", baseUrl: `http://127.0.0.1:${port}/v1`, model: "stub", apiKey: "", timeoutMs: 5_000 },
        close: () => new Promise((done) => server.close(done)),
      });
    });
  });
}

/** Answer with server-sent events when the client asked to stream. */
function sse(res, events) {
  res.writeHead(200, { "content-type": "text/event-stream" });
  for (const event of events) res.write(`data: ${JSON.stringify(event)}\n\n`);
  res.write("data: [DONE]\n\n");
  res.end();
}

function json(res, content) {
  res.writeHead(200, { "content-type": "application/json" });
  res.end(JSON.stringify({ choices: [{ message: { content, tool_calls: [] }, finish_reason: "stop" }], usage: { total_tokens: 3 } }));
}

test("a streamed completion is assembled from deltas, tool arguments included", async () => {
  const { runtime, close } = await serve((body, res) => {
    assert.equal(body.stream, true, "the client asked to stream");
    sse(res, [
      { choices: [{ delta: { content: "Hel" } }] },
      { choices: [{ delta: { content: "lo" } }] },
      { choices: [{ delta: { tool_calls: [{ index: 0, id: "c1", function: { name: "fs__read", arguments: "{\"pa" } }] } }] },
      { choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: "th\":\"a.py\"}" } }] } }] },
      { choices: [{ delta: {}, finish_reason: "tool_calls" }] },
      { usage: { total_tokens: 9 } },
    ]);
  });
  try {
    const tokens = [];
    const reply = await chat(runtime, [{ role: "user", content: "hi" }], { onToken: (delta) => tokens.push(delta) });
    assert.deepEqual(tokens, ["Hel", "lo"], "text reaches the listener as it lands");
    assert.equal(reply.content, "Hello");
    assert.equal(reply.toolCalls.length, 1);
    assert.equal(reply.toolCalls[0].name, "fs__read");
    assert.deepEqual(reply.toolCalls[0].arguments, { path: "a.py" }, "fragmented arguments are joined before parsing");
    assert.equal(reply.usage.total_tokens, 9);
    assert.equal(reply.raw.streamed, true);
  } finally { await close(); }
});

test("a provider that answers in one piece still works", async () => {
  const { runtime, close } = await serve((body, res) => json(res, "whole reply"));
  try {
    const reply = await chat(runtime, [{ role: "user", content: "hi" }], { onToken: () => {} });
    assert.equal(reply.content, "whole reply");
    assert.equal(reply.raw.streamed, undefined, "the plain path was used");
  } finally { await close(); }
});

test("an abort signal stops a request mid-flight with a named code", async () => {
  const { runtime, close, server } = await serve((body, res) => {
    // Never answer; the client must give up on its own terms.
    res.writeHead(200, { "content-type": "text/event-stream" });
    res.write(": holding\n\n");
    server.once("close", () => res.end());
  });
  try {
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 120);
    const started = Date.now();
    await assert.rejects(
      chat(runtime, [{ role: "user", content: "hi" }], { onToken: () => {}, signal: controller.signal }),
      (error) => error.code === "CANCELLED",
    );
    assert.ok(Date.now() - started < 2_000, "the cancel is honoured promptly, not at the timeout");
  } finally { await close(); }
});

test("stopping a task keeps the work done so far and reports it", async () => {
  const { runtime, close, server } = await serve((body, res) => {
    res.writeHead(200, { "content-type": "text/event-stream" });
    res.write("data: {\"choices\":[{\"delta\":{\"content\":\"partial \"}}]}\n\n");
    server.once("close", () => res.end());
  });
  try {
    const controller = new AbortController();
    const deltas = [];
    setTimeout(() => controller.abort(), 150);
    const result = await runAgent({
      prompt: "what is two plus two", mode: "ask", runtime, signal: controller.signal, maxSteps: 4,
      onDelta: (delta) => deltas.push(delta),
    });
    assert.equal(result.ok, false);
    assert.equal(result.cancelled, true, "a stop is reported as a stop, not a failure");
    assert.equal(result.error, "Stopped by user.");
    assert.equal(result.steps, 1);
    assert.deepEqual(deltas, ["partial "], "text streamed before the stop was delivered");
  } finally { await close(); }
});

test("an oversized context is trimmed, then summarised, without orphaning a tool result", async () => {
  const { runtime, close } = await serve((body, res) => json(res, "SUMMARY: wrote a.py and b.py; tests pass; c.py still failing."));
  try {
    const messages = [
      { role: "system", content: "system" },
      { role: "user", content: "the task" },
    ];
    for (let turn = 0; turn < 10; turn += 1) {
      messages.push({ role: "assistant", content: "", toolCalls: [{ id: `t${turn}`, name: "fs__read", arguments: { path: `${turn}.py` } }] });
      messages.push({ role: "tool", id: `t${turn}`, name: "fs__read", content: "x".repeat(3_000) });
    }
    const before = contextSize(messages);
    const events = [];
    const outcome = await compactMessages(messages, runtime, { budget: 4_000, eventSink: (event) => events.push(event) });
    assert.equal(outcome.compacted, true);
    assert.ok(outcome.after < before, `context shrank from ${before} to ${outcome.after}`);
    assert.equal(messages[0].role, "system", "the system message is untouched");
    assert.equal(messages[1].content, "the task", "the original request is untouched");
    assert.match(messages[2].content, /^\[Earlier progress on this task/, "the middle became one summary");
    assert.match(messages[2].content, /c\.py still failing/, "the summary came from the model");
    assert.notEqual(messages[3].role, "tool", "the kept tail does not start with an orphaned tool result");
    assert.equal(events.at(-1).type, "context.compacted");
    assert.equal(events.at(-1).tier, "summary");
  } finally { await close(); }
});

test("a context under budget is left exactly alone", async () => {
  const messages = [{ role: "system", content: "s" }, { role: "user", content: "u" }, { role: "assistant", content: "a" }];
  const snapshot = JSON.stringify(messages);
  const outcome = await compactMessages(messages, { protocol: "openai" }, { budget: 10_000 });
  assert.equal(outcome.compacted, false);
  assert.equal(JSON.stringify(messages), snapshot);
});

test("the plan tools publish a checklist and refuse a step that does not exist", async () => {
  const cwd = await mkdtemp(join(tmpdir(), "lolm-plan-"));
  const events = [];
  const runner = createToolRunner({ cwd, yes: true, mode: "trusted", eventSink: (event) => { events.push(event); } });
  try {
    const set = await runner.execute({ name: "plan__set", arguments: { steps: ["read the code", "fix it", "run tests"] } });
    assert.equal(set.ok, true);
    assert.equal(set.remaining, 3);
    const published = events.filter((event) => event.type === "plan.updated");
    assert.equal(published.length, 1);
    assert.deepEqual(published[0].items.map((item) => item.done), [false, false, false]);

    const done = await runner.execute({ name: "plan__done", arguments: { index: 2 } });
    assert.deepEqual(done.items.map((item) => item.done), [false, true, false]);
    assert.equal(done.remaining, 2);

    const missing = await runner.execute({ name: "plan__done", arguments: { index: 9 } });
    assert.equal(missing.ok, false);
    assert.equal(missing.code, "PLAN_STEP_MISSING");
    assert.equal(runner.evidence, 0, "declaring a plan is not evidence of having checked anything");
  } finally { await runner.close(); }
});

test("file edits carry a diff to the reader but not back into the model's context", async () => {
  const cwd = await mkdtemp(join(tmpdir(), "lolm-diff-"));
  const events = [];
  const runner = createToolRunner({ cwd, yes: true, mode: "trusted", eventSink: (event) => { events.push(event); } });
  try {
    const written = await runner.execute({ name: "fs__write", arguments: { path: "a.py", content: "x = 1\ny = 2\n" } });
    assert.equal(written.ok, true);
    assert.equal(written.created, true);
    assert.equal(written.added, 2);
    assert.ok(!("diff" in written), "the model does not get a second copy of what it wrote");
    const create = events.find((event) => event.type === "tool.completed" && event.tool === "fs.write");
    assert.match(create.result.diff, /\+x = 1/);

    const patched = await runner.execute({ name: "fs__patch", arguments: { path: "a.py", old_text: "y = 2", new_text: "y = 3" } });
    assert.equal(patched.ok, true);
    assert.deepEqual([patched.added, patched.removed], [1, 1]);
    assert.ok(!("diff" in patched));
    const patch = events.find((event) => event.type === "tool.completed" && event.tool === "fs.patch");
    assert.match(patch.result.diff, /-y = 2\n\+y = 3/);
    assert.equal(await readFile(join(cwd, "a.py"), "utf8"), "x = 1\ny = 3\n");
  } finally { await runner.close(); }
});

test("renderDiff colours by kind and caps a long diff", () => {
  const rows = renderDiff("--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n-old\n+new\n same", { max: 24 }).map(stripAnsi);
  assert.deepEqual(rows, ["@@ -1,2 +1,2 @@", "-old", "+new", " same"], "file headers are dropped, hunks kept");
  const long = renderDiff(Array.from({ length: 40 }, (_, index) => `+line ${index}`).join("\n"), { max: 5 }).map(stripAnsi);
  assert.equal(long.length, 6);
  assert.match(long.at(-1), /35 more line/);
});

test("a plan the model declares and abandons earns exactly one reminder", async () => {
  let turn = 0;
  const cwd = await mkdtemp(join(tmpdir(), "lolm-plan-loop-"));
  const { runtime, close } = await serve((body, res) => {
    turn += 1;
    const call = (name, args, id) => ({ id, type: "function", function: { name, arguments: JSON.stringify(args) } });
    const reply = (message) => { res.writeHead(200, { "content-type": "application/json" }); res.end(JSON.stringify({ choices: [{ message, finish_reason: "stop" }] })); };
    if (turn === 1) return reply({ content: null, tool_calls: [call("plan__set", { steps: ["look", "decide"] }, "p1")] });
    if (turn === 2) return reply({ content: "All done.", tool_calls: [] });                       // walks away at 0/2
    if (turn === 3) {
      assert.match(body.messages.at(-1).content, /still lists 2 step\(s\) as unfinished/, "the reminder names the count");
      return reply({ content: null, tool_calls: [call("plan__done", { index: 1 }, "d1"), call("plan__done", { index: 2 }, "d2")] });
    }
    return reply({ content: "All done, plan complete.", tool_calls: [] });
  });
  try {
    const events = [];
    const result = await runAgent({ prompt: "outline the approach for tidying this module", mode: "ask", runtime, cwd, maxSteps: 8, eventSink: (event) => { events.push(event); } });
    assert.equal(result.ok, true);
    assert.equal(turn, 4, "one reminder, then the model ticks its steps and finishes");
    assert.equal(events.filter((event) => event.type === "plan.reminded").length, 1);
    const last = events.filter((event) => event.type === "plan.updated").at(-1);
    assert.equal(last.remaining, 0, "the plan is complete by the end");
    assert.equal(result.interventions, 0, "a plan reminder is not an NFET intervention");
  } finally { await close(); }
});

test("memory round-trips through the tools and never counts as evidence", async () => {
  const dir = await mkdtemp(join(tmpdir(), "lolm-memory-"));
  process.env.LOLM_MEMORY_DIR = dir;
  const runner = createToolRunner({ cwd: dir, yes: true, mode: "trusted", eventSink: () => {} });
  try {
    const saved = await runner.execute({ name: "memory__save", arguments: { name: "Deploy target", description: "where the site deploys", body: "rsync to autohustle-aws", tags: ["deploy"] } });
    assert.equal(saved.ok, true);
    assert.equal(saved.name, "deploy-target", "names become stable slugs");
    const found = await runner.execute({ name: "memory__recall", arguments: { query: "autohustle" } });
    assert.equal(found.notes.length, 1);
    assert.match(found.notes[0].body, /rsync/);
    const got = await runner.execute({ name: "memory__get", arguments: { name: "deploy-target" } });
    assert.equal(got.description, "where the site deploys");
    assert.equal(runner.evidence, 0, "recalling a note is not evidence about the task");
    const gone = await runner.execute({ name: "memory__forget", arguments: { name: "deploy-target" } });
    assert.equal(gone.forgotten, true);
    assert.equal((await runner.execute({ name: "memory__list", arguments: {} })).notes.length, 0);
  } finally { await runner.close(); delete process.env.LOLM_MEMORY_DIR; }
});

test("saved notes are indexed in the system prompt with bodies left on demand", async () => {
  const dir = await mkdtemp(join(tmpdir(), "lolm-memory-"));
  process.env.LOLM_MEMORY_DIR = dir;
  const { saveNote } = await import("../lib/memory.mjs");
  await saveNote({ name: "python", description: "python3 only", body: "There is no `python` on PATH; use python3." }, { dir });
  let system = "";
  const { runtime, close } = await serve((body, res) => { system = body.messages[0].content; json(res, "ok"); });
  try {
    await runAgent({ prompt: "what is two plus two", mode: "ask", runtime, maxSteps: 2 });
    assert.match(system, /Memory \(notes you saved in earlier sessions/);
    assert.match(system, /- python: python3 only/);
    assert.doesNotMatch(system, /no `python` on PATH/, "the body stays out of the prompt until recalled");
  } finally { await close(); delete process.env.LOLM_MEMORY_DIR; }
});

test("LOLM_MEMORY=0 keeps notes out of the prompt and the toolbox", async () => {
  const dir = await mkdtemp(join(tmpdir(), "lolm-memory-"));
  process.env.LOLM_MEMORY_DIR = dir;
  process.env.LOLM_MEMORY = "0";
  const { saveNote } = await import("../lib/memory.mjs");
  await saveNote({ name: "secretish", body: "must not appear" }, { dir });
  let system = "", toolNames = [];
  const { runtime, close } = await serve((body, res) => { system = body.messages[0].content; toolNames = (body.tools || []).map((tool) => tool.function.name); json(res, "ok"); });
  try {
    await runAgent({ prompt: "what is two plus two", mode: "ask", runtime, maxSteps: 2 });
    assert.doesNotMatch(system, /secretish/);
    assert.ok(!toolNames.some((name) => name.startsWith("memory__")), "no memory tools are offered");
  } finally { await close(); delete process.env.LOLM_MEMORY_DIR; delete process.env.LOLM_MEMORY; }
});

test("Gemini streams text and function calls from server-sent events", async () => {
  const { runtime, close } = await serve((body, res) => {
    res.writeHead(200, { "content-type": "text/event-stream" });
    for (const event of [
      { candidates: [{ content: { parts: [{ text: "Hel" }] } }] },
      { candidates: [{ content: { parts: [{ text: "lo" }] } }] },
      { candidates: [{ content: { parts: [{ functionCall: { name: "fs__read", args: { path: "a.py" } }, thoughtSignature: "sig1" }] }, finishReason: "STOP" }], usageMetadata: { totalTokenCount: 7 } },
    ]) res.write(`data: ${JSON.stringify(event)}\n\n`);
    res.end();
  });
  const gemini = { ...runtime, protocol: "gemini", baseUrl: runtime.baseUrl.replace(/\/v1$/, ""), apiKey: "k" };
  try {
    const tokens = [];
    const reply = await chat(gemini, [{ role: "user", content: "hi" }], { onToken: (delta) => tokens.push(delta) });
    assert.deepEqual(tokens, ["Hel", "lo"]);
    assert.equal(reply.content, "Hello");
    assert.equal(reply.toolCalls[0].name, "fs__read");
    assert.deepEqual(reply.toolCalls[0].arguments, { path: "a.py" });
    assert.equal(reply.toolCalls[0].signature, "sig1", "the thought signature survives for replay");
    assert.equal(reply.usage.totalTokenCount, 7);
    assert.equal(reply.raw.streamed, true);
  } finally { await close(); }
});

test("the model is told its step budget and warned once before it runs out", async () => {
  const turns = [];
  const cwd = await mkdtemp(join(tmpdir(), "lolm-budget-"));
  const systems = [];
  const { runtime, close } = await serve((body, res) => {
    systems.push(body.messages[0].content);
    turns.push(body.messages.at(-1).content);
    res.writeHead(200, { "content-type": "application/json" });
    // Keep calling a tool forever; only the budget can end this.
    res.end(JSON.stringify({ choices: [{ message: { content: null, tool_calls: [
      { id: `c${turns.length}`, type: "function", function: { name: "fs__list", arguments: "{}" } },
    ] }, finish_reason: "tool_calls" }] }));
  });
  try {
    const events = [];
    const result = await runAgent({ prompt: "keep looking", mode: "code", runtime, cwd, maxSteps: 5, eventSink: (event) => events.push(event) });
    assert.match(systems[0], /Step budget for this task: 5\./, "the budget is operational context, not part of the request");
    assert.doesNotMatch(turns[0], /step budget/i, "the person's own words are left verbatim");
    const warnings = events.filter((event) => event.type === "budget.low");
    assert.equal(warnings.length, 1, "warned exactly once, not every remaining step");
    assert.equal(warnings[0].remaining, 2);
    assert.ok(turns.some((turn) => /2 step\(s\) remain\. Land the task now/.test(turn)), "the warning reaches the model");
    assert.equal(result.ok, false, "a run that never lands still ends at the cap");
  } finally { await close(); }
});
