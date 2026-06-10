/* Node test for lolm-nfet-client — no framework, no network. */
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import assert from "node:assert/strict";
import { AgentRunError, friendly, parseSSEStream, playReplay, runAgent } from "../index.mjs";

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
  const replay = JSON.parse(await readFile(join(here, "../../../site/replays/gate.json"), "utf-8"));
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

console.log(`\n${passed}/5 passed`);
