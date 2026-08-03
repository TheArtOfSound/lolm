#!/usr/bin/env python3
"""Apply the reviewed P1-A session binding corrections exactly once."""
from __future__ import annotations

from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def patch_core() -> None:
    path = Path("clients/cli/bin/lolm.mjs")
    text = path.read_text()
    if 'retry: [...COMMON, "yes", "id", "conversation"' in text:
        print("core already patched")
        return

    text = replace_once(
        text,
        '  inspect: [...COMMON, "id", "conversation"],\n  config: ["json", "help"],',
        '  inspect: [...COMMON, "id", "conversation"],\n'
        '  last: [...COMMON, "id", "conversation"],\n'
        '  retry: [...COMMON, "yes", "id", "conversation", "quiet", "idleTimeout", "save", "receipt", "maxSteps"],\n'
        '  resume: [...COMMON, "yes", "id", "conversation", "quiet", "idleTimeout", "save", "receipt", "maxSteps"],\n'
        '  config: ["json", "help"],',
        "core command flags",
    )

    session_pattern = re.compile(
        r'async function loadLatestSession\(\) \{.*?\n\}\n\n/\*\* Resolve bare follow-ups',
        re.S,
    )
    session_replacement = '''async function loadLatestSession(selector = "") {
  const { readdir, stat } = await import("node:fs/promises");
  const dir = sessionDir();
  let files = [];
  try {
    files = (await readdir(dir)).filter((f) => f.endsWith(".json"));
  } catch {
    return null;
  }
  if (!files.length) return null;
  const ranked = [];
  for (const f of files) {
    try {
      const st = await stat(join(dir, f));
      ranked.push({ f, mtime: st.mtimeMs });
    } catch { /* skip */ }
  }
  ranked.sort((a, b) => b.mtime - a.mtime);
  const wanted = String(selector || "").trim();
  for (const candidate of ranked) {
    try {
      const parsed = JSON.parse(await readFile(join(dir, candidate.f), "utf8"));
      if (!wanted) return parsed;
      const identities = [
        parsed.session_id,
        parsed.last_code_run_id,
        parsed.last_failed_run_id,
      ].filter(Boolean).map(String);
      if (identities.includes(wanted)) return parsed;
    } catch { /* skip malformed/disappeared session */ }
  }
  return null;
}

/** Resolve bare follow-ups'''
    text, count = session_pattern.subn(session_replacement, text, count=1)
    if count != 1:
        raise SystemExit(f"core session selector: expected one match, got {count}")

    text = replace_once(
        text,
        'async function cmdLast(flags) {\n  const p = await loadLatestSession();',
        'async function cmdLast(flags) {\n  const p = await loadLatestSession(flags.id || flags.conversation || "");',
        "cmdLast selector",
    )
    text = replace_once(
        text,
        'async function cmdRetry(args, flags) {\n  const p = await loadLatestSession();',
        'async function cmdRetry(args, flags) {\n  const p = await loadLatestSession(flags.id || flags.conversation || "");',
        "cmdRetry selector",
    )
    text = replace_once(
        text,
        'async function cmdResume(args, flags) {\n  // Force resume semantics with full package transport\n  const p = await loadLatestSession();',
        'async function cmdResume(args, flags) {\n  // Force resume semantics with full package transport\n  const p = await loadLatestSession(flags.id || flags.conversation || "");',
        "cmdResume selector",
    )
    text = replace_once(
        text,
        '      if (pkg?.resume_token) out(`${bold("token")}  ${String(pkg.resume_token).slice(0, 48)}`);',
        '      if (pkg?.resume_token) out(`${bold("token")}  ${dim("present")}`);',
        "resume token redaction",
    )
    text = replace_once(
        text,
        '  if (resolved.action === "clarify") {\n    if (JSON_MODE) return emit({ ok: false, ...resolved });',
        '  if (resolved.action === "clarify") {\n    if (JSON_MODE) { emit({ ok: false, ...resolved }); return 2; }',
        "retry clarify exit",
    )
    text = replace_once(
        text,
        '  if (!p?.last_code_run_id) {\n    if (JSON_MODE) return emit({ ok: false, error: "no_run" });',
        '  if (!p?.last_code_run_id) {\n    if (JSON_MODE) { emit({ ok: false, error: "no_run" }); return 2; }',
        "resume no-run exit",
    )
    path.write_text(text)


def patch_wrapper() -> None:
    path = Path("clients/cli/bin/lolm-delivery.mjs")
    text = path.read_text()
    if 'schema: "lolm.delivery.result.v2"' in text:
        print("wrapper already patched")
        return

    text = replace_once(
        text,
        '  const action = resolution.action;\n  const result = await runCore(["--json", action], { silent: true, env: actionEnvironment() });',
        '  const action = resolution.action;\n'
        '  const selector = resolution.record?.session_id || resolution.record?.run_id || resolution.value || "";\n'
        '  const coreArgs = ["--json", action, "--yes"];\n'
        '  if (selector) coreArgs.push("--conversation", selector);\n'
        '  for (const flag of ["--timeout", "--idle-timeout"]) {\n'
        '    const index = argv.indexOf(flag);\n'
        '    if (index >= 0 && argv[index + 1]) coreArgs.push(flag, argv[index + 1]);\n'
        '  }\n'
        '  const result = await runCore(coreArgs, { silent: true, env: actionEnvironment() });',
        "wrapper action selector",
    )
    text = replace_once(
        text,
        '  const result = await runCore(next);\n  const sealedReceipt = await readReceipt(receiptPath);\n  if (automaticReceiptDirectory) await rm(automaticReceiptDirectory, { recursive: true, force: true });\n  if (result.code !== 0) return result.code;\n  if (!kind || !deliveryDestination) return result.code;',
        '  const composeDeliveryJson = Boolean(jsonMode && command === "code" && kind && deliveryDestination);\n'
        '  const result = await runCore(next, { silent: composeDeliveryJson });\n'
        '  const sealedReceipt = await readReceipt(receiptPath);\n'
        '  if (automaticReceiptDirectory) await rm(automaticReceiptDirectory, { recursive: true, force: true });\n'
        '  const corePayload = composeDeliveryJson\n'
        '    ? (parseJsonOutput(result.stdout) || parseJsonOutput(result.stderr))\n'
        '    : null;\n'
        '  if (result.code !== 0) {\n'
        '    if (composeDeliveryJson) {\n'
        '      output(corePayload || { schema: "lolm.delivery.result.v2", ok: false, exit_code: result.code, error: "core_failed" });\n'
        '    }\n'
        '    return result.code;\n'
        '  }\n'
        '  if (!kind || !deliveryDestination) return result.code;',
        "wrapper JSON composition start",
    )
    text = replace_once(
        text,
        '  if (!delivered.length) {\n    process.stderr.write(\n      `LOLM did not deliver the requested ${kind || "artifact"}. ` +\n      `The run may have created only source code inside ${deliveryDestination}.\\n`,\n    );\n    return 1;\n  }',
        '  if (!delivered.length) {\n'
        '    const message = `LOLM did not deliver the requested ${kind || "artifact"}. ` +\n'
        '      `The run may have created only source code inside ${deliveryDestination}.`;\n'
        '    if (composeDeliveryJson) {\n'
        '      output({ schema: "lolm.delivery.result.v2", ok: false, exit_code: 1, core: corePayload, error: "requested_artifact_missing", message });\n'
        '    } else {\n'
        '      process.stderr.write(`${message}\\n`);\n'
        '    }\n'
        '    return 1;\n'
        '  }',
        "wrapper missing artifact JSON",
    )
    text = replace_once(
        text,
        '  process.stdout.write(`delivered ${saved.kind}\\n`);\n  for (const artifact of saved.artifacts.filter((item) => item.exists)) process.stdout.write(`saved     ${artifact.path}\\n`);\n  return 0;',
        '  if (composeDeliveryJson) {\n'
        '    output({\n'
        '      schema: "lolm.delivery.result.v2",\n'
        '      ok: true,\n'
        '      exit_code: 0,\n'
        '      core: corePayload,\n'
        '      delivery: recordSummary(saved, 1),\n'
        '    });\n'
        '    return 0;\n'
        '  }\n'
        '  process.stdout.write(`delivered ${saved.kind}\\n`);\n'
        '  for (const artifact of saved.artifacts.filter((item) => item.exists)) process.stdout.write(`saved     ${artifact.path}\\n`);\n'
        '  return 0;',
        "wrapper JSON composition finish",
    )
    path.write_text(text)


def patch_continuity_tests() -> None:
    path = Path("clients/cli/test/continuity.mjs")
    text = path.read_text()
    if "selects the exact core session" in text:
        print("continuity tests already patched")
        return
    text = replace_once(
        text,
        'const BIN = join(here, "..", "bin", "lolm-delivery.mjs");\n',
        'const BIN = join(here, "..", "bin", "lolm-delivery.mjs");\nconst CORE_BIN = join(here, "..", "bin", "lolm.mjs");\n',
        "core bin constant",
    )
    text = replace_once(
        text,
        '  assert.deepEqual(calls, [["--json", "retry"], ["--json", "resume"]]);',
        '  assert.deepEqual(calls, [\n'
        '    ["--json", "retry", "--yes", "--conversation", "sess_action"],\n'
        '    ["--json", "resume", "--yes", "--conversation", "sess_action"],\n'
        '  ]);',
        "fake action args",
    )
    insertion = r'''
test("core last selects the exact session and retry flags parse", async () => {
  const ctx = await isolated("core-session-selection");
  await mkdir(ctx.sessions, { recursive: true });
  await writeFile(join(ctx.sessions, "target.json"), JSON.stringify({
    session_id: "sess_target",
    last_code_run_id: "run_target",
    last_run_task: "target task",
    last_run_status: "terminated",
    last_checkpoint_id: "ckpt_target",
    workspace_snapshot: { "target.py": "print(1)" },
    updated_ts: 1,
  }));
  await new Promise((done) => setTimeout(done, 20));
  await writeFile(join(ctx.sessions, "decoy.json"), JSON.stringify({
    session_id: "sess_decoy",
    last_code_run_id: "run_decoy",
    last_run_task: "decoy task",
    last_run_status: "terminated",
    last_checkpoint_id: "ckpt_decoy",
    workspace_snapshot: { "decoy.py": "print(2)" },
    updated_ts: 2,
  }));
  const selected = await run(process.execPath, [
    CORE_BIN, "--json", "last", "--conversation", "sess_target",
  ], { env: ctx.env, timeout: 15_000 });
  const payload = JSON.parse(selected.stdout);
  assert.equal(payload.session_id, "sess_target");
  assert.equal(payload.last_code_run_id, "run_target");
  let retryFailure;
  try {
    await run(process.execPath, [
      CORE_BIN, "--json", "retry", "--yes", "--conversation", "missing_session",
    ], { env: ctx.env, timeout: 15_000 });
  } catch (error) {
    retryFailure = error;
  }
  assert.ok(retryFailure);
  assert.equal(retryFailure.code, 2);
  assert.doesNotMatch(retryFailure.stderr || "", /unknown flag/i);
  assert.equal(JSON.parse(retryFailure.stdout).action, "clarify");
});

'''
    anchor = 'test("artifact list, where, and inspect provide machine-readable local state", async () => {'
    text = replace_once(text, anchor, insertion + anchor, "continuity test insertion")
    path.write_text(text)


def patch_receipt_tests() -> None:
    path = Path("clients/cli/test/continuity_receipt.mjs")
    text = path.read_text()
    if "artifact code --json emits one composed document" in text:
        print("receipt tests already patched")
        return
    text = replace_once(
        text,
        "    `process.stdout.write('verdict   shipped\\\\nreceipt   ${receiptSha}  hash ok\\\\ntask      task_receipt_binding\\\\n');`,",
        "    `if (args.includes('--json')) process.stdout.write(JSON.stringify({schema:'lolm.cli.result.v2',ok:true,exit_code:0,shipped:true,receipt:{verdict:'shipped',receipt_sha:${JSON.stringify(receiptSha)}}}) + String.fromCharCode(10));`,\n"
        "    `else process.stdout.write('verdict   shipped\\\\nreceipt   ${receiptSha}  hash ok\\\\ntask      task_receipt_binding\\\\n');`,",
        "first fake core JSON output",
    )
    insertion = r'''
test("artifact code --json emits one composed document", async () => {
  const ctx = await context("composed-json");
  const receiptSha = "c".repeat(64);
  const manifestSha = "d".repeat(64);
  await writeFile(ctx.fakeCore, [
    `import { mkdir, writeFile } from 'node:fs/promises';`,
    `import { join } from 'node:path';`,
    `const args = process.argv.slice(2);`,
    `const value = (flag) => { const i = args.indexOf(flag); return i >= 0 ? args[i + 1] : ''; };`,
    `const save = value('--save'); const receipt = value('--receipt');`,
    `await mkdir(save, { recursive: true });`,
    `const nl = String.fromCharCode(10);`,
    `await writeFile(join(save, 'output.pdf'), Buffer.from('%PDF-1.4' + nl + 'json continuity' + nl + '%%EOF' + nl));`,
    `await writeFile(receipt, JSON.stringify({verdict:'shipped',receipt_sha:${JSON.stringify(receiptSha)},verification:{artifact_manifest_sha256:${JSON.stringify(manifestSha)}},files:['output.pdf']}));`,
    `process.stdout.write(JSON.stringify({schema:'lolm.cli.result.v2',ok:true,exit_code:0,shipped:true}) + nl);`,
  ].join("\n"));
  const env = {
    ...process.env,
    HOME: ctx.root,
    USERPROFILE: ctx.root,
    LOLM_CONTINUITY_LEDGER: ctx.ledger,
    LOLM_SESSION_DIR: ctx.sessions,
    LOLM_CORE_CLI: ctx.fakeCore,
    NO_COLOR: "1",
  };
  const result = await run(process.execPath, [
    BIN, "code", "Create a valid PDF report", "--json", "--base", "https://127.0.0.1.invalid",
  ], { env, timeout: 30_000 });
  assert.equal(result.stderr, "");
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.schema, "lolm.delivery.result.v2");
  assert.equal(payload.ok, true);
  assert.equal(payload.core.schema, "lolm.cli.result.v2");
  assert.equal(payload.delivery.receipt_sha, receiptSha);
  assert.equal(payload.delivery.manifest_sha, manifestSha);
  assert.equal(payload.delivery.fully_verified, true);
});

'''
    anchor = 'test("JSON-mode local failures emit one stdout document and no stderr payload", async () => {'
    text = replace_once(text, anchor, insertion + anchor, "receipt test insertion")
    path.write_text(text)


def main() -> None:
    patch_core()
    patch_wrapper()
    patch_continuity_tests()
    patch_receipt_tests()


if __name__ == "__main__":
    main()
