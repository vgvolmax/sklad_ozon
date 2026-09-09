# PR-A Supply Facts & Pack Multiplicity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add supplier pack multiplicity and one normalized supply-facts boundary that works with API-first evidence and existing file fallback without making static restrictions the future-capacity authority.

**Architecture:** Supplier workbook parsing is independent local evidence keyed by seller article. API mode uses Ozon cluster/warehouse/placement-zone catalogs from `OzonSourceSnapshot`; FILES mode may enrich from the existing restrictions workbook as dated conservative evidence. Both paths produce bounded immutable `SupplyFacts` consumed later by whole-pack planning.

**Tech Stack:** Python 3.13.14, openpyxl, frozen dataclasses, pytest; no new dependency.

**Spec:** `docs/superpowers/specs/2026-09-09-ozon-api-first-shipment-planner-design.md`

## Global Constraints

- Do not alter DemandEstimate, Need, Safe/Calculated Plan or seller-stock resolution.
- `Прайс списком!Упак` right-hand positive integer after `/` is pack multiplicity.
- Never use `Оглавление!КРАТНОСТЬ` as product multiplicity.
- Missing/conflicting pack data is incomplete; no silent `1` default.
- API placement zone is current operational evidence; FILES restrictions are dated fallback evidence only.
- Static `max_supply_qty` must never be described as guaranteed future capacity in API mode.
- Restrictions 56-day recommendation never replaces the analytical Ozon recommendation.

---

### Task 1: Add supplier pack importer

**Files:**
- Create: `backend/ingestion/supplier_packaging.py`
- Modify: `backend/ingestion/__init__.py` if public exports are centralized there.
- Create: `tests/ingestion/test_supplier_packaging.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class SupplierPackRecord:
    article: str
    pack_multiple: int


def import_supplier_packaging(data: bytes, report_context: ReportMeta) -> ImportResult[SupplierPackRecord]: ...
```

Parsing contract:

```text
sheet = Прайс списком
article column = КОД
pack text column = Упак
right side after final '/' = positive integer
```

- [ ] **Step 1: Add fixtures proving `36/6→6`, `54/9→9`, `100+/1→1`, whitespace normalization and repeated identical rows dedupe cleanly.**
- [ ] **Step 2: Add malformed/conflict tests for missing sheet/headers, no slash, zero/negative/non-integer right side and same article with different multiples. Conflicts remain diagnostics and do not choose a value.**
- [ ] **Step 3: Add a workbook containing `Оглавление!КРАТНОСТЬ` and prove it is ignored.**
- [ ] **Step 4: Run RED, implement single-open openpyxl parser, run GREEN.**

```bash
python -m pytest tests/ingestion/test_supplier_packaging.py -q
```

- [ ] **Step 5: Commit.**

```bash
git add backend/ingestion/supplier_packaging.py backend/ingestion/__init__.py tests/ingestion/test_supplier_packaging.py
git commit -m "feat: import supplier pack multiplicity"
```

---

### Task 2: Define normalized supply-facts contracts

**Files:**
- Create: `backend/supply/facts.py`
- Create: `tests/supply/test_facts.py`

**Interfaces:**

```python
class EvidenceSource(str, Enum):
    OZON_API = "ozon_api"
    RESTRICTIONS_FILE = "restrictions_file"

class PlacementZoneKind(str, Enum):
    KNOWN = "known"
    MULTIPLE = "multiple"
    UNKNOWN = "unknown"

@dataclass(frozen=True, slots=True)
class ClusterSupplyFacts:
    sku: str
    cluster_id: str
    placement_zone_kind: PlacementZoneKind
    placement_zones: tuple[str, ...]
    source: EvidenceSource
    observed_at: str | None
    fallback_allowed: bool | None = None
    fallback_capacity_qty: int | None = None
    fallback_capacity_unlimited: bool = False
    reason_codes: tuple[str, ...] = ()
```

- [ ] **Step 1: Write validation tests for unique `SKU × cluster`, explicit source, sorted unique zone evidence and nonnegative fallback capacity.**
- [ ] **Step 2: Run RED, implement immutable contracts/validators, run GREEN.**

```bash
python -m pytest tests/supply/test_facts.py -q
```

- [ ] **Step 3: Commit.**

```bash
git add backend/supply/facts.py tests/supply/test_facts.py
git commit -m "feat: define normalized supply facts"
```

---

### Task 3: Build API-mode supply facts from source snapshot

**Files:**
- Modify: `backend/supply/facts.py`
- Modify: `tests/supply/test_facts.py`

**Interfaces:**

```python
def build_api_supply_facts(snapshot: OzonSourceSnapshot) -> tuple[ClusterSupplyFacts, ...]: ...
```

- [ ] **Step 1: Add tests with one known zone, conflicting/multiple zones and no zone evidence; preserve `KNOWN/MULTIPLE/UNKNOWN` without guessing.**
- [ ] **Step 2: Prove API facts do not synthesize `max_supply_qty` and do not depend on old restrictions rows.**
- [ ] **Step 3: Implement from normalized API catalog/placement evidence and run GREEN.**

```bash
python -m pytest tests/supply/test_facts.py -q
```

- [ ] **Step 4: Commit.**

```bash
git add backend/supply/facts.py tests/supply/test_facts.py
git commit -m "feat: build API supply facts"
```

---

### Task 4: Preserve file restrictions as explicit dated fallback facts

**Files:**
- Modify: `backend/ingestion/restrictions.py`
- Modify: `backend/supply/facts.py`
- Modify: `tests/ingestion/test_restrictions.py`
- Modify: `tests/supply/test_facts.py`

**Required importer preservation/enrichment:**

Keep existing `RestrictionRecord` compatibility while adding the fields needed to retain source meaning, including placement-zone evidence and explicit capacity kind rather than ambiguous `None`.

- [ ] **Step 1: Add tests distinguishing `FINITE(0)`, positive FINITE, `UNLIMITED`, prohibited/unknown and missing.**
- [ ] **Step 2: Add placement-zone/report-date tests. Preserve `ReportMeta.report_generated_at` when source metadata proves it; otherwise keep unknown.**
- [ ] **Step 3: Add cluster aggregation tests: any explicit usable unlimited wins; else max independently proven positive finite; do not sum warehouses.**
- [ ] **Step 4: Add restrictions 56-day-reference test proving it is secondary evidence and never passed into `calculate_need()`.**
- [ ] **Step 5: Run RED, minimally enrich importer and fallback fact builder, run GREEN.**

```bash
python -m pytest tests/ingestion/test_restrictions.py tests/supply/test_facts.py -q
```

- [ ] **Step 6: Commit.**

```bash
git add backend/ingestion/restrictions.py backend/supply/facts.py tests/ingestion/test_restrictions.py tests/supply/test_facts.py
git commit -m "feat: preserve restrictions as fallback evidence"
```

---

### Task 5: Join packs to current article/SKU identities

**Files:**
- Create: `backend/supply/packaging.py`
- Create: `tests/supply/test_packaging.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ProductPackFacts:
    sku: str
    article: str
    pack_multiple: int | None
    complete: bool
    reason_codes: tuple[str, ...]


def resolve_product_packs(
    decision_rows,
    supplier_records: Iterable[SupplierPackRecord],
) -> tuple[ProductPackFacts, ...]: ...
```

- [ ] **Step 1: Add join tests where article is the supplier key and SKU is current Ozon identity.**
- [ ] **Step 2: Add missing/conflicting article mapping tests; affected SKU is incomplete and never borrows another article's multiple.**
- [ ] **Step 3: Run RED, implement deterministic join, run GREEN.**

```bash
python -m pytest tests/supply/test_packaging.py -q
```

- [ ] **Step 4: Commit.**

```bash
git add backend/supply/packaging.py tests/supply/test_packaging.py
git commit -m "feat: resolve product pack facts"
```

---

### Task 6: PR-A regression gate

- [ ] **Step 1: Run ingestion/supply focused tests.**

```bash
python -m pytest tests/ingestion tests/supply/test_facts.py tests/supply/test_packaging.py -q
```

- [ ] **Step 2: Run Product Completion acceptance and prove analytical plan values are unchanged.**

```bash
python -m pytest tests/api/test_product_completion_acceptance.py -q
```

- [ ] **Step 3: Run full suite.**

```bash
python -m pytest -q
```

Acceptance: pack multiplicity is explicit local evidence; API supply facts are current/non-capacity-guessing; file restrictions remain a conservative fallback only; upstream analytics remain unchanged.
