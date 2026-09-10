// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Notes the agent keeps between sessions.
 *
 * Each note is one small Markdown file under ~/.lolm/memory with a name, a
 * one-line description, and a body. The index of names and descriptions is
 * folded into the system prompt so the agent knows what it knows; bodies are
 * fetched on demand with memory.recall, so a large store costs nothing until
 * it is needed. Everything stays on this machine — the only place a note ever
 * goes is into the prompt sent to whichever provider the user chose.
 */
import { mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

const MAX_BODY = 8_000;
const MAX_NOTES = 400;

export function memoryDir() {
  return process.env.LOLM_MEMORY_DIR || join(homedir(), ".lolm", "memory");
}

export function slugify(value) {
  const slug = String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);
  if (!slug) throw Object.assign(new Error("A note needs a name with at least one letter or digit."), { code: "MEMORY_NAME_INVALID" });
  return slug;
}

function parse(text, name) {
  const match = /^---\n([\s\S]*?)\n---\n?([\s\S]*)$/.exec(text);
  const front = {};
  if (match) {
    for (const line of match[1].split("\n")) {
      const colon = line.indexOf(":");
      if (colon > 0) front[line.slice(0, colon).trim()] = line.slice(colon + 1).trim();
    }
  }
  const body = (match ? match[2] : text).trim();
  return {
    name,
    description: front.description || body.split("\n").find((line) => line.trim())?.slice(0, 160) || "",
    tags: front.tags ? front.tags.split(",").map((tag) => tag.trim()).filter(Boolean) : [],
    updated: front.updated || "",
    body,
  };
}

async function readAll(dir) {
  let entries;
  try { entries = await readdir(dir, { withFileTypes: true }); } catch { return []; }
  const notes = [];
  for (const entry of entries) {
    if (!entry.isFile() || !entry.name.endsWith(".md")) continue;
    try { notes.push(parse(await readFile(join(dir, entry.name), "utf8"), entry.name.slice(0, -3))); } catch { /* unreadable note: skip */ }
  }
  return notes.sort((a, b) => a.name.localeCompare(b.name));
}

export async function listNotes({ dir = memoryDir() } = {}) {
  return (await readAll(dir)).map(({ body, ...rest }) => rest);
}

export async function readNote(name, { dir = memoryDir() } = {}) {
  const slug = slugify(name);
  try { return parse(await readFile(join(dir, `${slug}.md`), "utf8"), slug); }
  catch { return null; }
}

export async function saveNote({ name, description = "", body = "", tags = [] }, { dir = memoryDir() } = {}) {
  const slug = slugify(name);
  const content = String(body || "").trim();
  if (!content) throw Object.assign(new Error("A note needs a body."), { code: "MEMORY_BODY_EMPTY" });
  if (content.length > MAX_BODY) throw Object.assign(new Error(`A note body is capped at ${MAX_BODY} characters; split it.`), { code: "MEMORY_BODY_TOO_LONG" });
  const existing = await readAll(dir);
  if (!existing.some((note) => note.name === slug) && existing.length >= MAX_NOTES) {
    throw Object.assign(new Error(`The memory store holds ${MAX_NOTES} notes; forget one before saving another.`), { code: "MEMORY_FULL" });
  }
  await mkdir(dir, { recursive: true, mode: 0o700 });
  const front = [
    "---",
    `name: ${slug}`,
    `description: ${String(description || content.split("\n")[0]).replace(/\n/g, " ").slice(0, 160)}`,
    `tags: ${(Array.isArray(tags) ? tags : []).map((tag) => String(tag).trim()).filter(Boolean).join(", ")}`,
    `updated: ${new Date().toISOString()}`,
    "---",
  ].join("\n");
  await writeFile(join(dir, `${slug}.md`), `${front}\n${content}\n`, { mode: 0o600 });
  return { name: slug, updated: true, path: join(dir, `${slug}.md`) };
}

export async function forgetNote(name, { dir = memoryDir() } = {}) {
  const slug = slugify(name);
  try { await rm(join(dir, `${slug}.md`)); return { name: slug, forgotten: true }; }
  catch { return { name: slug, forgotten: false }; }
}

/** Notes whose name, description, tags, or body mention the query. */
export async function recall(query, { dir = memoryDir(), limit = 5 } = {}) {
  const needle = String(query || "").toLowerCase().trim();
  const notes = await readAll(dir);
  if (!needle) return notes.slice(0, limit);
  const scored = notes.map((note) => {
    const haystacks = [note.name, note.description, note.tags.join(" "), note.body].map((value) => value.toLowerCase());
    // A hit in the name or description outranks one buried in the body.
    const score = (haystacks[0].includes(needle) ? 4 : 0) + (haystacks[1].includes(needle) ? 3 : 0)
      + (haystacks[2].includes(needle) ? 2 : 0) + (haystacks[3].includes(needle) ? 1 : 0);
    return { note, score };
  }).filter((row) => row.score > 0).sort((a, b) => b.score - a.score || a.note.name.localeCompare(b.note.name));
  return scored.slice(0, limit).map((row) => row.note);
}

/** The index as prompt text, bounded so a big store cannot crowd out the task. */
export async function digest({ dir = memoryDir(), maxChars = 2_400 } = {}) {
  const notes = await listNotes({ dir });
  if (!notes.length) return "";
  const lines = [];
  let used = 0;
  for (const note of notes) {
    const line = `- ${note.name}: ${note.description}`;
    if (used + line.length > maxChars) { lines.push(`- … ${notes.length - lines.length} more; use memory.recall`); break; }
    lines.push(line);
    used += line.length + 1;
  }
  return lines.join("\n");
}
