// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Small durable handoff record for natural retries across CLI processes. */
import { chmod, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { homedir } from "node:os";

export const LAST_TASK_PATH = process.env.LOLM_LAST_TASK || join(homedir(), ".lolm", "last-task.json");

function clean(value, max = 50_000) {
  return String(value || "").replace(/\0/g, "").slice(0, max);
}

export function isRetryPhrase(value) {
  return /^(try|retry|do|run|make)(?:\s+(?:it|that|the last (?:task|request|run)))?\s+again[.!]?$/i.test(clean(value, 200).trim())
    || /^retry(?:\s+the last (?:task|request|run))?[.!]?$/i.test(clean(value, 200).trim());
}

export async function loadLastTask() {
  try {
    const parsed = JSON.parse(await readFile(LAST_TASK_PATH, "utf8"));
    if (!parsed || typeof parsed !== "object" || !parsed.prompt || !parsed.command) return null;
    return parsed;
  } catch {
    return null;
  }
}

export async function saveLastTask(task = {}) {
  const record = {
    version: 1,
    command: clean(task.command, 30),
    prompt: clean(task.prompt),
    cwd: clean(task.cwd, 4096),
    out: clean(task.out, 4096),
    status: clean(task.status, 30),
    error: clean(task.error, 2000),
    result_path: clean(task.result_path, 4096),
    updated_at: new Date().toISOString(),
  };
  const directory = dirname(LAST_TASK_PATH);
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const temporary = `${LAST_TASK_PATH}.${process.pid}.tmp`;
  await writeFile(temporary, `${JSON.stringify(record, null, 2)}\n`, { mode: 0o600 });
  await rename(temporary, LAST_TASK_PATH);
  await chmod(LAST_TASK_PATH, 0o600).catch(() => {});
  return record;
}
