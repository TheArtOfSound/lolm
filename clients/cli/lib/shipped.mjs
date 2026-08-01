// Copyright (c) 2026 Qira LLC. All rights reserved.
/**
 * Strict fail-closed shipping decision.
 *
 * NEVER infer "shipped" from partial fields. A missing receipt field means fail.
 * A receipt that says "broken" is never shipped, even if done.ok is true.
 */

/**
 * @param {object} done - code_done payload
 * @param {object} receipt - code_receipt payload
 * @returns {{ shipped: boolean, reasons: string[] }}
 */
export function evaluateShipped(done, receipt, {
  receiptVerified = false,
  saveRequested = false,
  artifactsVerified = false,
} = {}) {
  const reasons = [];
  const d = done || {};
  const r = receipt || {};

  if (!receipt || typeof receipt !== "object" || !Object.keys(r).length) {
    reasons.push("missing_receipt");
  }
  if (d.ok !== true) reasons.push(`done.ok=${String(d.ok)}`);
  if (typeof d.run_id !== "string" || !d.run_id) reasons.push("done.run_id=missing");
  if (r.schema !== "lolm.code.receipt.v2") reasons.push(`schema=${r.schema ?? "missing"}`);
  if (typeof r.run_id !== "string" || !r.run_id) reasons.push("run_id=missing");
  if (d.run_id && r.run_id && d.run_id !== r.run_id) reasons.push("run_id=contradictory");
  if (r.verdict !== "shipped") {
    reasons.push(`verdict=${r.verdict ?? "missing"}`);
  }
  if (r.ok !== true) {
    reasons.push(`receipt.ok=${String(r.ok)}`);
  }
  if (r.syntax_ok !== true) reasons.push(`syntax_ok=${String(r.syntax_ok)}`);
  if (r.verification?.syntax_ok !== true) reasons.push(`verification.syntax_ok=${String(r.verification?.syntax_ok)}`);
  if (r.verification?.execution_ok !== true) reasons.push(`verification.execution_ok=${String(r.verification?.execution_ok)}`);
  if (r.verification?.contract_ok !== true) reasons.push(`verification.contract_ok=${String(r.verification?.contract_ok)}`);
  if (r.verification?.artifact_manifest_ok !== true) reasons.push(`verification.artifact_manifest_ok=${String(r.verification?.artifact_manifest_ok)}`);
  if (!receiptVerified) reasons.push("receipt_unverified");
  if (saveRequested && !artifactsVerified) reasons.push("artifacts_unverified");
  if (typeof r.failed_runs === "number" && r.failed_runs > 0 && r.green_runs === 0) {
    reasons.push(`failed_runs=${r.failed_runs} green_runs=0`);
  }
  // Prefer explicit green runs when the field exists
  if (r.green_runs != null && Number(r.green_runs) < 1 && r.verdict === "shipped") {
    // allow if ok true and syntax true (some receipts omit green_runs history)
  }
  if (r.expected_ok === false) {
    reasons.push("expected_ok=false");
  }
  if (r.stuck === true) {
    reasons.push("stuck");
  }

  // Fail closed: any reason → not shipped
  // But de-dupe: if only reasons are soft, still fail
  const shipped =
    reasons.length === 0
    && d.ok === true
    && typeof d.run_id === "string" && d.run_id.length > 0
    && r.schema === "lolm.code.receipt.v2"
    && typeof r.run_id === "string" && r.run_id.length > 0
    && d.run_id === r.run_id
    && r.verdict === "shipped"
    && r.ok === true
    && r.syntax_ok === true
    && r.verification?.syntax_ok === true
    && r.verification?.execution_ok === true
    && r.verification?.contract_ok === true
    && r.verification?.artifact_manifest_ok === true
    && receiptVerified
    && (!saveRequested || artifactsVerified);

  return { shipped, reasons: shipped ? [] : reasons };
}

/**
 * Ask/agent run: nonzero when proof is red or stream incomplete.
 */
export function evaluateAskOk(result) {
  const reasons = [];
  if (!result || typeof result !== "object") {
    return { ok: false, reasons: ["missing_result"] };
  }
  if (result.error) reasons.push(`error=${result.error}`);
  const proof = result.proof || {};
  const v = proof.verdict || "";
  // Red / incomplete proof types
  const red = /incomplete|failed|overclaim|no_proof|error/i.test(v);
  if (red) reasons.push(`proof.verdict=${v}`);
  if (result.ended_by === "error") reasons.push("ended_by=error");
  // Fail closed when --fail-on red and no answer
  const answer = (result.answer || result.response || result.final || "").trim();
  if (!answer && !result.tokens) {
    // some streams only put text on stdout via tokens; allow empty only if proof ok
    if (!v || red) reasons.push("empty_answer");
  }
  return { ok: reasons.length === 0, reasons };
}
