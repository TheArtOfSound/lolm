#!/usr/bin/env node
// Copyright (c) 2026 Qira LLC. All rights reserved.
/** User-facing LOLM launcher with verified delivery and deterministic continuity. */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import process from "node:process";
import {
  commandIndex,
  commandTask,
  isOfficialCredentialFabrication,
  makeDeliveryDirectory,
  requestedArtifactKind,
  requestedDestination,
  selectDeliveredArtifacts,
  walkFiles,
} from "../lib/delivery.mjs";
import {
  findContinuityRecord,
  listContinuityRecords,
  markRecordOpened,
  parseRunEvidence,
  recordContinuity,
  resolveContinuityQuestion,
} from "../lib/continuity.mjs";

const VERSION = "0.3.0-beta.2";
const CORE_VERSION = "0.3.0-beta.1";
const here = dirname(fileURLToPath(import.meta.url));
const coreCli = join(here, "lolm.mjs");
const argv = process.argv.slice(2);
const { command, task } = commandTask(argv);
const jsonMode = argv.includes("--json");

function printRefusal() {
  process.stderr.write(
    "LOLM cannot fabricate official proof of attendance, enrollment, employment, or another credential.\n" +
    "It can create a clearly labeled unofficial self-attestation, draft a request for genuine verification, " +
    "or assemble authentic documents you provide.\n",
  );
}

function artifactSelector(words) {
  let kind = "";
  let index = 1;
  for (const word of words) {
    if (/^\d+$/.test(word)) index = Math.max(1, Number(word));
    else if (!["--json", "-j"].includes(word)) kind = word.toLowerCase();
  }
  return { kind, index };
}

function output(value, { error = false } = {}) {
  const stream = error ? process.stderr : process.stdout;
  if (jsonMode) {
    stream.write(JSON.stringify(value, null, 2) + "\n");
    return;
  }
  if (typeof value === "string") stream.write(value.endsWith("\n") ? value : `${value}\n`);
  else stream.write(`${JSON.stringify(value)}\n`);
}

async function openLocal(path) {
  let executable = "xdg-open";
  let args = [path];
  if (process.platform === "darwin") executable = "open";
  else if (process.platform === "win32") {
    executable = "cmd";
    args = ["/c", "start", "", path];
  }
  if (process.env.LOLM_TEST_OPEN_COMMAND) {
    executable = process.execPath;
    args = [process.env.LOLM_TEST_OPEN_COMMAND, path];
  }
  return await new Promise((resolvePromise) => {
    let settled = false;
    const finish = (ok) => {
      if (settled) return;
      settled = true;
      resolvePromise(ok);
    };
    let child;
    try {
      child = spawn(executable, args, { stdio: "ignore", detached: true });
    } catch {
      finish(false);
      return;
    }
    child.once("error", () => finish(false));
    child.once("spawn", () => {
      child.unref();
      finish(true);
    });
    setTimeout(() => finish(false), 2000).unref();
  });
}

function recordSummary(record, position = 1) {
  const intact = (record.artifacts || []).filter((item) => item.exists && !item.changed);
  const changed = (record.artifacts || []).filter((item) => item.changed);
  const missing = (record.artifacts || []).filter((item) => !item.exists);
  return {
    index: position,
    id: record.id,
    ts: record.ts,
    task: record.task,
    kind: record.kind,
    verdict: record.verdict,
    receipt_sha: record.receipt_sha,
    task_id: record.task_id,
    sandbox_id: record.sandbox_id,
    states: record.states,
    fully_verified: record.fully_verified,
    intact: intact.map((item) => ({
      path: item.path,
      size: item.size,
      sha256: item.sha256,
      integrity: item.integrity,
      verified: item.verified,
    })),
    changed: changed.map((item) => ({ path: item.path, expected_sha256: item.sha256 })),
    missing: missing.map((item) => item.path),
  };
}

async function showArtifact({ action = "where", kind = "", index = 1 } = {}) {
  if (action === "list") {
    const records = await listContinuityRecords({ kind, limit: 50 });
    if (!records.length) {
      output(jsonMode ? { ok: false, error: "no_continuity_record" } : "No matching local continuity record was found.", { error: true });
      return 1;
    }
    if (jsonMode) output({ ok: true, records: records.map((record, i) => recordSummary(record, i + 1)) });
    else {
      records.forEach((record, i) => {
        const summary = recordSummary(record, i + 1);
        const path = summary.intact[0]?.path || summary.changed[0]?.path || summary.missing[0] || "<no local path>";
        process.stdout.write(`${i + 1}\t${record.kind}\t${record.verdict}\t${path}\n`);
      });
    }
    return 0;
  }

  const record = await findContinuityRecord({ kind, index });
  if (!record) {
    output(jsonMode ? { ok: false, error: "no_continuity_record", kind, index } : "No matching local continuity record was found.", { error: true });
    return 1;
  }
  const intact = record.artifacts.filter((item) => item.exists && !item.changed);
  const changed = record.artifacts.filter((item) => item.changed);
  const missing = record.artifacts.filter((item) => !item.exists);

  if (action === "inspect") {
    output(jsonMode ? { ok: intact.length > 0, record: recordSummary(record, index) } : JSON.stringify(recordSummary(record, index), null, 2));
    return intact.length ? 0 : 1;
  }
  if (!intact.length) {
    const message = changed.length
      ? "The recorded local artifact exists, but its SHA-256 has changed since delivery."
      : missing.length
        ? "The recorded local artifact is missing."
        : "No intact local artifact was found in the matching record.";
    output(jsonMode ? { ok: false, error: changed.length ? "artifact_changed" : "artifact_missing", record: recordSummary(record, index) } : message, { error: true });
    return 1;
  }
  if (action === "open") {
    const opened = await openLocal(intact[0].path);
    if (!opened) {
      output(jsonMode ? { ok: false, error: "host_opener_unavailable", path: intact[0].path } : `Could not open ${intact[0].path} with the host operating system.`, { error: true });
      return 1;
    }
    await markRecordOpened(record.id);
  }
  if (jsonMode) output({ ok: true, action, record: recordSummary(record, index), paths: intact.map((item) => item.path) });
  else for (const artifact of intact) process.stdout.write(`${artifact.path}\n`);
  return 0;
}

async function renderContinuityResolution(resolution) {
  if (!resolution?.handled) return null;
  if (resolution.intent === "open" && resolution.ok && resolution.paths?.[0]) {
    const opened = await openLocal(resolution.paths[0]);
    if (!opened) {
      output(jsonMode ? { ...resolution, ok: false, code: 1, error: "host_opener_unavailable" } : `Could not open ${resolution.paths[0]} with the host operating system.`, { error: true });
      return 1;
    }
    await markRecordOpened(resolution.record.id);
  }
  if (jsonMode) output(resolution);
  else if (resolution.paths?.length) {
    for (const path of resolution.paths) process.stdout.write(`${path}\n`);
  } else if (resolution.artifacts) {
    for (const artifact of resolution.artifacts) {
      const state = !artifact.exists ? "missing" : artifact.changed ? "changed" : artifact.verified ? "verified" : "unverified";
      process.stdout.write(`${state}\t${artifact.path}\n`);
    }
  } else if (resolution.value) output(resolution.value);
  else output(resolution.message || (resolution.ok ? "Resolved from local continuity." : "Unable to resolve from local continuity."), { error: !resolution.ok });
  return resolution.code;
}

async function runCore(args) {
  return await new Promise((resolvePromise) => {
    const child = spawn(process.execPath, [coreCli, ...args], {
      stdio: ["inherit", "pipe", "pipe"],
      env: process.env,
    });
    let transcript = "";
    const capture = (chunk, stream) => {
      const text = String(chunk);
      stream.write(text);
      transcript = (transcript + text).slice(-512 * 1024);
    };
    child.stdout?.on("data", (chunk) => capture(chunk, process.stdout));
    child.stderr?.on("data", (chunk) => capture(chunk, process.stderr));
    const forward = (signal) => {
      try { child.kill(signal); } catch { /* already exited */ }
    };
    process.once("SIGINT", () => forward("SIGINT"));
    process.once("SIGTERM", () => forward("SIGTERM"));
    child.once("error", (error) => {
      process.stderr.write(`LOLM failed to start: ${error.message}\n`);
      resolvePromise({ code: 1, transcript });
    });
    child.once("exit", (code, signal) => {
      if (signal) resolvePromise({ code: signal === "SIGINT" ? 130 : 1, transcript });
      else resolvePromise({ code: Number.isInteger(code) ? code : 1, transcript });
    });
  });
}

function rewritePresentation(text) {
  let rendered = String(text || "").split(CORE_VERSION).join(VERSION);
  if (!rendered.includes("artifact list|where|inspect|open")) {
    rendered = rendered.replace(
      "  receipts              Recent sealed code receipts.\n",
      "  receipts              Recent sealed code receipts.\n" +
      "  artifact list|where|inspect|open [kind] [index]\n" +
      "                        Resolve verified local artifacts without a model call.\n" +
      "  artifact last|open    Backward-compatible artifact shortcuts.\n",
    );
  }
  if (!rendered.includes("--trace")) {
    rendered = rendered.replace(
      "  --quiet, -q           less progress\n",
      "  --quiet, -q           less progress\n" +
      "  --trace               code: show the full controller and sandbox stream\n",
    );
  }
  return rendered;
}

async function runCorePresentation(args) {
  return await new Promise((resolvePromise) => {
    const child = spawn(process.execPath, [coreCli, ...args], {
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, NO_COLOR: process.env.NO_COLOR || "1" },
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.once("error", (error) => {
      process.stderr.write(`LOLM failed to start: ${error.message}\n`);
      resolvePromise(1);
    });
    child.once("exit", (code) => {
      if (stdout) process.stdout.write(rewritePresentation(stdout));
      if (stderr) process.stderr.write(rewritePresentation(stderr));
      resolvePromise(Number.isInteger(code) ? code : 1);
    });
  });
}

async function main() {
  if (!command && (argv.includes("--version") || argv.includes("-V"))) {
    process.stdout.write(`${VERSION}\n`);
    return 0;
  }
  const presentationOnly = argv.length === 0 || command === "help" || argv.includes("--help") || argv.includes("-h");
  if (presentationOnly) return await runCorePresentation(argv);

  if (command === "artifact") {
    const idx = commandIndex(argv);
    const sub = (argv[idx + 1] || "where").toLowerCase();
    const { kind, index } = artifactSelector(argv.slice(idx + 2));
    if (["last", "where", "path"].includes(sub)) return await showArtifact({ action: "where", kind, index });
    if (sub === "list") return await showArtifact({ action: "list", kind, index });
    if (sub === "inspect") return await showArtifact({ action: "inspect", kind, index });
    if (sub === "open") return await showArtifact({ action: "open", kind, index });
    process.stderr.write("usage: lolm artifact [list|where|inspect|open] [kind] [index] [--json]\n");
    return 2;
  }

  if (command === "ask") {
    const resolved = await resolveContinuityQuestion(task);
    const localCode = await renderContinuityResolution(resolved);
    if (localCode != null) return localCode;
  }

  if (["code", "build"].includes(command) && isOfficialCredentialFabrication(task)) {
    printRefusal();
    return 2;
  }

  const next = [...argv];
  let deliveryDestination = "";
  let automaticDestination = false;
  let kind = "";
  if (command === "code") {
    kind = requestedArtifactKind(task);
    const saveIndex = next.indexOf("--save");
    if (saveIndex >= 0 && next[saveIndex + 1]) {
      deliveryDestination = next[saveIndex + 1];
    } else if (kind) {
      deliveryDestination = makeDeliveryDirectory(task);
      automaticDestination = true;
      next.push("--save", deliveryDestination);
    }
    const traceIndex = next.indexOf("--trace");
    const trace = traceIndex >= 0;
    if (trace) next.splice(traceIndex, 1);
    if (!trace && !next.includes("--quiet") && !next.includes("-q") && !next.includes("--json")) next.push("--quiet");
  }

  const result = await runCore(next);
  if (result.code !== 0) return result.code;
  if (!kind || !deliveryDestination) return result.code;

  const files = await walkFiles(deliveryDestination);
  const delivered = selectDeliveredArtifacts(files, kind);
  if (!delivered.length) {
    process.stderr.write(
      `LOLM did not deliver the requested ${kind || "artifact"}. ` +
      `The run may have created only source code inside ${deliveryDestination}.\n`,
    );
    return 1;
  }
  const evidence = parseRunEvidence(result.transcript);
  const saved = await recordContinuity({
    task,
    kind,
    destination: automaticDestination ? (requestedDestination(task) || deliveryDestination) : deliveryDestination,
    files: delivered,
    generated: true,
    verified: evidence.verdict === "shipped",
    exported: true,
    delivered: true,
    ...evidence,
  });
  process.stdout.write(`delivered ${saved.kind}\n`);
  for (const artifact of saved.artifacts.filter((item) => item.exists)) process.stdout.write(`saved     ${artifact.path}\n`);
  return 0;
}

process.exitCode = await main();
