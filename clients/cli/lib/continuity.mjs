// Copyright (c) 2026 Qira LLC. All rights reserved.
/** Deterministic cross-command continuity and local artifact integrity. */
import { createHash, randomUUID } from "node:crypto";
import { createReadStream } from "node:fs";
import {
  mkdir,
  open,
  readFile,
  rename,
  stat,
  unlink,
  writeFile,
  lstat,
} from "node:fs/promises";
import { dirname, extname, join, resolve } from "node:path";
import { homedir } from "node:os";

export const CONTINUITY_SCHEMA = "lolm.continuity.ledger.v2";
const MAX_RECORDS = 200;
const MAX_ARTIFACTS_PER_RECORD = 100;
const LOCK_RETRIES = 300;
const LOCK_STALE_MS = 30_000;

export function continuityLedgerPath() {
  return resolve(
    process.env.LOLM_CONTINUITY_LEDGER ||
    process.env.LOLM_DELIVERY_LEDGER ||
    join(homedir(), ".lolm", "continuity.json"),
  );
}

function cleanText(value, limit = 1000) {
  return String(value || "").replace(/\u0000/g, "").slice(0, limit);
}

function normalizedKind(value) {
  const kind = cleanText(value, 40).toLowerCase();
  if (["doc", "document", "word", "report", "letter"].includes(kind)) return "document";
  if (["jpg", "jpeg", "png", "svg", "webp", "picture"].includes(kind)) return "image";
  if (["xls", "excel", "spreadsheet", "csv"].includes(kind)) return "xlsx";
  if (["ppt", "powerpoint", "slides", "presentation"].includes(kind)) return "pptx";
  if (["zip", "tar", "archive"].includes(kind)) return "archive";
  return kind || "artifact";
}

function inferKindFromPath(path) {
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
  return new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
}

async function atomicWriteJson(path, value) {
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, JSON.stringify(value, null, 2) + "\n", { mode: 0o600 });
    await rename(temporary, path);
  } finally {
    try { await unlink(temporary); } catch { /* renamed or already absent */ }
  }
}

async function withLedgerLock(fn) {
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
      await sleep(Math.min(100, 5 + attempt));
    }
  }
  if (!handle) throw new Error(`continuity ledger lock timeout: ${lockPath}`);
  try {
    return await fn(path);
  } finally {
    try { await handle.close(); } catch { /* already closed */ }
    try { await unlink(lockPath); } catch { /* already removed */ }
  }
}

async function readRawLedger(path = continuityLedgerPath()) {
  let text;
  try {
    text = await readFile(path, "utf8");
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    const wrapped = new Error(`continuity ledger contains invalid JSON: ${path}`);
    wrapped.code = "LOLM_CONTINUITY_INVALID_JSON";
    wrapped.cause = error;
    throw wrapped;
  }
}

async function hashFile(path) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(path)) hash.update(chunk);
  return hash.digest("hex");
}

async function fileEvidence(path) {
  const absolute = resolve(String(path));
  try {
    const linkInfo = await lstat(absolute);
    if (linkInfo.isSymbolicLink()) {
      return { path: absolute, exists: false, changed: false, reason: "symlink" };
    }
    if (!linkInfo.isFile()) {
      return { path: absolute, exists: false, changed: false, reason: "not_file" };
    }
    return {
      path: absolute,
      name: absolute.split(/[\\/]/).at(-1) || absolute,
      kind: inferKindFromPath(absolute),
      exists: true,
      changed: false,
      size: linkInfo.size,
      sha256: await hashFile(absolute),
    };
  } catch (error) {
    if (error?.code !== "ENOENT") {
      return { path: absolute, exists: false, changed: false, reason: "unreadable" };
    }
    return { path: absolute, exists: false, changed: false, reason: "missing" };
  }
}

function migrateV1(raw) {
  let deliveries = Array.isArray(raw?.deliveries) ? raw.deliveries : [];
  if (!deliveries.length && raw?.last) deliveries = [raw.last];
  const records = deliveries.slice(-MAX_RECORDS).map((entry) => ({
    id: `migrated-${randomUUID()}`,
    ts: Number(entry?.ts || 0),
    task: cleanText(entry?.task, 1000),
    kind: normalizedKind(entry?.kind),
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
    artifacts: (entry?.files || []).slice(0, MAX_ARTIFACTS_PER_RECORD).map((path) => ({
      path: resolve(String(path)),
      name: String(path).split(/[\\/]/).at(-1) || String(path),
      kind: normalizedKind(entry?.kind),
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
    migrated_from: cleanText(raw?.schema || "lolm.delivery.ledger.v1", 100),
    records,
    last_id: records.at(-1)?.id || "",
  };
}

export function normalizeLedger(raw) {
  if (raw?.schema === CONTINUITY_SCHEMA && Array.isArray(raw.records)) {
    return {
      schema: CONTINUITY_SCHEMA,
      records: raw.records.slice(-MAX_RECORDS),
      last_id: cleanText(raw.last_id, 100),
      migrated_from: cleanText(raw.migrated_from, 100),
    };
  }
  if (raw?.schema === "lolm.delivery.ledger.v1" || Array.isArray(raw?.deliveries) || raw?.last) {
    return migrateV1(raw);
  }
  return { schema: CONTINUITY_SCHEMA, records: [], last_id: "", migrated_from: "" };
}

export async function loadContinuityLedger({ persistMigration = true } = {}) {
  const path = continuityLedgerPath();
  const raw = await readRawLedger(path);
  const ledger = normalizeLedger(raw);
  if (persistMigration && raw && raw.schema !== CONTINUITY_SCHEMA) {
    return await withLedgerLock(async (lockedPath) => {
      const currentRaw = await readRawLedger(lockedPath);
      const current = normalizeLedger(currentRaw);
      if (currentRaw && currentRaw.schema !== CONTINUITY_SCHEMA) {
        await atomicWriteJson(lockedPath, current);
      }
      return current;
    });
  }
  return ledger;
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
  const requestedKind = normalizedKind(entry.kind);
  const artifacts = [];
  for (const candidate of (entry.files || []).slice(0, MAX_ARTIFACTS_PER_RECORD)) {
    const evidence = await fileEvidence(candidate);
    artifacts.push({
      ...evidence,
      kind: requestedKind === "artifact" ? evidence.kind : requestedKind,
      integrity: evidence.exists ? "verified_at_delivery" : `unavailable_at_delivery:${evidence.reason || "unknown"}`,
    });
  }
  const allExist = artifacts.length > 0 && artifacts.every((item) => item.exists);
  const states = {
    generated: entry.generated !== false,
    verified: entry.verified === true && allExist,
    exported: entry.exported !== false && allExist,
    delivered: entry.delivered !== false && allExist,
    opened: Boolean(entry.opened),
  };
  const record = {
    id: cleanText(entry.id, 100) || `continuity-${randomUUID()}`,
    ts: Number(entry.ts || Date.now() / 1000),
    task: cleanText(entry.task, 1000),
    kind: requestedKind,
    destination: entry.destination ? resolve(String(entry.destination)) : "",
    session_id: cleanText(entry.session_id, 160),
    run_id: cleanText(entry.run_id, 160),
    task_id: cleanText(entry.task_id, 160),
    sandbox_id: cleanText(entry.sandbox_id, 160),
    receipt_sha: cleanText(entry.receipt_sha, 128),
    manifest_sha: cleanText(entry.manifest_sha, 128),
    verdict: cleanText(entry.verdict, 40) || (states.delivered ? "delivered" : "incomplete"),
    states,
    artifacts,
    source_schema: CONTINUITY_SCHEMA,
  };
  return await withLedgerLock(async (path) => {
    const ledger = normalizeLedger(await readRawLedger(path));
    const records = [...ledger.records.slice(-(MAX_RECORDS - 1)), record];
    const next = { ...ledger, schema: CONTINUITY_SCHEMA, records, last_id: record.id };
    await atomicWriteJson(path, next);
    return record;
  });
}

async function refreshRecord(record) {
  const artifacts = [];
  for (const artifact of (record?.artifacts || []).slice(0, MAX_ARTIFACTS_PER_RECORD)) {
    const current = await fileEvidence(artifact.path);
    const expected = cleanText(artifact.sha256, 128);
    const changed = Boolean(current.exists && expected && current.sha256 !== expected);
    const verified = Boolean(current.exists && expected && !changed && record?.states?.verified);
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
  const wanted = normalizedKind(kind);
  if (!kind || wanted === "artifact") return true;
  if (normalizedKind(record.kind) === wanted) return true;
  return (record.artifacts || []).some((item) => normalizedKind(item.kind) === wanted);
}

export async function listContinuityRecords({ kind = "", limit = 20 } = {}) {
  const ledger = await loadContinuityLedger();
  const selected = ledger.records
    .filter((record) => kindMatches(record, kind))
    .slice(-Math.max(1, Math.min(MAX_RECORDS, Number(limit) || 20)))
    .reverse();
  const out = [];
  for (const record of selected) out.push(await refreshRecord(record));
  return out;
}

export async function findContinuityRecord({ kind = "", index = 1 } = {}) {
  const records = await listContinuityRecords({ kind, limit: MAX_RECORDS });
  const position = Math.max(1, Number(index || 1)) - 1;
  return records[position] || null;
}

export async function markRecordOpened(id) {
  return await withLedgerLock(async (path) => {
    const ledger = normalizeLedger(await readRawLedger(path));
    let changed = false;
    const records = ledger.records.map((record) => {
      if (record.id !== id) return record;
      changed = true;
      return {
        ...record,
        states: { ...record.states, opened: true },
        opened_ts: Date.now() / 1000,
      };
    });
    if (changed) await atomicWriteJson(path, { ...ledger, records });
    return changed;
  });
}

function referentKind(text) {
  const t = String(text || "").toLowerCase();
  if (/\bpdf\b/.test(t)) return "pdf";
  if (/\b(docx|word|document|report|letter)\b/.test(t)) return "document";
  if (/\b(xlsx|excel|spreadsheet|csv)\b/.test(t)) return "xlsx";
  if (/\b(pptx|powerpoint|slides?|presentation)\b/.test(t)) return "pptx";
  if (/\b(image|png|jpe?g|svg|webp|picture)\b/.test(t)) return "image";
  if (/\b(html|webpage|website|web page)\b/.test(t)) return "html";
  if (/\b(zip|archive|tar)\b/.test(t)) return "archive";
  return "";
}

export function classifyContinuityQuestion(text) {
  const t = String(text || "").trim().toLowerCase();
  if (!t) return null;
  const kind = referentKind(t);
  const explicitReferent = Boolean(kind || /\b(file|artifact)\b/.test(t));
  const pronounOnly = !explicitReferent && /\b(it|that|this)\b/.test(t);

  if (/\b(where|location|path|saved|save|put|find|folder|directory)\b/.test(t) && (explicitReferent || pronounOnly)) {
    return { intent: "where", kind, ambiguous: pronounOnly };
  }
  if (/\b(open|show me|launch)\b/.test(t) && (explicitReferent || pronounOnly)) {
    return { intent: "open", kind, ambiguous: pronounOnly };
  }
  if (/\b(what did you (create|make|generate)|what was (created|made|generated)|which files? did you (create|make|generate)|what files? were (created|made|generated)|what files? (was|were) (created|made|generated))\b/.test(t)) {
    return { intent: "created", kind, ambiguous: false };
  }

  const genericDelivery = /\bdid you actually (deliver|save|export)\b/.test(t);
  const referentDelivery = (explicitReferent || pronounOnly) &&
    /\b(deliver|delivered|save|saved|export|exported)\b/.test(t) &&
    /\b(did|was|were|actually|get|got)\b/.test(t);
  if (genericDelivery || referentDelivery) {
    return { intent: "delivery", kind, ambiguous: pronounOnly };
  }

  if (
    /\b(last|previous|prior)\s+(task|run|receipt)\b/.test(t) ||
    /\bwhat (was|is) (the )?(last|previous) (task|run|receipt)\b/.test(t) ||
    /\bshow (me )?(the )?(last|previous) (task|run|receipt)\b/.test(t)
  ) {
    const subject = t.includes("receipt") ? "receipt" : t.includes("run") ? "run" : "task";
    return { intent: subject, kind, ambiguous: false };
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
      const reason = changed.length
        ? "The recorded file exists but its SHA-256 has changed since delivery."
        : "The recorded local file is missing or unreadable.";
      return { handled: true, ok: false, code: 1, intent: query.intent, record, message: reason };
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
    return {
      handled: true,
      ok: true,
      code: 0,
      intent: query.intent,
      record,
      artifacts: record.artifacts,
    };
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
      ok: Boolean(record.receipt_sha),
      code: record.receipt_sha ? 0 : 1,
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
