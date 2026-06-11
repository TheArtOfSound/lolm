# lolm-edge — Cloudflare edge layer

A Cloudflare Worker that watches and accelerates the LOLM-NFET demo without
touching DNS (served from `*.workers.dev`, so it composes with the existing
GoDaddy → AWS setup instead of replacing it).

**Live:** https://lolm-edge.bryanleonard237.workers.dev

## What it does

| Job | How |
|---|---|
| **Synthetic uptime monitor** | A `*/5 * * * *` cron pings each backend line's `/status` (the 0.6B box + the 4B lab line), records latency and ready/down state into Workers KV, and keeps a 24h rolling window. The little 2-vCPU box can't reliably watch itself; the edge can. |
| **Edge cache for replays** | Replay JSON is immutable, so `/replays/*` is served from Cloudflare's global cache (`x-lolm-edge: hit`), sparing the origin. |
| **Public status** | `/` renders a status page; `/health` returns JSON uptime for both lines. Linked from the site footers. |

It deliberately **never proxies live agent runs** — those must hit the origin's
single-flight gate directly. The edge only watches and caches.

## Deploy

```bash
cd edge/cloudflare
wrangler kv namespace create MONITOR      # once; put the id in wrangler.jsonc
wrangler deploy
curl -X POST https://lolm-edge.<account>.workers.dev/check   # seed first sample
```

## Endpoints

- `GET /` — status page
- `GET /health` — uptime JSON (per line: last sample, 24h uptime %, avg latency)
- `GET /replays/<id>.json` — edge-cached replay
- `POST /check` — trigger a probe immediately (same work the cron does)
