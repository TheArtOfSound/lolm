// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** How the agent loop acts on NFET verdicts.
 *
 * The real controller needs a 4B model, so these drive the loop with a stub
 * monitor and a localhost OpenAI-compatible server. That isolates the one thing
 * under test — what the loop does with a verdict — from the model that produced
 * it, and proves a spurious `branch` can no longer discard a verified answer.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { runAgent } from "../lib/agent.mjs";

/** A server that always answers with the same final text and no tool calls. */
function stubProvider(content) {
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (chunk) => { body += chunk; });
    req.on("end", () => {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({
        choices: [{ message: { content, tool_calls: [] }, finish_reason: "stop" }],
        usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
      }));
    });
  });
  return new Promise((resolvePromise) => {
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolvePromise({
        server,
        runtime: {
          provider: "custom", protocol: "openai",
          baseUrl: `http://127.0.0.1:${port}/v1`, model: "stub", apiKey: "", timeoutMs: 5_000,
        },
      });
    });
  });
}

/** A controller that returns the same verdict every time it is consulted. */
function stubMonitor(label) {
  let calls = 0;
  return {
    async start() { return { available: true }; },
    async decide() {
      calls += 1;
      return {
        available: true,
        decision: { label, source: "stub" },
        telemetry: { avg_entropy: 1, avg_hidden_drift: 1, avg_gate: 0.7 },
        head_trained: true,
      };
    },
    get calls() { return calls; },
  };
}

async function drive({ prompt, verdict, mode = "ask" }) {
  const { server, runtime } = await stubProvider("Done. The answer is 4.");
  const events = [];
  try {
    const result = await runAgent({
      prompt, mode, runtime, monitor: stubMonitor(verdict),
      maxSteps: 8, eventSink: (event) => { events.push(event); },
    });
    return { result, events };
  } finally {
    await new Promise((resolvePromise) => server.close(resolvePromise));
  }
}

test("a spurious branch does not discard a verified answer", async () => {
  // "what is two plus two" needs no fresh evidence, so the answer is verified on
  // arrival. Before the fix a branch verdict forced up to three rebuild rounds.
  const { result, events } = await drive({ prompt: "what is two plus two", verdict: "branch" });
  assert.equal(result.ok, true);
  assert.equal(result.verified, true);
  assert.equal(result.steps, 1, "a verified answer must finalize on the first step");
  assert.equal(result.interventions, 0, "no rebuild rounds against a verified answer");
  assert.ok(events.some((e) => e.type === "nfet.downgraded" && e.from === "branch"),
    "the branch verdict is recorded as downgraded, not silently dropped");
  assert.ok(!events.some((e) => e.type === "nfet.intervention"), "no intervention fired");
});

test("branch still governs an unverified trajectory", async () => {
  // "latest" demands fresh evidence the stub never gathers, so the answer stays
  // unverified and the controller is allowed to push back.
  const { result, events } = await drive({ prompt: "what is the latest price of X", verdict: "branch" });
  assert.equal(result.ok, true);
  const interventions = events.filter((e) => e.type === "nfet.intervention");
  assert.ok(interventions.length >= 1, "an unverified trajectory is still corrected");
  assert.ok(interventions.every((e) => e.reason === "unverified_trajectory"));
  assert.ok(result.interventions <= 3, "interventions remain capped");
  assert.ok(!events.some((e) => e.type === "nfet.downgraded"), "nothing to downgrade while unverified");
});

test("verify is honoured once while unverified, not looped on a verified answer", async () => {
  const unverified = await drive({ prompt: "what is the latest status of X", verdict: "verify" });
  assert.ok(unverified.events.some((e) => e.type === "nfet.intervention" && e.decision === "verify"),
    "an unverified answer earns a verification pass");

  const verified = await drive({ prompt: "what is two plus two", verdict: "verify" });
  assert.equal(verified.result.steps, 1, "a verified answer is not sent back to verify");
  assert.equal(verified.result.interventions, 0);
});

test("interventionGuidance carries the trajectory and forbids a rebuild", async () => {
  const { interventionGuidance } = await import("../lib/agent.mjs");
  const runner = { changes: [{ path: "a.py" }, { path: "b.py" }], commands: [{ command: "pytest" }] };
  const text = interventionGuidance("branch", runner, "Implemented parse() and verified it.\nmore detail");
  assert.match(text, /edited 2 file\(s\)/);
  assert.match(text, /ran 1 command\(s\)/);
  assert.match(text, /Implemented parse\(\) and verified it\./);
  assert.match(text, /do not discard correct work/i);
  assert.doesNotMatch(text, /more detail/, "only the first non-empty line is quoted");
});
