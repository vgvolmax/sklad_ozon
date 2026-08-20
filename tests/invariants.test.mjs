import test from 'node:test';
import assert from 'node:assert/strict';
import { loadClassicScripts } from './helpers/load-classic-script.mjs';

const api = loadClassicScripts(['app/assets/js/domain/invariants.js']);

test('assertNonNegative accepts zero and rejects negative values', () => {
  assert.equal(api.assertNonNegative(0), 0);
  assert.throws(() => api.assertNonNegative(-1), /NON_NEGATIVE_REQUIRED/);
});

test('assertRate accepts inclusive bounds and rejects out-of-range values', () => {
  assert.equal(api.assertRate(0), 0);
  assert.equal(api.assertRate(1), 1);
  assert.throws(() => api.assertRate(1.1), /RATE_OUT_OF_RANGE/);
});

test('assertNonEmpty accepts content and rejects empty values', () => {
  assert.equal(api.assertNonEmpty('sku'), 'sku');
  assert.throws(() => api.assertNonEmpty(''), /NON_EMPTY_REQUIRED/);
  assert.throws(() => api.assertNonEmpty('   '), /NON_EMPTY_REQUIRED/);
});
