// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import { access, copyFile, cp, mkdir, readFile, readdir, rename, rm, stat, writeFile } from "node:fs/promises";
import { dirname, join, relative } from "node:path";
import { randomUUID } from "node:crypto";
import { MAX_READ, SKIP_DIRECTORIES, assertReadablePath, objectSchema, pathClassification, resolveUserPath, runFile } from "./shared.mjs";

async function walk(root, depth, prefix = "", output = []) {
  if (depth < 0 || output.length >= 1_000) return output;
  const entries = await readdir(root, { withFileTypes: true });
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    if (SKIP_DIRECTORIES.has(entry.name)) continue;
    const shown = join(prefix, entry.name);
    output.push({ path: shown, type: entry.isDirectory() ? "directory" : entry.isSymbolicLink() ? "symlink" : "file" });
    if (entry.isDirectory()) await walk(join(root, entry.name), depth - 1, shown, output);
    if (output.length >= 1_000) break;
  }
  return output;
}

async function atomicWrite(path, content) {
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.${process.pid}.${randomUUID()}.lolm-tmp`;
  await writeFile(temporary, content);
  await rename(temporary, path);
}

function fileSchema(extra = {}, required = ["path"]) {
  return objectSchema({ path: { type: "string", minLength: 1 }, ...extra }, required);
}

export function registerFilesystemTools(registry, { root, onAction = () => {} }) {
  registry.register({
    name: "fs.read", aliases: ["read_file"], description: "Read a UTF-8 text file inside the trusted workspace.", risk: "read",
    inputSchema: fileSchema({ offset: { type: "integer", minimum: 0 }, limit: { type: "integer", minimum: 1, maximum: MAX_READ } }),
    execute: async ({ path: value, offset = 0, limit = MAX_READ }, context) => {
      const path = resolveUserPath(root, value); assertReadablePath(root, path, context);
      const info = await stat(path); if (!info.isFile()) throw Object.assign(new Error("Path is not a file."), { code: "NOT_A_FILE" });
      if (info.size > MAX_READ && offset === 0 && limit === MAX_READ) throw Object.assign(new Error(`File exceeds the ${MAX_READ} byte default read limit; request a range.`), { code: "FILE_TOO_LARGE" });
      const content = await readFile(path, "utf8");
      return { path, size: info.size, offset, content: content.slice(offset, offset + limit), truncated: content.length > offset + limit };
    },
  });
  registry.register({
    name: "fs.write", aliases: ["write_file"], description: "Create or atomically replace a UTF-8 text file.", risk: "write",
    classify: ({ path }) => pathClassification(root, [path], { destructive: true }),
    inputSchema: fileSchema({ content: { type: "string" } }, ["path", "content"]),
    execute: async ({ path: value, content }, context) => {
      const path = resolveUserPath(root, value); onAction(`${context.dryRun ? "Would write" : "Writing"} ${path}`);
      await atomicWrite(path, content); return { path, bytes: Buffer.byteLength(content) };
    },
  });
  registry.register({
    name: "fs.patch", description: "Apply an exact text replacement to a file after verifying the old text is present.", risk: "write",
    classify: ({ path }) => pathClassification(root, [path], { destructive: true }),
    inputSchema: fileSchema({ old_text: { type: "string", minLength: 1 }, new_text: { type: "string" }, all: { type: "boolean" } }, ["path", "old_text", "new_text"]),
    execute: async ({ path: value, old_text, new_text, all = false }) => {
      const path = resolveUserPath(root, value); const content = await readFile(path, "utf8");
      const occurrences = content.split(old_text).length - 1;
      if (!occurrences) throw Object.assign(new Error("The exact old_text was not found; inspect the file before retrying."), { code: "PATCH_CONTEXT_MISSING" });
      if (occurrences > 1 && !all) throw Object.assign(new Error(`old_text occurs ${occurrences} times; provide more context or set all=true.`), { code: "PATCH_AMBIGUOUS" });
      const next = all ? content.split(old_text).join(new_text) : content.replace(old_text, new_text);
      await atomicWrite(path, next); return { path, replacements: all ? occurrences : 1, bytes: Buffer.byteLength(next) };
    },
  });
  registry.register({
    name: "fs.list", aliases: ["list_files"], description: "List files and directories recursively with a bounded depth.", risk: "read",
    inputSchema: fileSchema({ depth: { type: "integer", minimum: 0, maximum: 8 } }, []),
    execute: async ({ path: value = ".", depth = 2 }, context) => {
      const path = resolveUserPath(root, value); assertReadablePath(root, path, context); return { root: path, entries: await walk(path, depth) };
    },
  });
  registry.register({
    name: "fs.find", description: "Find workspace paths whose relative name contains a case-insensitive query.", risk: "read",
    inputSchema: objectSchema({ query: { type: "string", minLength: 1 }, path: { type: "string" }, depth: { type: "integer", minimum: 0, maximum: 12 } }, ["query"]),
    execute: async ({ query, path: value = ".", depth = 8 }, context) => {
      const path = resolveUserPath(root, value); assertReadablePath(root, path, context); const needle = query.toLowerCase();
      return { root: path, matches: (await walk(path, depth)).filter((row) => row.path.toLowerCase().includes(needle)).slice(0, 500) };
    },
  });
  registry.register({
    name: "fs.search", aliases: ["search_files"], description: "Search text files with ripgrep and return exact file, line, and match output.", risk: "read",
    inputSchema: objectSchema({ query: { type: "string", minLength: 1 }, path: { type: "string" }, glob: { type: "string" }, fixed: { type: "boolean" }, max_results: { type: "integer", minimum: 1, maximum: 1000 } }, ["query"]),
    execute: async ({ query, path: value = ".", glob, fixed = false, max_results = 200 }, context) => {
      const path = resolveUserPath(root, value); assertReadablePath(root, path, context);
      const args = ["-n", "--hidden", "--glob", "!.git/**", "--glob", "!node_modules/**"];
      if (fixed) args.push("-F"); if (glob) args.push("--glob", glob); args.push("--", query, path);
      const result = await runFile("rg", args, { cwd: root, timeoutMs: 30_000 });
      if (!result.ok && result.exit_code !== 1) throw Object.assign(new Error(result.stderr || result.error || "Search failed."), { code: "SEARCH_FAILED" });
      return { matches: result.stdout.split("\n").filter(Boolean).slice(0, max_results), truncated: result.stdout.split("\n").filter(Boolean).length > max_results };
    },
  });
  registry.register({
    name: "fs.stat", description: "Inspect file type, size, timestamps, and workspace-relative path.", risk: "read",
    inputSchema: fileSchema(),
    execute: async ({ path: value }, context) => {
      const path = resolveUserPath(root, value); assertReadablePath(root, path, context); const info = await stat(path);
      return { path, relative_path: relative(root, path), type: info.isFile() ? "file" : info.isDirectory() ? "directory" : "other", size: info.size, modified_at: info.mtime.toISOString(), mode: info.mode.toString(8).slice(-3) };
    },
  });
  registry.register({
    name: "fs.inspect", description: "Inspect a path and, for text files, return a numbered preview suitable for planning an edit.", risk: "read",
    inputSchema: fileSchema({ lines: { type: "integer", minimum: 1, maximum: 400 } }),
    execute: async ({ path: value, lines = 120 }, context) => {
      const path = resolveUserPath(root, value); assertReadablePath(root, path, context); const info = await stat(path);
      if (!info.isFile()) return { path, type: info.isDirectory() ? "directory" : "other", entries: info.isDirectory() ? await walk(path, 1) : [] };
      const content = await readFile(path, "utf8"); return { path, size: info.size, preview: content.split("\n").slice(0, lines).map((line, index) => `${index + 1}: ${line}`).join("\n"), truncated: content.split("\n").length > lines };
    },
  });
  registry.register({
    name: "fs.mkdir", description: "Create a directory, including missing parents.", risk: "write", classify: ({ path }) => pathClassification(root, [path]),
    inputSchema: fileSchema(), execute: async ({ path: value }) => { const path = resolveUserPath(root, value); await mkdir(path, { recursive: true }); return { path }; },
  });
  registry.register({
    name: "fs.move", description: "Move or rename a file or directory.", risk: "write", classify: ({ source, destination }) => pathClassification(root, [source, destination], { destructive: true }),
    inputSchema: objectSchema({ source: { type: "string", minLength: 1 }, destination: { type: "string", minLength: 1 } }, ["source", "destination"]),
    execute: async ({ source, destination }) => { const from = resolveUserPath(root, source), to = resolveUserPath(root, destination); await mkdir(dirname(to), { recursive: true }); await rename(from, to); return { source: from, destination: to }; },
  });
  registry.register({
    name: "fs.copy", description: "Copy a file or directory.", risk: "write", classify: ({ source, destination }) => pathClassification(root, [source, destination]),
    inputSchema: objectSchema({ source: { type: "string", minLength: 1 }, destination: { type: "string", minLength: 1 }, recursive: { type: "boolean" } }, ["source", "destination"]),
    execute: async ({ source, destination, recursive = false }) => { const from = resolveUserPath(root, source), to = resolveUserPath(root, destination); await mkdir(dirname(to), { recursive: true }); if (recursive) await cp(from, to, { recursive: true, errorOnExist: true }); else await copyFile(from, to); return { source: from, destination: to, recursive }; },
  });
  registry.register({
    name: "fs.delete", description: "Delete a file or, only when recursive is explicitly true, a directory tree.", risk: "write", approval: "confirm",
    classify: ({ path, recursive }) => pathClassification(root, [path], { destructive: true || recursive }),
    inputSchema: fileSchema({ recursive: { type: "boolean" } }),
    execute: async ({ path: value, recursive = false }) => { const path = resolveUserPath(root, value); if (path === root) throw Object.assign(new Error("Deleting the workspace root is blocked."), { code: "COMMAND_BLOCKED" }); await rm(path, { recursive, force: false }); return { path, recursive }; },
  });
}
