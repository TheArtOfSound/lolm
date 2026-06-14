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
<title>LOLM-NFET · status</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%2307090d'/%3E%3Cpath d='M5 7 Q20 7 26 16' stroke='%234ea1ff' stroke-width='2.2' fill='none'/%3E%3Cpath d='M5 12 Q19 12 26 16' stroke='%23b07fff' stroke-width='2.2' fill='none'/%3E%3Cpath d='M5 16 H26' stroke='%23ffb454' stroke-width='2.2'/%3E%3Cpath d='M5 20 Q19 20 26 16' stroke='%233fd6a0' stroke-width='2.2' fill='none'/%3E%3Cpath d='M5 25 Q20 25 26 16' stroke='%23ff6b81' stroke-width='2.2' fill='none'/%3E%3Ccircle cx='26' cy='16' r='2.6' fill='%23d7dde6'/%3E%3C/svg%3E">
<style>body{background:#07090d;color:#d7dde6;font:15px/1.6 -apple-system,system-ui,sans-serif;max-width:680px;margin:40px auto;padding:0 20px}
h1{font-size:20px}table{width:100%;border-collapse:collapse;margin:18px 0}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #1d2530}
th{font:11px ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;color:#5a6675}
a{color:#4ea1ff}.m{font:12px ui-monospace,monospace;color:#5a6675}</style></head>
<body><h1>LOLM-NFET · edge monitor</h1>
<p class="m">Cloudflare Worker watching ${health.origin} · last check ${when}</p>
<table><tr><th>line</th><th>uptime 24h</th><th>up / last hr</th><th>latency</th></tr>${rows}</table>
<p class="m">🟢 ready · 🟡 reachable, model loading/busy · 🔴 down · samples every 5 min</p>
<p><a href="/health">/health</a> · <a href="https://lolm.imagineqira.com">live demo →</a></p>
<p class="m" style="margin-top:24px;border-top:1px solid #1d2530;padding-top:14px">© 2026 Qira LLC · Bryan Leonard &amp; Brandyn Leonard · all rights reserved · patent pending</p>
</body></html>`;
}

// ---- cloud brain: shared memory + conversation sessions on D1 --------------
async function sha256hex(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function brainTurn(env, body) {
  const { session_id, role, content } = body;
  if (!session_id || !role || !content) return { error: "session_id, role, content required" };
  const now = Date.now();
  await env.BRAIN.prepare(
    "INSERT INTO sessions (id, created_at, last_at, turn_count) VALUES (?1, ?2, ?2, 1) " +
    "ON CONFLICT(id) DO UPDATE SET last_at=?2, turn_count=turn_count+1"
  ).bind(session_id, now).run();
  await env.BRAIN.prepare(
    "INSERT INTO turns (session_id, role, content, ts) VALUES (?, ?, ?, ?)"
  ).bind(session_id, String(role).slice(0, 16), String(content).slice(0, 20000), now).run();
  return { ok: true, ts: now };
}

async function brainSession(env, id, limit = 40) {
  const rows = await env.BRAIN.prepare(
    "SELECT role, content, ts FROM turns WHERE session_id=? ORDER BY ts ASC LIMIT ?"
  ).bind(id, Math.min(limit, 200)).all();
  return { session_id: id, turns: rows.results || [] };
}

async function brainRemember(env, body) {
  const text = String(body.text || "").trim();
  if (text.length < 8) return { error: "text too short" };
  const id = await sha256hex(text);
  const now = Date.now();
  await env.BRAIN.prepare(
    "INSERT INTO memory (id, text, kind, importance, source_session, ts, uses) " +
    "VALUES (?1, ?2, ?3, ?4, ?5, ?6, 0) ON CONFLICT(id) DO UPDATE SET " +
    "importance=MAX(importance, ?4), ts=?6"
  ).bind(id, text.slice(0, 4000), String(body.kind || "learning").slice(0, 24),
         Math.max(1, Math.min(5, parseInt(body.importance) || 3)),
         (body.source_session || null), now).run();
  return { ok: true, id };
}

async function brainRecall(env, q, limit = 6) {
  // Keyword overlap × importance, no neurons needed. Distinctive query words
  // (len>3) matched against memory text; ranked, and recall bumps `uses` so
  // the brain learns which memories actually help.
  const words = [...new Set((q || "").toLowerCase().match(/[a-z0-9]{4,}/g) || [])].slice(0, 12);
  if (!words.length) return { results: [], query_words: [] };
  const like = words.map(() => "text LIKE ?").join(" OR ");
  const binds = words.map((w) => `%${w}%`);
  const rows = await env.BRAIN.prepare(
    `SELECT id, text, kind, importance, source_session, ts, uses FROM memory WHERE ${like} LIMIT 60`
  ).bind(...binds).all();
  const scored = (rows.results || []).map((r) => {
    const t = r.text.toLowerCase();
    const matches = words.filter((w) => t.includes(w)).length;
    return { ...r, score: matches * (1 + 0.15 * (r.importance - 3)), matches };
  }).filter((r) => r.matches >= Math.min(2, words.length))
    .sort((a, b) => b.score - a.score).slice(0, Math.min(limit, 20));
  if (scored.length) {
    const ids = scored.map((r) => `'${r.id}'`).join(",");
    await env.BRAIN.prepare(`UPDATE memory SET uses=uses+1 WHERE id IN (${ids})`).run().catch(() => {});
  }
  return { results: scored, query_words: words };
}

async function brainStats(env) {
  const m = await env.BRAIN.prepare("SELECT COUNT(*) n, COALESCE(SUM(uses),0) uses FROM memory").first();
  const s = await env.BRAIN.prepare("SELECT COUNT(*) n FROM sessions").first();
  const t = await env.BRAIN.prepare("SELECT COUNT(*) n FROM turns").first();
  const top = await env.BRAIN.prepare(
    "SELECT text, kind, importance, uses FROM memory ORDER BY uses DESC, importance DESC LIMIT 8"
  ).all();
  const byKind = await env.BRAIN.prepare(
    "SELECT kind, COUNT(*) n FROM memory GROUP BY kind"
  ).all();
  return {
    memories: m?.n || 0, total_recalls: m?.uses || 0,
    sessions: s?.n || 0, conversation_turns: t?.n || 0,
    by_kind: byKind.results || [], most_used: top.results || [],
  };
}

// ---- multi-provider 70B cascade -------------------------------------------
// Each entry is an independent Llama-3.3-70B source. Workers AI runs on the CF
// account (no key); the rest are OpenAI-compatible and activate only when their
// key secret exists. Adding any free key (Groq is fastest) keeps 70B alive even
// when Cloudflare's neuron quota is exhausted.
function providerChain(env) {
  const chain = [{ name: "workers-ai", kind: "cf" }];
  if (env.GROQ_API_KEY) chain.push({
    name: "groq", kind: "openai", key: env.GROQ_API_KEY,
    url: "https://api.groq.com/openai/v1/chat/completions", model: "llama-3.3-70b-versatile" });
  if (env.CEREBRAS_API_KEY) chain.push({
    name: "cerebras", kind: "openai", key: env.CEREBRAS_API_KEY,
    url: "https://api.cerebras.ai/v1/chat/completions", model: "llama-3.3-70b" });
  if (env.TOGETHER_API_KEY) chain.push({
    name: "together", kind: "openai", key: env.TOGETHER_API_KEY,
    url: "https://api.together.xyz/v1/chat/completions",
    model: "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free" });
  if (env.OPENROUTER_API_KEY) chain.push({
    name: "openrouter", kind: "openai", key: env.OPENROUTER_API_KEY,
    url: "https://openrouter.ai/api/v1/chat/completions",
    model: "meta-llama/llama-3.3-70b-instruct:free" });
  return chain;
}

async function callOpenAICompatible(provider, messages, max_tokens) {
  const r = await fetch(provider.url, {
    method: "POST",
    headers: { "Content-Type": "application/json",
               "Authorization": `Bearer ${provider.key}` },
    body: JSON.stringify({ model: provider.model, messages, max_tokens, stream: false }),
    signal: AbortSignal.timeout(45000),
  });
  if (!r.ok) {
    const body = await r.text();
    const quota = r.status === 429 || /quota|rate.?limit|insufficient|exceeded/i.test(body);
    throw Object.assign(new Error(`${provider.name} ${r.status}: ${body.slice(0, 120)}`), { quota });
  }
  const j = await r.json();
  return (j.choices && j.choices[0] && j.choices[0].message && j.choices[0].message.content) || "";
}

async function generate70B(env, messages, max_tokens, modelOverride) {
  const chain = providerChain(env);
  const tried = [];
  let lastQuota = false;
  // Two passes. A simultaneous transient failure across every free tier (burst
  // rate-limiting) usually clears within ~a second, so if the whole chain
  // fails, back off briefly and try once more before giving up. Independent
  // providers + a retry pass means 70B essentially never goes dark for a single
  // request unless every account is truly exhausted at once.
  for (let pass = 0; pass < 2; pass++) {
    if (pass > 0) await new Promise((r) => setTimeout(r, 600));
    for (const provider of chain) {
      const t0 = Date.now();
      try {
        let text;
        if (provider.kind === "cf") {
          const r = await env.AI.run(modelOverride || "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
                                     { messages, max_tokens });
          text = (r && r.response) || "";
          // Workers AI sometimes reports failure in-band instead of throwing.
          if (!text.trim() && r && r.error) throw new Error(`workers-ai: ${r.error}`);
        } else {
          text = await callOpenAICompatible(provider, messages, max_tokens);
        }
        if (text && text.trim()) {
          return { text, model: provider.model || "llama-3.3-70b", provider: provider.name,
                   ms: Date.now() - t0, tried_providers: tried, retried: pass > 0 };
        }
        tried.push({ provider: provider.name, error: "empty", pass });
      } catch (e) {
        const msg = String(e.message || e);
        const quota = e.quota || /neuron|allocation|4006|Paid plan|quota|rate.?limit/i.test(msg);
        lastQuota = quota;
        tried.push({ provider: provider.name, error: msg.slice(0, 100), quota, pass });
        // continue to the next independent provider
      }
    }
  }
  return { error: "all 70B providers unavailable", tried_providers: tried,
           quota_exhausted: lastQuota,
           hint: "add a free GROQ_API_KEY (or CEREBRAS/TOGETHER/OPENROUTER) as a worker secret" };
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const p = url.pathname;
    const json = (obj, s = 200) => new Response(JSON.stringify(obj, null, 2), {
      status: s, headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
    });
    const authed = () => {
      const a = request.headers.get("authorization") || "";
      return env.AI_SECRET && a === `Bearer ${env.AI_SECRET}`;
    };

    // Cloud brain. Writes/reads of conversation + memory require the shared
    // secret (the origin box holds it). /brain/stats is public read-only so the
    // growing memory is verifiable by anyone.
    if (p === "/brain/stats") return json(await brainStats(env));
    if (p.startsWith("/brain/")) {
      if (!authed()) return json({ error: "unauthorized" }, 401);
      try {
        if (p === "/brain/turn" && request.method === "POST")
          return json(await brainTurn(env, await request.json()));
        if (p === "/brain/session")
          return json(await brainSession(env, url.searchParams.get("id"),
                                         parseInt(url.searchParams.get("limit")) || 40));
        if (p === "/brain/remember" && request.method === "POST")
          return json(await brainRemember(env, await request.json()));
        if (p === "/brain/recall")
          return json(await brainRecall(env, url.searchParams.get("q"),
                                        parseInt(url.searchParams.get("limit")) || 6));
      } catch (e) {
        return json({ error: String(e).slice(0, 200) }, 500);
      }
      return json({ error: "unknown brain route" }, 404);
    }

    // AI answer endpoint — Llama-70B via a CASCADE of INDEPENDENT providers, so
    // one account's quota dying never takes 70B down. Order: Cloudflare Workers
    // AI (on-account, no key) → Groq → Cerebras → Together → OpenRouter (each a
    // separate free account, enabled only when its key secret is set). All keys
    // stay in Cloudflare; the origin box just calls this one endpoint.
    if (p === "/ai/generate" && request.method === "POST") {
      const auth = request.headers.get("authorization") || "";
      if (!env.AI_SECRET || auth !== `Bearer ${env.AI_SECRET}`) {
        return json({ error: "unauthorized" }, 401);
      }
      let body;
      try { body = await request.json(); } catch { return json({ error: "bad json" }, 400); }
      const messages = Array.isArray(body.messages) ? body.messages : [];
      const max_tokens = Math.min(Math.max(parseInt(body.max_tokens) || 512, 16), 8192);
      const result = await generate70B(env, messages, max_tokens, body.model);
      if (result.text) return json(result);
      return json(result, result.quota_exhausted ? 429 : 502);
    }

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
