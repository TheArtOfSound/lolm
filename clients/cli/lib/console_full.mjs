// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** The full-screen console: fixed header, scrolling transcript, bordered input.
 *
 * It presents the same surface as the linear console, so the interactive loop
 * does not know which one it is talking to. Anything that cannot render a frame
 * — a pipe, a screen reader, a terminal that is not a TTY — gets the linear one
 * instead, which is why nothing here is allowed to be the only way to use LOLM.
 */
import readlineBase from "node:readline";
import { stdin as input, stdout as output } from "node:process";
import { homedir } from "node:os";
import { createScreen, fit } from "./screen.mjs";
import { createEditor } from "./editor.mjs";
import { caps, glyph, nfetSummary, renderMarkdown, stripAnsi, ui, wordmark, wrap } from "./tui.mjs";

const aside = (value) => ui.dim(value);

export function createFullScreenConsole({ version = "", provider = "", model = "", nfet = "", mode = "standard", workspace = process.cwd() } = {}) {
  const screen = createScreen({ output, alternate: caps.altScreen });
  const editor = createEditor();
  const transcript = [];
  let scrollOffset = 0;      // rows scrolled back from the live tail
  let verbose = false;
  let status = "";
  let statusSince = 0;
  let spinnerFrame = 0;
  let ticker = null;
  let closed = false;
  let pendingResolve = null;
  let context = { provider, model, nfet, mode, workspace };

  const columns = () => screen.size().columns;
  const inner = () => columns() - 4;

  /** Push already-styled text into the transcript, wrapping to the box width. */
  function push(value = "") {
    const text = String(value);
    for (const line of wrap(text, inner(), "").split("\n")) transcript.push(line);
    // Following the tail is the default; an explicit scroll-back is respected
    // until the reader returns to the bottom.
    if (scrollOffset === 0) render();
    else render();
  }

  function headerLines() {
    const width = columns();
    const left = `  ${wordmark()} ${ui.bold("personal agent")}`;
    const right = `${aside(`v${version}`)}  `;
    const pad = Math.max(1, width - stripAnsi(left).length - stripAnsi(right).length);
    const meta = [
      `${ui.green(glyph.dot)} ${ui.bold(context.provider)} ${aside(context.model)}`,
      `${ui.violet(glyph.diamond)} ${context.nfet}`,
      `${ui.amber(glyph.small)} ${context.mode}`,
    ].join(aside("   "));
    // A deep path would crowd out the status, so shorten $HOME to ~ and keep the
    // tail — the part that actually tells you where you are.
    const budget = Math.max(12, width - stripAnsi(meta).length - 10);
    let where = context.workspace.replace(homedir(), "~");
    if (where.length > budget) where = `…${where.slice(-(budget - 1))}`;
    const home = `${ui.cyan(glyph.home)} ${where}`;
    const metaPad = Math.max(2, width - stripAnsi(meta).length - stripAnsi(home).length - 4);
    return [
      `${left}${" ".repeat(pad)}${right}`,
      `  ${meta}${" ".repeat(metaPad)}${home}  `,
      aside(`  ${glyph.rule.repeat(Math.max(10, width - 4))}  `),
    ];
  }

  function inputLines() {
    const width = inner();
    const value = editor.value;
    // Wrap the buffer the same way it will be drawn so the cursor lands on the
    // row the reader sees, not the row the raw string implies.
    const rows = [];
    let cursorRow = 0;
    let cursorColumn = 0;
    let consumed = 0;
    for (const paragraph of value.split("\n")) {
      const chunks = [];
      for (let index = 0; index < paragraph.length; index += width) chunks.push(paragraph.slice(index, index + width));
      if (!chunks.length) chunks.push("");
      for (const chunk of chunks) {
        const start = consumed;
        const end = start + chunk.length;
        if (editor.cursor >= start && editor.cursor <= end) {
          cursorRow = rows.length;
          cursorColumn = editor.cursor - start;
        }
        rows.push(chunk);
        consumed = end;
      }
      consumed += 1; // the newline itself
    }
    const shown = rows.slice(-8);
    cursorRow -= rows.length - shown.length;
    return { rows: shown, cursorRow: Math.max(0, cursorRow), cursorColumn };
  }

  function footer() {
    const hint = editor.value.includes("\n")
      ? "⏎ send · ⌥⏎ newline · ^C clear"
      : "⏎ send · ⌥⏎ newline · PgUp scroll · /help · /exit";
    return aside(`  ${hint}`);
  }

  function render() {
    if (closed) return;
    const { rows: height, columns: width } = screen.size();
    const header = headerLines();
    const box = inputLines();
    const statusRow = status ? 1 : 0;
    const inputHeight = box.rows.length + 2;          // borders
    const viewport = Math.max(3, height - header.length - inputHeight - statusRow - 1);

    const maxOffset = Math.max(0, transcript.length - viewport);
    scrollOffset = Math.min(scrollOffset, maxOffset);
    const top = Math.max(0, transcript.length - viewport - scrollOffset);
    const visible = transcript.slice(top, top + viewport);

    const lines = [...header];
    for (let index = 0; index < viewport; index += 1) {
      lines.push(visible[index] === undefined ? "" : fit(`  ${visible[index]}`, width));
    }
    if (scrollOffset > 0) {
      lines[lines.length - 1] = fit(aside(`  ${glyph.rule.repeat(2)} ${scrollOffset} more line(s) below ${glyph.rule.repeat(2)}`), width);
    }
    if (status) {
      const seconds = Math.max(0, Math.round((Date.now() - statusSince) / 1000));
      const spin = caps.motion ? `${glyph.spinner[spinnerFrame % glyph.spinner.length]} ` : "";
      lines.push(fit(`  ${ui.violet(spin)}${aside(`${status} · ${seconds}s`)}`, width));
    }

    const edge = glyph.rule.repeat(Math.max(4, width - 4));
    lines.push(fit(`  ${ui.violet(`${glyph.topLeft}${edge}${glyph.topRight}`)}`, width));
    box.rows.forEach((row, index) => {
      const caret = index === 0 ? ui.violet("›") : " ";
      const padded = row + " ".repeat(Math.max(0, inner() - row.length - 1));
      lines.push(fit(`  ${ui.violet(glyph.pipe)}${caret}${padded}${ui.violet(glyph.pipe)}`, width));
    });
    lines.push(fit(`  ${ui.violet(`${glyph.bottomLeft}${edge}${glyph.bottomRight}`)}`, width));
    lines.push(footer());

    const cursorRowOnScreen = lines.length - 2 - box.rows.length + box.cursorRow;
    screen.draw(lines, { row: cursorRowOnScreen, column: 4 + box.cursorColumn });
  }

  function startTicker() {
    if (ticker) return;
    ticker = setInterval(() => { spinnerFrame += 1; render(); }, caps.motion ? 140 : 1_000);
    ticker.unref?.();
  }
  function stopTicker() {
    if (!ticker) return;
    clearInterval(ticker);
    ticker = null;
  }

  const onResize = () => { screen.invalidate(); render(); };
  let onKey = null;

  return {
    fullScreen: true,
    open() {
      screen.open();
      readlineBase.emitKeypressEvents(input);
      if (input.isTTY) input.setRawMode(true);
      output.on("resize", onResize);
      onKey = (sequence, info = {}) => {
        if (closed) return;
        const action = editor.key(sequence, info);
        if (action === "submit") {
          const value = editor.value.trim();
          if (!value) return render();
          editor.remember(value);
          editor.reset();
          scrollOffset = 0;
          const resolvePending = pendingResolve;
          pendingResolve = null;
          render();
          resolvePending?.(value);
          return;
        }
        if (action === "quit") { const p = pendingResolve; pendingResolve = null; p?.("/exit"); return; }
        if (action === "cancel") { const p = pendingResolve; pendingResolve = null; p?.("/exit"); return; }
        if (action === "scroll-up") { scrollOffset = Math.min(scrollOffset + 5, Math.max(0, transcript.length - 1)); return render(); }
        if (action === "scroll-down") { scrollOffset = Math.max(0, scrollOffset - 5); return render(); }
        if (action === "redraw") return render();
      };
      input.on("keypress", onKey);
      push(`${aside("Talk normally. I remember the conversation and unfinished work.")}`);
      push(`${aside("/help for controls · /debug for NFET detail · /exit when done")}`);
      render();
    },
    close() {
      if (closed) return;
      closed = true;
      stopTicker();
      if (onKey) input.off("keypress", onKey);
      output.off("resize", onResize);
      if (input.isTTY) input.setRawMode(false);
      screen.close();
    },
    /** Resolve with the reader's next submitted line. */
    read() {
      return new Promise((resolvePromise) => {
        pendingResolve = resolvePromise;
        render();
      });
    },
    setContext(next = {}) { context = { ...context, ...next }; render(); },
    setVerbose(value) { verbose = Boolean(value); },
    get verbose() { return verbose; },
    user(message) {
      push("");
      push(`${ui.indigo("›")} ${ui.bold(String(message || "").trim())}`);
    },
    phase(label, detail = "") {
      push("");
      push(`${ui.violet(glyph.diamond)} ${ui.bold(label)}${detail ? ` ${aside(`· ${detail}`)}` : ""}`);
      status = "Working locally";
      statusSince = Date.now();
      startTicker();
    },
    progress({ chars = 0, thinking = false } = {}) {
      status = thinking ? "Reasoning locally" : chars ? `Writing · ${chars} characters` : "Working";
      if (!statusSince) statusSince = Date.now();
      startTicker();
    },
    tool(label) { push(`  ${ui.cyan(glyph.arrow)} ${aside(label)}`); },
    activity(event) {
      if (event?.type === "tool.started") push(`  ${ui.violet(glyph.small)} ${event.tool}`);
      else if (event?.type === "tool.completed") {
        const detail = `${event.duration_ms || 0}ms${event.result?.id ? ` · ${event.result.id}` : ""}`;
        const left = `  ${ui.green(glyph.ok)} ${event.tool}`;
        const pad = Math.max(1, inner() - stripAnsi(left).length - detail.length);
        push(`${left}${" ".repeat(pad)}${aside(detail)}`);
      } else if (event?.type === "tool.failed") {
        push(`  ${ui.red(glyph.err)} ${event.tool} ${ui.red(event.error?.message || "failed")}`);
      }
    },
    nfet(result) { push(`  ${nfetSummary(result, { verbose })}`); },
    assistant(message) {
      status = ""; statusSince = 0; stopTicker();
      push("");
      push(`${ui.rose(glyph.diamond)} ${ui.bold("LOLM")}`);
      push(renderMarkdown(message));
    },
    success(message) { status = ""; stopTicker(); push(`${ui.green(glyph.ok)} ${message}`); },
    warning(message) { push(`${ui.amber(glyph.warn)} Warning: ${message}`); },
    error(message, { retry = false } = {}) {
      status = ""; stopTicker();
      push(`${ui.red(glyph.err)} Error: ${message}`);
      if (retry) push(aside("  Saved. Type “try again” to resume it."));
    },
    // The linear console needs these; the frame compositor owns its own cursor.
    attach() {},
    setPromptLive() {},
  };
}
