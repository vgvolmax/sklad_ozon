# PR-A Supply Facts & Pack Multiplicity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize all static facts required by the operational shipment planner: restriction capacity state, placement-zone evidence, Ozon 56-day reference and supplier pack multiplicity.

**Architecture:** Extend the existing restriction importer without changing demand/optimizer behavior. Add one focused supplier-packaging importer for the uploaded RTP price workbook. Derive conservative `SKU × cluster` physical facts in `backend/supply/feasibility.py`; PR-A deliberately produces no shipment quantities and no scheduling decisions.

**Tech Stack:** Python 3, openpyxl through existing ingestion helpers, frozen dataclasses/enums, pytest; no new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-09-08-ozon-shipment-planner-design.md`

## Global Constraints

- Keep `destination_cluster` demand semantics unchanged.
- Restriction `allowed` remains the authoritative allow/deny fact.
- Capacity state is explicit: `FINITE / UNLIMITED / UNKNOWN`; unknown never means unlimited.
- `ALLOWED + FINITE(0)` is unusable for positive shipment quantity.
- Multiple warehouse maxima inside one cluster are not summed.
- `placement_zone`, card errors and warehouse equipment explain/classify; they do not override explicit `allowed`.
- Numeric Ozon recommendation `0` is explicit zero; dash/blank is missing.
- Supplier pack multiplicity comes from the right-hand integer of `Прайс списком!Упак`, not `Оглавление!КРАТНОСТЬ`.
- Missing/conflicting multiplicity remains incomplete; never default silently to `1`.
- Reuse current ProductEconomics volume/available-stock source; do not add a competing volume source in this PR.
- No application/API/frontend change belongs in PR-A.

---

## File Structure

- Modify `backend/domain/contracts.py` — shared restriction capacity and Ozon-reference status contracts.
- Modify `backend/ingestion/restrictions.py` — explicit capacity kind, explanatory fields, recommendation reference parser.
- Create `backend/ingestion/supplier_packaging.py` — `КОД` + `Упак` importer for pack multiplicity.
- Modify `backend/ingestion/__init__.py` — export the new importer where repository convention requires it.
- Modify `backend/supply/contracts.py` — `PlacementZoneStatus`, `ClusterSupplyFacts`.
- Modify `backend/supply/feasibility.py` — non-additive cluster aggregation and zone-evidence aggregation.
- Modify `backend/supply/__init__.py` — public exports.
- Modify `tests/ingestion/test_restrictions.py` — real-report capacity/zone/recommendation tests.
- Create `tests/ingestion/test_supplier_packaging.py` — supplier workbook contract tests.
- Modify `tests/supply/test_placement.py` — cluster fact aggregation tests.

---

### Task 1: Preserve explicit restriction capacity and explanatory evidence

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

Extend `RestrictionRecord` without deleting existing fields:

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
    article: str = ""
    product_name: str = ""
    placement_zone: str = ""
    card_error: str = ""
    warehouse_equipment: str = ""
    liquidity_status: str = ""
```

- [ ] **Step 1: Add failing finite/unlimited/zero/unknown tests**

Use the real Ozon headers and assert:

```python
finite = import_restrictions(_row("Да", "120"), report_meta).records[0]
assert finite.capacity_kind is RestrictionCapacityKind.FINITE
assert finite.max_supply_qty == 120

unlimited = import_restrictions(_row("Да", "Без ограничений"), report_meta).records[0]
assert unlimited.capacity_kind is RestrictionCapacityKind.UNLIMITED
assert unlimited.max_supply_qty is None

zero = import_restrictions(_row("Да", "0"), report_meta).records[0]
assert zero.capacity_kind is RestrictionCapacityKind.FINITE
assert zero.max_supply_qty == 0

unknown = import_restrictions(_row("Да", ""), report_meta).records[0]
assert unknown.capacity_kind is RestrictionCapacityKind.UNKNOWN
assert unknown.max_supply_qty is None
```

- [ ] **Step 2: Add explanatory-field test**

For a real-format row assert exact preservation of:

```python
assert row.article == "40750"
assert row.product_name
assert row.placement_zone == "Сортируемый товар"
assert row.card_error == ""
assert row.warehouse_equipment == "Оборудован"
assert row.liquidity_status == "-"
```

Add a prohibited-but-equipped fixture and prove `state` remains `PROHIBITED`; equipment never flips eligibility.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/ingestion/test_restrictions.py -q
```

Expected: new attributes/capacity-kind assertions fail.

- [ ] **Step 4: Implement strict parsing**

Normalize maximum text once:

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

Keep malformed nonblank numeric evidence as `INVALID_MAX_SUPPLY_QTY` rather than converting it to UNKNOWN.

- [ ] **Step 5: Run GREEN and commit**

```bash
python -m pytest tests/ingestion/test_restrictions.py -q
git add backend/domain/contracts.py backend/ingestion/restrictions.py tests/ingestion/test_restrictions.py
git commit -m "feat: preserve restriction supply facts"
```

---

### Task 2: Import Ozon 56-day recommendation from the same restriction workbook

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
    report_date: str | None
    source_rows: tuple[int, ...]
```

Public pure helper:

```python
def extract_ozon_supply_recommendations(
    data: bytes,
    report_context: ReportMeta,
) -> ImportResult[OzonSupplyRecommendation]: ...
```

- [ ] **Step 1: Add dedupe tests**

Create three warehouse rows with the same `SKU × cluster` and recommendation `319`. Assert one recommendation result with `recommended_qty == 319`, `status == EXPLICIT`, `horizon_days == 56` and all source row numbers retained.

- [ ] **Step 2: Add zero-vs-missing tests**

```python
assert parse("0").recommended_qty == 0
assert parse("0").status is EXPLICIT
assert parse("-").recommended_qty is None
assert parse("-").status is MISSING
```

- [ ] **Step 3: Add conflict test**

Repeated warehouse rows `20` and `21` for the same `SKU × cluster` produce `CONFLICTING`, `recommended_qty is None`, and a diagnostic; never choose one silently.

- [ ] **Step 4: Run RED, implement one-workbook extraction, run GREEN**

Reuse `read_xlsx_tables(..., all_sheets=True)` and the exact normalized header `рекомендуемая поставка на 56 дней`. Do not introduce a second user upload.

```bash
python -m pytest tests/ingestion/test_restrictions.py -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/domain/contracts.py backend/ingestion/restrictions.py tests/ingestion/test_restrictions.py
git commit -m "feat: import Ozon supply reference"
```

---

### Task 3: Add supplier pack-multiplicity importer

**Files:**
- Create: `backend/ingestion/supplier_packaging.py`
- Modify: `backend/ingestion/__init__.py`
- Create: `tests/ingestion/test_supplier_packaging.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class SupplierPackRecord:
    article: str
    pack_multiple: int
    source_pack_text: str
    source_row: int


def import_supplier_packaging(
    data: bytes,
    report_context: ReportMeta,
) -> ImportResult[SupplierPackRecord]: ...
```

Source contract for the supplied RTP workbook:

```text
sheet: Прайс списком
КОД  -> article
Упак -> packaging text
```

Parser:

```python
def parse_pack_multiple(text: object) -> int:
    normalized = normalize_text(text)
    _, sep, right = normalized.rpartition("/")
    if not sep:
        raise ValueError
    value = int(right.strip())
    if value <= 0:
        raise ValueError
    return value
```

The left side is intentionally not parsed as a number, so `100+/1` returns `1`.

- [ ] **Step 1: Add exact known-product tests**

Fixture rows:

```text
40749 ; 72/6 -> 6
40750 ; 36/6 -> 6
40751 ; 54/9 -> 9
51624 ; 72/6 -> 6
```

Assert exact article and multiplicity.

- [ ] **Step 2: Add malformed and duplicate tests**

- blank article → malformed row diagnostic;
- `36` → invalid packaging diagnostic;
- `36/0` → invalid packaging diagnostic;
- duplicate article with same multiplicity → dedupe is allowed;
- duplicate article with different multiplicities → conflicting record is omitted/fail-closed with diagnostic.

- [ ] **Step 3: Prove the global `Оглавление!КРАТНОСТЬ` cell is irrelevant**

Add a workbook fixture with an `Оглавление` sheet containing a `КРАТНОСТЬ` label/value and a `Прайс списком` row `40750 / 36/6`. Assert importer still returns `6` from `Упак` and never reads the global cell.

- [ ] **Step 4: Run RED and implement the importer**

Use `read_xlsx_tables()` with a signature that requires normalized `код` and `упак`, and prefer the worksheet named `Прайс списком` when present. Keep XLSX/XLSM reading in Python; no browser spreadsheet parser.

```bash
python -m pytest tests/ingestion/test_supplier_packaging.py -q
```

- [ ] **Step 5: Run GREEN and commit**

```bash
python -m pytest tests/ingestion/test_supplier_packaging.py -q
git add backend/ingestion/supplier_packaging.py backend/ingestion/__init__.py tests/ingestion/test_supplier_packaging.py
git commit -m "feat: import supplier pack multiplicity"
```

---

### Task 4: Derive conservative cluster supply facts and zone status

**Files:**
- Modify: `backend/supply/contracts.py`
- Modify: `backend/supply/feasibility.py`
- Modify: `backend/supply/__init__.py`
- Modify: `tests/supply/test_placement.py`

**Interfaces:**

```python
class PlacementZoneEvidenceKind(str, Enum):
    KNOWN = "known"
    MULTIPLE = "multiple"
    UNKNOWN = "unknown"

@dataclass(frozen=True, slots=True)
class PlacementZoneEvidence:
    kind: PlacementZoneEvidenceKind
    zones: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ClusterSupplyFacts:
    sku: str
    cluster_id: str
    allowed: bool
    capacity_kind: RestrictionCapacityKind
    max_supply_qty: int | None
    placement_zone: PlacementZoneEvidence
    supporting_warehouses: tuple[str, ...]
    reason_codes: tuple[str, ...]
```

Public function:

```python
def build_cluster_supply_facts(
    records: Iterable[RestrictionRecord],
) -> tuple[ClusterSupplyFacts, ...]: ...
```

- [ ] **Step 1: Add capacity aggregation tests**

Assert:

```text
FINITE 23 + FINITE 139 -> FINITE 139
FINITE 46 + FINITE 46 -> FINITE 46, not 92
UNLIMITED + FINITE 46 -> UNLIMITED
ALLOWED 0 + ALLOWED 0 -> FINITE(0), allowed false for positive plan
all prohibited -> ineligible
```

- [ ] **Step 2: Add zone aggregation tests**

```text
Сортируемый + Сортируемый -> KNOWN("Сортируемый товар")
Сортируемый + Несортируемый -> MULTIPLE(two zones)
unknown-only usable rows -> UNKNOWN
```

An unknown zone alternative does not erase a separate known zone when all known usable rows agree; return `KNOWN` plus a reason code indicating incomplete alternative evidence.

- [ ] **Step 3: Run RED, implement deterministic aggregation, run GREEN**

Sort warehouse IDs/zones/reasons for stable output.

```bash
python -m pytest tests/supply/test_placement.py -q
```

- [ ] **Step 4: Run PR-A regression set**

```bash
python -m pytest tests/ingestion/test_restrictions.py tests/ingestion/test_supplier_packaging.py tests/supply/test_placement.py tests/supply/test_optimizer.py -q
```

Expected: all green; optimizer behavior unchanged.

- [ ] **Step 5: Commit**

```bash
git add backend/supply/contracts.py backend/supply/feasibility.py backend/supply/__init__.py tests/supply/test_placement.py
git commit -m "feat: derive cluster supply facts"
```

---

## PR-A Acceptance Gate

Before PR-A is complete:

- `40750` from a `36/6` supplier-pack row resolves to multiplicity `6`;
- restriction `Да + 0` is not usable for positive supply;
- unlimited and unknown capacity are distinct;
- multiple warehouse finite limits are not summed;
- placement zone is preserved/aggregated without guessing conflicts;
- Ozon recommendation zero and missing remain distinct;
- no demand, Flow, optimizer, API or UI behavior has changed.

Run:

```bash
python -m pytest -q
```

No PR-B work begins until the full suite is green.