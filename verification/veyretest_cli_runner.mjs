import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const sourcePath = resolve("verification/veyretest_cli.mjs");
const runtimePath = resolve("verification/.veyretest_cli_runtime.mjs");
let source = await readFile(sourcePath, "utf8");
source = source.replaceAll(
  '{ publicKeys: { "independent-test-key": publicKey } }',
  '{ publicKeys: { "independent-test-key": publicKey.export({ format: "pem", type: "spki" }) } }',
);
await writeFile(runtimePath, source, "utf8");
await import(runtimePath);
