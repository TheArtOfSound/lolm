// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Hand a self-contained piece of work to a fresh agent.
 *
 * The point is context, not concurrency. Answering "where is X configured?"
 * across a large repository can cost thirty file reads, and every one of them
 * stays in the caller's history for the rest of the task, crowding out the work
 * that actually matters. A delegate runs with its own empty history and returns
 * only its conclusion, so the caller pays for the answer instead of the search.
 *
 * The runAgent function is injected rather than imported: the agent owns the
 * toolbox, so importing it back here would be a cycle.
 */
import { objectSchema } from "./shared.mjs";

export const MAX_DELEGATIONS = 6;

export function registerDelegateTools(registry, { delegate, depth = 0, maxDepth = 1 } = {}) {
  if (typeof delegate !== "function" || depth >= maxDepth) return;
  let used = 0;
  registry.register({
    name: "agent.delegate",
    description:
      "Hand one self-contained question or piece of work to a fresh agent that starts with no history and returns only its conclusion. Use it for searches and surveys whose intermediate reading you do not need — 'find every place the timeout is configured and report the files and values'. Give it everything it needs in one instruction; it cannot see this conversation and cannot delegate further. Do not use it for work you are already partway through.",
    risk: "read",
    approval: "auto",
    inputSchema: objectSchema({
      task: { type: "string", minLength: 1 },
      mode: { type: "string", enum: ["ask", "code"] },
      max_steps: { type: "integer", minimum: 1, maximum: 20 },
    }, ["task"]),
    execute: async ({ task, mode = "ask", max_steps = 8 }, context) => {
      if (used >= MAX_DELEGATIONS) {
        throw Object.assign(new Error(`This run has already delegated ${MAX_DELEGATIONS} times; do the remaining work directly.`), { code: "DELEGATION_LIMIT" });
      }
      used += 1;
      const result = await delegate({ task, mode, maxSteps: max_steps, signal: context?.signal });
      // The caller gets the conclusion and a receipt of what happened, never
      // the sub-agent's transcript — carrying that back would defeat the point.
      return {
        answer: result.response || result.error || "",
        completed: Boolean(result.ok),
        steps: result.steps ?? null,
        changed_files: (result.changes || []).map((change) => change.path).filter(Boolean),
        commands_run: (result.commands || []).length,
        delegations_left: MAX_DELEGATIONS - used,
      };
    },
  });
}
