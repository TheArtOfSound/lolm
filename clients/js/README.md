# lolm-nfet-client

Client for the **LOLM-NFET agent protocol** — the agent at
[lolm.imagineqira.com](https://lolm.imagineqira.com) whose control decisions
(continue / retrieve / verify / branch / finalize) come from **measured latent
telemetry** — entropy, hidden drift, gate balance, regime entropy — instead of
prompted self-reports.

Every run streams as Server-Sent Events: draft tokens, the decisions with the
z-scores behind them, the actions they triggered, and a **proof receipt**
comparing the result against base mode. This package speaks that protocol
from Node (≥18) or the browser. Zero dependencies.

```bash
npm install lolm-nfet-client
```

## Live run

```js
import { runAgent, friendly } from "lolm-nfet-client";

const result = await runAgent({
  command: "Why check notes when you're unsure?",
  // defaults to the public demo at https://lolm.imagineqira.com
  onToken: (t) => { if (t.channel === "final") process.stdout.write(t.token); },
  onDecision: (d) => console.log("\n⟶", friendly({ event: "decision", data: d })),
  onProof: (p) => console.log("\n⊨", p.verdict),
});

console.log("\nended by:", result.ended_by, "| controls:", result.proof.control_counts);
```

The public demo is a tiny 0.6B research model on a shared 2-vCPU box — one
run at a time, a few per visitor per hour, ~1–2 minutes per run. A `429`
throws `AgentRunError` with the server's explanation. Against your own
workspace, point at the full agent endpoint and pass budgets:

```js
await runAgent({
  baseUrl: "http://127.0.0.1:7866",
  endpoint: "/api/agent/nfet/run/stream",
  command: "…",
  body: { max_segments: 6, segment_tokens: 48, allow_web: true },
});
```

## Memory

Give the agent **in-conversation** memory (the open thread) and **cross-session**
memory (durable facts it recalls in every conversation):

```js
import { runAgent, getMemory, rememberFact, forgetMemory } from "lolm-nfet-client";

const owner = "user-42";                       // your per-user key (no accounts)

// teach it something durable; `extract` lets the model mine the fact for you
await rememberFact({ owner, text: "I'm building an NFT pipeline in Python", extract: true });

// later, in a brand-new conversation, it remembers — pass history + memory:
await runAgent({
  command: "what am I working on, and what did I just say?",
  history: [{ role: "user", content: "hey" }, { role: "assistant", content: "Hi!" }],
  memory: (await getMemory({ owner })).map((m) => m.text),
  onToken: (t) => { if (t.channel === "final") process.stdout.write(t.token); },
});

// fully transparent — list and delete anything
const facts = await getMemory({ owner });      // [{id, text, kind, created_at}, …]
await forgetMemory({ owner, id: facts[0].id }); // or { owner, all: true }
```

## Build something visual

Turn a prompt into a complete, self-contained app you render in a sandboxed
iframe — the browser is the runtime, so a game is actually playable:

```js
import { buildVisual } from "lolm-nfet-client";

const { html } = await buildVisual({ task: "a playable snake game" });
// <iframe sandbox="allow-scripts" srcdoc={html}>  ← no network, no parent access
```

## Run code

The agentic loop writes real code, runs it in a **network-isolated bwrap jail**,
reads the failure, and fixes it — streamed live:

```js
import { runCode } from "lolm-nfet-client";

const done = await runCode({
  task: "print the first 10 prime numbers",
  onEvent: (e) => console.log(e.event, e.data),  // file_changed / command_finished / …
});
console.log(done.ran ? "ran in the jail" : "couldn't complete");
```

## Replays

Recorded real runs play through the same handlers — instant, no backend:

```js
import { playReplay } from "lolm-nfet-client";

await playReplay("https://lolm.imagineqira.com/replays/gate.json", {
  speed: 0, // instant; 1 = paced like the live stream
  onDecision: (d) => console.log(d.decision.label, d.decision.source, d.decision.zscores),
});
```

## Plain-English narration

`friendly(event)` returns the same wording the public Try page uses
("It noticed it wasn't sure — checking its notes"), or `null` for events
with nothing worth saying. Build a chat-style UI in a dozen lines.

## Protocol

| event | payload |
|---|---|
| `run_start` | command, head_trained, budgets |
| `segment_start` | segment index |
| `token` | `{token, channel: draft\|verify\|branch:k\|final, nfet?: {entropy, drift, gate, regime, control}}` |
| `decision` | control label, **source** (`head`/`heuristic`/`budget`), reason, z-scores |
| `action` | what the decision did (evidence added, verdict, branch kept) |
| `phase` | `finalize`, `base_comparison` |
| `proof` | receipt: verdict, control counts, similarity vs base |
| `run_done` | the full result payload |

## License

MIT (this client). The LOLM model and workspace are licensed separately under
the LOLM Community License — see [lolm.imagineqira.com](https://lolm.imagineqira.com).
