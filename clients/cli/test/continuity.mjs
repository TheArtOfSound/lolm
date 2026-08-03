// Copyright (c) 2026 Qira LLC. All rights reserved.
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";
import {
  CONTINUITY_SCHEMA,
  classifyContinuityQuestion,
  findContinuityRecord,
  listContinuityRecords,
  loadContinuityLedger,
  loadLatestSessionPointer,
  parseRunEvidence,
  recordContinuity,
  resolveContinuityQuestion,
} from "../lib/continuity.mjs";

const run = promisify(execFile);
const here = dirname(fileURLToPath(import.meta.url));
const BIN = join(here, "..", "bin", "lolm-delivery.mjs");
const CORE_BIN = join(here, "..", "bin", "lolm.mjs");
const MODULE_URL = pathToFileURL(join(here, "..", "lib", "continuity.mjs")).href;

let passed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

function sha256(body) {
  return createHash("sha256").update(body).digest("hex");
}

async function isolated(name) {
  const root = await mkdtemp(join(tmpdir(), `lolm-continuity-${name}-`));
  const ledger = join(root, "continuity.json");
  const sessions = join(root, "sessions");
  return {
    root,
    ledger,
    sessions,
    env: {
      ...process.env,
      LOLM_CONTINUITY_LEDGER: ledger,
      LOLM_SESSION_DIR: sessions,
      NO_COLOR: "1",
    },
  };
}

async function withEnvironment(values, fn) {
  const prior = new Map();
  for (const [key, value] of Object.entries(values)) {
    prior.set(key, process.env[key]);
    if (value == null) delete process.env[key];
    else process.env[key] = value;
  }
  try {
    return await fn();
  } finally {
    for (const [key, value] of prior) {
      if (value == null) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

async function withLedger(ctx, fn) {
  return await withEnvironment({
    LOLM_CONTINUITY_LEDGER: ctx.ledger,
    LOLM_SESSION_DIR: ctx.sessions,
  }, fn);
}

function buildReferenceCases() {
  const kinds = ["PDF", "document", "spreadsheet", "slides", "image", "HTML", "ZIP archive"];
  const cases = [];
  for (const kind of kinds) {
    for (const text of [
      `where is the ${kind}?`,
      `where did you save the ${kind}?`,
      `find the ${kind}`,
      `what is the path to the ${kind}?`,
      `which folder contains the ${kind}?`,
    ]) cases.push([text, "where"]);
    for (const text of [
      `open the ${kind}`,
      `show me the ${kind}`,
      `launch the ${kind}`,
    ]) cases.push([text, "open"]);
    for (const text of [
      `was the ${kind} delivered?`,
      `did the ${kind} save?`,
      `was the ${kind} exported?`,
      `did the ${kind} actually get delivered?`,
    ]) cases.push([text, "delivery"]);
  }
  for (const text of [
    "what did you create?",
    "what did you make?",
    "what did you generate?",
    "what was created?",
    "what was made?",
    "what was generated?",
    "what file was created?",
    "what files were created?",
    "which file did you make?",
    "which files did you generate?",
  ]) cases.push([text, "created"]);
  for (const [text, intent] of [
    ["what was the last task?", "task"],
    ["show me the previous task", "task"],
    ["prior task", "task"],
    ["what was the last run?", "run"],
    ["show the previous run", "run"],
    ["prior run", "run"],
    ["what was the last receipt?", "receipt"],
    ["show me the previous receipt", "receipt"],
    ["prior receipt", "receipt"],
    ["retry that", "retry"],
    ["try that again", "retry"],
    ["redo that", "retry"],
    ["run that again", "retry"],
    ["resume that", "resume"],
    ["continue that", "resume"],
    ["pick that up", "resume"],
    ["resume the last run", "resume"],
  ]) cases.push([text, intent]);
  return cases;
}

const referenceCases = buildReferenceCases();

test("classifies at least 100 deterministic continuity phrasings", () => {
  assert.ok(referenceCases.length >= 100, `only ${referenceCases.length} cases`);
  for (const [text, intent] of referenceCases) {
    const result = classifyContinuityQuestion(text);
    assert.ok(result, `unclassified: ${text}`);
    assert.equal(result.intent, intent, text);
  }
});

test("does not hijack ordinary informational questions", () => {
  for (const text of [
    "what is a PDF?",
    "explain file systems",
    "how does HTML work?",
    "tell me about the previous US election",
    "open source software is useful",
    "was the report accurate?",
    "retry policies in distributed systems",
    "resume writing is difficult",
  ]) assert.equal(classifyContinuityQuestion(text), null, text);
});

test("extracts receipt, manifest, session, run, task, sandbox, checkpoint, and verdict evidence", () => {
  const receipt = "a".repeat(64);
  const manifest = "b".repeat(64);
  const parsed = parseRunEvidence(
    `sandbox sbx_deadbeef\nsession_id=sess_123456\nrun_id=run_123456\n` +
    `checkpoint=ckpt_123\nverdict shipped\nreceipt ${receipt}\nmanifest ${manifest}\ntask task_abcdef123\n`,
  );
  assert.deepEqual(parsed, {
    receipt_sha: receipt,
    manifest_sha: manifest,
    session_id: "sess_123456",
    run_id: "run_123456",
    task_id: "task_abcdef123",
    sandbox_id: "sbx_deadbeef",
    checkpoint_id: "ckpt_123",
    verdict: "shipped",
  });
});

test("records stable artifact IDs, safe pointers, and verified intact bytes", async () => {
  const ctx = await isolated("verified");
  const pdf = join(ctx.root, "output.pdf");
  const body = Buffer.from("%PDF-1.4\nverified\n%%EOF\n");
  await writeFile(pdf, body);
  const pointer = {
    session_id: "sess_123456",
    run_id: "run_123456",
    checkpoint_id: "ckpt_123",
    resume_available: true,
    status: "terminated",
    task: "create a PDF",
    server_artifact_ids: ["server_artifact_1"],
  };
  await withLedger(ctx, async () => {
    await recordContinuity({
      task: "create a PDF",
      kind: "pdf",
      destination: ctx.root,
      files: [pdf],
      verified: true,
      delivered: true,
      receipt_sha: "c".repeat(64),
      manifest_sha: "d".repeat(64),
      task_id: "task_test",
      verdict: "shipped",
      session_pointer: pointer,
    });
    const record = await findContinuityRecord({ kind: "pdf" });
    assert.equal(record.fully_verified, true);
    assert.match(record.artifact_ids[0], /^artifact_[a-f0-9]{24}$/);
    assert.equal(record.artifacts[0].sha256, sha256(body));
    assert.equal(record.artifacts[0].expected_sha256, sha256(body));
    assert.equal(record.artifacts[0].current_sha256, sha256(body));
    assert.equal(record.artifacts[0].integrity, "verified");
    assert.equal(record.session_id, pointer.session_id);
    assert.equal(record.run_id, pointer.run_id);
    assert.equal(record.checkpoint_id, pointer.checkpoint_id);
    assert.equal(record.resume_pointer.available, true);
    assert.deepEqual(record.server_artifact_ids, ["server_artifact_1"]);
    const status = await resolveContinuityQuestion("was the PDF delivered?");
    assert.equal(status.ok, true);
    const retry = await resolveContinuityQuestion("retry that");
    assert.equal(retry.action, "retry");
    const resume = await resolveContinuityQuestion("resume that");
    assert.equal(resume.action, "resume");
  });
});

test("loads only safe session pointers and never returns the resume token", async () => {
  const ctx = await isolated("session-pointer");
  await mkdir(ctx.sessions, { recursive: true });
  await writeFile(join(ctx.sessions, "sess_1.json"), JSON.stringify({
    session_id: "sess_123456",
    last_code_run_id: "run_123456",
    last_run_task: "create a PDF",
    last_run_status: "terminated",
    last_checkpoint_id: "ckpt_123",
    resume_token: "secret-resume-token",
    workspace_snapshot: { "main.py": "print('x')" },
    artifact_ids: ["artifact_server"],
    last_receipt_sha: "a".repeat(64),
    last_manifest_sha: "b".repeat(64),
  }));
  await withLedger(ctx, async () => {
    const pointer = await loadLatestSessionPointer();
    assert.equal(pointer.session_id, "sess_123456");
    assert.equal(pointer.checkpoint_id, "ckpt_123");
    assert.equal(pointer.resume_available, true);
    assert.equal(pointer.workspace_file_count, 1);
    assert.equal("resume_token" in pointer, false);
    assert.doesNotMatch(JSON.stringify(pointer), /secret-resume-token/);
  });
});

test("detects a modified local file and preserves expected versus current SHA", async () => {
  const ctx = await isolated("changed");
  const pdf = join(ctx.root, "output.pdf");
  const original = Buffer.from("%PDF-1.4\noriginal\n");
  const changedBody = Buffer.from("%PDF-1.4\nchanged\n");
  await writeFile(pdf, original);
  await withLedger(ctx, async () => {
    await recordContinuity({
      task: "make PDF",
      kind: "pdf",
      destination: ctx.root,
      files: [pdf],
      verified: true,
      delivered: true,
      receipt_sha: "e".repeat(64),
      verdict: "shipped",
    });
    await writeFile(pdf, changedBody);
    const record = await findContinuityRecord({ kind: "pdf" });
    assert.equal(record.artifacts[0].changed, true);
    assert.equal(record.artifacts[0].verified, false);
    assert.equal(record.artifacts[0].expected_sha256, sha256(original));
    assert.equal(record.artifacts[0].current_sha256, sha256(changedBody));
    assert.notEqual(record.artifacts[0].expected_sha256, record.artifacts[0].current_sha256);
    const where = await resolveContinuityQuestion("where is the PDF?");
    assert.equal(where.ok, false);
    assert.match(where.message, /SHA-256 has changed/);
  });
});

test("detects a deleted local artifact", async () => {
  const ctx = await isolated("missing");
  const pdf = join(ctx.root, "output.pdf");
  await writeFile(pdf, Buffer.from("%PDF-1.4\n"));
  await withLedger(ctx, async () => {
    await recordContinuity({
      task: "make PDF",
      kind: "pdf",
      destination: ctx.root,
      files: [pdf],
      verified: true,
      delivered: true,
      receipt_sha: "f".repeat(64),
      verdict: "shipped",
    });
    await rm(pdf);
    const where = await resolveContinuityQuestion("find the PDF");
    assert.equal(where.ok, false);
    assert.match(where.message, /missing|unreadable/);
  });
});

test("migrates v1 paths without inventing SHA verification", async () => {
  const ctx = await isolated("migration");
  const pdf = join(ctx.root, "legacy.pdf");
  await writeFile(pdf, Buffer.from("%PDF-1.4\nlegacy\n"));
  await writeFile(ctx.ledger, JSON.stringify({
    schema: "lolm.delivery.ledger.v1",
    last: { task: "legacy", kind: "pdf", destination: ctx.root, files: [pdf], ts: 1 },
    deliveries: [{ task: "legacy", kind: "pdf", destination: ctx.root, files: [pdf], ts: 1 }],
  }));
  await withLedger(ctx, async () => {
    const ledger = await loadContinuityLedger();
    assert.equal(ledger.schema, CONTINUITY_SCHEMA);
    assert.equal(ledger.records.length, 1);
    const persisted = JSON.parse(await readFile(ctx.ledger, "utf8"));
    assert.equal(persisted.schema, CONTINUITY_SCHEMA);
    const record = await findContinuityRecord({ kind: "pdf" });
    assert.equal(record.artifacts[0].integrity, "legacy_unhashed");
    assert.equal(record.states.verified, false);
    assert.match(record.artifact_ids[0], /^artifact_[a-f0-9]{24}$/);
    const where = await resolveContinuityQuestion("where is the PDF?");
    assert.equal(where.ok, true);
    assert.equal(where.verified, false);
    const status = await resolveContinuityQuestion("was the PDF delivered?");
    assert.equal(status.ok, false);
    assert.match(status.message, /legacy delivery path/);
  });
});

test("fails closed on invalid JSON and unsupported ledger schemas", async () => {
  const ctx = await isolated("invalid-ledger");
  await writeFile(ctx.ledger, "{not valid json\n");
  await withLedger(ctx, async () => {
    await assert.rejects(loadContinuityLedger(), (error) => {
      assert.equal(error.code, "LOLM_CONTINUITY_INVALID_JSON");
      return true;
    });
  });
  await writeFile(ctx.ledger, JSON.stringify({ schema: "lolm.continuity.ledger.v999", records: [] }));
  await withLedger(ctx, async () => {
    await assert.rejects(loadContinuityLedger(), (error) => {
      assert.equal(error.code, "LOLM_CONTINUITY_UNSUPPORTED_SCHEMA");
      return true;
    });
  });
});

test("fails closed on ambiguous pronouns when several records exist", async () => {
  const ctx = await isolated("ambiguous");
  const pdf = join(ctx.root, "one.pdf");
  const image = join(ctx.root, "two.png");
  await writeFile(pdf, Buffer.from("%PDF-1.4\n"));
  await writeFile(image, Buffer.from("PNG"));
  await withLedger(ctx, async () => {
    await recordContinuity({ task: "pdf", kind: "pdf", destination: ctx.root, files: [pdf], delivered: true });
    await recordContinuity({ task: "image", kind: "image", destination: ctx.root, files: [image], delivered: true });
    const result = await resolveContinuityQuestion("where is it?");
    assert.equal(result.code, 2);
    assert.equal(result.intent, "clarify");
  });
});

test("selects artifact kinds and historical indices deterministically", async () => {
  const ctx = await isolated("selection");
  const first = join(ctx.root, "first.pdf");
  const image = join(ctx.root, "image.png");
  const second = join(ctx.root, "second.pdf");
  await writeFile(first, Buffer.from("%PDF-1.4\nfirst\n"));
  await writeFile(image, Buffer.from("PNG\n"));
  await writeFile(second, Buffer.from("%PDF-1.4\nsecond\n"));
  await withLedger(ctx, async () => {
    await recordContinuity({ task: "first", kind: "pdf", destination: ctx.root, files: [first], delivered: true });
    await recordContinuity({ task: "image", kind: "image", destination: ctx.root, files: [image], delivered: true });
    await recordContinuity({ task: "second", kind: "pdf", destination: ctx.root, files: [second], delivered: true });
    assert.equal((await findContinuityRecord({ kind: "pdf", index: 1 })).task, "second");
    assert.equal((await findContinuityRecord({ kind: "pdf", index: 2 })).task, "first");
    assert.equal((await listContinuityRecords({ kind: "image" })).length, 1);
  });
});

test("preserves all 30 simultaneous writers without corrupting JSON", async () => {
  const ctx = await isolated("concurrent");
  const jobs = [];
  for (let index = 0; index < 30; index++) {
    const file = join(ctx.root, `artifact-${index}.txt`);
    await writeFile(file, `artifact ${index}\n`);
    const script = [
      `import { recordContinuity } from ${JSON.stringify(MODULE_URL)};`,
      `await recordContinuity({task:${JSON.stringify(`task ${index}`)},kind:'document',destination:${JSON.stringify(ctx.root)},files:[${JSON.stringify(file)}],delivered:true,verdict:'shipped'});`,
    ].join("\n");
    jobs.push(run(process.execPath, ["--input-type=module", "--eval", script], {
      env: ctx.env,
      timeout: 30_000,
    }));
  }
  await Promise.all(jobs);
  await withLedger(ctx, async () => {
    const ledger = await loadContinuityLedger();
    assert.equal(ledger.records.length, 30);
    assert.equal(new Set(ledger.records.map((record) => record.task)).size, 30);
    JSON.parse(await readFile(ctx.ledger, "utf8"));
  });
});

test("30 isolated multi-process command sequences resolve without model or network access", async () => {
  for (let index = 0; index < 30; index++) {
    const ctx = await isolated(`sequence-${index}`);
    const pdf = join(ctx.root, `answer-${index}.pdf`);
    await writeFile(pdf, Buffer.from(`%PDF-1.4\nsequence ${index}\n%%EOF\n`));
    const receipt = index.toString(16).padStart(64, "0");
    const writer = [
      `import { recordContinuity } from ${JSON.stringify(MODULE_URL)};`,
      `await recordContinuity({task:${JSON.stringify(`sequence task ${index}`)},kind:'pdf',destination:${JSON.stringify(ctx.root)},files:[${JSON.stringify(pdf)}],verified:true,delivered:true,receipt_sha:${JSON.stringify(receipt)},run_id:${JSON.stringify(`run_sequence_${index}`)},verdict:'shipped'});`,
    ].join("\n");
    await run(process.execPath, ["--input-type=module", "--eval", writer], { env: ctx.env, timeout: 30_000 });

    const where = await run(process.execPath, [
      BIN, "ask", "where is the PDF?", "--base", "https://127.0.0.1.invalid",
    ], { env: ctx.env, timeout: 15_000 });
    assert.equal(where.stdout.trim(), pdf);
    assert.doesNotMatch(where.stdout + where.stderr, /ENOTFOUND|ECONNREFUSED|fetch failed|127\.0\.0\.1\.invalid/i);

    const inspect = await run(process.execPath, [BIN, "artifact", "inspect", "pdf", "--json"], {
      env: ctx.env,
      timeout: 15_000,
    });
    const parsed = JSON.parse(inspect.stdout);
    assert.equal(parsed.ok, true);
    assert.equal(parsed.record.fully_verified, true);
    assert.equal(parsed.record.receipt_sha, receipt);
    assert.match(parsed.record.artifact_ids[0], /^artifact_[a-f0-9]{24}$/);
    await rm(ctx.root, { recursive: true, force: true });
  }
});

test("retry that and resume that translate locally into core session actions", async () => {
  const ctx = await isolated("actions");
  const pdf = join(ctx.root, "action.pdf");
  const fakeCore = join(ctx.root, "fake-core.mjs");
  const argsPath = join(ctx.root, "core-args.jsonl");
  await writeFile(pdf, Buffer.from("%PDF-1.4\naction\n"));
  await writeFile(fakeCore, [
    `import { appendFile } from 'node:fs/promises';`,
    `await appendFile(process.env.LOLM_ACTION_ARGS, JSON.stringify(process.argv.slice(2)) + '\\n');`,
    `process.stdout.write(JSON.stringify({ok:true, receipt:{verdict:'shipped', files:['action.pdf']}}) + '\\n');`,
  ].join("\n"));
  await withLedger(ctx, async () => {
    await recordContinuity({
      task: "create action PDF",
      kind: "pdf",
      destination: ctx.root,
      files: [pdf],
      verified: true,
      delivered: true,
      receipt_sha: "a".repeat(64),
      verdict: "terminated",
      session_pointer: {
        session_id: "sess_action",
        run_id: "run_action",
        task: "create action PDF",
        status: "terminated",
        checkpoint_id: "ckpt_action",
        resume_available: true,
      },
    });
  });
  const env = { ...ctx.env, LOLM_CORE_CLI: fakeCore, LOLM_ACTION_ARGS: argsPath };
  const retry = await run(process.execPath, [BIN, "ask", "retry that", "--base", "https://127.0.0.1.invalid"], {
    env,
    timeout: 15_000,
  });
  assert.match(retry.stdout, /^retry shipped/m);
  const resume = await run(process.execPath, [BIN, "ask", "resume that", "--base", "https://127.0.0.1.invalid"], {
    env,
    timeout: 15_000,
  });
  assert.match(resume.stdout, /^resume shipped/m);
  const calls = (await readFile(argsPath, "utf8")).trim().split(/\r?\n/).map(JSON.parse);
  assert.deepEqual(calls, [
    ["--json", "retry", "--yes", "--conversation", "sess_action"],
    ["--json", "resume", "--yes", "--conversation", "sess_action"],
  ]);
  assert.doesNotMatch(retry.stdout + retry.stderr + resume.stdout + resume.stderr, /ENOTFOUND|fetch failed/);
});


test("core last selects the exact session and retry flags parse", async () => {
  const ctx = await isolated("core-session-selection");
  await mkdir(ctx.sessions, { recursive: true });
  await writeFile(join(ctx.sessions, "target.json"), JSON.stringify({
    session_id: "sess_target",
    last_code_run_id: "run_target",
    last_run_task: "target task",
    last_run_status: "terminated",
    last_checkpoint_id: "ckpt_target",
    workspace_snapshot: { "target.py": "print(1)" },
    updated_ts: 1,
  }));
  await new Promise((done) => setTimeout(done, 20));
  await writeFile(join(ctx.sessions, "decoy.json"), JSON.stringify({
    session_id: "sess_decoy",
    last_code_run_id: "run_decoy",
    last_run_task: "decoy task",
    last_run_status: "terminated",
    last_checkpoint_id: "ckpt_decoy",
    workspace_snapshot: { "decoy.py": "print(2)" },
    updated_ts: 2,
  }));
  const selected = await run(process.execPath, [
    CORE_BIN, "--json", "last", "--conversation", "sess_target",
  ], { env: ctx.env, timeout: 15_000 });
  const payload = JSON.parse(selected.stdout);
  assert.equal(payload.session_id, "sess_target");
  assert.equal(payload.last_code_run_id, "run_target");
  let retryFailure;
  try {
    await run(process.execPath, [
      CORE_BIN, "--json", "retry", "--yes", "--conversation", "missing_session",
    ], { env: ctx.env, timeout: 15_000 });
  } catch (error) {
    retryFailure = error;
  }
  assert.ok(retryFailure);
  assert.equal(retryFailure.code, 2);
  assert.doesNotMatch(retryFailure.stderr || "", /unknown flag/i);
  assert.equal(JSON.parse(retryFailure.stdout).action, "clarify");
});

test("artifact list, where, and inspect provide machine-readable local state", async () => {
  const ctx = await isolated("commands");
  const pdf = join(ctx.root, "command.pdf");
  await writeFile(pdf, Buffer.from("%PDF-1.4\ncommand\n"));
  await withLedger(ctx, async () => {
    await recordContinuity({
      task: "command task",
      kind: "pdf",
      destination: ctx.root,
      files: [pdf],
      verified: true,
      delivered: true,
      receipt_sha: "e".repeat(64),
      verdict: "shipped",
    });
  });
  for (const args of [
    ["artifact", "list", "pdf", "--json"],
    ["artifact", "where", "pdf", "--json"],
    ["artifact", "inspect", "pdf", "--json"],
  ]) {
    const result = await run(process.execPath, [BIN, ...args], { env: ctx.env, timeout: 15_000 });
    const parsed = JSON.parse(result.stdout);
    assert.equal(parsed.ok, true, args.join(" "));
    assert.equal(result.stderr, "");
  }
});

for (const [name, fn] of tests) {
  try {
    await fn();
    passed++;
    process.stdout.write(`✓ ${name}\n`);
  } catch (error) {
    process.stderr.write(`✗ ${name}\n${error.stack || error}\n`);
    process.exitCode = 1;
  }
}
process.stdout.write(`${passed}/${tests.length} continuity tests passed\n`);
