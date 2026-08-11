// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import { lookup } from "node:dns/promises";
import { isIP } from "node:net";
import { objectSchema } from "./shared.mjs";

function privateAddress(address) {
  const host = String(address || "").toLowerCase();
  return host === "::1" || host === "0.0.0.0" || /^127\./.test(host) || /^10\./.test(host) || /^192\.168\./.test(host) || /^169\.254\./.test(host) || /^172\.(1[6-9]|2\d|3[01])\./.test(host) || /^(?:fc|fd|fe80)/i.test(host);
}

async function publicUrl(value) {
  let url; try { url = new URL(String(value || "")); } catch { throw Object.assign(new Error("Invalid URL."), { code: "INVALID_URL" }); }
  if (!["http:", "https:"].includes(url.protocol)) throw Object.assign(new Error("Only HTTP and HTTPS URLs are supported."), { code: "INVALID_URL" });
  const host = url.hostname.toLowerCase();
  if (host === "localhost" || host.endsWith(".local") || privateAddress(host)) throw Object.assign(new Error("Private and loopback URLs are blocked."), { code: "PRIVATE_URL_BLOCKED" });
  const addresses = isIP(host) ? [{ address: host }] : await lookup(host, { all: true });
  if (!addresses.length || addresses.some((row) => privateAddress(row.address))) throw Object.assign(new Error("URL resolved to a private or loopback address."), { code: "PRIVATE_URL_BLOCKED" });
  return url;
}

function decodeHtml(value) {
  return String(value || "").replace(/<script[\s\S]*?<\/script>/gi, " ").replace(/<style[\s\S]*?<\/style>/gi, " ").replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/\s+/g, " ").trim();
}

async function fetchText(value, timeoutMs = 20_000) {
  const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    let current = await publicUrl(value); let response;
    for (let redirects = 0; redirects <= 5; redirects++) {
      response = await fetch(current, { redirect: "manual", headers: { "user-agent": "LOLM-CLI/1.2" }, signal: controller.signal });
      if (![301, 302, 303, 307, 308].includes(response.status)) break;
      const location = response.headers.get("location"); if (!location || redirects === 5) throw new Error("Invalid or excessive redirect chain.");
      current = await publicUrl(new URL(location, current).href);
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const type = response.headers.get("content-type") || ""; if (!/text|json|xml|html/.test(type)) throw new Error(`Unsupported content type: ${type}`);
    const body = await response.text(); if (Buffer.byteLength(body) > 2 * 1024 * 1024) throw new Error("Response exceeds 2 MB limit.");
    return { url: current.href, body };
  } finally { clearTimeout(timer); }
}

export function registerWebTools(registry) {
  registry.register({
    name: "web.search", aliases: ["web_search"], description: "Search the public web for current titles, URLs, and snippets.", risk: "read", approval: "auto",
    inputSchema: objectSchema({ query: { type: "string", minLength: 1 }, limit: { type: "integer", minimum: 1, maximum: 10 } }, ["query"]),
    execute: async ({ query, limit = 5 }) => {
      const { body } = await fetchText(`https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`); const results = [];
      const pattern = /class="result__a"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>[\s\S]*?class="result__snippet"[^>]*>([\s\S]*?)<\/a>/g;
      for (const match of body.matchAll(pattern)) { let url = match[1].replace(/&amp;/g, "&"); try { const parsed = new URL(url, "https://duckduckgo.com"); url = parsed.searchParams.get("uddg") || parsed.href; } catch {} results.push({ title: decodeHtml(match[2]), url, snippet: decodeHtml(match[3]) }); if (results.length >= limit) break; }
      return { query, results };
    },
  });
  registry.register({
    name: "web.fetch", aliases: ["fetch_url"], description: "Fetch bounded readable text from a public HTTP or HTTPS URL with SSRF protection.", risk: "read", approval: "auto",
    inputSchema: objectSchema({ url: { type: "string", minLength: 1 } }, ["url"]), execute: async ({ url }) => { const result = await fetchText(url); return { url: result.url, text: decodeHtml(result.body).slice(0, 40_000) }; },
  });
}
