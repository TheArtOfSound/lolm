// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import { access, stat } from "node:fs/promises";
import { constants } from "node:fs";
import { delimiter, join } from "node:path";
import { runFile } from "./tools/shared.mjs";

async function executable(name) {
  const extensions = process.platform === "win32" ? String(process.env.PATHEXT || ".EXE;.CMD;.BAT").split(";") : [""];
  for (const directory of String(process.env.PATH || "").split(delimiter)) for (const extension of extensions) {
    const path = join(directory, `${name}${extension}`);
    try { await access(path, constants.X_OK); return path; } catch {}
  }
  return null;
}

async function commandCheck(name, args = ["--version"], options = {}) {
  const path = await executable(name);
  if (!path) return { name, ok: false, detail: "not installed", optional: Boolean(options.optional), action: options.action || `Install ${name} to enable this integration.` };
  const result = await runFile(path, args, { timeoutMs: options.timeoutMs || 15_000 });
  return { name, ok: result.ok, path, optional: Boolean(options.optional), detail: (result.stdout || result.stderr).trim().split("\n")[0] || (result.ok ? "available" : `exit ${result.exit_code}`), ...(!result.ok && options.action ? { action: options.action } : {}) };
}

async function chromeCheck() {
  const candidates = process.platform === "darwin" ? ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium"] : process.platform === "win32" ? [join(process.env.PROGRAMFILES || "", "Google", "Chrome", "Application", "chrome.exe")] : [await executable("google-chrome"), await executable("chromium"), await executable("chromium-browser")];
  for (const path of candidates.filter(Boolean)) try { await access(path, constants.X_OK); return { name: "Chrome", ok: true, path, detail: "available" }; } catch {}
  return { name: "Chrome", ok: false, optional: true, detail: "not found", action: "Install Google Chrome or Chromium for browser/computer-use tools." };
}

export async function collectDiagnostics({ cwd, configPath, runtime, nfet }) {
  const checks = [];
  checks.push({ name: "Node.js", ok: Number(process.versions.node.split(".")[0]) >= 20, detail: process.version, action: "Install Node.js 20 or newer." });
  checks.push(await commandCheck("npm"));
  checks.push(await commandCheck("git"));
  checks.push(await commandCheck("gh", ["--version"], { optional: true, action: "Install GitHub CLI to enable github.* tools." }));
  checks.push(await commandCheck("wrangler", ["--version"], { optional: true, action: "Install Wrangler to enable cloudflare.* tools." }));
  checks.push(await commandCheck("ollama", ["--version"], { optional: runtime.provider !== "ollama", action: "Install Ollama only if you want local-model inference." }));
  checks.push(await chromeCheck());
  try { await import("playwright-core"); checks.push({ name: "Playwright", ok: true, detail: "playwright-core available" }); }
  catch { checks.push({ name: "Playwright", ok: false, detail: "playwright-core missing", action: "Reinstall lolm-cli so its browser automation dependency is installed." }); }
  try { await access(cwd, constants.R_OK | constants.W_OK); checks.push({ name: "Workspace", ok: true, detail: cwd }); }
  catch { checks.push({ name: "Workspace", ok: false, detail: cwd, action: "Choose a readable and writable directory with --cwd." }); }
  try { const info = await stat(configPath); const mode = info.mode & 0o777; checks.push({ name: "Config security", ok: (mode & 0o077) === 0, detail: `${configPath} · mode ${mode.toString(8)}`, action: `Run chmod 600 ${configPath}.` }); }
  catch { checks.push({ name: "Config", ok: false, detail: "not created", action: "Run lolm setup." }); }
  checks.push({ name: "Provider", ok: true, detail: `${runtime.label} · ${runtime.model}` });
  checks.push({ name: "API key", ok: !runtime.keyRequired || Boolean(runtime.apiKey), detail: runtime.keySource, action: `Run lolm setup ${runtime.provider}.` });
  checks.push({ name: "NFET source", ok: Boolean(nfet.home), detail: nfet.home || "not found", action: "Set LOLM_HOME to a real LOLM source checkout." });
  checks.push({ name: "NFET checkpoint", ok: Boolean(nfet.checkpoint_available), detail: nfet.checkpoint || "not found", action: "Configure a real trained checkpoint with lolm config set nfet-checkpoint PATH." });
  const gitRepo = await runFile("git", ["rev-parse", "--show-toplevel"], { cwd, timeoutMs: 5_000 });
  checks.push({ name: "Git workspace", ok: gitRepo.ok, detail: gitRepo.ok ? gitRepo.stdout.trim() : "not a Git repository", optional: true });
  const gh = checks.find((item) => item.name === "gh");
  if (gh?.ok) {
    const auth = await runFile("gh", ["auth", "status"], { cwd, timeoutMs: 15_000 });
    checks.push({ name: "GitHub auth", ok: auth.ok, detail: (auth.stdout || auth.stderr).trim().split("\n")[0] || "not authenticated", action: "Run gh auth login." });
  }
  return checks;
}
