// Copyright (c) 2026 Qira LLC. All rights reserved.
/** Canonical artifact validation and all-or-nothing local installation. */
import { chmod, lstat, mkdir, mkdtemp, open, readFile, rename, rm } from "node:fs/promises";
import { basename, dirname, resolve } from "node:path";
import { createHash } from "node:crypto";
import { safeDestination } from "./paths.mjs";
import { pyStyleDumps } from "./receipt.mjs";

const MAX_FILES = 100;
const MAX_FILE_BYTES = 20 * 1024 * 1024;
const MAX_TOTAL_BYTES = 50 * 1024 * 1024;

function fileCore(file) {
  return {
    path: file.path,
    type: file.type,
    size: file.size,
    sha256: file.sha256,
    executable: file.executable === true,
  };
}

export function manifestSha256(manifest) {
  const core = {
    schema: manifest?.schema,
    run_id: manifest?.run_id,
    artifact_id: manifest?.artifact_id,
    complete: manifest?.complete === true,
    files: (manifest?.files || []).map(fileCore),
    total_bytes: (manifest?.files || []).reduce((sum, file) => sum + Number(file.size || 0), 0),
  };
  return createHash("sha256").update(pyStyleDumps(core), "utf8").digest("hex");
}

function contentBytes(file) {
  if (file.encoding === "base64" && typeof file.content_base64 === "string") {
    return Buffer.from(file.content_base64, "base64");
  }
  if ((file.encoding === "utf-8" || file.encoding === "utf8") && typeof file.content === "string") {
    return Buffer.from(file.content, "utf8");
  }
  throw new Error(`artifact body missing for ${file.path}`);
}

export function validateManifest(manifest) {
  if (!manifest || manifest.schema !== "lolm.artifact.manifest.v1") {
    throw new Error("unsupported artifact manifest schema");
  }
  if (typeof manifest.run_id !== "string" || !manifest.run_id) throw new Error("manifest run_id missing");
  if (typeof manifest.artifact_id !== "string" || !manifest.artifact_id) throw new Error("manifest artifact_id missing");
  if (manifest.complete !== true) throw new Error("artifact manifest is incomplete");
  if (!Array.isArray(manifest.files) || manifest.files.length > MAX_FILES) {
    throw new Error(`artifact file count exceeds ${MAX_FILES}`);
  }
  const exact = new Set();
  const folded = new Set();
  const filePaths = new Set();
  let total = 0;
  for (const file of manifest.files) {
    if (!file || file.type !== "file") throw new Error("only regular file artifacts are supported");
    safeDestination("/artifact-root", file.path);
    const normalized = String(file.path).replace(/\\/g, "/").normalize("NFC");
    const lower = normalized.toLocaleLowerCase("en-US");
    if (exact.has(normalized) || folded.has(lower)) throw new Error(`duplicate or case collision: ${file.path}`);
    exact.add(normalized); folded.add(lower); filePaths.add(lower);
    const size = Number(file.size);
    if (!Number.isSafeInteger(size) || size < 0 || size > MAX_FILE_BYTES) {
      throw new Error(`invalid artifact size for ${file.path}`);
    }
    if (!/^[0-9a-f]{64}$/.test(String(file.sha256 || ""))) throw new Error(`invalid sha256 for ${file.path}`);
    if (file.content_omitted) throw new Error(`artifact body omitted for ${file.path}`);
    const bytes = contentBytes(file);
    const bodySha = createHash("sha256").update(bytes).digest("hex");
    if (bytes.length !== size || bodySha !== file.sha256) {
      throw new Error(`artifact content hash mismatch: ${file.path}`);
    }
    total += size;
    if (total > MAX_TOTAL_BYTES) throw new Error("artifact total size limit exceeded");
  }
  for (const path of exact) {
    const parts = path.toLocaleLowerCase("en-US").split("/");
    for (let i = 1; i < parts.length; i++) {
      if (filePaths.has(parts.slice(0, i).join("/"))) throw new Error(`file/directory collision: ${path}`);
    }
  }
  const expected = manifestSha256(manifest);
  if (manifest.manifest_sha256 !== expected) throw new Error("artifact manifest hash mismatch");
  return { files: manifest.files.length, total_bytes: total, manifest_sha256: expected };
}

async function mustNotExist(path) {
  try {
    await lstat(path);
    throw new Error(`destination already exists: ${path}`);
  } catch (error) {
    if (error?.code === "ENOENT") return;
    throw error;
  }
}

async function verifyTree(root, files) {
  const results = [];
  for (const file of files) {
    const path = safeDestination(root, file.path);
    const stat = await lstat(path);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`non-regular saved artifact: ${file.path}`);
    const bytes = await readFile(path);
    const sha256 = createHash("sha256").update(bytes).digest("hex");
    if (bytes.length !== file.size || sha256 !== file.sha256) {
      throw new Error(`saved artifact hash mismatch: ${file.path}`);
    }
    results.push({ path: file.path, size: bytes.length, sha256 });
  }
  return results;
}

export async function installVerifiedArtifacts(destination, manifest) {
  const validation = validateManifest(manifest);
  const dest = resolve(String(destination));
  await mustNotExist(dest);
  const parent = dirname(dest);
  await mkdir(parent, { recursive: true, mode: 0o700 });
  const staging = await mkdtemp(resolve(parent, `.${basename(dest)}.staging-`));
  await chmod(staging, 0o700);
  let committed = false;
  try {
    for (const file of manifest.files) {
      const bytes = contentBytes(file);
      const sha256 = createHash("sha256").update(bytes).digest("hex");
      if (bytes.length !== file.size || sha256 !== file.sha256) {
        throw new Error(`artifact content hash mismatch: ${file.path}`);
      }
      const path = safeDestination(staging, file.path);
      await mkdir(dirname(path), { recursive: true, mode: 0o700 });
      const handle = await open(path, "wx", file.executable ? 0o700 : 0o600);
      try {
        await handle.writeFile(bytes);
        await handle.sync();
      } finally {
        await handle.close();
      }
      await chmod(path, file.executable ? 0o755 : 0o644);
    }
    await verifyTree(staging, manifest.files);
    await mustNotExist(dest);
    await rename(staging, dest);
    committed = true;
    const files = await verifyTree(dest, manifest.files);
    return {
      requested: true,
      committed: true,
      verified: true,
      destination: dest,
      manifest_sha256: validation.manifest_sha256,
      files,
    };
  } finally {
    if (!committed) await rm(staging, { recursive: true, force: true });
  }
}

export async function installVerifiedFile(destination, content, expectedSha256) {
  const dest = resolve(String(destination));
  const bytes = Buffer.isBuffer(content) ? content : Buffer.from(String(content), "utf8");
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  if (!/^[0-9a-f]{64}$/.test(String(expectedSha256 || "")) || sha256 !== expectedSha256) {
    throw new Error("verified file hash mismatch");
  }
  await mustNotExist(dest);
  const parent = dirname(dest);
  await mkdir(parent, { recursive: true, mode: 0o700 });
  const staging = await mkdtemp(resolve(parent, `.${basename(dest)}.staging-`));
  const stagedFile = resolve(staging, "payload");
  let committed = false;
  try {
    const handle = await open(stagedFile, "wx", 0o600);
    try {
      await handle.writeFile(bytes);
      await handle.sync();
    } finally {
      await handle.close();
    }
    const check = await readFile(stagedFile);
    if (createHash("sha256").update(check).digest("hex") !== expectedSha256) {
      throw new Error("staged file hash mismatch");
    }
    await mustNotExist(dest);
    await rename(stagedFile, dest);
    committed = true;
    const final = await readFile(dest);
    if (createHash("sha256").update(final).digest("hex") !== expectedSha256) {
      throw new Error("committed file hash mismatch");
    }
    return { committed: true, verified: true, destination: dest, size: final.length, sha256 };
  } finally {
    await rm(staging, { recursive: true, force: true });
    if (!committed) {
      // destination is never created before the atomic rename.
    }
  }
}
