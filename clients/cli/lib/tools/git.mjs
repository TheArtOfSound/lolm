// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import { objectSchema, runFile, commandResult } from "./shared.mjs";

async function git(root, args, timeoutMs = 120_000) {
  return commandResult(await runFile("git", args, { cwd: root, timeoutMs }), `git ${args[0]}`);
}

async function dirty(root) {
  const result = await git(root, ["status", "--porcelain=v1", "--untracked-files=normal"]);
  return result.stdout.trim();
}

async function protectDirty(root, allowDirty) {
  const status = await dirty(root);
  if (status && !allowDirty) throw Object.assign(new Error("The workspace has uncommitted changes. Inspect or commit them, or explicitly set allow_dirty=true."), { code: "DIRTY_WORKTREE", status });
}

function pathsSchema(extra = {}, required = []) {
  return objectSchema({ paths: { type: "array", items: { type: "string", minLength: 1 }, minItems: 1, maxItems: 200 }, ...extra }, required);
}

export function registerGitTools(registry, { root }) {
  registry.register({ name: "git.status", description: "Show the current branch and exact working-tree changes.", risk: "read", inputSchema: objectSchema(), execute: async () => git(root, ["status", "--short", "--branch"]) });
  registry.register({
    name: "git.diff", description: "Show working-tree, staged, or commit-range changes.", risk: "read",
    inputSchema: objectSchema({ staged: { type: "boolean" }, ref: { type: "string" }, paths: { type: "array", items: { type: "string" }, maxItems: 100 } }),
    execute: async ({ staged = false, ref, paths = [] }) => { const args = ["diff"]; if (staged) args.push("--cached"); if (ref) args.push(ref); if (paths.length) args.push("--", ...paths); return git(root, args); },
  });
  registry.register({
    name: "git.log", description: "Read recent commit history.", risk: "read",
    inputSchema: objectSchema({ limit: { type: "integer", minimum: 1, maximum: 200 }, ref: { type: "string" } }),
    execute: async ({ limit = 20, ref }) => git(root, ["log", `--max-count=${limit}`, "--date=iso-strict", "--pretty=format:%h%x09%ad%x09%an%x09%s", ...(ref ? [ref] : [])]),
  });
  registry.register({
    name: "git.branch", description: "List local and remote branches and identify the current branch.", risk: "read",
    inputSchema: objectSchema({ all: { type: "boolean" } }), execute: async ({ all = true }) => git(root, ["branch", ...(all ? ["--all"] : []), "--verbose", "--no-abbrev"]),
  });
  registry.register({
    name: "git.checkout", description: "Switch to an existing branch with dirty-worktree protection.", risk: "write", approval: "confirm",
    inputSchema: objectSchema({ branch: { type: "string", minLength: 1 }, allow_dirty: { type: "boolean" } }, ["branch"]),
    execute: async ({ branch, allow_dirty = false }) => { await protectDirty(root, allow_dirty); return git(root, ["checkout", branch]); },
  });
  registry.register({
    name: "git.createBranch", description: "Create and switch to a new branch.", risk: "write", approval: "confirm",
    inputSchema: objectSchema({ branch: { type: "string", minLength: 1 }, start_point: { type: "string" }, allow_dirty: { type: "boolean" } }, ["branch"]),
    execute: async ({ branch, start_point, allow_dirty = false }) => { await protectDirty(root, allow_dirty); return git(root, ["checkout", "-b", branch, ...(start_point ? [start_point] : [])]); },
  });
  registry.register({
    name: "git.add", description: "Stage explicit paths for a commit.", risk: "write", approval: "confirm", inputSchema: pathsSchema({}, ["paths"]),
    execute: async ({ paths }) => git(root, ["add", "--", ...paths]),
  });
  registry.register({
    name: "git.commit", description: "Create a Git commit from already staged changes.", risk: "write", approval: "confirm",
    inputSchema: objectSchema({ message: { type: "string", minLength: 1, maxLength: 500 }, amend: { type: "boolean" } }, ["message"]),
    execute: async ({ message, amend = false }) => git(root, ["commit", ...(amend ? ["--amend"] : []), "-m", message]),
  });
  registry.register({
    name: "git.push", description: "Push commits to a remote repository. This changes remote state.", risk: "external", approval: "explicit",
    inputSchema: objectSchema({ remote: { type: "string" }, branch: { type: "string" }, set_upstream: { type: "boolean" }, force_with_lease: { type: "boolean" } }),
    execute: async ({ remote = "origin", branch, set_upstream = false, force_with_lease = false }) => git(root, ["push", ...(set_upstream ? ["--set-upstream"] : []), ...(force_with_lease ? ["--force-with-lease"] : []), remote, ...(branch ? [branch] : [])], 300_000),
  });
  registry.register({
    name: "git.pull", description: "Fetch and integrate a remote branch with dirty-worktree protection.", risk: "external", approval: "explicit",
    inputSchema: objectSchema({ remote: { type: "string" }, branch: { type: "string" }, rebase: { type: "boolean" }, allow_dirty: { type: "boolean" } }),
    execute: async ({ remote, branch, rebase = false, allow_dirty = false }) => { await protectDirty(root, allow_dirty); return git(root, ["pull", ...(rebase ? ["--rebase"] : []), ...(remote ? [remote] : []), ...(branch ? [branch] : [])], 300_000); },
  });
  registry.register({
    name: "git.fetch", description: "Fetch remote refs without changing the working tree.", risk: "external", approval: "confirm",
    inputSchema: objectSchema({ remote: { type: "string" }, prune: { type: "boolean" } }), execute: async ({ remote = "origin", prune = false }) => git(root, ["fetch", ...(prune ? ["--prune"] : []), remote], 300_000),
  });
  registry.register({
    name: "git.merge", description: "Merge a branch with dirty-worktree protection.", risk: "write", approval: "confirm",
    inputSchema: objectSchema({ branch: { type: "string", minLength: 1 }, no_ff: { type: "boolean" }, allow_dirty: { type: "boolean" } }, ["branch"]),
    execute: async ({ branch, no_ff = false, allow_dirty = false }) => { await protectDirty(root, allow_dirty); return git(root, ["merge", ...(no_ff ? ["--no-ff"] : []), branch]); },
  });
  registry.register({
    name: "git.restore", description: "Restore explicit paths from the index or a source revision. This can discard local changes.", risk: "write", approval: "confirm",
    inputSchema: pathsSchema({ staged: { type: "boolean" }, source: { type: "string" } }, ["paths"]),
    execute: async ({ paths, staged = false, source }) => git(root, ["restore", ...(staged ? ["--staged"] : []), ...(source ? ["--source", source] : []), "--", ...paths]),
  });
}
