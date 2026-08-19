function assertFinite(value: number, field: string): void {
  if (!Number.isFinite(value)) {
    throw new Error(`${field} must be finite`);
  }
}

export function assertNonNegative(value: number, field: string): number {
  assertFinite(value, field);
  if (value < 0) {
    throw new Error(`${field} must be non-negative`);
  }
  return value;
}

export function assertRate(value: number, field: string): number {
  assertFinite(value, field);
  if (value < 0 || value > 1) {
    throw new Error(`${field} must be between 0 and 1`);
  }
  return value;
}

export function assertNonEmpty(value: string, field: string): string {
  if (value.trim().length === 0) {
    throw new Error(`${field} must not be empty`);
  }
  return value;
}
