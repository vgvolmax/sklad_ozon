import test from 'node:test';
import assert from 'node:assert/strict';
import { loadClassicScripts } from './helpers/load-classic-script.mjs';

const api = loadClassicScripts(['app/assets/js/domain/contracts.js']);

test('defines the canonical order lifecycle categories', () => {
  assert.deepEqual(
    Array.from(api.OrderLifecycle),
    ['fulfilled', 'in_progress', 'cancelled', 'unknown'],
  );
  assert.equal(Object.isFrozen(api.OrderLifecycle), true);
});

test('creates exact report metadata and import result shapes', () => {
  const meta = api.createReportMeta({ sourceName: 'orders.csv' });
  assert.deepEqual(Object.keys(meta), [
    'sourceName',
    'importedAt',
    'reportGeneratedAt',
    'periodStart',
    'periodEnd',
    'recommendationHorizonDays',
  ]);
  assert.equal(meta.sourceName, 'orders.csv');
  assert.equal(meta.periodStart, null);

  const result = api.createImportResult([], [], meta);
  assert.deepEqual(Object.keys(result), ['records', 'diagnostics', 'meta']);
  assert.equal(result.meta, meta);
});

test('keeps demand destination separate from fulfillment origin without PII', () => {
  const order = api.createOrderRecord({
    sku: '1',
    originClusterId: 'Kazan',
    destinationClusterId: 'Moscow',
    buyerName: 'Must not enter canonical state',
    buyerAddress: 'Must not enter canonical state',
  });

  assert.equal(order.originClusterId, 'Kazan');
  assert.equal(order.destinationClusterId, 'Moscow');
  assert.equal('buyerName' in order, false);
  assert.equal('buyerAddress' in order, false);
  assert.deepEqual(Object.keys(order), [
    'acceptedAt', 'plannedShipAt', 'handedToDeliveryAt', 'deliveredAt',
    'lifecycle', 'rawStatus', 'sku', 'article', 'name', 'quantity',
    'sellerPrice', 'originClusterId', 'destinationClusterId',
    'originWarehouse', 'volumetricWeightKg',
  ]);
});
