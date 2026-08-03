// Copyright (c) 2026 Qira LLC. All rights reserved.
/** Deterministic cross-command continuity and local artifact integrity. */
import { createHash, randomUUID } from "node:crypto";
import { createReadStream } from "node:fs";
import {
  lstat,
  mkdir,
  open,
  readFile,
  rename,
  stat,
  unlink,
  writeFile,
} from "node:fs/promises";
import { dirname, extname, join, resolve } from "node:path";
import { homedir } from "node:os";

export const CONTINUITY_SCHEMA = "lolm.continuity.ledger.v2";
const MAX_RECORDS = 200;
const MAX_ARTIFACTS = 100;
const LOCK_RETRIES = 300;
const LOCK_STALE_MS = 30_000;
const RECEIPT_RE = /^[a-f0-9]{64}$/i;

export function continuityLedgerPath() {
  return resolve(
    process.env.LOLM_CONTINUITY_LEDGER ||
    process.env.LOLM_DELIVERY_LEDGER ||
    join(homedir(), ".lolm", "continuity.json"),
  );
}

function clean(value, limit = 1000) {
  return String(value || "").replace(/\u0000/g, "").slice(0, limit);
}

function kindOf(value) {
  const valueKind = clean(value, 40).toLowerCase();
  if (["doc", "document", "word", "report", "letter"].includes(valueKind)) return "document";
  if (["jpg", "jpeg", "png", "svg", "webp", "picture"].includes(valueKind)) return "image";
  if (["xls", "excel", "spreadsheet", "csv"].includes(valueKind)) return "xlsx";
  if (["ppt", "powerpoint", "slides", "presentation"].includes(valueKind)) return "pptx";
  if (["zip", "tar", "archive"].includes(valueKind)) return "archive";
  return valueKind || "artifact";
}

function pathKind(path) {
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
        const info = await stat(lockPath);
        if (Date.now() - info.mtimeMs > LOCK_STALE_MS) {
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

async function fileHash(path) {
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
      kind: pathKind(absolute),
      exists: true,
      changed: false,
      size: info.size,
      sha256: await fileHash(absolute),
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

function migrateV1(raw) {
  let deliveries = Array.isArray(raw?.deliveries) ? raw.deliveries : [];
  if (!deliveries.length && raw?.last) deliveries = [raw.last];
  const records = deliveries.slice(-MAX_RECORDS).map((entry) => ({
    id: `migrated-${randomUUID()}`,
    ts: Number(entry?.ts || 0),
    task: clean(entry?.task),
    kind: kindOf(entry?.kind),
    destination: entry?.destination ? resolve(String(entry.destination)) : "",
    session_id: "",
    run_id: "",
    task_id: "",
    sandbox_id: "",
    receipt_sha: "",
    manifest_sha: "",
    verdict: "legacy_delivery",
    states: {
      generated: true,
      verified: false,
      exported: true,
      delivered: true,
      opened: false,
    },
    artifacts: (entry?.files || []).slice(0, MAX_ARTIFACTS).map((path) => ({
      path: resolve(String(path)),
      name: String(path).split(/[\\/]/).at(-1) || String(path),
      kind: kindOf(entry?.kind),
      exists: true,
      changed: false,
      size: null,
      sha256: "",
      integrity: "legacy_unhashed",
    })),
    source_schema: "lolm.delivery.ledger.v1",
  }));
  return {
    schema: CONTINUITY_SCHEMA,
    migrated_from: clean(raw?.schema || "lolm.delivery.ledger.v1", 100),
    records,
    last_id: records.at(-1)?.id || "",
  };
}

export function normalizeLedger(raw) {
  if (raw?.schema === CONTINUITY_SCHEMA && Array.isArray(raw.records)) {
    return {
      schema: CONTINUITY_SCHEMA,
      records: raw.records.slice(-MAX_RECORDS),
      last_id: clean(raw.last_id, 100),
      migrated_from: clean(raw.migrated_from, 100),
    };
  }
  if (raw?.schema === "lolm.delivery.ledger.v1" || Array.isArray(raw?.deliveries) || raw?.last) {
    return migrateV1(raw);
  }
  return { schema: CONTINUITY_SCHEMA, records: [], last_id: "", migrated_from: "" };
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
    verdict: pick(/\bverdict\s+(shipped|stuck|broken|refused|incomplete)\b/i).toLowerCase(),
  };
}

export async function recordContinuity(entry) {
  const requestedKind = kindOf(entry.kind);
  const receiptSha = clean(entry.receipt_sha, 128);
  const inspected = [];
  for (const candidate of (entry.files || []).slice(0, MAX_ARTIFACTS)) {
    const evidence = await inspectFile(candidate);
    inspected.push({
      ...evidence,
      kind: requestedKind === "artifact" ? evidence.kind : requestedKind,
    });
  }
  const allExist = inspected.length > 0 && inspected.every((item) => item.exists);
  const verified = entry.verified === true && allExist && RECEIPT_RE.test(receiptSha);
  const artifacts = inspected.map((item) => ({
    ...item,
    integrity: !item.exists
      ? `unavailable_at_delivery:${item.reason || "unknown"}`
      : verified
        ? "verified_at_delivery"
        : "present_unverified_at_delivery",
  }));
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
    task: clean(entry.task),
    kind: requestedKind,
    destination: entry.destination ? resolve(String(entry.destination)) : "",
    session_id: clean(entry.session_id, 160),
    run_id: clean(entry.run_id, 160),
    task_id: clean(entry.task_id, 160),
    sandbox_id: clean(entry.sandbox_id, 160),
    receipt_sha: receiptSha,
    manifest_sha: clean(entry.manifest_sha, 128),
    verdict: clean(entry.verdict, 40) || (states.delivered ? "delivered" : "incomplete"),
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
  const receiptBound = RECEIPT_RE.test(clean(record?.receipt_sha, 128));
  for (const artifact of (record?.artifacts || []).slice(0, MAX_ARTIFACTS)) {
    const current = await inspectFile(artifact.path);
    const expected = clean(artifact.sha256, 128);
    const changed = Boolean(current.exists && expected && current.sha256 !== expected);
    const verified = Boolean(
      current.exists &&
      expected &&
      !changed &&
      record?.states?.verified &&
      receiptBound,
    );
    artifacts.push({
      ...artifact,
      ...current,
      changed,
      verified,
      integrity: !current.exists
        ? current.reason || "missing"
        : changed
          ? "changed"
          : verified
            ? "verified"
            : expected
              ? "hash_matches_unverified_record"
              : "legacy_unhashed",
    });
  }
  return {
    ...record,
    artifacts,
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
  const wanted = kindOf(kind);
  if (!kind || wanted === "artifact") return true;
  if (kindOf(record.kind) === wanted) return true;
  return (record.artifacts || []).some((item) => kindOf(item.kind) === wanted);
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
      return {
        ...record,
        states: { ...record.states, opened: true },
        opened_ts: Date.now() / 1000,
      };
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
  const genericDelivery = /\bdid you actually (deliver|save|export)\b/.test(value);

  if ((genericDelivery || ((explicit || pronounOnly) && deliveryVerb && deliveryShape)) && !locationCue) {
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
    /\b(last|previous|prior)\s+(task|run|receipt)\b/.test(value) ||
    /\bwhat (was|is) (the )?(last|previous) (task|run|receipt)\b/.test(value) ||
    /\bshow (me )?(the )?(last|previous) (task|run|receipt)\b/.test(value)
  ) {
    const intent = value.includes("receipt") ? "receipt" : value.includes("run") ? "run" : "task";
    return { intent, kind, ambiguous: false };
  }
  return null;
}

export async function resolveContinuityQuestion(text) {
  const query = classifyContinuityQuestion(text);
  if (!query) return null;
  if (query.ambiguous) {
    const recent = await listContinuityRecords({ limit: 3 });
    if (recent.length > 1) {
      return {
        handled: true,
        ok: false,
        code: 2,
        intent: "clarify",
        message: "More than one recent artifact could match. Name the type, such as PDF, document, image, spreadsheet, slides, HTML, or archive.",
      };
    }
  }

  const record = await findContinuityRecord({ kind: query.kind, index: 1 });
  if (!record) {
    return {
      handled: true,
      ok: false,
      code: 1,
      intent: query.intent,
      message: "No matching local continuity record was found.",
    };
  }

  const usable = record.artifacts.filter((item) => item.exists && !item.changed);
  const verified = record.artifacts.filter((item) => item.verified);
  const changed = record.artifacts.filter((item) => item.changed);
  const missing = record.artifacts.filter((item) => !item.exists);

  if (query.intent === "where" || query.intent === "open") {
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

  if (query.intent === "created") {
    return { handled: true, ok: true, code: 0, intent: query.intent, record, artifacts: record.artifacts };
  }

  if (query.intent === "delivery") {
    const delivered = Boolean(
      record.states?.delivered &&
      record.states?.verified &&
      record.artifacts.length > 0 &&
      verified.length === record.artifacts.length &&
      !changed.length &&
      !missing.length,
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
            : record.source_schema === "lolm.delivery.ledger.v1"
              ? "A legacy delivery path exists, but the old record has no SHA-256 proof and cannot be called verified."
              : "No. The recorded delivery is incomplete or unverified.",
    };
  }

  if (query.intent === "receipt") {
    return {
      handled: true,
      ok: RECEIPT_RE.test(clean(record.receipt_sha, 128)),
      code: RECEIPT_RE.test(clean(record.receipt_sha, 128)) ? 0 : 1,
      intent: query.intent,
      record,
      value: record.receipt_sha,
      message: record.receipt_sha ? "" : "The local record has no receipt SHA.",
    };
  }

  if (query.intent === "run") {
    const value = record.run_id || record.task_id || record.sandbox_id;
    return {
      handled: true,
      ok: Boolean(value),
      code: value ? 0 : 1,
      intent: query.intent,
      record,
      value,
      message: value ? "" : "The local record has no run identifier.",
    };
  }

  if (query.intent === "task") {
    return {
      handled: true,
      ok: Boolean(record.task),
      code: record.task ? 0 : 1,
      intent: query.intent,
      record,
      value: record.task,
      message: record.task ? "" : "The local record has no task text.",
    };
  }
  return null;
}
