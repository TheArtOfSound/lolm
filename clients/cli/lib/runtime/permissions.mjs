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

const SHELL_CONTROL = /[&|;<>\r\n`^]|\$\(|%[^%\r\n]+%|![A-Za-z_][A-Za-z0-9_]*!/;

// Automatic commands are strictly full-string matches. A prefix match would
// wrongly classify a command with additional executable arguments as safe.
const SAFE_EXECUTE = [
  /^(?:pwd|ls(?:\s+-[alh1]+)?(?:\s+\.)?|git\s+status|node\s+--version|python3?\s+--version)\s*$/i,
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
  if (/^(?:env|printenv|set)(?:\s|$)/i.test(value)) return { risk: "external", approval: "explicit", reason: "Environment dumps can expose secrets." };
  if (CATASTROPHIC.some((pattern) => pattern.test(value))) {
    return { risk: "execute", approval: "blocked", blocked: true, reason: "Command blocked because it matches a catastrophic or broadly destructive pattern." };
  }
  if (SHELL_CONTROL.test(value)) return { risk: "execute", approval: "confirm", reason: "Compound shell syntax and variable expansion cannot be approved automatically." };
  if (EXTERNAL.some((pattern) => pattern.test(value))) return { risk: "external", approval: "explicit", reason: "The command changes remote or production state." };
  if (/^(?:npm|pnpm|yarn|bun)\s+(?:test|run\s+\S+)|^(?:pytest|cargo\s+(?:test|check)|go\s+test|dotnet\s+test|make\s+(?:test|check))(?:\s|$)/i.test(value)) return { risk: "execute", approval: "confirm", reason: "Project scripts execute code and require approval." };
  if (MUTATING.some((pattern) => pattern.test(value))) return { risk: "write", approval: "confirm", reason: "The command can change local files, dependencies, or long-running state." };
  if (SAFE_EXECUTE.some((pattern) => pattern.test(value))) return { risk: "execute", approval: "auto", reason: "The command is a recognized inspection, test, or build operation." };
  return { risk: "execute", approval: "confirm", reason: "The command is executable but not in LOLM's known-safe catalog." };
}

function modeAllows(mode, decision) {
  if (decision.risk === "read") return true;
  if (mode === "trusted") return decision.risk !== "external" && !(decision.risk === "execute" && decision.approval !== "auto");
  if (mode === "readonly") return false;
  if (mode === "standard") return decision.approval === "auto" && decision.risk !== "external";
  if (mode === "developer") return decision.risk !== "external" && !(decision.risk === "execute" && decision.approval !== "auto") && decision.approval !== "explicit";
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
    // Running a shell command or modifying remote state always needs direct
    // human approval, regardless of --yes or the selected permission mode.
    const isShellTool = tool.name === "terminal.exec" || tool.name === "terminal.spawn";
    const humanOnly = decision.risk === "external" || (isShellTool && decision.approval !== "auto") || (decision.risk === "execute" && decision.approval !== "auto");
    if (!humanOnly && modeAllows(this.mode, decision)) return decision;
    if (!humanOnly && context.approved === true && decision.risk === "write") return decision;
    if (typeof this.confirm === "function") {
      const approved = await this.confirm({ tool, args, decision, context });
      if (approved) return decision;
    }
    throw new PermissionDeniedError(`${tool.name} needs approval in ${this.mode} mode. ${decision.reason}`, { ...decision, tool: tool.name });
  }
}
