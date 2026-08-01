# lolm-nfet-client

Zero-dependency Node/browser client for the LOLM HTTP and Server-Sent Events
protocol. Version `0.3.0-beta.1` adds bounded requests, standards-compliant SSE
framing, typed terminal-event failures, cancellation, and authenticated memory.

```bash
npm install lolm-nfet-client
```

## Live run

```js
import { runAgent, friendly } from "lolm-nfet-client";

const result = await runAgent({
  command: "Why check notes when you're unsure?",
  timeoutMs: 120_000,
  idleTimeoutMs: 30_000,
  onToken: (t) => {
    if (t.channel === "final") process.stdout.write(t.token);
  },
  onDecision: (d) => console.error(friendly({ event: "decision", data: d })),
});
console.log(result.ended_by);
```

The SSE parser accepts LF or CRLF, fragmented UTF-8 chunks, comments, optional
single spaces after `:`, multiline `data`, and a final event without a blank
terminator. Per-event and whole-stream byte limits are enforced.

## Authenticated memory

Durable memory is isolated by the authenticated API-key principal. The old
caller-controlled `owner` namespace is intentionally ignored.

```js
import { getMemory, rememberFact, forgetMemory } from "lolm-nfet-client";

const apiKey = process.env.LOLM_API_KEY;
await rememberFact({ apiKey, text: "I prefer Python." });
const facts = await getMemory({ apiKey });
await forgetMemory({ apiKey, id: facts[0].id });
```

## Code and visual streams

```js
import { runCode, buildVisual } from "lolm-nfet-client";

const { done, receipt } = await runCode({
  task: "print the first 10 primes",
  apiKey: process.env.LOLM_API_KEY,
  onEvent: ({ event, data }) => console.error(event, data),
});

const visual = await buildVisual({ task: "a playable snake game" });
// visual contains HTML plus the matching visual receipt. Consumers must still
// verify the receipt/content before treating the artifact as trusted.
```

`runAgent`, `runCode`, and `buildVisual` reject streams missing their required
terminal events. `buildVisual` also rejects contradictory done/receipt run IDs.
All network helpers accept `signal` and `timeoutMs`; streaming helpers also
accept `idleTimeoutMs`, `maxEventBytes`, and `maxStreamBytes`.

## Replays and receipt ledger

```js
import { playReplay, listCodeReceipts } from "lolm-nfet-client";

await playReplay("https://example.test/replay.json", {
  timeoutMs: 15_000,
  maxResponseBytes: 5 * 1024 * 1024,
});
const { receipts } = await listCodeReceipts({ limit: 20 });
```

## License

MIT for this client. The model and workspace are licensed separately under the
LOLM Community License.
