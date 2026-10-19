// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Small, deterministic evidence classifier for future outcome-trained LOLM controllers.
 *
 * This is NOT a success oracle: a passing command establishes only that the
 * named check exited cleanly. It does not establish task correctness, tool
 * independence, or that a test suite covers the modified files.
 *
 * Never persist raw commands, paths, stdout, prompts, or arguments here.
 */

const TEST_COMMANDS = [
  /^(?:npm|pnpm|yarn|bun)\s+test$/,
  /^(?:npm|pnpm|yarn|bun)\s+run\s+(?:test|test:unit|test:integration|test:e2e)$/,
  /^node\s+--test(?:\s+[\w./*_-]+)?$/,
  /^(?:python3?|\.venv\/bin\/python|uv\s+run\s+python)\s+-m\s+pytest(?:\s+[\w./*_-]+)?$/,
  /^(?:pytest|uv\s+run\s+pytest)(?:\s+[\w./*_-]+)?$/,
  /^cargo\s+test(?:\s+--(?:lib|bins|tests|all-targets))?$/,
  /^go\s+test(?:\s+\.\/\.\.\.|\s+[\w./_-]+)?$/,
];
const STRUCTURAL_COMMANDS = [
  /^(?:npm|pnpm|yarn|bun)\s+run\s+(?:build|lint|check|typecheck)$/,
  /^git\s+diff\s+--check$/,
  /^(?:python3?|\.venv\/bin\/python)\s+-m\s+compileall\s+[\w./_-]+$/,
  /^npx\s+tsc\s+--noEmit$/,
];

/** Prevent shell operators, output redirection, substitution, and flags
 * such as --help from creating fabricated acceptance evidence. */
function simpleCommand(value) {
  const command = String(value || "").trim().replace(/\s+/g, " ");
  if (!command || command.includes(String.fromCharCode(96)) || /[;|&<>\n\r]|\$\(|\\/.test(command)) return null;
  return command;
}

export function classifyOutcomeEvidence(command, result = {}) {
  if (result?.dry_run === true) return "not_executed";
  if (result?.timed_out || result?.error || !Number.isInteger(result?.exit_code)) return "unknown";
  if (result.exit_code !== 0) return "command_failed";
  const normalized = simpleCommand(command);
  if (normalized && TEST_COMMANDS.some((pattern) => pattern.test(normalized))) return "test_passed";
  if (normalized && STRUCTURAL_COMMANDS.some((pattern) => pattern.test(normalized))) return "structural_check_passed";
  return "command_succeeded";
}

export function createOutcomeEvidence() {
  const counts = { test_passed: 0, structural_check_passed: 0, command_succeeded: 0, command_failed: 0, unknown: 0, not_executed: 0 };
  return {
    observe(command, result) {
      const classification = classifyOutcomeEvidence(command, result);
      counts[classification] += 1;
      return classification;
    },
    get testPassed() { return counts.test_passed > 0; },
    snapshot() { return { ...counts }; },
  };
}

/** Opt-in stricter criterion for modified-code tasks; execution alone is
 * insufficient. Not a proof of correctness; callers must say 'checks passed'. */
export function hasCodeAcceptanceEvidence({ changes = 0, priorVerified = false, testPassed = false } = {}) {
  return changes > 0 ? Boolean(testPassed) : Boolean(priorVerified);
}
