/* Node test for lolm-nfet-client — no framework, no network. */
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import assert from "node:assert/strict";
import { AgentRunError, buildVisual, forgetMemory, friendly, getMemory, listCodeReceipts, parseSSEStream, playReplay, rememberFact, runAgent, runCode } from "../index.mjs";

const here = dirname(fileURLToPath(import.meta.url));
let passed = 0;
const ok = (name) => { passed++; console.log("  ✓", name); };

// 1. SSE parsing from a synthetic stream (chunk boundaries mid-line).
{
  const raw = 'event: run_start\ndata: {"command":"x"}\n\nevent: token\ndata: {"token":" hi","channel":"draft"}\n\nevent: run_done\ndata: {"ended_by":"nfet_finalize"}\n\n';
  const chunks = [raw.slice(0, 17), raw.slice(17, 60), raw.slice(60)];
  const stream = new ReadableStream({
    start(c) { for (const ch of chunks) c.enqueue(new TextEncoder().encode(ch)); c.close(); },
  });
  const events = [];
  for await (const ev of parseSSEStream(stream)) events.push(ev);
  assert.equal(events.length, 3);
  assert.equal(events[0].event, "run_start");
  assert.equal(events[1].data.token, " hi");
  assert.equal(events[2].data.ended_by, "nfet_finalize");
  ok("parseSSEStream handles chunked frames");
}

// 2. Replay playback over the REAL recorded replay shipped with the site.
{
  const replay = JSON.parse(await readFile(join(here, "../../../site/replays/credit-score.json"), "utf-8"));
  const seen = { tokens: 0, decisions: [], actions: [], proof: null };
  const result = await playReplay(replay, {
    speed: 0,
    onToken: () => seen.tokens++,
    onDecision: (d) => seen.decisions.push(d.decision.label),
    onAction: (a) => seen.actions.push(a.kind),
    onProof: (p) => (seen.proof = p),
  });
  assert.ok(seen.tokens > 50, "tokens streamed");
  assert.ok(seen.decisions.length >= 2, "decisions seen");
  assert.ok(seen.proof && seen.proof.verdict, "proof present");
  assert.ok(result && result.ended_by, "run_done returned");
  ok(`playReplay over real recording (${seen.tokens} tokens, decisions: ${seen.decisions.join(",")})`);
}

// 3. friendly() narration mapping.
{
  assert.match(friendly({ event: "decision", data: { decision: { label: "retrieve", source: "head" } } }), /checking its notes/);
  assert.match(friendly({ event: "decision", data: { decision: { label: "finalize", source: "heuristic" } } }), /finishing up/);
  assert.match(friendly({ event: "action", data: { kind: "verify", verdict: "revise" } }), /caught an issue/);
  assert.match(friendly({ event: "proof", data: { verdict: "nfet_control_visible" } }), /acted on its own uncertainty/);
  assert.equal(friendly({ event: "token", data: { token: "x" } }), null);
  assert.match(friendly({ event: "learned", data: { items: [{ text: "a" }] } }), /Remembered/);
  assert.match(friendly({ event: "continuity_tick", data: { model_used: true, facts: ["x"] } }), /continuity/i);
  ok("friendly() narration");
}

// 4. runAgent against a mocked fetch returning an SSE body.
{
  const body = 'event: run_start\ndata: {"command":"q"}\n\nevent: proof\ndata: {"verdict":"nfet_finalize_visible"}\n\nevent: run_done\ndata: {"ended_by":"nfet_finalize","proof":{"verdict":"nfet_finalize_visible"}}\n\n';
  const mockFetch = async () => new Response(body, { status: 200 });
  const proofSeen = [];
  const result = await runAgent({
    command: "q", fetch: mockFetch,
    onProof: (p) => proofSeen.push(p.verdict),
  });
  assert.equal(result.ended_by, "nfet_finalize");
  assert.deepEqual(proofSeen, ["nfet_finalize_visible"]);
  ok("runAgent happy path (mock fetch)");
}

// 5. runAgent surfaces refusals as AgentRunError.
{
  const mockFetch = async () => new Response(JSON.stringify({ error: "rate limit: try later" }), {
    status: 429, headers: { "Content-Type": "application/json" },
  });
  await assert.rejects(
    () => runAgent({ command: "q", fetch: mockFetch }),
    (err) => err instanceof AgentRunError && err.status === 429 && /rate limit/.test(err.message),
  );
  ok("runAgent surfaces 429 as AgentRunError");
}

// 6. runAgent threads history + memory into the request body.
{
  let sentBody = null;
  const body = 'event: run_done\ndata: {"ended_by":"nfet_finalize"}\n\n';
  const mockFetch = async (_url, init) => { sentBody = JSON.parse(init.body); return new Response(body, { status: 200 }); };
  await runAgent({
    command: "what did I just ask?", fetch: mockFetch,
    history: [{ role: "user", content: "how are you?" }],
    memory: ["The user's name is Bryan."],
  });
  assert.equal(sentBody.history[0].content, "how are you?");
  assert.deepEqual(sentBody.user_memory, ["The user's name is Bryan."]);
  ok("runAgent threads history + cross-session memory into the request");
}

// 7. buildVisual returns the HTML document.
{
  const mockFetch = async (url) => {
    assert.match(String(url), /\/api\/demo\/code\/visual$/);
    return new Response(JSON.stringify({ html: "<!DOCTYPE html><canvas>", bytes: 22 }), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  const r = await buildVisual({ task: "snake game", fetch: mockFetch });
  assert.ok(r.html.startsWith("<!DOCTYPE") && r.bytes === 22);
  ok("buildVisual returns a self-contained HTML app");
}

// 8. runCode streams the agentic loop and returns code_done + code_receipt.
{
  const body = 'event: code_start\ndata: {"sandbox":"sbx_1"}\n\nevent: command_finished\ndata: {"exit_code":0,"stdout":"42"}\n\nevent: code_done\ndata: {"ran":true,"produced_output":true,"ok":true}\n\nevent: code_receipt\ndata: {"receipt_sha":"abc123","ok":true,"verdict":"shipped","trail":[]}\n\n';
  const mockFetch = async () => new Response(body, { status: 200 });
  const events = [];
  let gotReceipt = null;
  const done = await runCode({
    task: "print 42",
    fetch: mockFetch,
    onEvent: (e) => events.push(e.event),
    onCodeReceipt: (r) => { gotReceipt = r; },
  });
  assert.deepEqual(events, ["code_start", "command_finished", "code_done", "code_receipt"]);
  assert.equal(done.ran, true);
  assert.equal(done.receipt.receipt_sha, "abc123");
  assert.equal(gotReceipt.receipt_sha, "abc123");
  assert.equal(friendly({ event: "code_receipt", data: gotReceipt }), "Sealed code receipt abc123…");
  ok("runCode streams the jailed coding loop + code_receipt");
}

// 8b. listCodeReceipts hits the audit ledger.
{
  const mockFetch = async (url) => {
    assert.match(String(url), /\/api\/demo\/code\/receipts/);
    return new Response(JSON.stringify({ receipts: [{ receipt_sha: "x" }], stats: { recent: 1 } }), { status: 200 });
  };
  const j = await listCodeReceipts({ fetch: mockFetch, limit: 5 });
  assert.equal(j.receipts[0].receipt_sha, "x");
  ok("listCodeReceipts reads the public audit ledger");
}

// 9. memory helpers require authentication and never use caller-owned namespaces.
{
  const calls = [];
  const mockFetch = async (url, init = {}) => {
    calls.push({
      url: String(url),
      method: init.method || "GET",
      apiKey: (init.headers || {})["X-LOLM-Api-Key"],
      owner: (init.headers || {})["X-Workspace-Owner"],
    });
    if (String(url).endsWith("/memory") && (init.method || "GET") === "GET")
      return new Response(JSON.stringify({ memories: [{ id: "m1", text: "The user's name is Bryan." }] }), { status: 200 });
    return new Response(JSON.stringify({ saved: { id: "m2" }, deleted: true }), { status: 200 });
  };
  await assert.rejects(
    () => getMemory({ fetch: mockFetch }),
    (err) => err instanceof AgentRunError && /authentication/i.test(err.message),
  );
  const mems = await getMemory({ apiKey: "lolm_test_secret", owner: "spoofed", fetch: mockFetch });
  assert.equal(mems[0].text, "The user's name is Bryan.");
  await rememberFact({ text: "The user prefers Python.", apiKey: "lolm_test_secret", owner: "spoofed", fetch: mockFetch });
  await forgetMemory({ id: "m1", apiKey: "lolm_test_secret", owner: "spoofed", fetch: mockFetch });
  assert.ok(calls.every((c) => c.apiKey === "lolm_test_secret"), "API key sent");
  assert.ok(calls.every((c) => c.owner === undefined), "caller owner header omitted");
  assert.equal(calls[2].method, "DELETE");
  ok("memory helpers require auth and omit caller-owned namespace headers");
}

console.log(`\n${passed} passed`);
