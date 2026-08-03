// Copyright (c) 2026 Qira LLC. All rights reserved.
/** Deterministic cross-command continuity and local artifact integrity. */
import { createHash, randomUUID } from "node:crypto";
import { access, mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname, extname, join, resolve } from "node:path";
import { homedir } from "node:os";

export const CONTINUITY_SCHEMA = "lolm.continuity.ledger.v2";
const MAX_RECORDS = 200;

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
  if (["doc", "document", "word"].includes(kind)) return "document";
  if (["jpg", "jpeg", "png", "svg", "webp"].includes(kind)) return "image";
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

async function fileEvidence(path) {
  const absolute = resolve(String(path));
  try {
    await access(absolute);
    const info = await stat(absolute);
    if (!info.isFile()) return { path: absolute, exists: false, reason: "not_file" };
    const body = await readFile(absolute);
    return {
      path: absolute,
      name: absolute.split(/[\\/]/).at(-1) || absolute,
      kind: inferKindFromPath(absolute),
      exists: true,
      changed: false,
      size: body.length,
      sha256: createHash("sha256").update(body).digest("hex"),
    };
  } catch {
    return { path: absolute, exists: false, changed: false, reason: "missing" };
  }
}

function migrateV1(raw) {
  const deliveries = Array.isArray(raw?.deliveries) ? raw.deliveries : [];
  const records = deliveries.map((entry) => ({
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
    verdict: "delivered",
    states: {
      generated: true,
      verified: true,
      exported: true,
      delivered: true,
      opened: false,
    },
    artifacts: (entry?.files || []).map((path) => ({
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
    migrated_from: raw?.schema || "lolm.delivery.ledger.v1",
    records: records.slice(-MAX_RECORDS),
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
  if (raw?.schema === "lolm.delivery.ledger.v1" || Array.isArray(raw?.deliveries)) {
    return migrateV1(raw);
  }
  return { schema: CONTINUITY_SCHEMA, records: [], last_id: "", migrated_from: "" };
}

export async function loadContinuityLedger({ persistMigration = true } = {}) {
  const path = continuityLedgerPath();
  let raw = null;
  try { raw = JSON.parse(await readFile(path, "utf8")); } catch { /* new ledger */ }
  const ledger = normalizeLedger(raw);
  if (persistMigration && raw && raw.schema !== CONTINUITY_SCHEMA) {
    await mkdir(dirname(path), { recursive: true, mode: 0o700 });
    await writeFile(path, JSON.stringify(ledger, null, 2) + "\n", { mode: 0o600 });
  }
  return ledger;
}

export function parseRunEvidence(transcript) {
  const text = String(transcript || "");
  const pick = (pattern) => text.match(pattern)?.[1] || "";
  return {
    receipt_sha: pick(/\breceipt\s+([a-f0-9]{64})\b/i),
    task_id: pick(/\btask\s+(task_[a-z0-9]+)\b/i),
    sandbox_id: pick(/\bsandbox\s+(sbx_[a-z0-9]+)\b/i),
    verdict: pick(/\bverdict\s+(shipped|stuck|broken|refused|incomplete)\b/i).toLowerCase(),
  };
}

export async function recordContinuity(entry) {
  const path = continuityLedgerPath();
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const ledger = await loadContinuityLedger({ persistMigration: false });
  const requestedKind = normalizedKind(entry.kind);
  const artifacts = [];
  for (const candidate of entry.files || []) {
    const evidence = await fileEvidence(candidate);
    artifacts.push({
      ...evidence,
      kind: requestedKind === "artifact" ? evidence.kind : requestedKind,
      integrity: evidence.exists ? "verified_at_delivery" : "missing_at_delivery",
    });
  }
  const states = {
    generated: entry.generated !== false,
    verified: entry.verified !== false && artifacts.some((item) => item.exists),
    exported: entry.exported !== false && artifacts.some((item) => item.exists),
    delivered: entry.delivered !== false && artifacts.some((item) => item.exists),
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
  const records = [...ledger.records.slice(-(MAX_RECORDS - 1)), record];
  const next = { ...ledger, schema: CONTINUITY_SCHEMA, records, last_id: record.id };
  await writeFile(path, JSON.stringify(next, null, 2) + "\n", { mode: 0o600 });
  return record;
}

async function refreshRecord(record) {
  const artifacts = [];
  for (const artifact of record?.artifacts || []) {
    const current = await fileEvidence(artifact.path);
    const expected = cleanText(artifact.sha256, 128);
    const changed = Boolean(current.exists && expected && current.sha256 !== expected);
    artifacts.push({
      ...artifact,
      ...current,
      changed,
      integrity: !current.exists ? "missing" : changed ? "changed" : expected ? "verified" : "legacy_unhashed",
    });
  }
  return {
    ...record,
    artifacts,
    files: artifacts.filter((item) => item.exists && !item.changed).map((item) => item.path),
    existing_files: artifacts.filter((item) => item.exists).map((item) => item.path),
    exists: artifacts.some((item) => item.exists),
    intact: artifacts.some((item) => item.exists && !item.changed),
    missing: artifacts.filter((item) => !item.exists).map((item) => item.path),
    changed: artifacts.filter((item) => item.changed).map((item) => item.path),
  };
}

function kindMatches(record, kind) {
  const wanted = normalizedKind(kind);
  if (!kind || wanted === "artifact") return true;
  if (record.kind === wanted) return true;
  return (record.artifacts || []).some((item) => normalizedKind(item.kind) === wanted);
}

export async function listContinuityRecords({ kind = "", limit = 20 } = {}) {
  const ledger = await loadContinuityLedger();
  const selected = ledger.records.filter((record) => kindMatches(record, kind)).slice(-Math.max(1, limit)).reverse();
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
  const path = continuityLedgerPath();
  const ledger = await loadContinuityLedger({ persistMigration: false });
  let changed = false;
  const records = ledger.records.map((record) => {
    if (record.id !== id) return record;
    changed = true;
    return { ...record, states: { ...record.states, opened: true }, opened_ts: Date.now() / 1000 };
  });
  if (changed) await writeFile(path, JSON.stringify({ ...ledger, records }, null, 2) + "\n", { mode: 0o600 });
}

function referentKind(text) {
  const t = String(text || "").toLowerCase();
  if (/\bpdf\b/.test(t)) return "pdf";
  if (/\b(docx|word|document)\b/.test(t)) return "document";
  if (/\b(xlsx|excel|spreadsheet|csv)\b/.test(t)) return "xlsx";
  if (/\b(pptx|powerpoint|slides?|presentation)\b/.test(t)) return "pptx";
  if (/\b(image|png|jpe?g|svg|webp)\b/.test(t)) return "image";
  if (/\b(html|webpage|website)\b/.test(t)) return "html";
  return "";
}

export function classifyContinuityQuestion(text) {
  const t = String(text || "").trim().toLowerCase();
  if (!t) return null;
  const kind = referentKind(t);
  if (/\b(where|location|path|saved|save|put|find)\b/.test(t) && /\b(it|that|file|artifact|pdf|document|image|spreadsheet|slides?|html)\b/.test(t)) {
    return { intent: "where", kind };
  }
  if (/\b(open|show me)\b/.test(t) && /\b(it|that|file|artifact|pdf|document|image|spreadsheet|slides?|html)\b/.test(t)) {
    return { intent: "open", kind };
  }
  if (/\b(what did you (create|make)|what was created|which files? did you create)\b/.test(t)) {
    return { intent: "created", kind };
  }
  if (/\b(did (it|that|the file) (deliver|save|export)|was (it|that|the file) delivered|did you actually (deliver|save|export))\b/.test(t)) {
    return { intent: "delivery", kind };
  }
  if (/\b(last|previous|prior)\s+(task|run|receipt)\b/.test(t) || /\bwhat (was|is) the last (task|run|receipt)\b/.test(t)) {
    const subject = t.includes("receipt") ? "receipt" : t.includes("run") ? "run" : "task";
    return { intent: subject, kind };
  }
  return null;
}

export async function resolveContinuityQuestion(text) {
  const query = classifyContinuityQuestion(text);
  if (!query) return null;
  const record = await findContinuityRecord({ kind: query.kind, index: 1 });
  if (!record) {
    return { handled: true, ok: false, code: 1, message: "No matching local continuity record was found." };
  }
  const intact = record.artifacts.filter((item) => item.exists && !item.changed);
  const changed = record.artifacts.filter((item) => item.changed);
  const missing = record.artifacts.filter((item) => !item.exists);
  if (query.intent === "where" || query.intent === "open") {
    if (!intact.length) {
      const reason = changed.length ? "The recorded file exists but its hash has changed since delivery." : "The recorded local file is missing.";
      return { handled: true, ok: false, code: 1, intent: query.intent, record, message: reason };
    }
    return { handled: true, ok: true, code: 0, intent: query.intent, record, paths: intact.map((item) => item.path) };
  }
  if (query.intent === "created") {
    return { handled: true, ok: true, code: 0, intent: query.intent, record, artifacts: record.artifacts };
  }
  if (query.intent === "delivery") {
    const delivered = Boolean(record.states?.delivered && intact.length && !changed.length && !missing.length);
    return {
      handled: true,
      ok: delivered,
      code: delivered ? 0 : 1,
      intent: query.intent,
      record,
      message: delivered
        ? `Yes. ${intact.length} verified local artifact${intact.length === 1 ? "" : "s"} remain intact.`
        : changed.length
          ? "No longer verified. At least one delivered file has changed."
          : "No. The recorded delivery is incomplete or the local file is missing.",
    };
  }
  if (query.intent === "receipt") {
    return { handled: true, ok: Boolean(record.receipt_sha), code: record.receipt_sha ? 0 : 1, intent: query.intent, record, value: record.receipt_sha, message: record.receipt_sha ? "" : "The local record has no receipt SHA." };
  }
  if (query.intent === "run") {
    const value = record.run_id || record.task_id || record.sandbox_id;
    return { handled: true, ok: Boolean(value), code: value ? 0 : 1, intent: query.intent, record, value, message: value ? "" : "The local record has no run identifier." };
  }
  if (query.intent === "task") {
    return { handled: true, ok: Boolean(record.task), code: record.task ? 0 : 1, intent: query.intent, record, value: record.task, message: record.task ? "" : "The local record has no task text." };
  }
  return null;
}
