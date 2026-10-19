#!/usr/bin/env node
// Run the established *.test.mjs suite without platform-specific shell globs.
// Plain 'node --test' also discovers legacy test/*.mjs scripts and expands scope.
import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const directory = join(root, "test");
const files = readdirSync(directory)
  .filter((name) => name.endsWith(".test.mjs"))
  .sort()
  .map((name) => join(directory, name));

if (files.length === 0) {
  console.error("No *.test.mjs test files found.");
  process.exit(1);
}
const result = spawnSync(process.execPath, ["--test", ...files], {
  cwd: root,
  stdio: "inherit",
  shell: false,
  env: process.env,
});
if (result.error) console.error(result.error.message);
process.exit(typeof result.status === "number" ? result.status : 1);
