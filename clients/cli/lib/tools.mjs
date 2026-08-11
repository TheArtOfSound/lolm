// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Structured local tools with typed schemas, explicit risk classes, and compatibility aliases. */
import { confirm as confirmPrompt } from "./tui.mjs";
import { createAgentToolbox } from "./tools/index.mjs";

const definitionToolbox = createAgentToolbox({ mode: "readonly" });
export const TOOL_DEFINITIONS = definitionToolbox.registry.providerDefinitions();

function approvalLabel({ tool, args, decision }) {
  const target = args.path || args.command || args.branch || args.url || args.process_id || "the requested action";
  return `${tool.name} (${decision.risk}): ${target}\n${decision.reason} Continue?`;
}

export function createToolRunner({ cwd = process.cwd(), yes = false, dryRun = false, mode, onAction = () => {}, eventSink } = {}) {
  const changes = [];
  const commands = [];
  let evidence = 0;
  let verified = false;
  const toolbox = createAgentToolbox({
    cwd,
    mode: mode || (yes ? "developer" : "standard"),
    onAction,
    eventSink,
    confirm: (request) => yes || confirmPrompt(approvalLabel(request)),
  });
  const ready = toolbox.loadExtensions();

  return {
    changes,
    commands,
    registry: toolbox.registry,
    ready,
    get tools() { return toolbox.registry.providerDefinitions(); },
    get evidence() { return evidence; },
    get verified() { return verified; },
    close: () => toolbox.close(),
    async execute(call) {
      await ready;
      const tool = toolbox.registry.resolve(call?.name);
      // Some OpenAI-compatible providers copy the selected tool name back into
      // the argument object. It is transport envelope metadata, not a customer
      // argument, and strict schemas should not waste an autonomous step on it.
      let normalizedCall = call?.arguments && typeof call.arguments === "object" && !Array.isArray(call.arguments) && Object.hasOwn(call.arguments, "tool")
        ? { ...call, arguments: Object.fromEntries(Object.entries(call.arguments).filter(([key]) => key !== "tool")) }
        : call;
      if (tool?.name === "fs.list" && normalizedCall?.arguments?.path === "") {
        normalizedCall = { ...normalizedCall, arguments: { ...normalizedCall.arguments, path: "." } };
      }
      const result = await toolbox.registry.execute(normalizedCall, { approved: yes, dryRun, cwd: toolbox.root });
      if (!result.ok) return { ok: false, ...result.error, error: result.error?.message, tool: result.tool };
      const canonical = result.tool;
      const value = result.dry_run ? { dry_run: true, permission: result.permission } : (result.result || {});
      if (canonical.startsWith("fs.") && ["fs.write", "fs.patch", "fs.mkdir", "fs.move", "fs.copy", "fs.delete"].includes(canonical)) {
        changes.push({ action: canonical.slice(3), ...value, dry_run: dryRun });
      }
      if (canonical === "terminal.exec" || canonical === "terminal.spawn") {
        commands.push({ command: normalizedCall.arguments?.command, ...value, dry_run: dryRun });
        if (canonical === "terminal.exec" && value.exit_code === 0 && !value.timed_out) verified = true;
      }
      if (tool?.risk === "read" || ["git.status", "git.diff", "terminal.status"].includes(canonical)) evidence++;
      return { ok: true, ...value, tool: canonical, duration_ms: result.duration_ms };
    },
  };
}

export { createAgentToolbox } from "./tools/index.mjs";
