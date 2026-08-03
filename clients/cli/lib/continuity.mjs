// Copyright (c) 2026 Qira LLC. All rights reserved.
/** Deterministic cross-command continuity and local artifact integrity. */
import { createHash, randomUUID } from "node:crypto";
import { createReadStream } from "node:fs";
import {
  lstat,
  mkdir,
  open,
  readFile,
  readdir,
  rename,
  stat,
  unlink,
  writeFile,
} from "node:fs/promises";
import { dirname, extname, join, resolve } from "node:path";
import { homedir } from "node:os";

export const CONTINUITY_SCHEMA = "lolm.continuity.ledger.v2";
const LEGACY_SCHEMA = "lolm.delivery.ledger.v1";
const MAX_RECORDS = 200;
const MAX_ARTIFACTS = 100;
const LOCK_RETRIES = 300;
const LOCK_STALE_MS = 30_000;
const SHA_RE = /^[a-f0-9]{64}$/i;

export function continuityLedgerPath() {
  return resolve(
    process.env.LOLM_CONTINUITY_LEDGER ||
    process.env.LOLM_DELIVERY_LEDGER ||
    join(homedir(), ".lolm", "continuity.json"),
  );
}

function sessionDirectory() {
  return resolve(process.env.LOLM_SESSION_DIR || join(homedir(), ".lolm", "sessions"));
}

function clean(value, limit = 1000) {
  return String(value || "").replace(/\u0000/g, "").slice(0, limit);
}

function normalizedKind(value) {
  const kind = clean(value, 40).toLowerCase();
  if (["doc", "document", "word", "report", "letter"].includes(kind)) return "document";
  if (["jpg", "jpeg", "png", "svg", "webp", "picture"].includes(kind)) return "image";
  if (["xls", "excel", "spreadsheet", "csv"].includes(kind)) return "xlsx";
  if (["ppt", "powerpoint", "slides", "presentation"].includes(kind)) return "pptx";
  if (["zip", "tar", "archive"].includes(kind)) return "archive";
  return kind || "artifact";
}

function inferKind(path) {
  const ext = extname(path).toLowerCase();
  if (ext === ".pdf") return "pdf";
  if ([".doc", ".docx", ".odt", ".rtf", ".txt", ".md"].includes(ext)) return "document";
  if ([".xls", ".xlsx", ".csv"].includes(ext)) return "xlsx";
  if ([".ppt", ".pptx"].includes(ext)) return "pptx";
  if ([".png", ".jpg", ".jpeg", ".svg", ".webp"].includes(ext)) return "image";
  if ([".html", ".htm"].includes(ext)) return "html";
  if ([".zip", ".tar", ".gz", ".tgz"].includes(ext)) return "archive";
  return "artifact";
}

function artifactId(path, kind, sha256) {
  const material = `${normalizedKind(kind)}\u0000${resolve(String(path))}\u0000${clean(sha256, 64).toLowerCase()}`;
  return `artifact_${createHash("sha256").update(material).digest("hex").slice(0, 24)}`;
}

function sleep(ms) {
  return new Promise((done) => setTimeout(done, ms));
}

async function atomicWrite(path, value) {
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, JSON.stringify(value, null, 2) + "\n", { mode: 0o600 });
    await rename(temporary, path);
  } finally {
    try { await unlink(temporary); } catch { /* renamed or absent */ }
  }
}

async function withLock(fn) {
  const path = continuityLedgerPath();
  const lockPath = `${path}.lock`;
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  let handle = null;
  for (let attempt = 0; attempt < LOCK_RETRIES; attempt++) {
    try {
      handle = await open(lockPath, "wx", 0o600);
      await handle.writeFile(JSON.stringify({ pid: process.pid, ts: Date.now() }) + "\n");
      break;
    } catch (error) {
      if (error?.code !== "EEXIST") throw error;
      try {
        if (Date.now() - (await stat(lockPath)).mtimeMs > LOCK_STALE_MS) {
          await unlink(lockPath);
          continue;
        }
      } catch (lockError) {
        if (lockError?.code !== "ENOENT") throw lockError;
      }
      await sleep(Math.min(100, attempt + 5));
    }
  }
  if (!handle) throw new Error(`continuity ledger lock timeout: ${lockPath}`);
  try {
    return await fn(path);
  } finally {
    try { await handle.close(); } catch { /* already closed */ }
    try { await unlink(lockPath); } catch { /* already absent */ }
  }
}

async function readRaw(path = continuityLedgerPath()) {
  let text;
  try {
    text = await readFile(path, "utf8");
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
  try {
    return JSON.parse(text);
  } catch (cause) {
    const error = new Error(`continuity ledger contains invalid JSON: ${path}`);
    error.code = "LOLM_CONTINUITY_INVALID_JSON";
    error.cause = cause;
    throw error;
  }
}

async function hashFile(path) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(path)) hash.update(chunk);
  return hash.digest("hex");
}

async function inspectFile(path) {
  const absolute = resolve(String(path));
  try {
    const info = await lstat(absolute);
    if (info.isSymbolicLink()) return { path: absolute, exists: false, changed: false, reason: "symlink" };
    if (!info.isFile()) return { path: absolute, exists: false, changed: false, reason: "not_file" };
    return {
      path: absolute,
      name: absolute.split(/[\\/]/).at(-1) || absolute,
      kind: inferKind(absolute),
      exists: true,
      changed: false,
      size: info.size,
      sha256: await hashFile(absolute),
    };
  } catch (error) {
    return {
      path: absolute,
      exists: false,
      changed: false,
      reason: error?.code === "ENOENT" ? "missing" : "unreadable",
    };
  }
}

function unsupportedSchema(raw) {
  const error = new Error(`unsupported continuity ledger schema: ${clean(raw?.schema || "unknown", 100)}`);
  error.code = "LOLM_CONTINUITY_UNSUPPORTED_SCHEMA";
  return error;
}

function migrateLegacy(raw) {
  let deliveries = Array.isArray(raw?.deliveries) ? raw.deliveries : [];
  if (!deliveries.length && raw?.last) deliveries = [raw.last];
  const records = deliveries.slice(-MAX_RECORDS).map((entry) => {
    const kind = normalizedKind(entry?.kind);
    const artifacts = (entry?.files || []).slice(0, MAX_ARTIFACTS).map((value) => {
      const path = resolve(String(value));
      return {
        path,
        name: path.split(/[\\/]/).at(-1) || path,
        kind,
        exists: true,
        changed: false,
        size: null,
        sha256: "",
        expected_sha256: "",
        current_sha256: "",
        artifact_id: artifactId(path, kind, ""),
        integrity: "legacy_unhashed",
      };
    });
    return {
      id: `migrated-${randomUUID()}`,
      ts: Number(entry?.ts || 0),
      task: clean(entry?.task),
      kind,
      destination: entry?.destination ? resolve(String(entry.destination)) : "",
      session_id: "",
      run_id: "",
      task_id: "",
      sandbox_id: "",
      receipt_sha: "",
      manifest_sha: "",
      artifact_ids: artifacts.map((artifact) => artifact.artifact_id),
      server_artifact_ids: [],
      checkpoint_id: "",
      resume_pointer: null,
      verdict: "legacy_delivery",
      states: { generated: true, verified: false, exported: true, delivered: true, opened: false },
      artifacts,
      source_schema: LEGACY_SCHEMA,
    };
  });
  return {
    schema: CONTINUITY_SCHEMA,
    migrated_from: clean(raw?.schema || LEGACY_SCHEMA, 100),
    records,
    last_id: records.at(-1)?.id || "",
  };
}

export function normalizeLedger(raw) {
  if (raw == null) return { schema: CONTINUITY_SCHEMA, records: [], last_id: "", migrated_from: "" };
  if (raw?.schema && ![CONTINUITY_SCHEMA, LEGACY_SCHEMA].includes(raw.schema)) throw unsupportedSchema(raw);
  if (raw?.schema === CONTINUITY_SCHEMA) {
    if (!Array.isArray(raw.records)) throw unsupportedSchema(raw);
    return {
      schema: CONTINUITY_SCHEMA,
      records: raw.records.slice(-MAX_RECORDS),
      last_id: clean(raw.last_id, 100),
      migrated_from: clean(raw.migrated_from, 100),
    };
  }
  if (raw?.schema === LEGACY_SCHEMA || (!raw?.schema && (Array.isArray(raw?.deliveries) || raw?.last))) {
    return migrateLegacy(raw);
  }
  throw unsupportedSchema(raw);
}

export async function loadContinuityLedger({ persistMigration = true } = {}) {
  const path = continuityLedgerPath();
  const raw = await readRaw(path);
  const ledger = normalizeLedger(raw);
  if (!persistMigration || !raw || raw.schema === CONTINUITY_SCHEMA) return ledger;
  return await withLock(async (lockedPath) => {
    const currentRaw = await readRaw(lockedPath);
    const current = normalizeLedger(currentRaw);
    if (currentRaw && currentRaw.schema !== CONTINUITY_SCHEMA) await atomicWrite(lockedPath, current);
    return current;
  });
}

export async function loadLatestSessionPointer() {
  const directory = sessionDirectory();
  let names = [];
  try {
    names = (await readdir(directory)).filter((name) => name.endsWith(".json"));
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
  const candidates = [];
  for (const name of names) {
    const path = join(directory, name);
    try {
      const info = await stat(path);
      if (info.isFile()) candidates.push({ path, mtime: info.mtimeMs });
    } catch { /* disappeared */ }
  }
  candidates.sort((a, b) => b.mtime - a.mtime);
  if (!candidates.length) return null;
  let raw;
  try { raw = JSON.parse(await readFile(candidates[0].path, "utf8")); }
  catch { return null; }
  const checkpointId = clean(raw.last_checkpoint_id, 160);
  const workspaceCount = raw.workspace_snapshot && typeof raw.workspace_snapshot === "object"
    ? Object.keys(raw.workspace_snapshot).length
    : 0;
  return {
    session_id: clean(raw.session_id, 160),
    run_id: clean(raw.last_code_run_id, 160),
    task: clean(raw.last_run_task),
    status: clean(raw.last_run_status, 40),
    checkpoint_id: checkpointId,
    resume_available: Boolean(checkpointId || workspaceCount || raw.resume_token),
    workspace_file_count: workspaceCount,
    receipt_sha: SHA_RE.test(clean(raw.last_receipt_sha, 128)) ? clean(raw.last_receipt_sha, 128) : "",
    manifest_sha: SHA_RE.test(clean(raw.last_manifest_sha, 128)) ? clean(raw.last_manifest_sha, 128) : "",
    server_artifact_ids: Array.isArray(raw.artifact_ids)
      ? raw.artifact_ids.slice(-20).map((value) => clean(value, 200))
      : [],
  };
}

export function parseRunEvidence(transcript) {
  const text = String(transcript || "");
  const pick = (pattern) => text.match(pattern)?.[1] || "";
  return {
    receipt_sha: pick(/\breceipt\s+([a-f0-9]{64})\b/i),
    manifest_sha: pick(/\b(?:manifest|artifact manifest)\s+([a-f0-9]{64})\b/i),
    session_id: pick(/\bsession(?:_id)?[\s:=]+([a-z0-9_.-]{6,160})\b/i),
    run_id: pick(/\brun(?:_id)?[\s:=]+([a-z0-9_.-]{6,160})\b/i),
    task_id: pick(/\btask\s+(task_[a-z0-9]+)\b/i),
    sandbox_id: pick(/\bsandbox\s+(sbx_[a-z0-9]+)\b/i),
    checkpoint_id: pick(/\b(?:checkpoint|ckpt)[\s:=]+([a-z0-9_.-]{3,160})\b/i),
    verdict: pick(/\bverdict\s+(shipped|stuck|broken|refused|incomplete|terminated)\b/i).toLowerCase(),
  };
}

export async function recordContinuity(entry) {
  const requestedKind = normalizedKind(entry.kind);
  const session = entry.session_pointer && typeof entry.session_pointer === "object" ? entry.session_pointer : {};
  const receiptSha = clean(entry.receipt_sha || session.receipt_sha, 128);
  const manifestSha = clean(entry.manifest_sha || session.manifest_sha, 128);
  const inspected = [];
  for (const candidate of (entry.files || []).slice(0, MAX_ARTIFACTS)) {
    const evidence = await inspectFile(candidate);
    const kind = requestedKind === "artifact" ? evidence.kind : requestedKind;
    inspected.push({
      ...evidence,
      kind,
      artifact_id: artifactId(evidence.path, kind, evidence.sha256 || ""),
    });
  }
  const allExist = inspected.length > 0 && inspected.every((item) => item.exists);
  const verified = entry.verified === true && allExist && SHA_RE.test(receiptSha);
  const artifacts = inspected.map((item) => ({
    ...item,
    expected_sha256: item.sha256 || "",
    current_sha256: item.sha256 || "",
    integrity: !item.exists
      ? `unavailable_at_delivery:${item.reason || "unknown"}`
      : verified ? "verified_at_delivery" : "present_unverified_at_delivery",
  }));
  const sessionId = clean(entry.session_id || session.session_id, 160);
  const runId = clean(entry.run_id || session.run_id, 160);
  const checkpointId = clean(entry.checkpoint_id || session.checkpoint_id, 160);
  const resumeAvailable = Boolean(entry.resume_available ?? session.resume_available ?? checkpointId);
  const states = {
    generated: entry.generated !== false,
    verified,
    exported: entry.exported !== false && allExist,
    delivered: entry.delivered !== false && allExist,
    opened: Boolean(entry.opened),
  };
  const record = {
    id: clean(entry.id, 100) || `continuity-${randomUUID()}`,
    ts: Number(entry.ts || Date.now() / 1000),
    task: clean(entry.task || session.task),
    kind: requestedKind,
    destination: entry.destination ? resolve(String(entry.destination)) : "",
    session_id: sessionId,
    run_id: runId,
    task_id: clean(entry.task_id, 160),
    sandbox_id: clean(entry.sandbox_id, 160),
    receipt_sha: receiptSha,
    manifest_sha: manifestSha,
    artifact_ids: artifacts.map((item) => item.artifact_id),
    server_artifact_ids: Array.isArray(session.server_artifact_ids)
      ? session.server_artifact_ids.slice(-20).map((value) => clean(value, 200)) : [],
    checkpoint_id: checkpointId,
    resume_pointer: (sessionId || runId || checkpointId || resumeAvailable)
      ? {
          session_id: sessionId,
          run_id: runId,
          checkpoint_id: checkpointId,
          available: resumeAvailable,
          status: clean(entry.status || session.status || entry.verdict, 40),
        }
      : null,
    verdict: clean(entry.verdict || session.status, 40) || (states.delivered ? "delivered" : "incomplete"),
    states,
    artifacts,
    source_schema: CONTINUITY_SCHEMA,
  };
  return await withLock(async (path) => {
    const ledger = normalizeLedger(await readRaw(path));
    const records = [...ledger.records.slice(-(MAX_RECORDS - 1)), record];
    await atomicWrite(path, { ...ledger, schema: CONTINUITY_SCHEMA, records, last_id: record.id });
    return record;
  });
}

async function refreshRecord(record) {
  const artifacts = [];
  const receiptBound = SHA_RE.test(clean(record?.receipt_sha, 128));
  for (const artifact of (record?.artifacts || []).slice(0, MAX_ARTIFACTS)) {
    const current = await inspectFile(artifact.path);
    const expected = clean(artifact.expected_sha256 || artifact.sha256, 128);
    const currentSha = clean(current.sha256, 128);
    const changed = Boolean(current.exists && expected && currentSha !== expected);
    const verified = Boolean(current.exists && expected && !changed && record?.states?.verified && receiptBound);
    artifacts.push({
      ...artifact,
      ...current,
      sha256: expected || currentSha,
      expected_sha256: expected,
      current_sha256: currentSha,
      artifact_id: clean(artifact.artifact_id, 100) || artifactId(
        current.path || artifact.path,
        artifact.kind || current.kind,
        expected,
      ),
      changed,
      verified,
      integrity: !current.exists
        ? current.reason || "missing"
        : changed ? "changed" : verified ? "verified" : expected ? "hash_matches_unverified_record" : "legacy_unhashed",
    });
  }
  return {
    ...record,
    artifacts,
    artifact_ids: artifacts.map((item) => item.artifact_id),
    files: artifacts.filter((item) => item.exists && !item.changed).map((item) => item.path),
    verified_files: artifacts.filter((item) => item.verified).map((item) => item.path),
    existing_files: artifacts.filter((item) => item.exists).map((item) => item.path),
    exists: artifacts.some((item) => item.exists),
    intact: artifacts.some((item) => item.exists && !item.changed),
    fully_verified: artifacts.length > 0 && artifacts.every((item) => item.verified),
    missing: artifacts.filter((item) => !item.exists).map((item) => item.path),
    changed: artifacts.filter((item) => item.changed).map((item) => item.path),
  };
}

function kindMatches(record, kind) {
  const wanted = normalizedKind(kind);
  if (!kind || wanted === "artifact") return true;
  return normalizedKind(record.kind) === wanted
    || (record.artifacts || []).some((item) => normalizedKind(item.kind) === wanted);
}

export async function listContinuityRecords({ kind = "", limit = 20 } = {}) {
  const ledger = await loadContinuityLedger();
  const count = Math.max(1, Math.min(MAX_RECORDS, Number(limit) || 20));
  const selected = ledger.records.filter((record) => kindMatches(record, kind)).slice(-count).reverse();
  const records = [];
  for (const record of selected) records.push(await refreshRecord(record));
  return records;
}

export async function findContinuityRecord({ kind = "", index = 1 } = {}) {
  const records = await listContinuityRecords({ kind, limit: MAX_RECORDS });
  return records[Math.max(1, Number(index) || 1) - 1] || null;
}

export async function markRecordOpened(id) {
  return await withLock(async (path) => {
    const ledger = normalizeLedger(await readRaw(path));
    let found = false;
    const records = ledger.records.map((record) => {
      if (record.id !== id) return record;
      found = true;
      return { ...record, states: { ...record.states, opened: true }, opened_ts: Date.now() / 1000 };
    });
    if (found) await atomicWrite(path, { ...ledger, records });
    return found;
  });
}

function referentKind(text) {
  const value = String(text || "").toLowerCase();
  if (/\bpdf\b/.test(value)) return "pdf";
  if (/\b(docx|word|document|report|letter)\b/.test(value)) return "document";
  if (/\b(xlsx|excel|spreadsheet|csv)\b/.test(value)) return "xlsx";
  if (/\b(pptx|powerpoint|slides?|presentation)\b/.test(value)) return "pptx";
  if (/\b(image|png|jpe?g|svg|webp|picture)\b/.test(value)) return "image";
  if (/\b(html|webpage|website|web page)\b/.test(value)) return "html";
  if (/\b(zip|archive|tar)\b/.test(value)) return "archive";
  return "";
}

export function classifyContinuityQuestion(text) {
  const value = String(text || "").trim().toLowerCase();
  if (!value) return null;
  const kind = referentKind(value);
  const explicit = Boolean(kind || /\b(file|artifact)\b/.test(value));
  const pronounOnly = !explicit && /\b(it|that|this)\b/.test(value);
  const locationCue = /\b(where|location|path|find|folder|directory)\b/.test(value);
  const deliveryVerb = /\b(deliver|delivered|save|saved|export|exported)\b/.test(value);
  const deliveryShape = /\b(did|was|were|actually|get|got)\b/.test(value);

  if (/^(retry that|try that again|redo that|run that again|retry the last run)[.!]?$/i.test(value)) {
    return { intent: "retry", kind: "", ambiguous: false };
  }
  if (/^(resume that|continue that|pick that up|continue the last run|resume the last run)[.!]?$/i.test(value)) {
    return { intent: "resume", kind: "", ambiguous: false };
  }
  if ((/\bdid you actually (deliver|save|export)\b/.test(value) || ((explicit || pronounOnly) && deliveryVerb && deliveryShape)) && !locationCue) {
    return { intent: "delivery", kind, ambiguous: pronounOnly };
  }
  if ((locationCue || /\b(saved|save|put)\b/.test(value)) && (explicit || pronounOnly)) {
    return { intent: "where", kind, ambiguous: pronounOnly };
  }
  if (/\b(open|show me|launch)\b/.test(value) && (explicit || pronounOnly)) {
    return { intent: "open", kind, ambiguous: pronounOnly };
  }
  if (/\b(what did you (create|make|generate)|what was (created|made|generated)|which files? did you (create|make|generate)|what files? were (created|made|generated)|what files? (was|were) (created|made|generated))\b/.test(value)) {
    return { intent: "created", kind, ambiguous: false };
  }
  if (
    /\b(last|previous|prior)\s+(task|run|receipt)\b/.test(value)
    || /\bwhat (was|is) (the )?(last|previous) (task|run|receipt)\b/.test(value)
    || /\bshow (me )?(the )?(last|previous) (task|run|receipt)\b/.test(value)
  ) {
    return { intent: value.includes("receipt") ? "receipt" : value.includes("run") ? "run" : "task", kind, ambiguous: false };
  }
  return null;
}

export async function resolveContinuityQuestion(text) {
  const query = classifyContinuityQuestion(text);
  if (!query) return null;
  if (query.ambiguous && (await listContinuityRecords({ limit: 3 })).length > 1) {
    return {
      handled: true,
      ok: false,
      code: 2,
      intent: "clarify",
      message: "More than one recent artifact could match. Name the type, such as PDF, document, image, spreadsheet, slides, HTML, or archive.",
    };
  }

  const record = await findContinuityRecord({ kind: query.kind, index: 1 });
  if (!record) return { handled: true, ok: false, code: 1, intent: query.intent, message: "No matching local continuity record was found." };

  if (query.intent === "retry") {
    const value = record.run_id || record.session_id || record.task_id || record.sandbox_id;
    return value && record.task
      ? { handled: true, ok: true, code: 0, intent: "retry", action: "retry", record, value }
      : { handled: true, ok: false, code: 2, intent: "retry", record, message: "The last local record lacks a run pointer or task text to retry." };
  }
  if (query.intent === "resume") {
    const available = Boolean(record.resume_pointer?.available || record.checkpoint_id);
    return available && record.task
      ? { handled: true, ok: true, code: 0, intent: "resume", action: "resume", record, value: record.checkpoint_id || record.run_id }
      : { handled: true, ok: false, code: 2, intent: "resume", record, message: "The last local record has no checkpoint or workspace pointer to resume." };
  }

  const usable = record.artifacts.filter((item) => item.exists && !item.changed);
  const verified = record.artifacts.filter((item) => item.verified);
  const changed = record.artifacts.filter((item) => item.changed);
  const missing = record.artifacts.filter((item) => !item.exists);

  if (["where", "open"].includes(query.intent)) {
    if (!usable.length) {
      return {
        handled: true,
        ok: false,
        code: 1,
        intent: query.intent,
        record,
        message: changed.length
          ? "The recorded file exists but its SHA-256 has changed since delivery."
          : "The recorded local file is missing or unreadable.",
      };
    }
    return {
      handled: true,
      ok: true,
      code: 0,
      intent: query.intent,
      record,
      paths: usable.map((item) => item.path),
      verified: verified.length === usable.length,
    };
  }
  if (query.intent === "created") return { handled: true, ok: true, code: 0, intent: query.intent, record, artifacts: record.artifacts };
  if (query.intent === "delivery") {
    const delivered = Boolean(
      record.states?.delivered
      && record.states?.verified
      && record.artifacts.length
      && verified.length === record.artifacts.length
      && !changed.length
      && !missing.length,
    );
    return {
      handled: true,
      ok: delivered,
      code: delivered ? 0 : 1,
      intent: query.intent,
      record,
      message: delivered
        ? `Yes. ${verified.length} verified local artifact${verified.length === 1 ? "" : "s"} remain intact.`
        : changed.length
          ? "No longer verified. At least one delivered file has changed."
          : missing.length
            ? "No longer available. At least one delivered local file is missing or unreadable."
            : record.source_schema === LEGACY_SCHEMA
              ? "A legacy delivery path exists, but the old record has no SHA-256 proof and cannot be called verified."
              : "No. The recorded delivery is incomplete or unverified.",
    };
  }
  if (query.intent === "receipt") {
    const valid = SHA_RE.test(clean(record.receipt_sha, 128));
    return {
      handled: true,
      ok: valid,
      code: valid ? 0 : 1,
      intent: query.intent,
      record,
      value: valid ? record.receipt_sha : "",
      message: valid ? "" : record.receipt_sha ? "The local record contains a malformed receipt SHA." : "The local record has no receipt SHA.",
    };
  }
  if (query.intent === "run") {
    const value = record.run_id || record.session_id || record.task_id || record.sandbox_id;
    return { handled: true, ok: Boolean(value), code: value ? 0 : 1, intent: query.intent, record, value, message: value ? "" : "The local record has no run identifier." };
  }
  if (query.intent === "task") {
    return { handled: true, ok: Boolean(record.task), code: record.task ? 0 : 1, intent: query.intent, record, value: record.task, message: record.task ? "" : "The local record has no task text." };
  }
  return null;
}
