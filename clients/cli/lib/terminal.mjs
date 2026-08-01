// Copyright (c) 2026 Qira LLC. All rights reserved.
/** Strip terminal controls from untrusted human-readable output. */

const ESCAPE_SEQUENCE = /(?:\u001B\][\s\S]*?(?:\u0007|\u001B\\)|\u001B[P^_][\s\S]*?\u001B\\|\u001B\[[0-?]*[ -\/]*[@-~]|\u001B[@-_])/g;
const C0_C1 = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]/g;
const DANGEROUS_LAYOUT = /[\u000D\u202A-\u202E\u2066-\u2069]/g;

export function safeTerminal(value) {
  return String(value ?? "")
    .replace(ESCAPE_SEQUENCE, "")
    .replace(C0_C1, "")
    .replace(DANGEROUS_LAYOUT, "");
}
