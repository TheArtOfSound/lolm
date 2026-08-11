// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later

export const PERMISSION_MODES = Object.freeze(["readonly", "standard", "developer", "trusted"]);
export const RISK_CLASSES = Object.freeze(["read", "write", "execute", "external"]);

const CATASTROPHIC = [
  /(?:^|\s)(?:rm|unlink)\s+(?:-[^\s]*r[^\s]*f|-[^\s]*f[^\s]*r)\s+(?:\/|~|\$HOME)(?:\s|$)/i,
  /(?:^|\s)(?:mkfs|fdisk|diskutil\s+eraseDisk)\b/i,
  /(?:^|\s)dd\s+[^\n]*\bof=\/(?:dev\/)?(?:disk|sd|nvme)/i,
  /(?:^|\s)git\s+(?:reset\s+--hard|clean\s+-[^\s]*f)/i,
  /(?:^|\s)(?:shutdown|reboot|halt)\b/i,
];

const EXTERNAL = [
  /(?:^|\s)(?:git\s+push|gh\s+(?:pr\s+(?:create|merge)|release\s+create)|wrangler\s+deploy|npm\s+publish|docker\s+push)\b/i,
  /(?:^|\s)(?:curl|wget)\b[^\n]*(?:-X\s*(?:POST|PUT|PATCH|DELETE)|--data|-d\s)/i,
];

const MUTATING = [
  /(?:^|\s)(?:npm|pnpm|yarn|bun)\s+(?:install|add|remove|update|upgrade)\b/i,
  /(?:^|\s)(?:pip|uv|cargo|brew|apt|dnf)\s+(?:install|add|remove|upgrade|update)\b/i,
  /(?:^|\s)git\s+(?:add|commit|checkout|switch|merge|pull|restore|rebase|cherry-pick)\b/i,
  /(?:^|\s)(?:mv|cp|mkdir|touch|chmod|chown|tee|sed\s+-i)\b/i,
  /(?:^|\s)(?:npm|pnpm|yarn|bun)\s+(?:start|dev|serve)\b/i,
];

const SAFE_EXECUTE = [
  /(?:^|\s)(?:npm|pnpm|yarn|bun)\s+(?:test|run\s+(?:test|build|lint|check|typecheck))\b/i,
  /(?:^|\s)(?:pytest|cargo\s+(?:test|check)|go\s+test|dotnet\s+test|make\s+(?:test|check))\b/i,
  /(?:^|\s)(?:git\s+(?:status|diff|log|show|branch)|gh\s+(?:auth\s+status|pr\s+(?:list|view|checks)|issue\s+(?:list|view)|run\s+(?:list|view)))\b/i,
  /(?:^|\s)(?:ls|pwd|find|rg|grep|head|tail|wc|which|type|env|printenv|node\s+--version|python3?\s+--version)\b/i,
];

export class PermissionDeniedError extends Error {
  constructor(message, details = {}) {
    super(message);
    this.name = "PermissionDeniedError";
    this.code = details.blocked ? "COMMAND_BLOCKED" : "APPROVAL_REQUIRED";
    this.details = details;
  }
}

export function classifyCommand(command) {
  const value = String(command || "").trim();
  if (!value) return { risk: "execute", approval: "confirm", reason: "Empty commands are not executable." };
  if (CATASTROPHIC.some((pattern) => pattern.test(value))) {
    return { risk: "execute", approval: "blocked", blocked: true, reason: "The command matches a catastrophic or broadly destructive pattern." };
  }
  if (EXTERNAL.some((pattern) => pattern.test(value))) return { risk: "external", approval: "explicit", reason: "The command changes remote or production state." };
  if (MUTATING.some((pattern) => pattern.test(value))) return { risk: "write", approval: "confirm", reason: "The command can change local files, dependencies, or long-running state." };
  if (SAFE_EXECUTE.some((pattern) => pattern.test(value))) return { risk: "execute", approval: "auto", reason: "The command is a recognized inspection, test, or build operation." };
  return { risk: "execute", approval: "confirm", reason: "The command is executable but not in LOLM's known-safe catalog." };
}

function modeAllows(mode, decision) {
  if (decision.risk === "read") return true;
  if (mode === "trusted") return true;
  if (mode === "readonly") return false;
  if (mode === "standard") return decision.risk === "execute" && decision.approval === "auto";
  if (mode === "developer") return decision.risk !== "external" && decision.approval !== "explicit";
  return false;
}

export class PermissionPolicy {
  constructor({ mode = "standard", confirm } = {}) {
    if (!PERMISSION_MODES.includes(mode)) throw new Error(`Unknown permission mode: ${mode}`);
    this.mode = mode;
    this.confirm = confirm;
  }

  async authorize(tool, args = {}, context = {}) {
    const dynamic = typeof tool.classify === "function" ? tool.classify(args, context) : {};
    const decision = {
      risk: dynamic.risk || tool.risk,
      approval: dynamic.approval || tool.approval || (tool.risk === "read" ? "auto" : "confirm"),
      reason: dynamic.reason || tool.permissionReason || "This action requires permission.",
      blocked: Boolean(dynamic.blocked),
    };
    if (!RISK_CLASSES.includes(decision.risk)) throw new Error(`Invalid risk class for ${tool.name}: ${decision.risk}`);
    if (decision.blocked || decision.approval === "blocked") throw new PermissionDeniedError(decision.reason, { ...decision, blocked: true, tool: tool.name });
    if (context.dryRun && decision.risk !== "read") return { ...decision, dryRun: true };
    if (modeAllows(this.mode, decision)) return decision;
    if (context.approved === true) return decision;
    if (typeof this.confirm === "function") {
      const approved = await this.confirm({ tool, args, decision, context });
      if (approved) return decision;
    }
    throw new PermissionDeniedError(`${tool.name} needs approval in ${this.mode} mode. ${decision.reason}`, { ...decision, tool: tool.name });
  }
}
