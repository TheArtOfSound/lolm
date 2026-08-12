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
import { copyText } from "./clipboard.mjs";
import { scrollKey, searchTranscript, settingsKey, settingsModel } from "./overlays.mjs";

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
  // "input" is the normal state; "scroll" is vim navigation over the
  // transcript; "settings" is the panel. Only one owns the keyboard at a time.
  let uiMode = "input";
  let vimPending = "";
  let searching = false;
  let searchQuery = "";
  let lastSearch = "";
  let notice = "";
  let panel = { rows: [], index: 0, editing: false, buffer: "" };
  let onSetting = null;

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
    if (notice) return `  ${ui.green(notice)}`;
    if (uiMode === "settings") {
      return aside(panel.editing ? "  type a value · ⏎ apply · esc cancel" : "  ↑↓ move · ←→ change · ⏎ edit · esc close");
    }
    if (uiMode === "scroll") {
      if (searching) return `  ${ui.violet("/")}${searchQuery}${aside("   ⏎ find · esc cancel")}`;
      return aside("  j k scroll · ^D ^U half · gg top · G bottom · / search · y copy · esc input");
    }
    const hint = editor.value.includes("\n")
      ? "⏎ send · ⌥⏎ newline · ^C clear · ^S settings"
      : "⏎ send · ⌥⏎ newline · esc/^G scroll · ^S settings · /help · /exit";
    return aside(`  ${hint}`);
  }

  /** The settings panel, drawn over the transcript. */
  function panelLines(width) {
    const rows = [aside(`  ${glyph.rule} settings ${glyph.rule.repeat(Math.max(2, width - 16))}`)];
    panel.rows.forEach((row, index) => {
      const selected = index === panel.index;
      const marker = selected ? ui.violet("›") : " ";
      const value = selected && panel.editing ? `${panel.buffer}${ui.violet("▏")}` : row.value;
      const left = `  ${marker} ${selected ? ui.bold(row.label) : row.label}`;
      const pad = Math.max(1, 22 - stripAnsi(left).length);
      rows.push(`${left}${" ".repeat(pad)}${value}${selected ? aside(`   ${row.hint}`) : ""}`);
    });
    return rows;
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
    if (uiMode === "settings") {
      const rows = panelLines(width);
      for (let index = 0; index < viewport; index += 1) lines.push(fit(rows[index] ?? "", width));
    } else {
      for (let index = 0; index < viewport; index += 1) {
        lines.push(visible[index] === undefined ? "" : fit(`  ${visible[index]}`, width));
      }
    }
    if (uiMode !== "settings" && scrollOffset > 0) {
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

    if (uiMode === "input") {
      const cursorRowOnScreen = lines.length - 2 - box.rows.length + box.cursorRow;
      screen.draw(lines, { row: cursorRowOnScreen, column: 4 + box.cursorColumn });
    } else {
      screen.draw(lines, null);
    }
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
  let onEscape = null;

  return {
    fullScreen: true,
    open() {
      screen.open();
      readlineBase.emitKeypressEvents(input);
      if (input.isTTY) input.setRawMode(true);
      output.on("resize", onResize);
      // readline never reports a lone Escape: it holds the byte back and folds
      // it into the next key as Alt+key. A terminal sends a bare ESC as its own
      // read, so watching the raw stream is the only way to see the keypress.
      onEscape = (chunk) => {
        if (closed || String(chunk) !== "\x1b") return;
        if (uiMode === "settings") { uiMode = "input"; return render(); }
        if (uiMode === "scroll") {
          if (searching) { searching = false; searchQuery = ""; return render(); }
          uiMode = "input"; vimPending = "";
          return render();
        }
        if (!editor.value) { uiMode = "scroll"; vimPending = ""; render(); }
      };
      input.on("data", onEscape);
      onKey = (sequence, info = {}) => {
        if (closed) return;
        if (notice) { notice = ""; }

        // Settings owns every key while it is open.
        if (uiMode === "settings") {
          const next = settingsKey(info.name, { ...panel, sequence, ctrl: info.ctrl, meta: info.meta });
          panel = { rows: next.rows, index: next.index, editing: next.editing, buffer: next.buffer };
          if (next.action === "close") uiMode = "input";
          if (next.action === "apply" && next.value) {
            const applied = onSetting?.(next.key, next.value);
            if (applied?.error) notice = `${glyph.err} ${applied.error}`;
            panel.rows = settingsModel({ ...context, verbose });
          }
          return render();
        }

        // Scrollback navigation, including an incremental search prompt.
        if (uiMode === "scroll") {
          const height = Math.max(3, screen.size().rows - 8);
          if (searching) {
            if (info.name === "escape") { searching = false; searchQuery = ""; return render(); }
            if (info.name === "return") {
              const hit = searchTranscript(transcript, searchQuery, { strip: stripAnsi });
              searching = false;
              lastSearch = searchQuery;
              searchQuery = "";
              if (hit) scrollOffset = Math.min(hit.offset, Math.max(0, transcript.length - height));
              else notice = `no match for ${lastSearch}`;
              return render();
            }
            if (info.name === "backspace") { searchQuery = searchQuery.slice(0, -1); return render(); }
            if (sequence && !info.ctrl && !info.meta) { searchQuery += sequence; return render(); }
            return render();
          }
          if (info.name === "escape" || info.name === "i") { uiMode = "input"; vimPending = ""; return render(); }
          if (info.name === "slash" || sequence === "/") { searching = true; searchQuery = ""; return render(); }
          if (info.name === "n" && lastSearch) {
            const hit = searchTranscript(transcript, lastSearch, { from: transcript.length - scrollOffset, strip: stripAnsi });
            if (hit) scrollOffset = Math.min(hit.offset, Math.max(0, transcript.length - height));
            return render();
          }
          if (sequence === "y" || info.name === "y") {
            // Copy what is on screen, which is what the reader can see and meant.
            const top = Math.max(0, transcript.length - height - scrollOffset);
            const text = transcript.slice(top, top + height).map(stripAnsi).join("\n").trim();
            copyText(text, { output }).then((result) => {
              notice = result.confirmed
                ? `${glyph.ok} ${result.note} (${result.routes.join(", ")})`
                : `${glyph.ok} ${result.note} ${result.backup}`;
              render();
            }).catch((error) => { notice = `${glyph.err} copy failed: ${error.message}`; render(); });
            return render();
          }
          const moved = scrollKey(sequence === "G" ? "G" : info.name || sequence, {
            offset: scrollOffset, total: transcript.length, height, ctrl: info.ctrl, pending: vimPending,
          });
          scrollOffset = moved.offset;
          vimPending = moved.pending;
          return render();
        }

        // Input mode.
        if (info.ctrl && info.name === "s") {
          panel = { rows: settingsModel({ ...context, verbose }), index: 0, editing: false, buffer: "" };
          uiMode = "settings";
          return render();
        }
        if ((info.ctrl && info.name === "g") || (info.name === "escape" && !editor.value)) {
          uiMode = "scroll"; vimPending = ""; return render();
        }
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
        if (action === "scroll-up") { uiMode = "scroll"; scrollOffset = Math.min(scrollOffset + 5, Math.max(0, transcript.length - 1)); return render(); }
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
      if (onEscape) input.off("data", onEscape);
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
    /** The loop supplies this so the panel can apply a change and report a
     *  rejection ({error}) without the console knowing how config works. */
    onSettingChange(handler) { onSetting = handler; },
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
