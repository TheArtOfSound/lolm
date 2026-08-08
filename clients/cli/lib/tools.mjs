// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Local tools used by the provider model under explicit CLI approval. */
import { access, mkdir, readFile, readdir, rename, stat, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { spawn } from "node:child_process";
import { lookup } from "node:dns/promises";
import { isIP } from "node:net";
import { confirm } from "./tui.mjs";

const MAX_READ = 1024 * 1024;
const SKIP = new Set([".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__"]);

export const TOOL_DEFINITIONS = [
  ["list_files", "List files under a directory before editing.", { path: { type: "string" }, depth: { type: "integer" } }],
  ["read_file", "Read a UTF-8 text file. Always read a file before changing it.", { path: { type: "string" } }, ["path"]],
  ["search_files", "Search repository text with a regular expression.", { query: { type: "string" }, path: { type: "string" } }, ["query"]],
  ["web_search", "Search the public web for current information and return titles, URLs, and snippets.", { query: { type: "string" }, limit: { type: "integer" } }, ["query"]],
  ["fetch_url", "Fetch readable text from a public HTTP or HTTPS URL.", { url: { type: "string" } }, ["url"]],
  ["write_file", "Create or replace a text file on the user's computer.", { path: { type: "string" }, content: { type: "string" } }, ["path", "content"]],
  ["run_command", "Run a shell command in the current working directory for build, test, or inspection.", { command: { type: "string" }, timeout_ms: { type: "integer" } }, ["command"]],
].map(([name, description, properties, required = []]) => ({
  type: "function",
  function: { name, description, parameters: { type: "object", properties, required, additionalProperties: false } },
}));

function resolvePath(cwd, value = ".") {
  return resolve(cwd, String(value || "."));
}

async function walk(root, depth, prefix = "", out = []) {
  if (depth < 0 || out.length >= 500) return out;
  const entries = await readdir(root, { withFileTypes: true });
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    if (SKIP.has(entry.name)) continue;
    const shown = join(prefix, entry.name);
    out.push(entry.isDirectory() ? `${shown}/` : shown);
    if (entry.isDirectory()) await walk(join(root, entry.name), depth - 1, shown, out);
    if (out.length >= 500) break;
  }
  return out;
}

function commandAllowed(command) {
  const text = String(command || "").trim();
  const blocked = [
    /(^|[;&|])\s*sudo\b/i,
    /\brm\s+(-[^\s]*r[^\s]*f|-[^\s]*f[^\s]*r)\s+(?:\/|~|\$HOME)(?:\s|$)/i,
    /\b(?:shutdown|reboot|halt|mkfs|diskutil\s+erase|dd\s+if=)\b/i,
    /\bgit\s+(?:reset\s+--hard|clean\s+-[^\s]*f)/i,
  ];
  return text && !blocked.some((pattern) => pattern.test(text));
}

function privateAddress(address) {
  const host = String(address || "").toLowerCase();
  return host === "::1" || host === "0.0.0.0" || /^127\./.test(host) || /^10\./.test(host)
    || /^192\.168\./.test(host) || /^169\.254\./.test(host) || /^172\.(1[6-9]|2\d|3[01])\./.test(host)
    || /^fc|^fd|^fe80/i.test(host);
}

async function publicUrl(value) {
  let url;
  try { url = new URL(String(value || "")); } catch { throw new Error("invalid URL"); }
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("only HTTP and HTTPS URLs are supported");
  const host = url.hostname.toLowerCase();
  if (host === "localhost" || host.endsWith(".local") || privateAddress(host)) {
    throw new Error("private and loopback URLs are blocked");
  }
  const addresses = isIP(host) ? [{ address: host }] : await lookup(host, { all: true });
  if (!addresses.length || addresses.some((row) => privateAddress(row.address))) throw new Error("URL resolved to a private or loopback address");
  return url;
}

function decodeHtml(value) {
  return String(value || "").replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/\s+/g, " ").trim();
}

async function fetchText(url, timeoutMs = 20_000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    let current = await publicUrl(url);
    let response;
    for (let redirects = 0; redirects <= 5; redirects++) {
      response = await fetch(current, { redirect: "manual", headers: { "user-agent": "LOLM-CLI/1.1" }, signal: controller.signal });
      if (![301, 302, 303, 307, 308].includes(response.status)) break;
      const location = response.headers.get("location");
      if (!location) throw new Error("redirect response did not include a location");
      if (redirects === 5) throw new Error("too many redirects");
      current = await publicUrl(new URL(location, current).href);
    }
    const type = response.headers.get("content-type") || "";
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    if (!/text|json|xml|html/.test(type)) throw new Error(`unsupported content type: ${type}`);
    const text = await response.text();
    if (Buffer.byteLength(text) > 2 * 1024 * 1024) throw new Error("response exceeds 2 MB limit");
    return text;
  } finally { clearTimeout(timer); }
}

function run(command, cwd, timeoutMs) {
  return new Promise((resolvePromise) => {
    const child = spawn(process.env.SHELL || "/bin/sh", ["-lc", command], { cwd, env: process.env, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "", stderr = "", timedOut = false;
    const cap = (current, chunk) => `${current}${chunk}`.slice(-256 * 1024);
    child.stdout.on("data", (chunk) => { stdout = cap(stdout, chunk); });
    child.stderr.on("data", (chunk) => { stderr = cap(stderr, chunk); });
    const timer = setTimeout(() => { timedOut = true; child.kill("SIGTERM"); }, timeoutMs);
    child.on("exit", (code, signal) => {
      clearTimeout(timer);
      resolvePromise({ ok: code === 0 && !timedOut, exit_code: code, signal, timed_out: timedOut, stdout, stderr });
    });
    child.on("error", (error) => { clearTimeout(timer); resolvePromise({ ok: false, error: error.message, stdout, stderr }); });
  });
}

function runFile(command, args, cwd, timeoutMs) {
  return new Promise((resolvePromise) => {
    const child = spawn(command, args, { cwd, env: process.env, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "", stderr = "", timedOut = false;
    child.stdout.on("data", (chunk) => { stdout = `${stdout}${chunk}`.slice(-256 * 1024); });
    child.stderr.on("data", (chunk) => { stderr = `${stderr}${chunk}`.slice(-256 * 1024); });
    const timer = setTimeout(() => { timedOut = true; child.kill("SIGTERM"); }, timeoutMs);
    child.on("exit", (code, signal) => { clearTimeout(timer); resolvePromise({ ok: code === 0 && !timedOut, exit_code: code, signal, timed_out: timedOut, stdout, stderr }); });
    child.on("error", (error) => { clearTimeout(timer); resolvePromise({ ok: false, error: error.message, stdout, stderr }); });
  });
}

export function createToolRunner({ cwd = process.cwd(), yes = false, dryRun = false, onAction = () => {} } = {}) {
  const root = resolve(cwd);
  const changes = [];
  const commands = [];
  let evidence = 0;
  let verified = false;
  async function approve(label) { return yes || await confirm(label); }

  return {
    changes,
    commands,
    get evidence() { return evidence; },
    get verified() { return verified; },
    async execute(call) {
      const args = call.arguments || {};
      const name = call.name;
      if (name === "list_files") {
        const target = resolvePath(root, args.path || ".");
        const files = await walk(target, Math.max(0, Math.min(Number(args.depth ?? 2), 6)));
        evidence++;
        return { ok: true, root: target, files };
      }
      if (name === "read_file") {
        const path = resolvePath(root, args.path);
        const info = await stat(path);
        if (!info.isFile()) return { ok: false, error: "not a file" };
        if (info.size > MAX_READ) return { ok: false, error: `file exceeds ${MAX_READ} byte read limit` };
        evidence++;
        return { ok: true, path, content: await readFile(path, "utf8") };
      }
      if (name === "search_files") {
        const target = resolvePath(root, args.path || ".");
        const result = await runFile("rg", ["-n", "--hidden", "--glob", "!.git/**", "--glob", "!node_modules/**", "--", String(args.query || ""), target], root, 20_000);
        if (result.ok || result.exit_code === 1) evidence++;
        return { ok: result.ok || result.exit_code === 1, matches: result.stdout.split("\n").filter(Boolean).slice(0, 200), stderr: result.stderr };
      }
      if (name === "web_search") {
        const query = String(args.query || "").trim();
        const limit = Math.max(1, Math.min(Number(args.limit || 5), 10));
        const url = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`;
        const html = await fetchText(url);
        const results = [];
        const pattern = /class="result__a"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>[\s\S]*?class="result__snippet"[^>]*>([\s\S]*?)<\/a>/g;
        for (const match of html.matchAll(pattern)) {
          let href = match[1].replace(/&amp;/g, "&");
          try { const parsed = new URL(href, "https://duckduckgo.com"); href = parsed.searchParams.get("uddg") || parsed.href; } catch {}
          results.push({ title: decodeHtml(match[2]), url: href, snippet: decodeHtml(match[3]) });
          if (results.length >= limit) break;
        }
        evidence++;
        return { ok: true, query, results };
      }
      if (name === "fetch_url") {
        const url = await publicUrl(args.url);
        const body = await fetchText(url);
        evidence++;
        return { ok: true, url: url.href, text: decodeHtml(body).slice(0, 40_000) };
      }
      if (name === "write_file") {
        const path = resolvePath(root, args.path);
        const outside = relative(root, path).startsWith("..") || isAbsolute(relative(root, path));
        const exists = await access(path).then(() => true).catch(() => false);
        const label = `${exists ? "Replace" : "Create"} ${path}${outside ? " (outside the working directory)" : ""}?`;
        if (!await approve(label)) return { ok: false, denied: true, error: "user denied file write" };
        onAction(`${dryRun ? "Would write" : "Writing"} ${path}`);
        if (!dryRun) {
          await mkdir(dirname(path), { recursive: true });
          const temp = `${path}.${process.pid}.lolm-tmp`;
          await writeFile(temp, String(args.content ?? ""));
          await rename(temp, path);
        }
        changes.push({ path, bytes: Buffer.byteLength(String(args.content ?? "")), dry_run: dryRun });
        return { ok: true, path, bytes: Buffer.byteLength(String(args.content ?? "")), dry_run: dryRun };
      }
      if (name === "run_command") {
        const command = String(args.command || "").trim();
        if (!commandAllowed(command)) return { ok: false, error: "command blocked by the LOLM destructive-action guard" };
        if (!await approve(`Run in ${root}: ${command}?`)) return { ok: false, denied: true, error: "user denied command" };
        onAction(`${dryRun ? "Would run" : "Running"} ${command}`);
        if (dryRun) { commands.push({ command, dry_run: true }); return { ok: true, command, dry_run: true }; }
        const result = await run(command, root, Math.max(1000, Math.min(Number(args.timeout_ms || 120_000), 600_000)));
        commands.push({ command, ...result });
        if (result.ok) verified = true;
        return result;
      }
      return { ok: false, error: `unknown tool: ${name}` };
    },
  };
}
