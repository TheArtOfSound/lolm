// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import { objectSchema, runFile, commandResult } from "./shared.mjs";

async function gh(root, args, timeoutMs = 120_000) {
  return commandResult(await runFile("gh", args, { cwd: root, timeoutMs }), `gh ${args.slice(0, 2).join(" ")}`);
}

const numberSchema = { type: "integer", minimum: 1 };

export function registerGitHubTools(registry, { root }) {
  registry.register({ name: "github.auth", description: "Inspect GitHub CLI authentication without exposing tokens.", risk: "read", inputSchema: objectSchema(), execute: async () => gh(root, ["auth", "status"]) });
  registry.register({ name: "github.repo", description: "Inspect the current GitHub repository metadata.", risk: "read", inputSchema: objectSchema({ repo: { type: "string" } }), execute: async ({ repo }) => gh(root, ["repo", "view", ...(repo ? [repo] : []), "--json", "nameWithOwner,url,defaultBranchRef,visibility,description"]) });
  registry.register({
    name: "github.prList", description: "List pull requests with structured JSON output.", risk: "read",
    inputSchema: objectSchema({ repo: { type: "string" }, state: { type: "string", enum: ["open", "closed", "merged", "all"] }, limit: { type: "integer", minimum: 1, maximum: 200 } }),
    execute: async ({ repo, state = "open", limit = 30 }) => gh(root, ["pr", "list", ...(repo ? ["--repo", repo] : []), "--state", state, "--limit", String(limit), "--json", "number,title,state,url,headRefName,baseRefName,isDraft,author,statusCheckRollup"]),
  });
  registry.register({ name: "github.prView", description: "Inspect a pull request, checks, files, and review state.", risk: "read", inputSchema: objectSchema({ number: numberSchema, repo: { type: "string" } }, ["number"]), execute: async ({ number, repo }) => gh(root, ["pr", "view", String(number), ...(repo ? ["--repo", repo] : []), "--json", "number,title,body,state,url,files,reviews,reviewDecision,statusCheckRollup,commits"]), });
  registry.register({
    name: "github.prCreate", description: "Create a GitHub pull request from the current branch.", risk: "external", approval: "explicit",
    inputSchema: objectSchema({ title: { type: "string", minLength: 1 }, body: { type: "string" }, base: { type: "string" }, head: { type: "string" }, draft: { type: "boolean" }, repo: { type: "string" } }, ["title", "body"]),
    execute: async ({ title, body, base, head, draft = true, repo }) => gh(root, ["pr", "create", "--title", title, "--body", body, ...(base ? ["--base", base] : []), ...(head ? ["--head", head] : []), ...(draft ? ["--draft"] : []), ...(repo ? ["--repo", repo] : [])], 300_000),
  });
  registry.register({
    name: "github.prComment", description: "Add a comment to a pull request.", risk: "external", approval: "explicit",
    inputSchema: objectSchema({ number: numberSchema, body: { type: "string", minLength: 1 }, repo: { type: "string" } }, ["number", "body"]), execute: async ({ number, body, repo }) => gh(root, ["pr", "comment", String(number), "--body", body, ...(repo ? ["--repo", repo] : [])]),
  });
  registry.register({
    name: "github.issueList", description: "List repository issues with structured JSON output.", risk: "read",
    inputSchema: objectSchema({ repo: { type: "string" }, state: { type: "string", enum: ["open", "closed", "all"] }, limit: { type: "integer", minimum: 1, maximum: 200 } }), execute: async ({ repo, state = "open", limit = 30 }) => gh(root, ["issue", "list", ...(repo ? ["--repo", repo] : []), "--state", state, "--limit", String(limit), "--json", "number,title,state,url,labels,assignees,author"]),
  });
  registry.register({ name: "github.issueView", description: "Inspect a GitHub issue and comments.", risk: "read", inputSchema: objectSchema({ number: numberSchema, repo: { type: "string" } }, ["number"]), execute: async ({ number, repo }) => gh(root, ["issue", "view", String(number), ...(repo ? ["--repo", repo] : []), "--json", "number,title,body,state,url,labels,assignees,comments,author"]), });
  registry.register({
    name: "github.issueCreate", description: "Create a GitHub issue.", risk: "external", approval: "explicit",
    inputSchema: objectSchema({ title: { type: "string", minLength: 1 }, body: { type: "string" }, labels: { type: "array", items: { type: "string" }, maxItems: 20 }, repo: { type: "string" } }, ["title", "body"]),
    execute: async ({ title, body, labels = [], repo }) => gh(root, ["issue", "create", "--title", title, "--body", body, ...labels.flatMap((label) => ["--label", label]), ...(repo ? ["--repo", repo] : [])]),
  });
  registry.register({
    name: "github.runList", description: "List GitHub Actions workflow runs.", risk: "read",
    inputSchema: objectSchema({ repo: { type: "string" }, limit: { type: "integer", minimum: 1, maximum: 100 }, workflow: { type: "string" } }), execute: async ({ repo, limit = 20, workflow }) => gh(root, ["run", "list", ...(repo ? ["--repo", repo] : []), "--limit", String(limit), ...(workflow ? ["--workflow", workflow] : []), "--json", "databaseId,name,workflowName,status,conclusion,url,headBranch,headSha,createdAt"]),
  });
  registry.register({ name: "github.runView", description: "Inspect a GitHub Actions run and failed logs.", risk: "read", inputSchema: objectSchema({ id: { type: "integer", minimum: 1 }, repo: { type: "string" }, failed_logs: { type: "boolean" } }, ["id"]), execute: async ({ id, repo, failed_logs = false }) => gh(root, ["run", "view", String(id), ...(repo ? ["--repo", repo] : []), ...(failed_logs ? ["--log-failed"] : ["--json", "databaseId,name,status,conclusion,url,jobs,workflowName,headSha"])]), });
  registry.register({
    name: "github.workflowRun", description: "Dispatch a GitHub Actions workflow.", risk: "external", approval: "explicit",
    inputSchema: objectSchema({ workflow: { type: "string", minLength: 1 }, repo: { type: "string" }, ref: { type: "string" }, fields: { type: "object" } }, ["workflow"]),
    execute: async ({ workflow, repo, ref, fields = {} }) => gh(root, ["workflow", "run", workflow, ...(repo ? ["--repo", repo] : []), ...(ref ? ["--ref", ref] : []), ...Object.entries(fields).flatMap(([key, value]) => ["--field", `${key}=${value}`])]),
  });
}
