# PR-B Restrictions, Ozon Reference & Placement Candidate Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fully normalize the already-uploaded Ozon restrictions workbook, preserve explicit warehouse capacity semantics and Ozon recommendation/reference data, and build a pure placement candidate graph without assigning quantities.

**Architecture:** Keep the existing restrictions upload and existing `import_restrictions()` compatibility surface. Extend warehouse records with explicit capacity state/explanatory evidence, add a second pure importer for Ozon `SKU × destination` recommendations from the same workbook, derive conservative `SKU × origin` cluster capability, and create candidate edges for `SKU × selected origin × destination`. PR-B does not consume capacity, choose routes, or allocate quantities; PR-C owns all global optimization.

**Tech Stack:** Python 3, openpyxl, frozen dataclasses/enums, `Decimal`, pytest; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-global-placement-optimizer-amendment.md`

## Global Constraints

- `destination_cluster` remains demand geography; `origin_cluster` remains physical placement origin.
- The existing restrictions workbook remains one user upload; no second file is introduced.
- Numeric recommendation `0` is explicit zero; `-`/blank is missing and MUST NOT become zero.
- Recommendation horizon/date are parsed from source metadata when present and remain unknown when not proven.
- Restriction capacity state is exactly `FINITE / UNLIMITED / UNKNOWN`.
- `ALLOWED + FINITE(0)` is not a usable origin.
- Multiple warehouse limits inside one cluster are not summed.
- Secondary fields (`Зона размещения`, card errors, equipped, liquidity) are explanation only and never numeric optimizer weights.
- Historical Flow quantity/share never becomes a future allocation weight.
- LOCAL is candidate metadata, not a hard quantity-first rule.
- Non-local candidates require complete direct tariff evidence supplied to this layer as primitive route evidence.
- PR-B MUST NOT create `desired_qty`, consume origin capacity, run greedy sequential fill or run seller-stock scarcity.
- `backend/supply` must not import `backend.economics` at module import time.
- Use TDD and preserve all existing importer/placement regressions.

---

## File Structure

- Modify `backend/domain/contracts.py` — shared `RestrictionCapacityKind` and Ozon recommendation status enum if domain-level reuse is needed.
- Modify `backend/ingestion/restrictions.py` — explicit warehouse capacity state, explanatory fields, recommendation importer, workbook metadata parsing.
- Modify `backend/supply/contracts.py` — cluster capability and placement-candidate contracts.
- Modify `backend/supply/feasibility.py` — conservative cluster-capacity aggregation and usable-origin semantics.
- Create `backend/supply/candidates.py` — pure candidate-graph builder with no quantity allocation.
- Modify `backend/supply/__init__.py` — export new contracts/builders.
- Modify `tests/ingestion/test_restrictions.py` — real-format capacity, recommendation, metadata, dedupe/conflict and secondary-field tests.
- Modify `tests/supply/test_placement.py` — cluster capability aggregation and zero-capacity tests.
- Create `tests/supply/test_candidates.py` — selected-network candidate topology tests.
- Run `tests/supply/test_optimizer.py` unchanged as regression; PR-B must not alter legacy optimizer behavior.

---

### Task 1: Make warehouse capacity state explicit

**Files:**
- Modify: `backend/domain/contracts.py`
- Modify: `backend/ingestion/restrictions.py`
- Test: `tests/ingestion/test_restrictions.py`

**Interfaces:**

```python
class RestrictionCapacityKind(str, Enum):
    FINITE = "finite"
    UNLIMITED = "unlimited"
    UNKNOWN = "unknown"
```

Extend the existing record without removing current fields:

```python
@dataclass(frozen=True, slots=True)
class RestrictionRecord:
    sku: str
    warehouse: str
    state: RestrictionState
    reason: str
    source_value: str
    cluster: str = ""
    max_supply_qty: int | None = None
    capacity_kind: RestrictionCapacityKind = RestrictionCapacityKind.UNKNOWN
    placement_zone: str = ""
    card_error: str = ""
    warehouse_equipment: str = ""
    liquidity_status: str = ""
```

- [ ] **Step 1: Add failing parsing tests for finite, unlimited, zero and unknown**

Add a helper that uses the real Ozon header names:

```python
def _real_restriction_csv(maximum: str, allowed: str = "Да") -> bytes:
    return (
        "Артикул;SKU;Название товара;Рекомендуемая поставка на 56 дней;"
        "Кластер;Склад;Возможно ли поставить товар;Зона размещения;"
        "Ошибки в карточке товара;Склад оборудован под хранение товара;"
        "Статус ликвидности: Без продаж, ограничен;Максимальный размер поставки\n"
        f"34886;1832759439;Кран;319;Москва;W1;{allowed};Сортируемый товар;"
        f";Оборудован;-;{maximum}\n"
    ).encode("utf-8")
```

Assert:

```python
row = import_restrictions(_real_restriction_csv("120"), report_meta).records[0]
assert row.capacity_kind is RestrictionCapacityKind.FINITE
assert row.max_supply_qty == 120

row = import_restrictions(_real_restriction_csv("Без ограничений"), report_meta).records[0]
assert row.capacity_kind is RestrictionCapacityKind.UNLIMITED
assert row.max_supply_qty is None

row = import_restrictions(_real_restriction_csv("0"), report_meta).records[0]
assert row.capacity_kind is RestrictionCapacityKind.FINITE
assert row.max_supply_qty == 0

row = import_restrictions(_real_restriction_csv(""), report_meta).records[0]
assert row.capacity_kind is RestrictionCapacityKind.UNKNOWN
assert row.max_supply_qty is None
```

- [ ] **Step 2: Add malformed-capacity regression**

```python
result = import_restrictions(_real_restriction_csv("сто двадцать"), report_meta)
assert result.records == ()
assert any(x.code == "INVALID_MAX_SUPPLY_QTY" for x in result.diagnostics)
```

- [ ] **Step 3: Run and verify RED**

Run:

```bash
python -m pytest tests/ingestion/test_restrictions.py -q
```

Expected: new capacity-kind assertions fail because current `None` conflates unlimited and unknown.

- [ ] **Step 4: Implement strict capacity parsing**

Use normalized text and exactly these semantics:

```python
if maximum_text == "без ограничений":
    capacity_kind = RestrictionCapacityKind.UNLIMITED
    max_qty = None
elif maximum_text in {"", "-"}:
    capacity_kind = RestrictionCapacityKind.UNKNOWN
    max_qty = None
else:
    value = float(maximum)
    max_qty = int(value)
    if value != max_qty or max_qty < 0:
        raise ValueError
    capacity_kind = RestrictionCapacityKind.FINITE
```

For a prohibited row with `-`, keep UNKNOWN capacity; physical prohibition already makes it unusable. Do not invent finite zero for a dash.

- [ ] **Step 5: Preserve explanatory fields**

Map normalized source columns:

```python
placement_zone = normalize_text(row.get("зона размещения"))
card_error = normalize_text(row.get("ошибки в карточке товара"))
warehouse_equipment = normalize_text(row.get("склад оборудован под хранение товара"))
liquidity_status = normalize_text(row.get("статус ликвидности: без продаж, ограничен"))
```

Do not derive state from these fields.

- [ ] **Step 6: Run focused tests and commit**

```bash
python -m pytest tests/ingestion/test_restrictions.py -q
git add backend/domain/contracts.py backend/ingestion/restrictions.py tests/ingestion/test_restrictions.py
git commit -m "feat: preserve restriction capacity evidence"
```

---

### Task 2: Import Ozon recommendation/reference from the same workbook

**Files:**
- Modify: `backend/domain/contracts.py`
- Modify: `backend/ingestion/restrictions.py`
- Test: `tests/ingestion/test_restrictions.py`

**Interfaces:**

```python
class OzonRecommendationStatus(str, Enum):
    EXPLICIT = "explicit"
    MISSING = "missing"
    CONFLICTING = "conflicting"


@dataclass(frozen=True, slots=True)
class OzonSupplyRecommendation:
    sku: str
    destination_cluster_id: str
    recommended_qty: int | None
    status: OzonRecommendationStatus
    horizon_days: int | None
    report_generated_at: str | None
    source_rows: tuple[int, ...]
```

Public function:

```python
def import_ozon_supply_recommendations(
    data: bytes,
    report_context: ReportMeta,
) -> ImportResult[OzonSupplyRecommendation]:
```

- [ ] **Step 1: Add XLSX fixture helper with preamble**

Use openpyxl in the test to generate a workbook with:

```text
A1 = "Дата формирования отчета:"
B1 = "01.09.2026"
A2 = "Выбранные фильтры:"
B2 = "Москва, рекомендуемая поставка на 56 дней"
row 4 = real Ozon headers
```

Write at least two warehouse rows for the same `SKU × cluster`.

- [ ] **Step 2: Add explicit recommendation dedupe test**

Two warehouse rows with recommendation `319` must yield exactly one record:

```python
assert result.records == (
    OzonSupplyRecommendation(
        sku="1832759439",
        destination_cluster_id="Москва",
        recommended_qty=319,
        status=OzonRecommendationStatus.EXPLICIT,
        horizon_days=56,
        report_generated_at="2026-09-01",
        source_rows=(5, 6),
    ),
)
```

Use the actual normalized SKU identity convention already used by the application; if existing joins use seller article rather than numeric Ozon SKU, adapt the fixture so the new contract uses the same canonical identity. Do not create a parallel identity system.

- [ ] **Step 3: Add zero-vs-missing tests**

```python
# numeric zero
assert record.recommended_qty == 0
assert record.status is OzonRecommendationStatus.EXPLICIT

# dash/blank
assert record.recommended_qty is None
assert record.status is OzonRecommendationStatus.MISSING
```

- [ ] **Step 4: Add conflict test**

For the same `SKU × cluster`, rows `100` and `120` must produce one `CONFLICTING` record with `recommended_qty is None` and a diagnostic code:

```text
CONFLICTING_OZON_RECOMMENDATION
```

- [ ] **Step 5: Add metadata fallback tests**

When the date/horizon cannot be proven:

```python
assert record.report_generated_at is None
assert record.horizon_days is None
```

No hard-coded future 56-day fallback is allowed.

- [ ] **Step 6: Run and verify RED**

```bash
python -m pytest tests/ingestion/test_restrictions.py -q
```

Expected: recommendation contracts/functions absent.

- [ ] **Step 7: Implement workbook metadata parsing**

Inside `backend/ingestion/restrictions.py`, use `openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=True)` for XLSX. For each sheet, repair truncated dimensions exactly as existing `read_xlsx_tables()` does before scanning.

Parse:

```python
_DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")
_HORIZON_RE = re.compile(r"рекомендуемая поставка на\s+(\d+)\s+дн", re.I)
```

First prefer explicit workbook/header text. Unknown stays `None`.

- [ ] **Step 8: Deduplicate after parsing all sheets**

Group by canonical `(sku, destination_cluster_id)`. Preserve sorted unique source rows. Identical explicit values dedupe; explicit conflicts become `CONFLICTING`; only missing values become `MISSING`.

- [ ] **Step 9: Run tests and commit**

```bash
python -m pytest tests/ingestion/test_restrictions.py -q
git add backend/domain/contracts.py backend/ingestion/restrictions.py tests/ingestion/test_restrictions.py
git commit -m "feat: import Ozon supply recommendation reference"
```

---

### Task 3: Aggregate warehouse evidence into usable SKU × origin capability

**Files:**
- Modify: `backend/supply/contracts.py`
- Modify: `backend/supply/feasibility.py`
- Test: `tests/supply/test_placement.py`

**Interfaces:**

Extend/replace the current capability surface with:

```python
@dataclass(frozen=True, slots=True)
class SupplyFeasibility:
    sku: str
    origin_cluster_id: str
    allowed: bool
    capacity_kind: RestrictionCapacityKind
    max_supply_qty: int | None
    usable: bool
    supporting_warehouses: tuple[str, ...]
    reason_codes: tuple[str, ...]
```

- [ ] **Step 1: Add max-not-sum tests**

For two allowed finite warehouses 100 and 300:

```python
assert result.capacity_kind is RestrictionCapacityKind.FINITE
assert result.max_supply_qty == 300
assert result.usable is True
```

Explicitly assert the result is not 400.

- [ ] **Step 2: Add unlimited and unknown-alternative tests**

- finite 120 + UNKNOWN -> finite 120;
- finite 120 + UNLIMITED -> UNLIMITED;
- all UNKNOWN -> UNKNOWN, `usable=False`.

- [ ] **Step 3: Add ALLOWED + FINITE(0) test**

```python
assert result.allowed is True
assert result.capacity_kind is RestrictionCapacityKind.FINITE
assert result.max_supply_qty == 0
assert result.usable is False
assert "ZERO_PHYSICAL_CAPACITY" in result.reason_codes
```

- [ ] **Step 4: Run and verify RED**

```bash
python -m pytest tests/supply/test_placement.py -q
```

- [ ] **Step 5: Implement conservative aggregation**

Use exactly:

```python
known = [x for x in allowed_rows if x.capacity_kind in {
    RestrictionCapacityKind.FINITE,
    RestrictionCapacityKind.UNLIMITED,
}]

if not known:
    kind, qty = RestrictionCapacityKind.UNKNOWN, None
elif any(x.capacity_kind is RestrictionCapacityKind.UNLIMITED for x in known):
    kind, qty = RestrictionCapacityKind.UNLIMITED, None
else:
    kind = RestrictionCapacityKind.FINITE
    qty = max(x.max_supply_qty for x in known if x.max_supply_qty is not None)

usable = allowed and (
    kind is RestrictionCapacityKind.UNLIMITED
    or kind is RestrictionCapacityKind.FINITE and qty is not None and qty > 0
)
```

Preserve warehouse names/reasons for explanation.

- [ ] **Step 6: Run placement + legacy optimizer regression and commit**

```bash
python -m pytest tests/supply/test_placement.py tests/supply/test_optimizer.py -q
git add backend/supply/contracts.py backend/supply/feasibility.py tests/supply/test_placement.py
git commit -m "feat: derive usable cluster supply capability"
```

---

### Task 4: Define quantity-free placement candidate contracts

**Files:**
- Modify: `backend/supply/contracts.py`
- Create: `tests/supply/test_candidates.py`

**Interfaces:**

```python
class CoverageType(str, Enum):
    LOCAL = "local"
    ROUTE = "route"


@dataclass(frozen=True, slots=True)
class RoutePlanningEvidence:
    origin_cluster_id: str
    destination_cluster_id: str
    direct_tariff_complete: bool
    direct_route_fee: Decimal | None
    direct_tariff_reason_code: str | None
    route_cost_index: Decimal | None
    route_cost_index_coverage: Decimal | None
    route_cost_index_spread: Decimal | None
    route_confidence: RouteConfidence
    observed_flow_qty: int
    observed_flow_share: Decimal | None


@dataclass(frozen=True, slots=True)
class PlacementCandidate:
    sku: str
    origin_cluster_id: str
    destination_cluster_id: str
    coverage_type: CoverageType
    origin_capacity_kind: RestrictionCapacityKind
    origin_capacity_qty: int | None
    direct_route_fee: Decimal | None
    route_cost_index: Decimal | None
    route_cost_index_coverage: Decimal | None
    route_cost_index_spread: Decimal | None
    route_confidence: RouteConfidence
    observed_flow_qty: int
    observed_flow_share: Decimal | None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlacementCandidateGraph:
    sku: str
    selected_origins: tuple[str, ...]
    destination_cluster_ids: tuple[str, ...]
    candidates: tuple[PlacementCandidate, ...]
    blocked_pairs: tuple[tuple[str, str, tuple[str, ...]], ...]
```

There is deliberately no `desired_qty`, `allocated_qty`, seller stock or objective on these contracts.

- [ ] **Step 1: Add contract tests rejecting quantity fields by construction**

Instantiate a valid candidate and assert its public dataclass fields do not include:

```text
desired_qty
final_allocated_qty
seller_available_stock
```

- [ ] **Step 2: Add identity/capacity validation tests**

Reject blank IDs, LOCAL with differing origin/destination, ROUTE with identical origin/destination, and `FINITE(0)` candidates as usable candidate objects.

- [ ] **Step 3: Run and verify RED**

```bash
python -m pytest tests/supply/test_candidates.py -q
```

- [ ] **Step 4: Implement contracts and deterministic ordering**

Sort candidates by `(sku, destination_cluster_id, origin_cluster_id)` for stable wire/test behavior. Do not encode route preference in sort order.

- [ ] **Step 5: Run and commit**

```bash
python -m pytest tests/supply/test_candidates.py -q
git add backend/supply/contracts.py tests/supply/test_candidates.py
git commit -m "feat: define placement candidate graph contracts"
```

---

### Task 5: Build candidate topology without consuming capacity

**Files:**
- Create: `backend/supply/candidates.py`
- Modify: `backend/supply/__init__.py`
- Test: `tests/supply/test_candidates.py`

**Public interface:**

```python
def build_placement_candidate_graph(
    *,
    sku: str,
    destination_cluster_ids: tuple[str, ...],
    selected_origin_cluster_ids: tuple[str, ...],
    feasibility: tuple[SupplyFeasibility, ...],
    route_evidence: tuple[RoutePlanningEvidence, ...],
) -> PlacementCandidateGraph:
```

- [ ] **Step 1: Add selected-network filtering test**

Given feasible Москва/Питер but selected only Москва, no candidate may use Питер.

- [ ] **Step 2: Add local candidate test**

A usable selected origin equal to destination creates LOCAL candidate even when no historical Flow exists. Candidate creation itself does not consume any capacity.

- [ ] **Step 3: Add non-local direct-tariff gate test**

For Москва → Казань:

```python
RoutePlanningEvidence(
    direct_tariff_complete=False,
    direct_route_fee=None,
    direct_tariff_reason_code="MISSING_TARIFF",
    ...
)
```

must produce no usable candidate and a blocked pair reason containing `MISSING_TARIFF`.

- [ ] **Step 4: Add no-greedy-consumption regression**

With one origin capacity 100 and two destinations, both candidate edges must exist with the same origin-capacity evidence. PR-B must not reduce the second edge to zero because the first edge was iterated first.

- [ ] **Step 5: Add historical-share isolation test**

Changing observed Flow from 90% to 1% must not add/remove a candidate when restriction/tariff facts are unchanged.

- [ ] **Step 6: Run and verify RED**

```bash
python -m pytest tests/supply/test_candidates.py -q
```

- [ ] **Step 7: Implement the pure builder**

Build feasibility lookup by `(sku, origin)`, route-evidence lookup by `(origin, destination)`, iterate every destination against every selected origin, and:

- skip non-usable physical origins;
- create LOCAL candidate without requiring historical route evidence;
- require complete direct tariff evidence for ROUTE;
- copy capacity/evidence only;
- never decrement capacity or choose a quantity.

- [ ] **Step 8: Run PR-B suite**

```bash
python -m pytest \
  tests/ingestion/test_restrictions.py \
  tests/supply/test_placement.py \
  tests/supply/test_candidates.py \
  tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/supply/candidates.py backend/supply/__init__.py tests/supply/test_candidates.py
git commit -m "feat: build selected-network placement candidates"
```

---

## PR-B completion gate

Before opening PR-B, run:

```bash
python -m pytest -q
```

Then verify by search/review:

```text
- no PR-B production function creates desired route quantities;
- no LOCAL-first quantity assignment remains in new candidate path;
- no capacity is decremented inside candidate generation;
- recommendation dash/blank is never coerced to zero;
- secondary warehouse fields are preserved only as explanations;
- legacy import/optimizer behavior remains regression-green.
```
