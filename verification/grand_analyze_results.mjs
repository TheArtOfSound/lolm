import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { basename, join, resolve } from "node:path";

const inputRoot = resolve(process.argv[2] || "grand-audit-download");
const outputRoot = resolve(process.argv[3] || "grand-audit-summary");
await mkdir(outputRoot, { recursive: true });

async function collect(root, suffix, out = []) {
  let entries = [];
  try { entries = await readdir(root, { withFileTypes: true }); } catch { return out; }
  for (const entry of entries) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) await collect(path, suffix, out);
    else if (entry.isFile() && entry.name.endsWith(suffix)) out.push(path);
  }
  return out;
}

const jsonlFiles = await collect(inputRoot, ".jsonl");
const records = [];
for (const path of jsonlFiles) {
  const raw = await readFile(path, "utf8");
  for (const line of raw.split(/\r?\n/)) {
    if (!line.trim()) continue;
    try {
      const value = JSON.parse(line);
      if (value?.schema === "lolm.grand.behavior.case.v1") records.push(value);
    } catch { /* raw logs may contain non-JSON lines */ }
  }
}

const textOf = (record) => JSON.stringify(record);
const median = (values) => {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
};

const categories = {};
for (const record of records) {
  const key = record.category || "unknown";
  const bucket = categories[key] ||= { cases: 0, scores: [], checks: 0, passed: 0, failed: 0, durations: [], shipped: 0, nonzero: 0, fatal: 0 };
  bucket.cases++;
  bucket.scores.push(Number(record.score || 0));
  bucket.checks += Number(record.passed || 0) + Number(record.failed || 0);
  bucket.passed += Number(record.passed || 0);
  bucket.failed += Number(record.failed || 0);
  bucket.durations.push(Number(record.duration_ms || 0));
  if (record.fatal) bucket.fatal++;
  for (const run of record.runs || []) {
    if (run.parsed?.shipped === true || run.parsed?.ok === true && run.parsed?.exit_code === 0) bucket.shipped++;
    if (run.process?.code !== 0) bucket.nonzero++;
  }
}
for (const bucket of Object.values(categories)) {
  bucket.average_score = bucket.scores.length ? bucket.scores.reduce((a, b) => a + b, 0) / bucket.scores.length : 0;
  bucket.pass_rate = bucket.checks ? bucket.passed / bucket.checks : 0;
  bucket.median_duration_ms = median(bucket.durations);
  delete bucket.scores;
  delete bucket.durations;
}

const signatures = [
  ["cross_language_contamination", /padding:\s*20px;[\s\S]{0,200}SyntaxError|html_as_python|forbid_\.py[^}]*false/i],
  ["repeated_unavailable_tool", /xdg_open_mentions=[3-9]|xdg_open_mentions=\d{2,}|no method available[\s\S]*no method available/i],
  ["missing_context_not_clarified", /clarifies_missing_context[^}]*"pass":false|followup_does_not_invent_context[^}]*"pass":false/i],
  ["unsupported_self_description", /no_false_fixed_model_identity[^}]*"pass":false/i],
  ["retrieval_diminishing_returns", /no_retrieval_loop[^}]*"pass":false|Found 0 useful notes[\s\S]*Found 0 useful notes/i],
  ["artifact_not_delivered", /expected_file_delivered[^}]*"pass":false|expected_extension_delivered[^}]*"pass":false/i],
  ["expected_success_failed", /expected_to_ship[^}]*"pass":false/i],
  ["false_success_or_exit_mismatch", /no_false_zero[^}]*"pass":false|expected_fail_safe[^}]*"pass":false/i],
  ["receipt_or_artifact_verification_failure", /shipped_receipt_verified[^}]*"pass":false|shipped_artifacts_verified[^}]*"pass":false/i],
  ["repetition_or_bloat", /bounded_repetition[^}]*"pass":false|concise[^}]*"pass":false/i],
  ["timeout_or_termination", /"timedOut":true|"code":124|terminated/i],
  ["service_or_rate_failure", /HTTP 429|rate limit|HTTP 5\d\d|ECONNRESET|fetch failed/i],
];

const rootCauses = {};
for (const [name, pattern] of signatures) {
  const affected = records.filter((record) => pattern.test(textOf(record)));
  rootCauses[name] = {
    cases: affected.length,
    fraction: records.length ? affected.length / records.length : 0,
    examples: affected.slice(0, 5).map((r) => ({ id: r.id, category: r.category, score: r.score })),
  };
}

const allChecks = records.flatMap((r) => (r.checks || r.evaluations?.flatMap((e) => e.checks || []) || []).map((c) => ({ ...c, case_id: r.id, category: r.category })));
const failedChecks = allChecks.filter((c) => c.pass === false);
const checkFailures = {};
for (const check of failedChecks) {
  const bucket = checkFailures[check.name] ||= { count: 0, examples: [] };
  bucket.count++;
  if (bucket.examples.length < 8) bucket.examples.push({ case_id: check.case_id, category: check.category, detail: String(check.detail || "").slice(0, 500) });
}

const lowest = [...records]
  .sort((a, b) => (a.score || 0) - (b.score || 0) || (b.failed || 0) - (a.failed || 0))
  .slice(0, 25)
  .map((r) => ({ id: r.id, category: r.category, score: r.score, failed: r.failed, duration_ms: r.duration_ms, prompt: r.prompt || r.steps?.map((s) => s.prompt).join(" -> ") }));

const totalChecks = records.reduce((n, r) => n + Number(r.passed || 0) + Number(r.failed || 0), 0);
const passedChecks = records.reduce((n, r) => n + Number(r.passed || 0), 0);
const summary = {
  schema: "lolm.grand.behavior.summary.v1",
  generated_at: new Date().toISOString(),
  input_files: jsonlFiles.map((p) => basename(p)),
  live_cases: records.length,
  live_checks: totalChecks,
  live_passed: passedChecks,
  live_failed: totalChecks - passedChecks,
  live_pass_rate: totalChecks ? passedChecks / totalChecks : 0,
  average_case_score: records.length ? records.reduce((n, r) => n + Number(r.score || 0), 0) / records.length : 0,
  median_case_duration_ms: median(records.map((r) => Number(r.duration_ms || 0))),
  categories,
  root_causes: rootCauses,
  failed_check_types: Object.fromEntries(Object.entries(checkFailures).sort((a, b) => b[1].count - a[1].count)),
  lowest_scoring_cases: lowest,
};

await writeFile(join(outputRoot, "grand-audit-summary.json"), JSON.stringify(summary, null, 2) + "\n", "utf8");
await writeFile(join(outputRoot, "grand-audit-records.json"), JSON.stringify(records, null, 2) + "\n", "utf8");

const lines = [];
lines.push("# LOLM Grand Behavioral Audit - Machine Summary", "");
lines.push(`Generated: ${summary.generated_at}`);
lines.push(`Live cases: ${summary.live_cases}`);
lines.push(`Live checks: ${summary.live_checks}`);
lines.push(`Pass rate: ${(summary.live_pass_rate * 100).toFixed(1)}%`);
lines.push(`Average case score: ${(summary.average_case_score * 100).toFixed(1)}%`);
lines.push(`Median case duration: ${(summary.median_case_duration_ms / 1000).toFixed(1)} seconds`, "");
lines.push("## Category results", "");
lines.push("| Category | Cases | Pass rate | Avg score | Median seconds | Shipped observations | Nonzero exits |");
lines.push("|---|---:|---:|---:|---:|---:|---:|");
for (const [name, bucket] of Object.entries(categories).sort((a, b) => a[1].pass_rate - b[1].pass_rate)) {
  lines.push(`| ${name} | ${bucket.cases} | ${(bucket.pass_rate * 100).toFixed(1)}% | ${(bucket.average_score * 100).toFixed(1)}% | ${(bucket.median_duration_ms / 1000).toFixed(1)} | ${bucket.shipped} | ${bucket.nonzero} |`);
}
lines.push("", "## Root-cause signatures", "");
for (const [name, value] of Object.entries(rootCauses).sort((a, b) => b[1].cases - a[1].cases)) {
  lines.push(`- **${name}**: ${value.cases} cases (${(value.fraction * 100).toFixed(1)}%)`);
}
lines.push("", "## Most frequent failed checks", "");
for (const [name, value] of Object.entries(summary.failed_check_types).slice(0, 20)) lines.push(`- **${name}**: ${value.count}`);
lines.push("", "## Lowest-scoring cases", "");
for (const item of lowest) lines.push(`- ${item.id} (${item.category}): ${(Number(item.score || 0) * 100).toFixed(1)}%, ${item.failed} failed checks`);
await writeFile(join(outputRoot, "grand-audit-summary.md"), lines.join("\n") + "\n", "utf8");
console.log(JSON.stringify({ ok: true, live_cases: summary.live_cases, live_checks: summary.live_checks, pass_rate: summary.live_pass_rate }));
