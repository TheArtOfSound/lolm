// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Dependency-free terminal presentation for LOLM.
 *
 * Two rules shape everything here. Meaning is never carried by colour alone —
 * every state that matters also has a word or an ASCII-safe mark. And nothing
 * repaints unless the terminal is a TTY that asked for it, so a screen reader,
 * a pipe, and a CI log all receive the same linear text.
 */
import readlineBase from "node:readline";
import readline from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";
import { detectCapabilities, explainCapabilities } from "./terminal_caps.mjs";

export const caps = detectCapabilities();
export { explainCapabilities };
export const color = caps.color;

const esc = (code, value) => (caps.color ? `\x1b[${code}m${value}\x1b[0m` : String(value));
export const ui = {
  bold: (v) => esc("1", v), dim: (v) => esc("2", v), rose: (v) => esc("38;5;204", v),
  violet: (v) => esc("38;5;141", v), indigo: (v) => esc("38;5;111", v),
  green: (v) => esc("38;5;84", v), amber: (v) => esc("38;5;214", v), red: (v) => esc("38;5;203", v),
  cyan: (v) => esc("38;5;81", v),
};

// Dim grey on a light theme is close to invisible, so anything the reader
// actually needs uses plain text and dim is reserved for true asides.
const aside = (v) => ui.dim(v);

const UNICODE = {
  ok: "✓", warn: "!", err: "×", bullet: "•", diamond: "◆", small: "◇", arrow: "↳",
  home: "⌂", dot: "●", rule: "─", spinner: ["◐", "◓", "◑", "◒"],
  topLeft: "╭", topRight: "╮", bottomLeft: "╰", bottomRight: "╯", pipe: "│",
};
const ASCII = {
  ok: "OK", warn: "!", err: "x", bullet: "-", diamond: "*", small: "-", arrow: "->",
  home: "@", dot: "*", rule: "-", spinner: ["|", "/", "-", "\\"],
  topLeft: "+", topRight: "+", bottomLeft: "+", bottomRight: "+", pipe: "|",
};
// A screen reader announces "black circle" and "house" for decorative symbols,
// so plain mode drops to ASCII even where the terminal could render more.
export const glyph = caps.unicode && !caps.plain ? UNICODE : ASCII;

export function stripAnsi(value) {
  return String(value).replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "");
}

const TRANSLITERATE = [
  [/[·•]/g, "-"], [/[—–]/g, "-"], [/[""]/g, '"'], [/['']/g, "'"],
  [/…/g, "..."], [/[›»]/g, ">"], [/[‹«]/g, "<"], [/[─━]/g, "-"],
  [/[│┃]/g, "|"], [/[╭╮╰╯┌┐└┘]/g, "+"], [/[✓✔]/g, "OK"], [/[×✗✘]/g, "x"],
  [/[◆◇◈]/g, "*"], [/[●○◐◓◑◒]/g, "*"], [/[↳→]/g, "->"], [/⌂/g, "@"],
];

/** Fold typographic characters to ASCII when the locale cannot render them.
 *  Applied at the write edge so no call site has to remember. */
export function asciiSafe(value) {
  let text = String(value ?? "");
  if (caps.unicode && !caps.plain) return text;
  for (const [pattern, replacement] of TRANSLITERATE) text = text.replace(pattern, replacement);
  // Anything still outside printable ASCII would render as noise or be read
  // out character by character; drop it rather than emit mojibake.
  return caps.unicode ? text : text.replace(/[^\x09\x0a\x0d\x20-\x7e\x1b[\]]/g, "");
}

/** The prompt the reader types at. Box drawing is decoration, not information. */
export function inputPrompt() {
  if (caps.plain) return "\nYou: ";
  // readline writes this itself, so it never passes the sanitised write edge.
  return asciiSafe(`\n${ui.indigo(`${glyph.topLeft}${glyph.rule} YOU`)}\n${ui.violet(`${glyph.bottomLeft}${glyph.rule}›`)} `);
}

/** Wrap to the terminal width so indentation survives; never split a word. */
export function wrap(text, width = caps.width, indent = "") {
  const limit = Math.max(20, width - indent.length);
  const lines = [];
  for (const paragraph of String(text ?? "").split("\n")) {
    if (stripAnsi(paragraph).length <= limit) { lines.push(indent + paragraph); continue; }
    let current = "";
    for (const word of paragraph.split(/(\s+)/)) {
      if (stripAnsi(current + word).length > limit && current.trim()) {
        lines.push(indent + current.trimEnd());
        current = /^\s+$/.test(word) ? "" : word;
      } else current += word;
    }
    if (current.trim()) lines.push(indent + current.trimEnd());
  }
  return lines.join("\n");
}

export function wordmark() {
  return `${ui.rose("LO")}${ui.indigo("LM")}`;
}

export function banner({ version = "", provider = "", model = "", nfet = "" } = {}) {
  const meta = [provider && `${provider} · ${model}`, nfet, version && `v${version}`].filter(Boolean).join("  |  ");
  if (caps.plain || !caps.unicode) {
    return [`LOLM — local intelligence console`, meta].filter(Boolean).join("\n");
  }
  const width = Math.min(78, Math.max(54, caps.width));
  const line = glyph.rule.repeat(width - 2);
  const title = `${wordmark()}  ${aside("local intelligence console")}`;
  return [
    aside(`${glyph.topLeft}${line}${glyph.topRight}`),
    `${glyph.pipe}  ${title}${" ".repeat(Math.max(1, width - 6 - stripAnsi(title).length))}${glyph.pipe}`,
    `${glyph.pipe}  ${aside(meta)}${" ".repeat(Math.max(1, width - 4 - meta.length))}${glyph.pipe}`,
    aside(`${glyph.bottomLeft}${line}${glyph.bottomRight}`),
  ].join("\n");
}

export function section(label, detail = "") {
  const suffix = detail ? ` ${aside(detail)}` : "";
  process.stderr.write(asciiSafe(`\n${ui.violet(glyph.diamond)} ${ui.bold(label)}${suffix}\n`));
}

const toErr = (line) => process.stderr.write(asciiSafe(line));
export function note(message) { toErr(`${aside("  -")} ${message}\n`); }
export function success(message) { toErr(`${ui.green(glyph.ok)} ${message}\n`); }
export function warning(message) { toErr(`${ui.amber(glyph.warn)} Warning: ${message}\n`); }
export function failure(message) { toErr(`${ui.red(glyph.err)} Error: ${message}\n`); }

export async function spinner(label, work, { enabled = caps.motion } = {}) {
  if (!enabled) {
    // Say it once so the reason for the wait is on the record, then be quiet.
    if (!caps.tty || caps.plain) process.stderr.write(`${label}…\n`);
    return work();
  }
  const frames = glyph.spinner;
  let index = 0;
  let active = true;
  const draw = () => {
    if (!active) return;
    output.write(`\r\x1b[2K${ui.violet(frames[index++ % frames.length])} ${aside(label)}`);
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
  const text = String(markdown || "").trim();
  if (!caps.color) return caps.plain ? text : wrap(text);
  let inCode = false;
  return text.split("\n").map((line) => {
    if (/^```/.test(line)) { inCode = !inCode; return aside(line); }
    if (inCode) return ui.cyan(line);
    if (/^#{1,3}\s+/.test(line)) return ui.bold(line.replace(/^#{1,3}\s+/, ""));
    if (/^\s*[-*]\s+/.test(line)) return line.replace(/^(\s*)[-*]\s+/, `$1${ui.violet(glyph.bullet)} `);
    return line.replace(/\*\*([^*]+)\*\*/g, (_, value) => ui.bold(value)).replace(/`([^`]+)`/g, (_, value) => ui.cyan(value));
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
    const answer = await rl.question(`${question}${fallback ? ` ${aside(`[${fallback}]`)}` : ""}: `);
    return answer.trim() || fallback;
  } finally { rl.close(); }
}

export async function secretPrompt(question) {
  if (!input.isTTY) return "";
  return await new Promise((resolvePromise) => {
    readlineBase.emitKeypressEvents(input);
    const wasRaw = input.isRaw;
    input.setRawMode?.(true);
    // Masking is silent by nature; say so, or a reader gets no feedback at all.
    output.write(`${question} (typing is hidden): `);
    let value = "";
    const onKey = (text, key) => {
      if (key?.ctrl && key.name === "c") {
        cleanup(); output.write("\n"); resolvePromise(null); return;
      }
      if (key?.name === "return" || key?.name === "enter") {
        cleanup(); output.write("\n"); resolvePromise(value); return;
      }
      if (key?.name === "backspace") {
        if (value) { value = value.slice(0, -1); if (!caps.plain) output.write("\b \b"); }
        return;
      }
      if (text && !key?.ctrl && !key?.meta) { value += text; if (!caps.plain) output.write(glyph.bullet); }
    };
    const cleanup = () => { input.off("keypress", onKey); input.setRawMode?.(Boolean(wasRaw)); };
    input.on("keypress", onKey);
  });
}

export function nfetLine(result) {
  if (!result?.available) return aside(`NFET unavailable · ${result?.reason || "not loaded"}`);
  const decision = result.decision || {};
  const colors = { continue: ui.green, retrieve: ui.amber, verify: ui.cyan, branch: ui.violet, finalize: ui.green };
  const paint = colors[decision.label] || aside;
  return `${ui.violet("NFET")} ${paint(String(decision.label || "unknown").toUpperCase())} ${aside(`· ${decision.source || ""} · H ${result.telemetry?.avg_entropy ?? "–"} · Δ ${result.telemetry?.avg_hidden_drift ?? "–"} · gate ${result.telemetry?.avg_gate ?? "–"}`)}`;
}

export function nfetSummary(result, { verbose = false } = {}) {
  if (verbose) return nfetLine(result);
  if (!result?.available) return `Quality controller offline ${aside(`· ${result?.reason || "not loaded"}`)}`;
  const label = result.decision?.label || "continue";
  const summaries = {
    continue: ["Trajectory stable", ui.green],
    retrieve: ["Gathering better evidence", ui.amber],
    verify: ["Checking the result", ui.cyan],
    branch: ["Comparing another approach", ui.violet],
    finalize: ["Result checked", ui.green],
  };
  const [message, paint] = summaries[label] || ["Quality pass complete", aside];
  return `${ui.violet("NFET")} ${paint(glyph.diamond)} ${message}`;
}

export function createConsoleSurface({ version = "", provider = "", model = "", nfet = "", mode = "standard", workspace = process.cwd() } = {}) {
  let alternate = false;
  let closed = false;
  let progressVisible = false;
  let progressTimer = null;
  let progressStarted = 0;
  let progressLabel = "Working";
  let progressFrame = 0;
  let lastSpoken = 0;
  let verbose = false;

  const drawProgress = () => {
    if (!progressVisible) return;
    const elapsed = Math.max(0, Math.floor((Date.now() - progressStarted) / 1000));
    if (!caps.motion) {
      // Append one durable line every 15s instead of repainting a spinner, so
      // a screen reader hears "still working" rather than a stream of frames.
      if (Date.now() - lastSpoken < 15_000) return;
      lastSpoken = Date.now();
      output.write(asciiSafe(`   ${progressLabel} (${elapsed}s)\n`));
      return;
    }
    output.write(`\r\x1b[2K  ${ui.violet(glyph.spinner[progressFrame++ % glyph.spinner.length])} ${aside(`${progressLabel} · ${elapsed}s`)}`);
  };
  const startProgress = (label) => {
    progressLabel = label || "Working";
    if (!progressVisible) {
      progressVisible = true;
      progressStarted = Date.now();
      lastSpoken = Date.now();
      progressTimer = setInterval(drawProgress, caps.motion ? 120 : 5_000);
      if (!caps.motion) output.write(`   ${progressLabel}…\n`);
      return;
    }
    drawProgress();
  };
  const clearProgress = () => {
    if (!progressVisible) return;
    clearInterval(progressTimer);
    progressTimer = null;
    if (caps.motion) output.write("\r\x1b[2K");
    progressVisible = false;
  };
  const writeLine = (value = "") => {
    clearProgress();
    output.write(asciiSafe(`${value}\n`));
  };
  const close = () => {
    if (closed) return;
    closed = true;
    clearProgress();
    if (caps.tty && !caps.plain) output.write("\x1b[?25h");
    if (alternate) output.write("\x1b[?1049l");
  };

  return {
    open() {
      alternate = caps.altScreen;
      if (alternate) output.write("\x1b[?1049h\x1b[2J\x1b[H\x1b[?25h");
      if (caps.plain) {
        // Labelled lines read correctly aloud; a row of symbol-prefixed columns
        // does not. Same information, ordered for listening rather than glancing.
        writeLine("LOLM personal agent, version " + version + ".");
        writeLine("Provider: " + provider + ", model " + model + ".");
        writeLine("Quality controller: " + (nfet || "unknown") + ".");
        writeLine("Working directory: " + workspace + ".");
        writeLine("Permissions: " + mode + ".");
        writeLine("Talk normally. Type slash help for controls, slash exit when done.");
        process.once("exit", close);
        return;
      }
      writeLine(`${wordmark()}  ${ui.bold("PERSONAL AGENT")}`);
      writeLine(aside("Local intelligence that works on your computer"));
      writeLine();
      writeLine(`${ui.green(glyph.dot)} ${provider} ${aside(`· ${model}`)}   ${ui.violet(glyph.diamond)} ${nfet}   ${aside(`v${version}`)}`);
      writeLine(`${ui.cyan(glyph.home)} ${workspace}   ${ui.amber(glyph.small)} ${mode} permissions`);
      writeLine(wrap("Talk normally. I remember the conversation and unfinished work."));
      writeLine(aside("/help for controls  ·  /debug for NFET details  ·  /exit when done"));
      writeLine(aside(glyph.rule.repeat(Math.min(96, Math.max(48, caps.width - 2)))));
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
      const suffix = detail ? ` ${aside(`· ${detail}`)}` : "";
      writeLine(`${ui.violet(glyph.diamond)} ${ui.bold(label)}${suffix}`);
      startProgress("Working locally");
    },
    progress({ chars = 0, thinking = false } = {}) {
      startProgress(thinking ? "Reasoning locally" : chars ? `Writing · ${chars} characters` : "Working");
    },
    tool(label) { writeLine(`  ${ui.cyan(glyph.arrow)} ${label}`); },
    activity(event) {
      if (event?.type === "tool.started") writeLine(`  ${ui.violet(glyph.small)} ${event.tool} running`);
      else if (event?.type === "tool.completed") {
        const processId = event.result?.id ? ` · ${event.result.id}` : "";
        writeLine(`  ${ui.green(glyph.ok)} ${event.tool} ${aside(`${event.duration_ms || 0}ms${processId}`)}`);
      } else if (event?.type === "tool.failed") writeLine(`  ${ui.red(glyph.err)} ${event.tool} failed: ${event.error?.message || "unknown error"}`);
    },
    nfet(result) { writeLine(`  ${nfetSummary(result, { verbose })}`); },
    assistant(message) {
      clearProgress();
      writeLine();
      writeLine(caps.plain ? `LOLM: ${renderMarkdown(message)}` : `${wordmark()}  ${renderMarkdown(message)}`);
    },
    success(message) { writeLine(`${ui.green(glyph.ok)} ${message}`); },
    warning(message) { writeLine(`${ui.amber(glyph.warn)} Warning: ${message}`); },
    error(message, { retry = false } = {}) {
      writeLine(`${ui.red(glyph.err)} Error: ${message}`);
      if (retry) writeLine(aside("  I saved the request. Type “try again” and I’ll resume it."));
    },
  };
}
