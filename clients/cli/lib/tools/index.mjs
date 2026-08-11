// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import { resolve } from "node:path";
import { ToolRegistry } from "../runtime/registry.mjs";
import { PermissionPolicy } from "../runtime/permissions.mjs";
import { ProcessManager } from "../runtime/processes.mjs";
import { registerTerminalTools } from "./terminal.mjs";
import { registerFilesystemTools } from "./filesystem.mjs";
import { registerGitTools } from "./git.mjs";
import { registerGitHubTools } from "./github.mjs";
import { registerCloudflareTools } from "./cloudflare.mjs";
import { BrowserManager, registerBrowserTools, registerComputerTools } from "./browser.mjs";
import { registerWebTools } from "./web.mjs";

export function createAgentToolbox({ cwd = process.cwd(), mode = "standard", confirm, onAction, eventSink } = {}) {
  const root = resolve(cwd);
  const processes = new ProcessManager();
  const browser = new BrowserManager({ root });
  const registry = new ToolRegistry({ permissionPolicy: new PermissionPolicy({ mode, confirm }), eventSink });
  const shared = { root, processes, browser, onAction };
  registerTerminalTools(registry, shared);
  registerFilesystemTools(registry, shared);
  registerGitTools(registry, shared);
  registerGitHubTools(registry, shared);
  registerCloudflareTools(registry, shared);
  registerBrowserTools(registry, shared);
  registerComputerTools(registry, shared);
  registerWebTools(registry, shared);
  return {
    root, registry, processes, browser,
    async close() { processes.close(); await browser.close().catch(() => {}); },
  };
}
