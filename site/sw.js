/* Documentation-only service worker. No API response or browser agent is cached. */
const CACHE = "lolm-docs-v1-2026-08-08-qira-apps";
const SHELL = ["/", "/index.html", "/install.html", "/docs.html", "/research.html", "/lolm-ds.css", "/lolm-ds.js", "/manifest.webmanifest"];
self.addEventListener("install", (event) => { self.skipWaiting(); event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL))); });
self.addEventListener("activate", (event) => { event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))).then(() => self.clients.claim())); });
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/")) return;
  event.respondWith(fetch(event.request).then((response) => {
    if (response.status === 200 && url.origin === self.location.origin) caches.open(CACHE).then((cache) => cache.put(event.request, response.clone()));
    return response;
  }).catch(() => caches.match(event.request).then((hit) => hit || caches.match("/index.html"))));
});
