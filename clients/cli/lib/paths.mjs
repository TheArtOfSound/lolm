// Copyright (c) 2026 Qira LLC. All rights reserved.
/**
 * Path containment for --save / artifact install.
 * Server-supplied paths must never escape the chosen root directory.
 */
import { resolve, relative, isAbsolute, sep } from "node:path";

const WINDOWS_RESERVED = /^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$/i;

/**
 * Resolve `serverPath` under `rootDir`, rejecting absolute paths, `..` escapes,
 * null bytes, and empty segments that would leave the root.
 * @returns {string} absolute destination path
 */
export function safeDestination(rootDir, serverPath) {
  if (serverPath == null || String(serverPath).trim() === "") {
    throw new Error("empty artifact path rejected");
  }
  const raw = String(serverPath);
  if (raw.includes("\0")) throw new Error("NUL in artifact path rejected");
  // Normalize separators; reject absolute (posix or windows)
  const cleaned = raw.replace(/\\/g, "/");
  if (isAbsolute(cleaned) || /^[a-zA-Z]:[\\/]/.test(cleaned) || cleaned.startsWith("//")) {
    throw new Error(`absolute artifact path rejected: ${serverPath}`);
  }
  // Reject path traversal tokens even before resolve
  const parts = cleaned.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) {
    throw new Error(`unsafe artifact path segment: ${serverPath}`);
  }
  for (const part of parts) {
    if (part.length > 255 || part.endsWith(".") || part.endsWith(" ")
        || part.includes(":") || WINDOWS_RESERVED.test(part)) {
      throw new Error(`platform-unsafe artifact path rejected: ${serverPath}`);
    }
  }

  const root = resolve(String(rootDir));
  const dest = resolve(root, parts.join(sep));
  const rel = relative(root, dest);

  if (rel === ".." || rel.startsWith(`..${sep}`) || isAbsolute(rel)) {
    throw new Error(`artifact escaped output directory: ${serverPath}`);
  }
  // Final safety: dest must start with root + sep (or equal root — not a file)
  if (dest !== root && !dest.startsWith(root + sep)) {
    throw new Error(`artifact escaped output directory: ${serverPath}`);
  }
  return dest;
}

/** True if path is safe under root (non-throwing). */
export function isSafeUnder(rootDir, serverPath) {
  try {
    safeDestination(rootDir, serverPath);
    return true;
  } catch {
    return false;
  }
}

export function normalizeServerPath(p) {
  const raw = String(p || "").replace(/\\/g, "/").normalize("NFC");
  safeDestination("/artifact-root", raw);
  return raw;
}
