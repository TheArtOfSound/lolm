// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Copy to the clipboard the terminal is actually attached to.
 *
 * OSC 52 asks the terminal emulator to set the system clipboard, which is the
 * only route that works through SSH and inside a container — the machine
 * running LOLM may have no clipboard of its own. The catch is that it is
 * fire-and-forget: the terminal never answers, and a multiplexer will swallow
 * the sequence unless it is wrapped for passthrough. So every copy is also
 * written to a backup file whose path is reported, and the result says plainly
 * which routes were used and whether delivery could be confirmed.
 */
import { mkdir, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";

const OSC52_LIMIT = 74_994; // what a conservative terminal will accept in one go

function tmuxWrap(sequence) {
  // tmux only forwards a DCS-wrapped escape, and only with allow-passthrough on.
  return `\x1bPtmux;${sequence.replace(/\x1b/g, "\x1b\x1b")}\x1b\\`;
}

function screenWrap(sequence) {
  // GNU screen caps a DCS string, so the payload is split across chunks.
  const chunks = sequence.match(/.{1,480}/g) || [sequence];
  return chunks.map((chunk) => `\x1bP${chunk}\x1b\\`).join("");
}

export function osc52(text, { multiplexer = "" } = {}) {
  const payload = Buffer.from(String(text), "utf8").toString("base64");
  const sequence = `\x1b]52;c;${payload}\x07`;
  if (multiplexer === "tmux") return tmuxWrap(sequence);
  if (multiplexer === "screen") return screenWrap(sequence);
  return sequence;
}

/** Is tmux configured to let an inner program talk to the outer terminal? */
async function tmuxPassthrough() {
  if (!process.env.TMUX) return false;
  return new Promise((resolvePromise) => {
    const child = spawn("tmux", ["show", "-gv", "allow-passthrough"], { stdio: ["ignore", "pipe", "ignore"] });
    let out = "";
    child.stdout.on("data", (chunk) => { out += chunk; });
    child.on("close", () => resolvePromise(/^(on|all)\s*$/i.test(out)));
    child.on("error", () => resolvePromise(false));
  });
}

/** A native clipboard, when LOLM is running on the same machine as the display. */
function nativeCopy(text) {
  const candidates = process.platform === "darwin"
    ? [["pbcopy", []]]
    : process.platform === "win32"
      ? [["clip", []]]
      : [["wl-copy", []], ["xclip", ["-selection", "clipboard"]], ["xsel", ["--clipboard", "--input"]]];
  return new Promise((resolvePromise) => {
    const tryNext = (index) => {
      if (index >= candidates.length) return resolvePromise("");
      const [command, args] = candidates[index];
      const child = spawn(command, args, { stdio: ["pipe", "ignore", "ignore"] });
      child.on("error", () => tryNext(index + 1));
      child.on("close", (code) => (code === 0 ? resolvePromise(command) : tryNext(index + 1)));
      child.stdin.end(String(text));
    };
    tryNext(0);
  });
}

export function backupPath() {
  return process.env.LOLM_COPY_FILE || join(homedir(), ".lolm", "clipboard.txt");
}

/**
 * Copy text by every route available, and report honestly.
 * @returns {{routes: string[], confirmed: boolean, backup: string, note: string}}
 */
export async function copyText(text, { output = process.stdout, env = process.env } = {}) {
  const value = String(text ?? "");
  const routes = [];
  let confirmed = false;

  // A local clipboard tool is the only route that can actually be confirmed.
  const remote = Boolean(env.SSH_CONNECTION || env.SSH_TTY);
  if (!remote) {
    const native = await nativeCopy(value).catch(() => "");
    if (native) { routes.push(native); confirmed = true; }
  }

  if (!confirmed && env.LOLM_CLIPBOARD_NO_OSC52 !== "1") {
    const multiplexer = env.TMUX ? "tmux" : /screen/.test(env.TERM || "") ? "screen" : "";
    const passthrough = multiplexer === "tmux" ? await tmuxPassthrough() : true;
    if (multiplexer === "tmux" && !passthrough) {
      // Say why rather than emit a sequence tmux is going to eat.
      routes.push("tmux buffer");
      await new Promise((resolvePromise) => {
        const child = spawn("tmux", ["load-buffer", "-"], { stdio: ["pipe", "ignore", "ignore"] });
        child.on("close", resolvePromise);
        child.on("error", resolvePromise);
        child.stdin.end(value);
      });
    } else if (Buffer.byteLength(value, "utf8") <= OSC52_LIMIT) {
      output.write(osc52(value, { multiplexer }));
      routes.push(multiplexer ? `OSC 52 via ${multiplexer}` : "OSC 52");
    }
  }

  const backup = backupPath();
  await mkdir(join(backup, ".."), { recursive: true, mode: 0o700 }).catch(() => {});
  await writeFile(backup, value, { mode: 0o600 }).catch(() => {});

  const note = confirmed
    ? "Copied."
    : routes.length
      ? "Copy sent. The terminal cannot confirm it, so a copy is also saved below."
      : "No clipboard route was available; the text is saved below.";
  return { routes, confirmed, backup, note };
}
