/**
 * lolm-edge — Cloudflare edge layer for the LOLM-NFET demo.
 *
 * Three jobs, all reversible and DNS-free (served from *.workers.dev):
 *   1. Cron synthetic monitor — every 5 min, ping each backend line's
 *      /status, record latency + up/down into KV (rolling window + uptime
 *      counters). The little AWS box can't watch itself; the edge can.
 *   2. Edge cache for the replay library — replays are immutable JSON, so
 *      the Cloudflare cache serves them globally and spares the origin.
 *   3. Public read endpoints — /health, /uptime, and a small status page —
 *      so uptime is visible without touching the origin.
 *
 * It never proxies live agent runs (those must hit the origin's single-flight
 * gate directly); it only watches and caches.
 */

const WINDOW = 288; // 5-min samples over 24h

function lines(env) {
  // "demo:0.6B server,demo4b:4B lab line" -> [{path, label}]
  return (env.LINES || "demo:0.6B").split(",").map((pair) => {
    const [path, ...rest] = pair.split(":");
    return { path: path.trim(), label: (rest.join(":") || path).trim() };
  });
}

async function probe(env, line) {
  const url = `${env.ORIGIN}/api/${line.path}/status`;
  const t0 = Date.now();
  try {
    const r = await fetch(url, { cf: { cacheTtl: 0 }, signal: AbortSignal.timeout(8000) });
    const ms = Date.now() - t0;
    if (!r.ok) return { up: false, ms, ready: false, busy: false, code: r.status };
    const j = await r.json();
    return { up: true, ms, ready: !!j.model_ready, busy: !!j.busy };
  } catch (e) {
    return { up: false, ms: Date.now() - t0, ready: false, busy: false, err: String(e).slice(0, 80) };
  }
}

async function recordSample(env, ts) {
  const out = {};
  for (const line of lines(env)) {
    const res = await probe(env, line);
    const key = `line:${line.path}`;
    const prev = (await env.MONITOR.get(key, "json")) || {
      label: line.label, samples: [], up_count: 0, total: 0,
    };
    prev.label = line.label;
    prev.samples.push({ ts, ...res });
    if (prev.samples.length > WINDOW) prev.samples = prev.samples.slice(-WINDOW);
    prev.total += 1;
    if (res.up && res.ready) prev.up_count += 1;
    prev.last = { ts, ...res };
    await env.MONITOR.put(key, JSON.stringify(prev));
    out[line.path] = prev.last;
  }
  await env.MONITOR.put("last_run", String(ts));
  return out;
}

async function readHealth(env) {
  const out = { origin: env.ORIGIN, checked: Number(await env.MONITOR.get("last_run")) || null, lines: {} };
  for (const line of lines(env)) {
    const data = await env.MONITOR.get(`line:${line.path}`, "json");
    if (!data) { out.lines[line.path] = { label: line.label, status: "no-data" }; continue; }
    const recent = data.samples.slice(-12); // last hour
    const upRecent = recent.filter((s) => s.up && s.ready).length;
    const avgMs = recent.length ? Math.round(recent.reduce((a, s) => a + s.ms, 0) / recent.length) : null;
    out.lines[line.path] = {
      label: data.label,
      last: data.last,
      uptime_24h: data.total ? +(100 * data.up_count / data.total).toFixed(1) : null,
      up_last_hour: `${upRecent}/${recent.length}`,
      avg_latency_ms: avgMs,
      samples: data.total,
    };
  }
  return out;
}

async function cachedReplay(request, env, ctx, path) {
  const cache = caches.default;
  const cacheKey = new Request(new URL(request.url).toString(), request);
  let hit = await cache.match(cacheKey);
  if (hit) {
    hit = new Response(hit.body, hit);
    hit.headers.set("x-lolm-edge", "hit");
    return hit;
  }
  const origin = await fetch(`${env.ORIGIN}${path}`, { signal: AbortSignal.timeout(8000) });
  const resp = new Response(origin.body, origin);
  resp.headers.set("Cache-Control", "public, max-age=300");
  resp.headers.set("Access-Control-Allow-Origin", "*");
  resp.headers.set("x-lolm-edge", "miss");
  if (origin.ok) ctx.waitUntil(cache.put(cacheKey, resp.clone()));
  return resp;
}

function statusPage(health) {
  const rows = Object.entries(health.lines).map(([path, l]) => {
    const up = l.last && l.last.up && l.last.ready;
    const dot = up ? "🟢" : (l.last && l.last.up ? "🟡" : "🔴");
    return `<tr><td>${dot} ${l.label || path}</td><td>${l.uptime_24h ?? "—"}%</td>` +
           `<td>${l.up_last_hour ?? "—"}</td><td>${l.avg_latency_ms ?? "—"} ms</td></tr>`;
  }).join("");
  const when = health.checked ? new Date(health.checked).toISOString() : "never";
  return `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LOLM edge status</title>
<style>body{background:#07090d;color:#d7dde6;font:15px/1.6 -apple-system,system-ui,sans-serif;max-width:680px;margin:40px auto;padding:0 20px}
h1{font-size:20px}table{width:100%;border-collapse:collapse;margin:18px 0}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #1d2530}
th{font:11px ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;color:#5a6675}
a{color:#4ea1ff}.m{font:12px ui-monospace,monospace;color:#5a6675}</style></head>
<body><h1>LOLM-NFET · edge monitor</h1>
<p class="m">Cloudflare Worker watching ${health.origin} · last check ${when}</p>
<table><tr><th>line</th><th>uptime 24h</th><th>up / last hr</th><th>latency</th></tr>${rows}</table>
<p class="m">🟢 ready · 🟡 reachable, model loading/busy · 🔴 down · samples every 5 min</p>
<p><a href="/health">/health</a> · <a href="https://lolm.imagineqira.com">live demo →</a></p>
</body></html>`;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const p = url.pathname;
    const json = (obj, s = 200) => new Response(JSON.stringify(obj, null, 2), {
      status: s, headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
    });

    if (p === "/health" || p === "/uptime") return json(await readHealth(env));
    if (p === "/check" && request.method === "POST") return json(await recordSample(env, Date.now()));
    if (p.startsWith("/replays/")) return cachedReplay(request, env, ctx, p);
    if (p === "/" || p === "/status") {
      return new Response(statusPage(await readHealth(env)), {
        headers: { "content-type": "text/html; charset=utf-8" },
      });
    }
    return json({ error: "not found", endpoints: ["/", "/health", "/replays/*"] }, 404);
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(recordSample(env, Date.now()));
  },
};
