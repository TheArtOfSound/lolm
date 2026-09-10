// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** A plan the agent declares and ticks off, shown live to the reader.
 *
 * Without this a multi-step task is opaque until it ends. The tools are cheap
 * and side-effect free on the workspace, so they carry the read risk class; the
 * runner excludes them from its evidence count so declaring a plan never
 * passes for having checked anything.
 */
import { objectSchema } from "./shared.mjs";

export function registerPlanTools(registry) {
  let items = [];
  const snapshot = () => ({
    items: items.map((item, index) => ({ index: index + 1, text: item.text, done: item.done })),
    remaining: items.filter((item) => !item.done).length,
  });
  const publish = (context) => registry.emit("plan.updated", snapshot(), context);

  registry.register({
    name: "plan.set",
    description: "Declare the steps for a task with three or more distinct parts, before starting them. Replaces any previous plan. Keep steps short and concrete.",
    risk: "read",
    inputSchema: objectSchema({
      steps: { type: "array", items: { type: "string", minLength: 1 }, minItems: 1, maxItems: 12 },
    }, ["steps"]),
    execute: async ({ steps }, context) => {
      items = steps.map((text) => ({ text: String(text).trim(), done: false }));
      await publish(context);
      return snapshot();
    },
  });
  registry.register({
    name: "plan.done",
    description: "Mark a plan step complete by its 1-based index, as soon as it is actually finished.",
    risk: "read",
    inputSchema: objectSchema({ index: { type: "integer", minimum: 1 } }, ["index"]),
    execute: async ({ index }, context) => {
      const item = items[index - 1];
      if (!item) throw Object.assign(new Error(`There is no plan step ${index}; the plan has ${items.length}.`), { code: "PLAN_STEP_MISSING" });
      item.done = true;
      await publish(context);
      return snapshot();
    },
  });
  registry.register({
    name: "plan.get",
    description: "Read the current plan and which steps remain.",
    risk: "read",
    inputSchema: objectSchema(),
    execute: async () => snapshot(),
  });
}
