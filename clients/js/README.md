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
