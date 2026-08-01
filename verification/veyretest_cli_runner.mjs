import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const sourcePath = resolve("verification/veyretest_cli.mjs");
const runtimePath = resolve("verification/.veyretest_cli_runtime.mjs");
let source = await readFile(sourcePath, "utf8");
source = source.replaceAll(
  '{ publicKeys: { "independent-test-key": publicKey } }',
  '{ publicKeys: { "independent-test-key": publicKey.export({ format: "pem", type: "spki" }) } }',
);
source = source.replace(
  'for (let size = 1; size <= raw.length; size++) {\n    const chunks = [];\n    for (let i = 0; i < raw.length; i += size) chunks.push(raw.slice(i, i + size));',
  'const rawBytes = Buffer.from(raw);\n  for (let size = 1; size <= rawBytes.length; size++) {\n    const chunks = [];\n    for (let i = 0; i < rawBytes.length; i += size) chunks.push(rawBytes.subarray(i, i + size));',
);
await writeFile(runtimePath, source, "utf8");
await import(runtimePath);
