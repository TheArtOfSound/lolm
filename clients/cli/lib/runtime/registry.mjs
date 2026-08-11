// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import { assertSchema, ToolValidationError } from "./schema.mjs";
import { PermissionDeniedError, PermissionPolicy, RISK_CLASSES } from "./permissions.mjs";

export function providerToolName(name) {
  return String(name).replace(/[^a-zA-Z0-9_-]/g, "__").slice(0, 64);
}

function normalizedError(error) {
  return {
    code: error?.code || "TOOL_FAILED",
    message: error instanceof Error ? error.message : String(error),
    ...(error?.issues ? { issues: error.issues } : {}),
    ...(error?.details ? { details: error.details } : {}),
  };
}

export class ToolRegistry {
  constructor({ permissionPolicy = new PermissionPolicy(), eventSink } = {}) {
    this.permissionPolicy = permissionPolicy;
    this.eventSink = eventSink;
    this.tools = new Map();
    this.aliases = new Map();
  }

  register(definition) {
    const tool = { approval: definition.risk === "read" ? "auto" : "confirm", ...definition };
    if (!tool.name || !/^[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+$/i.test(tool.name)) throw new Error(`Tool name must be namespaced: ${tool.name || "(missing)"}`);
    if (!tool.description || typeof tool.execute !== "function") throw new Error(`Tool ${tool.name} needs a description and execute function.`);
    if (!RISK_CLASSES.includes(tool.risk)) throw new Error(`Tool ${tool.name} has invalid risk class ${tool.risk}.`);
    if (this.tools.has(tool.name)) throw new Error(`Tool already registered: ${tool.name}`);
    tool.inputSchema ||= { type: "object", additionalProperties: false };
    tool.providerName = providerToolName(tool.name);
    this.tools.set(tool.name, tool);
    this.aliases.set(tool.providerName, tool.name);
    for (const alias of tool.aliases || []) {
      if (this.aliases.has(alias) || this.tools.has(alias)) throw new Error(`Tool alias already registered: ${alias}`);
      this.aliases.set(alias, tool.name);
    }
    return this;
  }

  resolve(name) {
    return this.tools.get(name) || this.tools.get(this.aliases.get(name));
  }

  list({ group, risk } = {}) {
    return [...this.tools.values()]
      .filter((tool) => !group || tool.name.startsWith(`${group}.`))
      .filter((tool) => !risk || tool.risk === risk)
      .map(({ execute, classify, ...tool }) => ({ ...tool }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  providerDefinitions(options = {}) {
    const allowed = options.names ? new Set(options.names) : null;
    return this.list().filter((tool) => !allowed || allowed.has(tool.name) || (tool.aliases || []).some((alias) => allowed.has(alias))).map((tool) => ({
      type: "function",
      function: {
        name: tool.providerName,
        description: `${tool.description} [risk: ${tool.risk}; canonical name: ${tool.name}]`,
        parameters: tool.inputSchema,
      },
    }));
  }

  async emit(type, payload, context) {
    const sink = context?.eventSink || this.eventSink;
    if (typeof sink === "function") await sink({ type, ...payload });
  }

  async execute(call, context = {}) {
    const requestedName = call?.name || call?.tool || call?.function?.name;
    const tool = this.resolve(requestedName);
    const startedAt = Date.now();
    if (!tool) return { ok: false, tool: requestedName, duration_ms: 0, error: { code: "UNKNOWN_TOOL", message: `Unknown tool: ${requestedName}` } };

    let args = call?.arguments ?? call?.args ?? call?.function?.arguments ?? {};
    try {
      if (typeof args === "string") args = JSON.parse(args || "{}");
      assertSchema(tool.inputSchema, args, `${tool.name} arguments`);
      const permission = await this.permissionPolicy.authorize(tool, args, context);
      await this.emit("tool.started", { tool: tool.name, args, permission }, context);
      if (permission.dryRun) {
        const result = { ok: true, tool: tool.name, duration_ms: Date.now() - startedAt, dry_run: true, permission };
        await this.emit("tool.completed", result, context);
        return result;
      }
      const value = await tool.execute(args, { ...context, tool, permission });
      const result = { ok: true, tool: tool.name, duration_ms: Date.now() - startedAt, result: value ?? null };
      await this.emit("tool.completed", result, context);
      return result;
    } catch (error) {
      const result = { ok: false, tool: tool.name, duration_ms: Date.now() - startedAt, error: normalizedError(error) };
      await this.emit("tool.failed", result, context);
      if (error instanceof ToolValidationError || error instanceof PermissionDeniedError) return result;
      return result;
    }
  }
}
