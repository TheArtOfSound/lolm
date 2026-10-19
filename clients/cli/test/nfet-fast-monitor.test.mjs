// SPDX-License-Identifier: AGPL-3.0-or-later
import test from 'node:test';
import assert from 'node:assert/strict';
import { monitorTokenBudget } from '../lib/agent.mjs';

test('default NFET monitor budget remains unchanged', () => {
  const original = process.env.LOLM_NFET_FAST_MONITOR;
  try {
    delete process.env.LOLM_NFET_FAST_MONITOR;
    assert.equal(monitorTokenBudget('code', 'A complete implementation'), 128);
    assert.equal(monitorTokenBudget('ask', 'A question'), 128);
    assert.equal(monitorTokenBudget('document', 'A document'), 64);
  } finally {
    if (original === undefined) delete process.env.LOLM_NFET_FAST_MONITOR;
    else process.env.LOLM_NFET_FAST_MONITOR = original;
  }
});

test('fast monitor is explicitly opt-in and has bounded smaller windows', () => {
  const original = process.env.LOLM_NFET_FAST_MONITOR;
  try {
    process.env.LOLM_NFET_FAST_MONITOR = '1';
    assert.equal(monitorTokenBudget('code', 'A complete implementation'), 48);
    assert.equal(monitorTokenBudget('ask', 'A question'), 32);
    assert.equal(monitorTokenBudget('document', 'A document'), 32);
    assert.equal(monitorTokenBudget('ask', 'hello'), 32);
    process.env.LOLM_NFET_FAST_MONITOR = '0';
    assert.equal(monitorTokenBudget('code', 'A complete implementation'), 128);
  } finally {
    if (original === undefined) delete process.env.LOLM_NFET_FAST_MONITOR;
    else process.env.LOLM_NFET_FAST_MONITOR = original;
  }
});
