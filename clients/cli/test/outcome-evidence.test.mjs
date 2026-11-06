// SPDX-License-Identifier: AGPL-3.0-or-later
import test from 'node:test';
import assert from 'node:assert/strict';
import { classifyOutcomeEvidence, createOutcomeEvidence, hasCodeAcceptanceEvidence } from '../lib/runtime/outcome-evidence.mjs';

const ok = { exit_code: 0, timed_out: false };

test('records real test exits but not setup or inspection commands', () => {
  for (const cmd of ['npm test', 'npm run test', 'node --test', 'python3 -m pytest', 'pytest', 'cargo test', 'go test ./...']) {
    assert.equal(classifyOutcomeEvidence(cmd, ok), 'test_passed', cmd);
  }
  for (const cmd of ['echo ok', 'ls', 'git status', 'python3 --version', 'npm install', 'curl example.com']) {
    assert.equal(classifyOutcomeEvidence(cmd, ok), 'command_succeeded', cmd);
  }
});

test('separates lint/build evidence from tests', () => {
  for (const cmd of ['npm run build', 'npm run lint', 'npm run typecheck', 'git diff --check', 'npx tsc --noEmit']) {
    assert.equal(classifyOutcomeEvidence(cmd, ok), 'structural_check_passed', cmd);
  }
});

test('does not accept chained, masked, or no-op shell commands as tests', () => {
  for (const cmd of ['npm test || true', 'npm test && echo passed', 'npm test; echo passed', 'npm test | cat', 'npm test -- --help', 'npm test > results.log']) {
    assert.equal(classifyOutcomeEvidence(cmd, ok), 'command_succeeded', cmd);
  }
});

test('does not count failed, timed out, dry-run, or missing exits', () => {
  assert.equal(classifyOutcomeEvidence('npm test', { exit_code: 1 }), 'command_failed');
  assert.equal(classifyOutcomeEvidence('npm test', { exit_code: 0, timed_out: true }), 'unknown');
  assert.equal(classifyOutcomeEvidence('npm test', { exit_code: 0, dry_run: true }), 'not_executed');
  assert.equal(classifyOutcomeEvidence('npm test', {}), 'unknown');
});

test('aggregates only non-sensitive counts, never command strings', () => {
  const record = createOutcomeEvidence();
  record.observe('npm test', ok);
  record.observe('echo secret-value', ok);
  record.observe('npm test', { exit_code: 9 });
  const s = record.snapshot();
  assert.equal(s.test_passed, 1);
  assert.equal(s.command_succeeded, 1);
  assert.equal(s.command_failed, 1);
  assert.equal(record.testPassed, true);
  assert.equal(JSON.stringify(s).includes('secret-value'), false);
});

test('strict acceptance requires a passed test when files changed', () => {
  assert.equal(hasCodeAcceptanceEvidence({changes: 2, priorVerified: true, testPassed: false}), false);
  assert.equal(hasCodeAcceptanceEvidence({changes: 2, priorVerified: false, testPassed: true}), true);
  assert.equal(hasCodeAcceptanceEvidence({changes: 0, priorVerified: true, testPassed: false}), true);
});
