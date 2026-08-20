globalThis.SkladOzon = globalThis.SkladOzon || {};

(function (api) {
  api.assertNonNegative = function (value) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
      throw new Error('NON_NEGATIVE_REQUIRED');
    }
    return value;
  };

  api.assertRate = function (value) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1) {
      throw new Error('RATE_OUT_OF_RANGE');
    }
    return value;
  };

  api.assertNonEmpty = function (value) {
    if (typeof value !== 'string' || value.trim().length === 0) {
      throw new Error('NON_EMPTY_REQUIRED');
    }
    return value;
  };
})(globalThis.SkladOzon);
