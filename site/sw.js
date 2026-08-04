/* LOLM-NFET service worker — make the demo work anywhere, even with no network.
 *
 * Resilience tiers, from best to last-resort:
 *   1. live backend (Workers AI 70B + LOLM telemetry)        — needs network
 *   2. cached replays of real runs                            — works offline
 *   3. in-browser answer engine (transformers.js, opt-in)    — works offline
 *
 * This worker guarantees tiers 2 and 3 are always reachable: it precaches the
 * whole site shell and every replay at install, and serves them cache-first so
 * the page loads and replays play with zero connectivity. Live API calls are
 * network-only (never cached — they must hit the origin's single-flight gate),
 * but their failure degrades gracefully in the page, not here.
 */

const CACHE = "lolm-v21-workspace-identity-2026-08-03";  // bump on any shell/asset change
// v21: browser mints free API key so workspace chats persist (X-LOLM-Api-Key).
// v20: generated artifacts render as downloadable cards; exact-byte PDF delivery.
// v19: product/pricing unification — canonical product-config, correct plan
// quotas, safer pricing page, honest model wording.
const SHELL = [
  "/", "/index.html", "/try.html", "/pricing.html", "/app.html",
  "/og-card.png", "/lolm-ds.css", "/lolm-ds.js", "/artifact-delivery-ui.js",
  "/product-config.json", "/product-config.js",
  "/manifest.webmanifest", "/replays/index.json",
];

self.addEventListener("install", (event) => {
  // Take over IMMEDIATELY. Without this, a new worker waits until every LOLM
  // tab is closed — long-lived app tabs kept serving a week-old UI while every
  // deploy silently piled up behind them.
  self.skipWaiting();
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(SHELL.map((u) => new Request(u, { cache: "reload" })));
    // also precache every replay listed in the index, so all recorded runs
    // are available offline
    try {
      const idx = await (await fetch("/replays/index.json", { cache: "reload" })).json();
      const ids = (idx.replays || []).map((r) => `/replays/${r.id}.json`);
      await Promise.all(ids.map((u) =>
        cache.add(new Request(u, { cache: "reload" })).catch(() => {})));
    } catch (e) { /* offline at install — shell is still cached */ }
    self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
    self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET") return;

  // Live API + product config: network-only. Never cache mutable status/pricing.
  if (url.pathname.startsWith("/api/")) return;
  if (url.pathname === "/product-config.json" || url.pathname === "/product-config.js") {
    event.respondWith(fetch(event.request).catch(async () => {
      const cache = await caches.open(CACHE);
      return (await cache.match(event.request)) || Response.error();
    }));
    return;
  }

  // Media: hand straight to the browser, no worker in the middle. A <video> fetches
  // by Range, and cache.put() REJECTS a 206 Partial Content — which would fall
  // through the catch below and answer a video request with index.html, breaking
  // playback outright. Big clips also have no business in an offline shell.
  if (url.pathname.startsWith("/media/") || event.request.headers.has("range")) return;

  const isHTML = event.request.mode === "navigate" ||
                 (event.request.headers.get("accept") || "").includes("text/html");

  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    if (isHTML) {
      // Network-first for pages: always fresh when online, cached when offline.
      try {
        const resp = await fetch(event.request);
        if (resp && resp.ok) cache.put(event.request, resp.clone());
        return resp;
      } catch (e) {
        return (await cache.match(event.request)) || (await cache.match("/try.html"))
            || (await cache.match("/index.html"));
      }
    }
    // Static + replays: cache-first with background revalidate.
    const cached = await cache.match(event.request);
    const network = fetch(event.request).then((resp) => {
      // status must be exactly 200: resp.ok also covers 206, which cache.put rejects.
      if (resp && resp.status === 200 && url.origin === self.location.origin) {
        cache.put(event.request, resp.clone()).catch(() => {});
      }
      return resp;
    }).catch(() => null);
    return cached || (await network) || cache.match("/index.html");
  })());
});
