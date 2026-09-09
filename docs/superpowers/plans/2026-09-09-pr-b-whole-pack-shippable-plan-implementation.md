# PR-B Whole-Pack ShippablePlan Implementation Plan

> Implement task-by-task with TDD. Read `AGENTS.md` and the canonical API-first shipment design first.

**Goal:** convert current Calculated Plan into one immutable all-cluster whole-pack operational plan using the already-resolved seller stock, supplier pack multiplicity and canonical unit volume.

## Global invariants

- Calculated Plan remains the analytical owner of target quantities.
- Existing seller-stock resolution is consumed, never reimplemented.
- Whole-pack plan is built **once for the full analysis across all clusters**.
- Later selected shipment clusters are filter-only and never trigger reallocation.
- Pack rounding is operational adjustment, not additional demand.
- Missing stock/multiplicity/volume remains causal incomplete evidence; never assume zero or one.
- Preserve immutable source/analysis identity and `analysis_as_of` downstream.

---

## Task 1 — define immutable contracts

Create frozen domain contracts such as:

```python
@dataclass(frozen=True, slots=True)
class ShippableLine:
    sku: str
    article: str
    destination_cluster_id: str
    analytical_qty: int
    pack_multiple: int
    resolved_seller_stock: int
    shippable_qty: int
    unit_volume_l: Decimal
    total_volume_l: Decimal
    placement_zone_kind: str
    placement_zones: tuple[str, ...]
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ShippablePlan:
    shippable_plan_id: str
    analysis_snapshot_id: str
    source_snapshot_id: str | None
    analysis_as_of: date
    lines: tuple[ShippableLine, ...]
    diagnostics: tuple
```

SKU is canonical identity; article is seller-facing label.

Tests reject bool-as-int, negative quantities, non-positive multiplicity and invalid volume.

---

## Task 2 — whole-pack rounding per cluster ceiling

For every positive Calculated Plan line, compute a pack-compatible operational target while preserving the analytical quantity as evidence.

Canonical behavior:

```text
analytical 17, pack 6 → operational target 18
analytical 18, pack 6 → 18
```

Do not round a zero analytical target into a positive shipment.

Record rounding delta/reason explicitly for explanation.

---

## Task 3 — enforce per-SKU seller-stock ceiling across all clusters

Allocation uses the seller stock already resolved by current analysis.

For each SKU:

```text
sum(shippable_qty across all destination clusters)
<= resolved seller stock
```

If seller stock is insufficient for all rounded targets, use the existing Calculated allocation order/priority semantics already produced upstream. Do not create a new shipment-time priority or rerun economics.

Every positive `shippable_qty` must satisfy:

```text
shippable_qty % pack_multiple == 0
```

If stock cannot fund the next whole pack, leave residual stock unallocated rather than emitting a partial pack.

---

## Task 4 — propagate unit volume and placement-zone evidence

For each line:

```text
total_volume_l = unit_volume_l * shippable_qty
```

Preserve exact normalized `placement_zones` and summary `placement_zone_kind`; do not reduce multi-zone evidence to a lossy flag.

Missing unit volume or zone evidence produces an operational compatibility diagnostic but does not mutate demand/Need.

---

## Task 5 — immutable identity and deterministic IDs

`ShippablePlan` must be deterministically tied to:

```text
analysis_snapshot_id
source_snapshot_id when API mode
analysis_as_of
scenario settings that own Calculated Plan
pack evidence version/content basis
```

Shipment requests later cannot provide another `as_of` or silently attach a plan to a different analysis/source snapshot.

Use stable deterministic ordering and ID/fingerprint rules; no Python object identity.

---

## Task 6 — prove shipment selection is filter-only

Add a pure helper/test showing:

```text
full ShippablePlan
→ select Moscow + Perm
→ exact original Moscow/Perm line quantities
```

No selected line can increase and unselected quantity is never redistributed.

This helper may live in PR-C if ownership is clearer there, but PR-B acceptance must already make the invariant impossible to reinterpret.

---

## Task 7 — regression gate

Tests must cover:
- rounding up to whole pack;
- zero remains zero;
- seller stock exact fit / remainder below one pack / scarcity across multiple clusters;
- conflicting/missing seller stock remains blocked by existing resolver semantics;
- missing/conflicting multiplicity never becomes `1`;
- unit-volume propagation;
- `placement_zones` preserved;
- all-cluster plan invariant to later shipment selection;
- `analysis_as_of` copied from parent analysis only.

Run:

```bash
python -m pytest tests/supply tests/decision -q
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
python -m pytest -q
```

Acceptance: one immutable all-cluster plan exists, every positive quantity is a complete pack, total allocation never exceeds existing resolved seller stock, and shipment scope cannot reallocate it.