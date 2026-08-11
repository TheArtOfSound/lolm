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
        cleanup(); output.write("\n"); resolvePromise(null); return;
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

export function nfetSummary(result, { verbose = false } = {}) {
  if (verbose) return nfetLine(result);
  if (!result?.available) return `${ui.dim("Quality controller offline")} ${ui.dim(`· ${result?.reason || "not loaded"}`)}`;
  const label = result.decision?.label || "continue";
  const summaries = {
    continue: ["Trajectory stable", ui.green],
    retrieve: ["Gathering better evidence", ui.amber],
    verify: ["Checking the result", ui.cyan],
    branch: ["Comparing another approach", ui.violet],
    finalize: ["Result checked", ui.green],
  };
  const [message, paint] = summaries[label] || ["Quality pass complete", ui.dim];
  return `${ui.violet("NFET")} ${paint("◆")} ${message}`;
}

export function createConsoleSurface({ version = "", provider = "", model = "", nfet = "" } = {}) {
  let alternate = false;
  let closed = false;
  let progressVisible = false;
  let progressTimer = null;
  let progressStarted = 0;
  let progressLabel = "Working";
  let progressFrame = 0;
  let verbose = false;
  const drawProgress = () => {
    if (!progressVisible) return;
    const frames = ["◐", "◓", "◑", "◒"];
    const elapsed = Math.max(0, Math.floor((Date.now() - progressStarted) / 1000));
    output.write(`\r\x1b[2K  ${ui.violet(frames[progressFrame++ % frames.length])} ${ui.dim(`${progressLabel} · ${elapsed}s`)}`);
  };
  const startProgress = (label) => {
    progressLabel = label || "Working";
    if (!progressVisible) {
      progressVisible = true;
      progressStarted = Date.now();
      progressTimer = setInterval(drawProgress, 120);
    }
    drawProgress();
  };
  const clearProgress = () => {
    if (!progressVisible) return;
    clearInterval(progressTimer);
    progressTimer = null;
    output.write("\r\x1b[2K");
    progressVisible = false;
  };
  const writeLine = (value = "") => {
    clearProgress();
    output.write(`${value}\n`);
  };
  const close = () => {
    if (closed) return;
    closed = true;
    clearProgress();
    output.write("\x1b[?25h");
    if (alternate) output.write("\x1b[?1049l");
  };
  return {
    open() {
      alternate = Boolean(output.isTTY && process.env.LOLM_NO_ALT_SCREEN !== "1");
      if (alternate) output.write("\x1b[?1049h");
      output.write("\x1b[2J\x1b[H\x1b[?25h");
      writeLine(`${wordmark()}  ${ui.bold("PERSONAL AGENT")}`);
      writeLine(ui.dim("Local intelligence that works on your computer"));
      writeLine();
      writeLine(`${ui.green("●")} ${provider} ${ui.dim(`· ${model}`)}   ${ui.violet("◆")} ${nfet}   ${ui.dim(`v${version}`)}`);
      writeLine(ui.dim("Talk normally. I remember the conversation and unfinished work."));
      writeLine(ui.dim("/help for controls  ·  /debug for NFET details  ·  /exit when done"));
      writeLine(ui.dim("─".repeat(Math.min(96, Math.max(48, (output.columns || 80) - 2)))));
      process.once("exit", close);
    },
    close,
    setVerbose(value) { verbose = Boolean(value); },
    get verbose() { return verbose; },
    user(message) {
      writeLine();
      writeLine(`${ui.indigo("YOU")}  ${String(message || "").trim()}`);
    },
    phase(label, detail = "") {
      clearProgress();
      const suffix = detail ? ` ${ui.dim(`· ${detail}`)}` : "";
      writeLine(`${ui.violet("◆")} ${ui.bold(label)}${suffix}`);
      startProgress("Working locally");
    },
    progress({ chars = 0, thinking = false } = {}) {
      const label = thinking ? "Reasoning locally" : chars ? `Writing · ${chars} characters` : "Working";
      startProgress(label);
    },
    tool(label) { writeLine(`  ${ui.cyan("↳")} ${label}`); },
    nfet(result) { writeLine(`  ${nfetSummary(result, { verbose })}`); },
    assistant(message) {
      clearProgress();
      writeLine();
      writeLine(`${wordmark()}  ${renderMarkdown(message)}`);
    },
    success(message) { writeLine(`${ui.green("✓")} ${message}`); },
    warning(message) { writeLine(`${ui.amber("!")} ${message}`); },
    error(message, { retry = false } = {}) {
      writeLine(`${ui.red("×")} ${message}`);
      if (retry) writeLine(ui.dim("  I saved the request. Type “try again” and I’ll resume it."));
    },
  };
}
