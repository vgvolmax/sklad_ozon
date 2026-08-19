import { describe, expect, expectTypeOf, it } from 'vitest';
import { assertNonEmpty, assertNonNegative, assertRate } from '../../src/domain/invariants';
import type { OrderLifecycle, OrderRecord } from '../../src/domain/models';
import type { ImportResult } from '../../src/domain/result';

describe('runtime invariants', () => {
  it('rejects negative quantity', () => {
    expect(() => assertNonNegative(-1, 'quantity')).toThrow('quantity');
  });

  it('accepts non-negative finite values', () => {
    expect(assertNonNegative(0, 'quantity')).toBe(0);
    expect(assertNonNegative(2.5, 'quantity')).toBe(2.5);
  });

  it('accepts decimal rates from zero through one', () => {
    expect(assertRate(0.25, 'commissionRate')).toBe(0.25);
    expect(assertRate(0, 'commissionRate')).toBe(0);
    expect(assertRate(1, 'commissionRate')).toBe(1);
  });

  it('rejects rates outside the inclusive unit interval', () => {
    expect(() => assertRate(-0.01, 'commissionRate')).toThrow('commissionRate');
    expect(() => assertRate(1.01, 'commissionRate')).toThrow('commissionRate');
  });

  it('rejects empty and whitespace-only strings', () => {
    expect(() => assertNonEmpty('  ', 'sku')).toThrow('sku');
    expect(assertNonEmpty(' sku-1 ', 'sku')).toBe(' sku-1 ');
  });
});

it('exposes the canonical order and import contracts', () => {
  expectTypeOf<OrderLifecycle>().toEqualTypeOf<
    'fulfilled' | 'in_progress' | 'cancelled' | 'unknown'
  >();

  const order: OrderRecord = {
    acceptedAt: '2026-08-01T12:00:00Z',
    plannedShipAt: null,
    handedToDeliveryAt: null,
    deliveredAt: null,
    lifecycle: 'in_progress',
    rawStatus: 'Ожидает отгрузки',
    sku: '123',
    article: 'seller-123',
    name: 'Товар',
    quantity: 1,
    sellerPrice: 100,
    originClusterId: 'Казань',
    destinationClusterId: 'Москва',
    originWarehouse: null,
    volumetricWeightKg: null,
  };

  const result: ImportResult<OrderRecord> = {
    records: [order],
    diagnostics: [],
    meta: {
      sourceName: 'orders.csv',
      importedAt: '2026-08-19T12:00:00Z',
      reportGeneratedAt: null,
      periodStart: null,
      periodEnd: null,
      recommendationHorizonDays: null,
    },
  };

  expect(result.records).toEqual([order]);
});
