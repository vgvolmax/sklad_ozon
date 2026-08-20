globalThis.SkladOzon = globalThis.SkladOzon || {};

(function (api) {
  api.OrderLifecycle = Object.freeze([
    'fulfilled',
    'in_progress',
    'cancelled',
    'unknown',
  ]);

  api.createReportMeta = function (fields) {
    fields = fields || {};
    return {
      sourceName: fields.sourceName || '',
      importedAt: fields.importedAt || '',
      reportGeneratedAt: fields.reportGeneratedAt || null,
      periodStart: fields.periodStart || null,
      periodEnd: fields.periodEnd || null,
      recommendationHorizonDays: fields.recommendationHorizonDays ?? null,
    };
  };

  api.createOrderRecord = function (fields) {
    fields = fields || {};
    return {
      acceptedAt: fields.acceptedAt || '',
      plannedShipAt: fields.plannedShipAt || null,
      handedToDeliveryAt: fields.handedToDeliveryAt || null,
      deliveredAt: fields.deliveredAt || null,
      lifecycle: fields.lifecycle || 'unknown',
      rawStatus: fields.rawStatus || '',
      sku: fields.sku || '',
      article: fields.article || '',
      name: fields.name || '',
      quantity: fields.quantity ?? 0,
      sellerPrice: fields.sellerPrice ?? 0,
      originClusterId: fields.originClusterId || '',
      destinationClusterId: fields.destinationClusterId || '',
      originWarehouse: fields.originWarehouse || null,
      volumetricWeightKg: fields.volumetricWeightKg ?? null,
    };
  };

  api.createImportResult = function (records, diagnostics, meta) {
    return { records: records, diagnostics: diagnostics, meta: meta };
  };
})(globalThis.SkladOzon);
