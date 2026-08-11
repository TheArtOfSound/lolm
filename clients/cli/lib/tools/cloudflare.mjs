// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import { access, readFile } from "node:fs/promises";
import { join } from "node:path";
import { objectSchema, runFile, commandResult } from "./shared.mjs";

async function wrangler(root, args, timeoutMs = 120_000) {
  let result = await runFile("wrangler", args, { cwd: root, timeoutMs });
  if (result.code === "ENOENT") result = await runFile("npx", ["--yes", "wrangler", ...args], { cwd: root, timeoutMs });
  return commandResult(result, `wrangler ${args[0] || ""}`);
}

async function configFile(root) {
  for (const name of ["wrangler.jsonc", "wrangler.json", "wrangler.toml"]) {
    const path = join(root, name);
    try { await access(path); return path; } catch {}
  }
  return null;
}

export function registerCloudflareTools(registry, { root, processes }) {
  registry.register({
    name: "cloudflare.detect", description: "Detect Wrangler configuration and Cloudflare-related package scripts.", risk: "read", inputSchema: objectSchema(),
    execute: async () => { const config = await configFile(root); let scripts = {}; try { scripts = JSON.parse(await readFile(join(root, "package.json"), "utf8")).scripts || {}; } catch {} return { config, scripts: Object.fromEntries(Object.entries(scripts).filter(([key, value]) => /wrangler|cloudflare|pages|deploy/i.test(`${key} ${value}`))) }; },
  });
  registry.register({ name: "cloudflare.version", description: "Read the installed Wrangler version.", risk: "read", inputSchema: objectSchema(), execute: async () => wrangler(root, ["--version"]) });
  registry.register({ name: "cloudflare.whoami", description: "Verify Cloudflare authentication without exposing credentials.", risk: "read", inputSchema: objectSchema(), execute: async () => wrangler(root, ["whoami"]) });
  registry.register({
    name: "cloudflare.project", description: "Inspect the local Wrangler project configuration.", risk: "read", inputSchema: objectSchema(),
    execute: async () => { const path = await configFile(root); if (!path) throw Object.assign(new Error("No wrangler.jsonc, wrangler.json, or wrangler.toml was found."), { code: "NO_WRANGLER_CONFIG" }); return { path, content: await readFile(path, "utf8") }; },
  });
  registry.register({
    name: "cloudflare.dev", description: "Start Wrangler's local development server and return a process ID.", risk: "execute", approval: "confirm",
    inputSchema: objectSchema({ command: { type: "string" }, port: { type: "integer", minimum: 1, maximum: 65535 }, remote: { type: "boolean" } }),
    execute: async ({ command, port, remote = false }) => processes.spawn(command || `wrangler dev${port ? ` --port ${port}` : ""}${remote ? " --remote" : ""}`, { cwd: root }),
  });
  registry.register({
    name: "cloudflare.deploy", description: "Deploy the current project with Wrangler and return the complete deployment receipt.", risk: "external", approval: "explicit",
    inputSchema: objectSchema({ environment: { type: "string" }, dry_run: { type: "boolean" }, command: { type: "string" } }),
    execute: async ({ environment, dry_run = false, command }) => {
      if (command) return commandResult(await runFile(process.env.SHELL || "/bin/sh", ["-lc", command], { cwd: root, timeoutMs: 600_000 }), "Cloudflare deploy");
      return wrangler(root, ["deploy", ...(environment ? ["--env", environment] : []), ...(dry_run ? ["--dry-run"] : [])], 600_000);
    },
  });
  registry.register({
    name: "cloudflare.tail", description: "Start a Wrangler log tail and return a process ID.", risk: "external", approval: "confirm",
    inputSchema: objectSchema({ environment: { type: "string" }, format: { type: "string", enum: ["json", "pretty"] } }),
    execute: async ({ environment, format = "pretty" }) => processes.spawn(`wrangler tail --format ${format}${environment ? ` --env ${environment}` : ""}`, { cwd: root }),
  });
}
