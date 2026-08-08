// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Dependency-free terminal presentation for LOLM. */
import readlineBase from "node:readline";
import readline from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";

export const color = Boolean(output.isTTY && !process.env.NO_COLOR && process.env.TERM !== "dumb");
const esc = (code, value) => color ? `\x1b[${code}m${value}\x1b[0m` : String(value);
export const ui = {
  bold: (v) => esc("1", v), dim: (v) => esc("2", v), rose: (v) => esc("38;5;204", v),
  violet: (v) => esc("38;5;141", v), indigo: (v) => esc("38;5;111", v),
  green: (v) => esc("38;5;84", v), amber: (v) => esc("38;5;214", v), red: (v) => esc("38;5;203", v),
  cyan: (v) => esc("38;5;81", v),
};

export function wordmark() {
  return `${ui.rose("LO")}${ui.indigo("LM")}`;
}

export function banner({ version = "", provider = "", model = "", nfet = "" } = {}) {
  const width = Math.min(78, Math.max(54, output.columns || 72));
  const line = "─".repeat(width - 2);
  const title = `${wordmark()}  ${ui.dim("local intelligence console")}`;
  const meta = [provider && `${provider} · ${model}`, nfet, version && `v${version}`].filter(Boolean).join("  │  ");
  return [
    ui.dim(`╭${line}╮`),
    `│  ${title}${" ".repeat(Math.max(1, width - 6 - stripAnsi(title).length))}│`,
    `│  ${ui.dim(meta)}${" ".repeat(Math.max(1, width - 4 - meta.length))}│`,
    ui.dim(`╰${line}╯`),
  ].join("\n");
}

export function stripAnsi(value) {
  return String(value).replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "");
}

export function section(label, detail = "") {
  const suffix = detail ? ` ${ui.dim(detail)}` : "";
  process.stderr.write(`\n${ui.violet("◆")} ${ui.bold(label)}${suffix}\n`);
}

export function note(message) { process.stderr.write(`${ui.dim("  ·")} ${message}\n`); }
export function success(message) { process.stderr.write(`${ui.green("✓")} ${message}\n`); }
export function warning(message) { process.stderr.write(`${ui.amber("!")} ${message}\n`); }
export function failure(message) { process.stderr.write(`${ui.red("×")} ${message}\n`); }

export async function spinner(label, work, { enabled = output.isTTY } = {}) {
  if (!enabled) return work();
  const frames = ["◐", "◓", "◑", "◒"];
  let index = 0;
  let active = true;
  const draw = () => {
    if (!active) return;
    output.write(`\r\x1b[2K${ui.violet(frames[index++ % frames.length])} ${ui.dim(label)}`);
  };
  draw();
  const timer = setInterval(draw, 90);
  try {
    return await work();
  } finally {
    active = false;
    clearInterval(timer);
    output.write("\r\x1b[2K");
  }
}

export function renderMarkdown(markdown) {
  if (!color) return String(markdown || "").trim();
  let inCode = false;
  return String(markdown || "").trim().split("\n").map((line) => {
    if (/^```/.test(line)) { inCode = !inCode; return ui.dim(line); }
    if (inCode) return ui.cyan(line);
    if (/^#{1,3}\s+/.test(line)) return ui.bold(line.replace(/^#{1,3}\s+/, ""));
    if (/^\s*[-*]\s+/.test(line)) return line.replace(/^(\s*)[-*]\s+/, `$1${ui.violet("•")} `);
    return line.replace(/\*\*([^*]+)\*\*/g, (_, text) => ui.bold(text)).replace(/`([^`]+)`/g, (_, text) => ui.cyan(text));
  }).join("\n");
}

export async function confirm(question, defaultYes = false) {
  if (!input.isTTY) return false;
  const rl = readline.createInterface({ input, output });
  try {
    const answer = await rl.question(`${question} ${defaultYes ? "[Y/n]" : "[y/N]"} `);
    if (!answer.trim()) return defaultYes;
    return /^y(es)?$/i.test(answer.trim());
  } finally { rl.close(); }
}

export async function prompt(question, fallback = "") {
  const rl = readline.createInterface({ input, output });
  try {
    const answer = await rl.question(`${question}${fallback ? ` ${ui.dim(`[${fallback}]`)}` : ""}: `);
    return answer.trim() || fallback;
  } finally { rl.close(); }
}

export async function secretPrompt(question) {
  if (!input.isTTY) return "";
  return await new Promise((resolvePromise) => {
    readlineBase.emitKeypressEvents(input);
    const wasRaw = input.isRaw;
    input.setRawMode?.(true);
    output.write(`${question}: `);
    let value = "";
    const onKey = (text, key) => {
      if (key?.ctrl && key.name === "c") {
        cleanup(); output.write("\n"); resolvePromise(""); return;
      }
      if (key?.name === "return" || key?.name === "enter") {
        cleanup(); output.write("\n"); resolvePromise(value); return;
      }
      if (key?.name === "backspace") {
        if (value) { value = value.slice(0, -1); output.write("\b \b"); }
        return;
      }
      if (text && !key?.ctrl && !key?.meta) { value += text; output.write("•"); }
    };
    const cleanup = () => { input.off("keypress", onKey); input.setRawMode?.(Boolean(wasRaw)); };
    input.on("keypress", onKey);
  });
}

export function nfetLine(result) {
  if (!result?.available) return ui.dim(`NFET unavailable · ${result?.reason || "not loaded"}`);
  const d = result.decision || {};
  const colors = { continue: ui.green, retrieve: ui.amber, verify: ui.cyan, branch: ui.violet, finalize: ui.green };
  const paint = colors[d.label] || ui.dim;
  return `${ui.violet("NFET")} ${paint(String(d.label || "unknown").toUpperCase())} ${ui.dim(`· ${d.source || ""} · H ${result.telemetry?.avg_entropy ?? "–"} · Δ ${result.telemetry?.avg_hidden_drift ?? "–"} · gate ${result.telemetry?.avg_gate ?? "–"}`)}`;
}
