// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** The agent's own notes, kept between sessions. */
import { objectSchema } from "./shared.mjs";
import { forgetNote, listNotes, readNote, recall, saveNote } from "../memory.mjs";

export function registerMemoryTools(registry) {
  registry.register({
    name: "memory.recall",
    description: "Search notes saved in earlier sessions by name, description, tag, or body and return the matching notes in full.",
    risk: "read",
    inputSchema: objectSchema({ query: { type: "string" }, limit: { type: "integer", minimum: 1, maximum: 20 } }),
    execute: async ({ query = "", limit = 5 }) => ({ notes: await recall(query, { limit }) }),
  });
  registry.register({
    name: "memory.list",
    description: "List every saved note's name, description, and tags without their bodies.",
    risk: "read",
    inputSchema: objectSchema(),
    execute: async () => ({ notes: await listNotes() }),
  });
  registry.register({
    name: "memory.get",
    description: "Read one saved note in full by name.",
    risk: "read",
    inputSchema: objectSchema({ name: { type: "string", minLength: 1 } }, ["name"]),
    execute: async ({ name }) => {
      const note = await readNote(name);
      if (!note) throw Object.assign(new Error(`No note named ${name}.`), { code: "MEMORY_NOTE_MISSING" });
      return note;
    },
  });
  // Saving a note is a write, but to the agent's own store rather than the
  // workspace, so it needs no confirmation; it is still reported like any tool.
  registry.register({
    name: "memory.save",
    description: "Save a durable fact worth knowing in a future session — a user preference, a project convention, where something lives, a decision and why. One note per fact; a repeated name replaces the note. Do not save secrets or anything that is only true for this task.",
    risk: "write",
    approval: "auto",
    inputSchema: objectSchema({
      name: { type: "string", minLength: 1 },
      description: { type: "string" },
      body: { type: "string", minLength: 1 },
      tags: { type: "array", items: { type: "string" }, maxItems: 8 },
    }, ["name", "body"]),
    execute: async ({ name, description, body, tags }) => saveNote({ name, description, body, tags }),
  });
  registry.register({
    name: "memory.forget",
    description: "Delete a saved note by name.",
    risk: "write",
    approval: "confirm",
    inputSchema: objectSchema({ name: { type: "string", minLength: 1 } }, ["name"]),
    execute: async ({ name }) => forgetNote(name),
  });
}
