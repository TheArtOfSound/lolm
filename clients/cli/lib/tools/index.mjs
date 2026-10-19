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
import { registerPlanTools } from "./plan.mjs";
import { registerMemoryTools } from "./memory.mjs";
import { registerDelegateTools } from "./delegate.mjs";
import { PluginManager } from "../plugins.mjs";
import { McpManager } from "../mcp.mjs";

export function createAgentToolbox({ cwd = process.cwd(), mode = "standard", confirm, approveExtension, onAction, eventSink, delegate, depth = 0 } = {}) {
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
  registerPlanTools(registry, shared);
  // LOLM_MEMORY=0 keeps the store out of a run entirely — automation and
  // benchmarks must not read or write a person's notes.
  if (process.env.LOLM_MEMORY !== "0") registerMemoryTools(registry, shared);
  registerDelegateTools(registry, { delegate, depth });
  const plugins = new PluginManager({ root, registry });
  const mcp = new McpManager({ root, registry });
  return {
    root, registry, processes, browser, plugins, mcp,
    async loadExtensions({ includeDisabledMcp = false } = {}) {
      const pluginStatus = await plugins.loadEnabled({ approve: approveExtension });
      const mcpStatus = await mcp.connectEnabled({ includeDisabled: includeDisabledMcp, approve: approveExtension });
      return { plugins: pluginStatus, mcp: mcpStatus };
    },
    async close() { mcp.close(); processes.close(); await browser.close().catch(() => {}); },
  };
}
