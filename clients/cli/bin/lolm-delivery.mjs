#!/usr/bin/env node
// Copyright (c) 2026 Qira LLC. All rights reserved.
/** User-facing LOLM launcher with artifact delivery and local referent resolution. */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import process from "node:process";
import {
  artifactLocationQuestion,
  commandIndex,
  commandTask,
  isOfficialCredentialFabrication,
  loadLastDelivery,
  makeDeliveryDirectory,
  recordDelivery,
  requestedArtifactKind,
  requestedDestination,
  selectDeliveredArtifacts,
  walkFiles,
} from "../lib/delivery.mjs";

const VERSION = "0.3.0-beta.2";
const CORE_VERSION = "0.3.0-beta.1";
const here = dirname(fileURLToPath(import.meta.url));
const coreCli = join(here, "lolm.mjs");
const argv = process.argv.slice(2);
const { command, task } = commandTask(argv);

function printRefusal() {
  process.stderr.write(
    "LOLM cannot fabricate official proof of attendance, enrollment, employment, or another credential.\n" +
    "It can create a clearly labeled unofficial self-attestation, draft a request for genuine verification, " +
    "or assemble authentic documents you provide.\n",
  );
}

async function showLastArtifact({ open = false } = {}) {
  const last = await loadLastDelivery();
  if (!last || !last.exists) {
    process.stderr.write(
      "No delivered local artifact was found. A previous run may have generated a file only inside its sandbox.\n",
    );
    return 1;
  }
  for (const path of last.files) process.stdout.write(`${path}\n`);
  if (open && last.files[0] && process.platform === "darwin") {
    const child = spawn("open", [last.files[0]], { stdio: "ignore" });
    child.unref();
  }
  return 0;
}

async function runCore(args) {
  return await new Promise((resolve) => {
    const child = spawn(process.execPath, [coreCli, ...args], {
      stdio: "inherit",
      env: process.env,
    });
    const forward = (signal) => {
      try { child.kill(signal); } catch { /* already exited */ }
    };
    process.once("SIGINT", () => forward("SIGINT"));
    process.once("SIGTERM", () => forward("SIGTERM"));
    child.once("error", (error) => {
      process.stderr.write(`LOLM failed to start: ${error.message}\n`);
      resolve(1);
    });
    child.once("exit", (code, signal) => {
      if (signal) resolve(signal === "SIGINT" ? 130 : 1);
      else resolve(Number.isInteger(code) ? code : 1);
    });
  });
}

function rewritePresentation(text) {
  let rendered = String(text || "").split(CORE_VERSION).join(VERSION);
  if (!rendered.includes("artifact last|open")) {
    rendered = rendered.replace(
      "  receipts              Recent sealed code receipts.\n",
      "  receipts              Recent sealed code receipts.\n" +
      "  artifact last|open    Show or open the last verified local artifact.\n",
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
  return await new Promise((resolve) => {
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
      resolve(1);
    });
    child.once("exit", (code) => {
      if (stdout) process.stdout.write(rewritePresentation(stdout));
      if (stderr) process.stderr.write(rewritePresentation(stderr));
      resolve(Number.isInteger(code) ? code : 1);
    });
  });
}

async function main() {
  if (!command && (argv.includes("--version") || argv.includes("-V"))) {
    process.stdout.write(`${VERSION}\n`);
    return 0;
  }
  const presentationOnly = argv.length === 0 || command === "help" ||
    argv.includes("--help") || argv.includes("-h");
  if (presentationOnly) return await runCorePresentation(argv);

  if (command === "artifact") {
    const idx = commandIndex(argv);
    const sub = argv[idx + 1] || "last";
    if (["last", "where", "path", "list"].includes(sub)) return await showLastArtifact();
    if (sub === "open") return await showLastArtifact({ open: true });
    process.stderr.write("usage: lolm artifact [last|open]\n");
    return 2;
  }

  if (command === "ask" && artifactLocationQuestion(task)) {
    return await showLastArtifact();
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
    if (!trace && !next.includes("--quiet") && !next.includes("-q") && !next.includes("--json")) {
      next.push("--quiet");
    }
  }

  const code = await runCore(next);
  if (code !== 0) return code;
  if (!kind || !deliveryDestination) return code;

  const files = await walkFiles(deliveryDestination);
  const delivered = selectDeliveredArtifacts(files, kind);
  if (!delivered.length) {
    process.stderr.write(
      `LOLM did not deliver the requested ${kind || "artifact"}. ` +
      `The run may have created only source code inside ${deliveryDestination}.\n`,
    );
    return 1;
  }
  const saved = await recordDelivery({
    task,
    kind,
    destination: automaticDestination
      ? (requestedDestination(task) || deliveryDestination)
      : deliveryDestination,
    files: delivered,
  });
  process.stdout.write(`delivered ${saved.kind}\n`);
  for (const file of saved.files) process.stdout.write(`saved     ${file}\n`);
  return 0;
}

process.exitCode = await main();
