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

async function main() {
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
  let autoDestination = "";
  let kind = "";
  if (command === "code") {
    kind = requestedArtifactKind(task);
    const hasSave = next.includes("--save");
    if (kind && !hasSave) {
      autoDestination = makeDeliveryDirectory(task);
      next.push("--save", autoDestination);
    }
    const traceIndex = next.indexOf("--trace");
    const trace = traceIndex >= 0;
    if (trace) next.splice(traceIndex, 1);
    if (!trace && !next.includes("--quiet") && !next.includes("-q") && !next.includes("--json")) {
      next.push("--quiet");
    }
  }

  const code = await runCore(next);
  if (!autoDestination) return code;
  if (code !== 0) return code;

  const files = await walkFiles(autoDestination);
  const delivered = selectDeliveredArtifacts(files, kind);
  if (!delivered.length) {
    process.stderr.write(
      `LOLM did not deliver the requested ${kind || "artifact"}. ` +
      `The run may have created only source code inside ${autoDestination}.\n`,
    );
    return 1;
  }
  const saved = await recordDelivery({
    task,
    kind,
    destination: requestedDestination(task) || autoDestination,
    files: delivered,
  });
  process.stdout.write(`delivered ${saved.kind}\n`);
  for (const file of saved.files) process.stdout.write(`saved     ${file}\n`);
  return 0;
}

process.exitCode = await main();
