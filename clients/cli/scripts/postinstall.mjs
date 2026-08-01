#!/usr/bin/env node
// Copyright (c) 2026 Qira LLC. All rights reserved.
/** Friendly banner after `npm install -g lolm-cli` (npm is silent by default). */
import process from "node:process";

const lines = [
  "",
  "  ✓ lolm-cli installed — the command is:  lolm",
  "",
  "  Next:",
  '    lolm status',
  '    lolm code "write fizzbuzz to 20 in solution.py and run it" --save ./out',
  '    lolm build "a snake game" -o snake.html',
  "",
  "  Web app:  https://lolm.imagineqira.com/app.html",
  "  Help:     lolm --help",
  "",
];

// Skip noisy output in CI without terminating the host process.
if (process.env.CI !== "true" && process.env.LOLM_CLI_QUIET !== "1") {
  try {
    process.stderr.write(lines.join("\n"));
  } catch {
    /* ignore */
  }
}
