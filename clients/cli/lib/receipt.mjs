// Copyright (c) 2026 Qira LLC. All rights reserved.
/** Independent receipt and artifact verification. */
import {
  createHash, createHmac, createPublicKey, verify as verifySignature,
} from "node:crypto";

export const SEALED_CORE_KEYS = [
  "kind", "task", "summary", "ts", "steps", "ran", "produced_output", "stuck",
  "budget_hit", "error", "files", "green_runs", "failed_runs", "verifies",
  "expected", "expected_ok", "missing_expected", "last_stdout_tail", "trail",
  "syntax_ok", "syntax_error", "syntax_checked", "ok", "visual_missing_html",
  "nfet", "task_state",
];

const POST_SEAL_KEYS = new Set([
  "receipt_sha", "signature", "signing_key",
  "ledger_sha", "prev_ledger_sha", "ledger_ts", "source", "demo", "selftest",
]);
const ED25519_SPKI_PREFIX = Buffer.from("302a300506032b6570032100", "hex");

export function pyStyleDumps(value) {
  return _dump(value);
}

function _dump(value) {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "null";
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(_dump).join(",")}]`;
  if (typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${_dump(value[key])}`).join(",")}}`;
  }
  return "null";
}

export function sha256Short(value, length = 24) {
  return createHash("sha256").update(String(value), "utf8").digest("hex").slice(0, length);
}

export function extractSealedCore(receipt) {
  const core = {};
  for (const key of SEALED_CORE_KEYS) {
    if (Object.prototype.hasOwnProperty.call(receipt || {}, key)) core[key] = receipt[key];
  }
  return core;
}

export function extractSignedCore(receipt) {
  return Object.fromEntries(Object.entries(receipt || {}).filter(([key]) => !POST_SEAL_KEYS.has(key)));
}

function parseHmacKeys(raw) {
  const keys = {};
  for (const part of String(raw || "").split(",")) {
    const index = part.indexOf(":");
    if (index < 1) continue;
    const kid = part.slice(0, index).trim();
    const secret = part.slice(index + 1).trim();
    if (!kid || !secret) continue;
    keys[kid] = /^[0-9a-fA-F]{32,}$/.test(secret) ? Buffer.from(secret, "hex") : Buffer.from(secret);
  }
  return keys;
}

export function verifyHmacSignature(blobUtf8, signature, keysEnv) {
  if (!signature?.sig) return { signature_valid: false, reason: "missing_signature" };
  const keys = parseHmacKeys(keysEnv ?? process.env.LOLM_RECEIPT_KEYS ?? "");
  if (!Object.keys(keys).length) return { signature_valid: null, reason: "no_keys_configured" };
  const kid = signature.key_id || signature.kid || "";
  const candidates = kid && keys[kid] ? [[kid, keys[kid]]] : Object.entries(keys);
  for (const [candidate, secret] of candidates) {
    const expected = createHmac("sha256", secret).update(blobUtf8).digest("hex");
    if (expected === signature.sig) return { signature_valid: true, kid: candidate, reason: "ok" };
  }
  return { signature_valid: false, kid: kid || null, reason: "bad_signature" };
}

function envPublicKeys() {
  const out = {};
  for (const part of String(process.env.LOLM_RECEIPT_PUBLIC_KEYS || "").split(",")) {
    const index = part.indexOf(":");
    if (index > 0) out[part.slice(0, index).trim()] = part.slice(index + 1).trim();
  }
  return out;
}

function asPublicKey(value) {
  if (!value) return null;
  if (typeof value !== "string" || value.includes("BEGIN PUBLIC KEY")) return createPublicKey(value);
  const raw = Buffer.from(value, "base64url");
  if (raw.length !== 32) throw new Error("Ed25519 public key must be 32 bytes");
  return createPublicKey({ key: Buffer.concat([ED25519_SPKI_PREFIX, raw]), format: "der", type: "spki" });
}

function verifyEd25519(blob, signature, publicKeys) {
  if (!signature || signature.alg !== "Ed25519" || !signature.sig) {
    return { signature_valid: false, reason: "missing_or_unsupported_signature" };
  }
  const keyId = signature.key_id || signature.kid || "";
  const available = { ...envPublicKeys(), ...(publicKeys || {}) };
  if (!keyId || !available[keyId]) {
    return { signature_valid: null, reason: "unknown_key", key_id: keyId || null };
  }
  try {
    const valid = verifySignature(
      null,
      Buffer.from(blob, "utf8"),
      asPublicKey(available[keyId]),
      Buffer.from(signature.sig, "base64url"),
    );
    return { signature_valid: valid, reason: valid ? "ok" : "bad_signature", key_id: keyId };
  } catch (error) {
    return { signature_valid: false, reason: `invalid_public_key:${error.message}`, key_id: keyId };
  }
}

export function verifyCodeReceipt(receipt, { publicKeys = {} } = {}) {
  const r = receipt && typeof receipt === "object" ? receipt : {};
  const notes = [];
  const isV2 = r.schema === "lolm.code.receipt.v2" || r.schema === "lolm.visual.receipt.v2";
  const core = isV2 ? extractSignedCore(r) : extractSealedCore(r);
  const blob = pyStyleDumps(core);
  const expectedLength = isV2 ? 64 : 24;
  const expected = sha256Short(blob, expectedLength);
  const claimed = typeof r.receipt_sha === "string" ? r.receipt_sha : null;
  const receipt_hash_match = !!claimed && claimed === expected;
  if (!receipt_hash_match) notes.push(`receipt_sha mismatch: claimed=${claimed || "missing"} recomputed=${expected}`);

  let signature = { signature_valid: false, reason: "unsigned_legacy_receipt" };
  if (isV2) signature = verifyEd25519(blob, r.signature, publicKeys);
  else if (r.signature) signature = verifyHmacSignature(blob, r.signature);
  if (signature.signature_valid !== true) notes.push(`signature: ${signature.reason}`);

  const codeSchema = r.schema === "lolm.code.receipt.v2";
  const visualSchema = r.schema === "lolm.visual.receipt.v2";
  const schema_valid = codeSchema || visualSchema;
  const verification = r.verification || {};
  const codeChecks = codeSchema
    && r.verdict === "shipped"
    && r.ok === true
    && r.syntax_ok === true
    && verification.syntax_ok === true
    && verification.execution_ok === true
    && verification.contract_ok === true
    && verification.artifact_manifest_ok === true
    && /^[0-9a-f]{64}$/.test(String(verification.artifact_manifest_sha256 || ""));
  const visualChecks = visualSchema
    && r.verdict === "verified"
    && r.ok === true
    && verification.browser_ok === true
    && /^[0-9a-f]{64}$/.test(String(verification.html_sha256 || ""));
  const runBound = typeof r.run_id === "string" && r.run_id.length > 0;
  const nowSeconds = Math.floor(Date.now() / 1000);
  const timestamp_valid = Number.isSafeInteger(r.signed_at)
    && r.signed_at > 0
    && r.signed_at <= nowSeconds + 300;
  const verdict_consistent = !!(codeChecks || visualChecks);
  if (!schema_valid) notes.push("unsupported receipt schema");
  if (!runBound) notes.push("missing run_id");
  if (!timestamp_valid) notes.push("missing, malformed, or future signed_at");
  if (!verdict_consistent) notes.push("receipt verdict or verification fields are incomplete/contradictory");
  const verified = schema_valid && runBound && timestamp_valid && receipt_hash_match
    && signature.signature_valid === true && verdict_consistent;

  return {
    schema_valid,
    receipt_hash_match,
    expected_sha: expected,
    claimed_sha: claimed,
    signature_valid: signature.signature_valid,
    signing_key: signature.key_id || signature.kid || r.signature?.key_id || null,
    signature_reason: signature.reason,
    timestamp_valid,
    ledger_link_present: !!(r.ledger_sha || r.prev_ledger_sha),
    ledger_sha: r.ledger_sha || null,
    prev_ledger_sha: r.prev_ledger_sha || null,
    verdict_consistent,
    shipped_allowed: !!codeChecks,
    notes,
    verified_at: new Date().toISOString(),
    integrity: { verified, method: "sha256+Ed25519-v2" },
  };
}

export function verifyArtifacts(files, manifestFiles) {
  const map = files instanceof Map ? files : new Map(Object.entries(files || {}));
  const results = [];
  let all_ok = true;
  for (const file of manifestFiles || []) {
    const content = map.get(file.path);
    if (content == null) {
      results.push({ path: file.path, ok: false, reason: "missing_file" });
      all_ok = false;
      continue;
    }
    const bytes = Buffer.isBuffer(content) ? content : Buffer.from(String(content), "utf8");
    const sha256 = createHash("sha256").update(bytes).digest("hex");
    const match = /^[0-9a-f]{64}$/.test(String(file.sha256 || "")) && sha256 === file.sha256;
    if (!match || bytes.length !== file.size) all_ok = false;
    results.push({ path: file.path, ok: match && bytes.length === file.size, bytes: bytes.length,
      sha256, expected: file.sha256, reason: match ? "ok" : "hash_mismatch" });
  }
  return { ok: all_ok, files: results };
}
