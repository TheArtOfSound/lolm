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

const CACHE = "lolm-nfet-v2";   // bump on any shell/asset change so returning
                                // visitors get the update (activate clears old)
const SHELL = [
  "/", "/index.html", "/try.html", "/og-card.png",
  "/manifest.webmanifest", "/replays/index.json",
];

self.addEventListener("install", (event) => {
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

  // Live API: network-only. Never cache a single-flight run; let the page handle
  // failure (offline banner / replays / in-browser engine).
  if (url.pathname.startsWith("/api/")) return;

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
      if (resp && resp.ok && url.origin === self.location.origin) cache.put(event.request, resp.clone());
      return resp;
    }).catch(() => null);
    return cached || (await network) || cache.match("/index.html");
  })());
});
