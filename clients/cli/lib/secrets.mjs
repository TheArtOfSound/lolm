// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import { spawn } from "node:child_process";
import { userInfo } from "node:os";

const ACCOUNT = process.env.USER || process.env.USERNAME || userInfo().username || "lolm-user";
const SERVICE_PREFIX = "lolm-cli-provider";

function run(command, args, { input } = {}) {
  return new Promise((resolvePromise) => {
    const child = spawn(command, args, { stdio: [input === undefined ? "ignore" : "pipe", "pipe", "pipe"] });
    let stdout = "", stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    if (input !== undefined) child.stdin.end(input);
    child.on("close", (code) => resolvePromise({ ok: code === 0, code, stdout, stderr }));
    child.on("error", (error) => resolvePromise({ ok: false, code: error.code, stdout, stderr: error.message }));
  });
}

function service(provider) { return `${SERVICE_PREFIX}:${String(provider).toLowerCase()}`; }

export function nativeSecretBackend() {
  if (process.env.LOLM_DISABLE_NATIVE_SECRETS === "1") return null;
  if (process.platform === "darwin") return "macOS Keychain";
  if (process.platform === "linux") return "Secret Service (when secret-tool is installed)";
  return null;
}

export async function storeProviderSecret(provider, value) {
  if (!value) return { stored: false, backend: null, reference: null };
  if (process.env.LOLM_DISABLE_NATIVE_SECRETS === "1") return { stored: false, backend: null, reference: null };
  if (process.platform === "darwin") {
    const result = await run("security", ["add-generic-password", "-a", ACCOUNT, "-s", service(provider), "-w", value, "-U"]);
    if (!result.ok) throw Object.assign(new Error(`macOS Keychain rejected the credential: ${result.stderr.trim() || `exit ${result.code}`}`), { code: "SECRET_STORE_FAILED" });
    return { stored: true, backend: "macOS Keychain", reference: `keychain:${service(provider)}` };
  }
  if (process.platform === "linux") {
    const result = await run("secret-tool", ["store", "--label", `LOLM ${provider} API key`, "application", "lolm-cli", "provider", provider], { input: value });
    if (result.ok) return { stored: true, backend: "Secret Service", reference: `secret-service:${provider}` };
    if (result.code !== "ENOENT") throw Object.assign(new Error(`Secret Service rejected the credential: ${result.stderr.trim() || `exit ${result.code}`}`), { code: "SECRET_STORE_FAILED" });
  }
  return { stored: false, backend: null, reference: null };
}

export async function getProviderSecret(provider, reference) {
  if (!reference) return "";
  if (reference.startsWith("keychain:") && process.platform === "darwin") {
    const result = await run("security", ["find-generic-password", "-a", ACCOUNT, "-s", service(provider), "-w"]);
    return result.ok ? result.stdout.replace(/\r?\n$/, "") : "";
  }
  if (reference.startsWith("secret-service:") && process.platform === "linux") {
    const result = await run("secret-tool", ["lookup", "application", "lolm-cli", "provider", provider]);
    return result.ok ? result.stdout.replace(/\r?\n$/, "") : "";
  }
  return "";
}

export async function deleteProviderSecret(provider, reference) {
  if (!reference) return false;
  if (reference.startsWith("keychain:") && process.platform === "darwin") return (await run("security", ["delete-generic-password", "-a", ACCOUNT, "-s", service(provider)])).ok;
  if (reference.startsWith("secret-service:") && process.platform === "linux") return (await run("secret-tool", ["clear", "application", "lolm-cli", "provider", provider])).ok;
  return false;
}
