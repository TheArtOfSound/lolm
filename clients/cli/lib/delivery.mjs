// Copyright (c) 2026 Qira LLC. All rights reserved.
/** Local artifact delivery, destination inference, and cross-command continuity. */
import { access, mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import { extname, join, resolve } from "node:path";
import { homedir } from "node:os";

const VALUE_FLAGS = new Set([
  "--base", "--timeout", "--idle-timeout", "--save", "--out", "-o",
  "--limit", "--max-steps", "--id", "--api-key", "--license",
  "--fail-on", "--receipt", "--conversation",
]);
const ARTIFACT_EXTS = new Set([
  ".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md",
  ".html", ".htm", ".png", ".jpg", ".jpeg", ".svg", ".csv",
  ".xlsx", ".pptx", ".zip",
]);
const CODE_EXTS = new Set([".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".sh"]);

export function commandIndex(argv) {
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i];
    if (token === "--") continue;
    if (token.startsWith("-")) {
      if (VALUE_FLAGS.has(token)) i++;
      continue;
    }
    return i;
  }
  return -1;
}

export function commandTask(argv) {
  const idx = commandIndex(argv);
  if (idx < 0) return { command: "", task: "" };
  const command = argv[idx];
  const words = [];
  for (let i = idx + 1; i < argv.length; i++) {
    const token = argv[i];
    if (token === "--") {
      words.push(...argv.slice(i + 1));
      break;
    }
    if (token.startsWith("-")) {
      if (VALUE_FLAGS.has(token)) i++;
      continue;
    }
    words.push(token);
  }
  return { command, task: words.join(" ").trim() };
}

export function requestedArtifactKind(task) {
  const t = String(task || "").toLowerCase();
  if (/\bpdf\b/.test(t)) return "pdf";
  if (/\b(docx|word document)\b/.test(t)) return "docx";
  if (/\b(spreadsheet|xlsx|excel)\b/.test(t)) return "xlsx";
  if (/\b(slides?|powerpoint|pptx|presentation)\b/.test(t)) return "pptx";
  if (/\b(image|png|jpe?g|svg)\b/.test(t)) return "image";
  if (/\b(html|webpage|web page|website)\b/.test(t)) return "html";
  if (/\b(document|file|report|letter|resume|invoice|receipt)\b/.test(t)) return "document";
  return "";
}

export function requestedDestination(task) {
  const t = String(task || "").toLowerCase();
  if (/\b(desktop|on my desktop|to my desktop)\b/.test(t)) return join(homedir(), "Desktop");
  if (/\b(downloads?|download folder)\b/.test(t)) return join(homedir(), "Downloads");
  if (/\b(documents?|document folder)\b/.test(t)) return join(homedir(), "Documents");
  return "";
}

export function isOfficialCredentialFabrication(task) {
  const t = String(task || "").toLowerCase();
  if (/\b(unofficial|self[- ]?attestation|personal statement|clearly labeled draft)\b/.test(t)) return false;
  const proof = /\b(proof|prove|proving|verification|verify|certificate|official letter|transcript)\b/.test(t);
  const status = /\b(attend|attendance|enroll|enrollment|student|graduate|graduated|employed|employment)\b/.test(t);
  const institution = /\b(asu|university|college|school|employer|company|government|bank)\b/.test(t);
  return proof && status && institution;
}

export function artifactLocationQuestion(text) {
  const t = String(text || "").trim().toLowerCase();
  const where = /\b(where|find|location|saved|put|downloaded|open)\b/.test(t);
  const referent = /\b(pdf|document|file|artifact|it|that)\b/.test(t);
  return where && referent;
}

export function makeDeliveryDirectory(task, root = "") {
  const base = root || requestedDestination(task) || join(homedir(), "Downloads");
  const kind = requestedArtifactKind(task) || "artifact";
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const nonce = Math.random().toString(16).slice(2, 8);
  return resolve(base, `LOLM-${kind}-${stamp}-${nonce}`);
}

export async function walkFiles(root, limit = 200) {
  const out = [];
  async function visit(dir) {
    if (out.length >= limit) return;
    let entries = [];
    try { entries = await readdir(dir, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      if (out.length >= limit) break;
      const path = join(dir, entry.name);
      if (entry.isDirectory()) await visit(path);
      else if (entry.isFile()) out.push(path);
    }
  }
  await visit(root);
  return out;
}

export function selectDeliveredArtifacts(paths, kind = "") {
  const wanted = String(kind || "").toLowerCase();
  const matches = paths.filter((path) => {
    const ext = extname(path).toLowerCase();
    if (!ARTIFACT_EXTS.has(ext)) return false;
    if (wanted === "pdf") return ext === ".pdf";
    if (wanted === "docx") return ext === ".docx";
    if (wanted === "xlsx") return ext === ".xlsx" || ext === ".csv";
    if (wanted === "pptx") return ext === ".pptx";
    if (wanted === "html") return ext === ".html" || ext === ".htm";
    if (wanted === "image") return [".png", ".jpg", ".jpeg", ".svg"].includes(ext);
    return !CODE_EXTS.has(ext);
  });
  return matches.sort();
}

function ledgerPath() {
  return process.env.LOLM_DELIVERY_LEDGER || join(homedir(), ".lolm", "deliveries.json");
}

export async function recordDelivery(entry) {
  const path = ledgerPath();
  await mkdir(resolve(path, ".."), { recursive: true, mode: 0o700 });
  let previous = { schema: "lolm.delivery.ledger.v1", deliveries: [] };
  try { previous = JSON.parse(await readFile(path, "utf8")); } catch { /* new ledger */ }
  const deliveries = Array.isArray(previous.deliveries) ? previous.deliveries.slice(-99) : [];
  const nextEntry = {
    ts: Date.now() / 1000,
    task: String(entry.task || "").slice(0, 500),
    kind: entry.kind || "artifact",
    destination: resolve(String(entry.destination || "")),
    files: (entry.files || []).map((file) => resolve(String(file))),
  };
  deliveries.push(nextEntry);
  const next = { schema: "lolm.delivery.ledger.v1", last: nextEntry, deliveries };
  await writeFile(path, JSON.stringify(next, null, 2) + "\n", { mode: 0o600 });
  return nextEntry;
}

export async function loadLastDelivery() {
  try {
    const ledger = JSON.parse(await readFile(ledgerPath(), "utf8"));
    const entry = ledger.last || (ledger.deliveries || []).at(-1);
    if (!entry) return null;
    const existing = [];
    for (const file of entry.files || []) {
      try {
        await access(file);
        const info = await stat(file);
        if (info.isFile()) existing.push(resolve(file));
      } catch { /* missing local file */ }
    }
    return { ...entry, files: existing, exists: existing.length > 0 };
  } catch {
    return null;
  }
}
