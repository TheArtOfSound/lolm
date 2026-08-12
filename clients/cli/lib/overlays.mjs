// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Scrollback navigation and the settings panel.
 *
 * Both are viewport concerns rather than editing concerns, so they live beside
 * the console instead of inside the input editor. Keeping them here also keeps
 * their key handling honest: each returns a plain description of what should
 * happen, and the console decides how to render it.
 */
import { PERMISSION_MODES } from "./runtime/permissions.mjs";

/** Vim-style movement over a transcript of `total` lines in a `height` viewport.
 *  `offset` counts lines scrolled back from the live tail. */
export function scrollKey(name, { offset, total, height, ctrl = false, pending = "" }) {
  const maxOffset = Math.max(0, total - height);
  const clamp = (value) => Math.max(0, Math.min(maxOffset, value));
  // `gg` needs two keystrokes, so a pending prefix is carried between calls.
  if (pending === "g") {
    if (name === "g") return { offset: maxOffset, pending: "" };
    return { offset, pending: "" };
  }
  switch (name) {
    case "j": case "down": return { offset: clamp(offset - 1), pending: "" };
    case "k": case "up": return { offset: clamp(offset + 1), pending: "" };
    case "d": return ctrl ? { offset: clamp(offset - Math.floor(height / 2)), pending: "" } : { offset, pending: "" };
    case "u": return ctrl ? { offset: clamp(offset + Math.floor(height / 2)), pending: "" } : { offset, pending: "" };
    case "f": case "pagedown": return { offset: clamp(offset - height), pending: "" };
    case "b": case "pageup": return { offset: clamp(offset + height), pending: "" };
    case "G": return { offset: 0, pending: "" };
    case "g": return { offset, pending: "g" };
    default: return { offset, pending: "" };
  }
}

/** Find the next line matching `query`, searching backwards through history. */
export function searchTranscript(transcript, query, { from = 0, strip = (value) => value } = {}) {
  const needle = String(query || "").toLowerCase();
  if (!needle) return null;
  for (let index = transcript.length - 1 - from; index >= 0; index -= 1) {
    if (strip(transcript[index]).toLowerCase().includes(needle)) {
      return { index, offset: transcript.length - 1 - index };
    }
  }
  return null;
}

/** The editable settings, described once so the panel and its keys agree. */
export function settingsModel(context) {
  return [
    { key: "provider", label: "Provider", value: context.provider, hint: "type a name, ⏎ to apply" , editable: true },
    { key: "model", label: "Model", value: context.model, hint: "type a name, ⏎ to apply", editable: true },
    { key: "mode", label: "Permissions", value: context.mode, choices: PERMISSION_MODES, hint: "← → to change" },
    { key: "cwd", label: "Workspace", value: context.workspace, hint: "type a path, ⏎ to apply", editable: true },
    { key: "verbose", label: "NFET detail", value: context.verbose ? "shown" : "hidden", choices: ["hidden", "shown"], hint: "← → to change" },
    { key: "nfet", label: "Controller", value: context.nfet, hint: "read-only" },
  ];
}

/**
 * Apply one key to the settings panel.
 * @returns {{rows, index, editing, buffer, action?, key?, value?}}
 */
export function settingsKey(name, { rows, index, editing, buffer, sequence = "", ctrl = false, meta = false }) {
  const row = rows[index];
  if (editing) {
    if (name === "escape") return { rows, index, editing: false, buffer: "" };
    if (name === "return") return { rows, index, editing: false, buffer: "", action: "apply", key: row.key, value: buffer.trim() };
    if (name === "backspace") return { rows, index, editing: true, buffer: buffer.slice(0, -1) };
    if (sequence && !ctrl && !meta) return { rows, index, editing: true, buffer: buffer + sequence };
    return { rows, index, editing: true, buffer };
  }
  if (name === "escape" || name === "q") return { rows, index, editing, buffer, action: "close" };
  if (name === "up" || name === "k") return { rows, index: Math.max(0, index - 1), editing, buffer };
  if (name === "down" || name === "j") return { rows, index: Math.min(rows.length - 1, index + 1), editing, buffer };
  if ((name === "left" || name === "right" || name === "h" || name === "l") && row?.choices) {
    const step = name === "left" || name === "h" ? -1 : 1;
    const at = row.choices.indexOf(row.value);
    const next = row.choices[(at + step + row.choices.length) % row.choices.length];
    return { rows, index, editing, buffer, action: "apply", key: row.key, value: next };
  }
  if (name === "return" && row?.editable) return { rows, index, editing: true, buffer: "" };
  return { rows, index, editing, buffer };
}
