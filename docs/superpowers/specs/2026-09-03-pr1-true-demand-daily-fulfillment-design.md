# PR1 — True Demand & Daily Fulfillment Foundation — Design

**Date:** 2026-09-03  
**Status:** approved PR design  
**Parent design:** `docs/superpowers/specs/2026-09-03-real-data-demand-stockout-flow-design.md`

## 1. Purpose

PR1 creates a canonical daily analytical layer from normalized Ozon orders and proves a non-negotiable planning invariant:

> planning for `SKU × cluster` uses the customer destination's own observed demand; physical dispatch from an origin to other destinations never increases the origin's demand or calculated need.

PR1 is intentionally backend-only foundation work. It does not add daily stockout detection, financial impact calculation, new diagnostics presentation or Flow UI.

## 2. Existing behavior to preserve

Current code already has correct high-level semantics:

- demand is grouped by `order.destination_cluster`;
- route history is grouped by `order.origin_cluster → order.destination_cluster`;
- demand estimate is keyed by `SKU × destination`;
- `calculate_need()` receives destination weekly rate, destination FBO stock and destination inbound;
- route economics and placement happen downstream of quantity calculation.

PR1 must preserve all existing externally observable weekly demand, M1/M2/L and need values for the same normalized orders.

## 3. New canonical daily contracts

Create `backend/analytics/daily.py` with immutable dataclasses.

```python
from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True, slots=True)
class DailyDemandCell:
    sku: str
    day: date
    destination_cluster_id: str
    quantity: int
    observation_count: int

@dataclass(frozen=True, slots=True)
class DailyFulfillmentCell:
    sku: str
    day: date
    origin_cluster_id: str
    destination_cluster_id: str
    quantity: int
    observation_count: int

@dataclass(frozen=True, slots=True)
class DailyOrderFacts:
    demand: tuple[DailyDemandCell, ...]
    fulfillment: tuple[DailyFulfillmentCell, ...]
    excluded_future: int
    excluded_undated: int
```

Field names may only change if the implementation plan and tests are updated consistently before coding begins. The concepts must not change.

## 4. One source pass, two populations

Expose:

```python
def build_daily_order_facts(
    orders: Iterable[OrderRecord],
    as_of: date,
) -> DailyOrderFacts:
    ...
```

Each order is validated once and then evaluated independently for the two populations.

### 4.1 Demand population

Eligibility uses the existing `is_net_demand(order)` contract.

Group key:

```text
(day, sku, destination_cluster)
```

Origin must not be part of the key and must not affect demand aggregation.

### 4.2 Fulfillment population

Eligibility uses existing `is_fulfilled_route(order)`.

Group key:

```text
(day, sku, origin_cluster, destination_cluster)
```

### 4.3 Lifecycle consequence

An `IN_PROGRESS` order may count toward destination demand while not yet appearing in fulfilled routing.

Therefore this is invalid:

```text
destination demand == sum(fulfilled routes)
```

The two datasets answer different questions.

## 5. Date semantics

Use the same canonical source event timestamp currently used by weekly analytics: `accepted_at`, parsed through the existing date parser.

Rules:

- unparseable/undated order: excluded from daily facts and counted in `excluded_undated`;
- event date `> as_of`: excluded and counted in `excluded_future`;
- event date `<= as_of`: eligible for a daily fact if lifecycle population allows it.

PR1 does not decide whether the current partial ISO week is valid stockout evidence. That belongs to PR2.

Weekly compatibility layers continue to exclude the current incomplete ISO week exactly as today.

## 6. Weekly demand must derive from daily demand

Add an explicit daily-to-weekly function, for example:

```python
def aggregate_weekly_demand(
    daily: DailyOrderFacts,
    as_of: date,
    week_policy: WeekPolicy = WeekPolicy.COMPLETED_ISO_WEEKS,
) -> DemandResult:
    ...
```

or equivalently accept `Iterable[DailyDemandCell]` plus exclusion metadata.

The dedicated implementation plan fixes the exact signature used in code.

Required outcome:

```text
old aggregate_demand(orders, as_of)
==
new build_daily_order_facts(orders, as_of) → weekly demand
```

for every existing acceptance fixture.

The public `aggregate_demand(orders, as_of)` API may remain as a compatibility wrapper, but application orchestration should build daily facts once and reuse them.

## 7. Weekly routes must derive from daily fulfillment

Add an explicit daily-to-weekly route function, for example:

```python
def build_weekly_route_profile(
    daily: DailyOrderFacts,
    as_of: date,
    week_policy: WeekPolicy = WeekPolicy.COMPLETED_ISO_WEEKS,
) -> RouteProfile:
    ...
```

Required outcome:

```text
old build_route_profile(orders, as_of)
==
new daily fulfillment → weekly route profile
```

for existing fixtures.

Existing `build_route_profile()` may remain as a compatibility wrapper.

## 8. Application orchestration

`backend/application.py` should perform one daily-facts build near the start of analysis:

```python
daily = build_daily_order_facts(orders, as_of)
demand = aggregate_weekly_demand(daily, as_of)
observed = build_weekly_route_profile(daily, as_of)
```

Then continue through the existing pipeline:

```text
demand estimate
stockout
clean routes
need
route economics
placement
allocation
snapshot
```

No downstream quantity formula is changed in PR1.

## 9. AnalysisResult boundary

Extend the internal `AnalysisResult` with daily facts only if required for PR2 continuity.

Preferred contract:

```python
@dataclass(frozen=True, slots=True)
class AnalysisResult:
    daily_facts: DailyOrderFacts
    demand: DemandResult
    observed_routes: RouteProfile
    ...
```

This is an internal backend result, not a browser payload requirement.

## 10. Snapshot/browser boundary

PR1 must **not** add raw daily facts to `AnalysisSnapshot` or API presentation JSON.

Reason:

- real reports contain tens of thousands of order rows;
- future UI should receive bounded presentation series/episodes, not an unbounded route matrix;
- PR3 is responsible for compact presentation aggregates.

A regression should prove that new daily facts are not serialized into the browser snapshot in PR1.

## 11. Core business proofs

### 11.1 Donor inflation trap

Input, same SKU:

```text
Москва → Москва 500
Москва → Казань 300
Москва → Тверь  200
```

Expected:

```text
Moscow physical fulfillment = 1000
Moscow destination demand = 500
Kazan destination demand = 300
Tver destination demand = 200
```

Moscow need must use the Moscow demand series only.

### 11.2 External fulfillment mirror case

Input:

```text
Москва → Казань 300
Казань → Казань   0
```

Expected:

```text
Kazan destination demand = 300
```

Local fulfillment of zero does not erase Kazan demand.

### 11.3 Origin permutation invariance

Construct datasets A and B with identical:

```text
sku
destination
quantity
lifecycle
accepted_at
```

but different origins.

Expected:

```text
daily demand A == daily demand B
weekly demand A == weekly demand B
demand estimates A == demand estimates B
NeedComparison A == NeedComparison B
```

and:

```text
daily fulfillment A != daily fulfillment B
weekly routes A != weekly routes B
```

This is the strongest protection against accidental donor-volume inflation.

### 11.4 Lifecycle separation

Input for one destination:

```text
FULFILLED   10
IN_PROGRESS  5
CANCELLED    7
```

Expected with existing lifecycle semantics:

```text
destination demand = 15
fulfilled routing = 10
```

## 12. Weekly equivalence proofs

Run existing analytics fixtures through old and new paths while implementing PR1.

At merge, all expected weekly outputs must remain unchanged:

- included weeks;
- excluded current/future/undated counts where applicable;
- DemandCell identities and quantities;
- RouteCell identities, quantities, observation counts and shares;
- DemandEstimate M1/M2/L/regime/current_weekly_rate;
- NeedComparison quantities.

No “small acceptable drift” exists for these values. They must be identical.

## 13. Need isolation proof

At least one application/decision regression must show that changing only origins while keeping destination orders constant leaves calculated need unchanged.

The test should include destination FBO stock and inbound so it protects the complete quantity chain, not only demand aggregation.

Example:

```text
weekly destination rate = 100
horizon = 56 days
FBO = 200
inbound = 100
```

The need result must remain identical under different origin routing.

## 14. Performance contract

`build_daily_order_facts()` must be linear in the number of normalized orders apart from dictionary/sort overhead:

```text
O(n) aggregation + O(k log k) deterministic output sort
```

No all-pairs joins, nested route scans by order or repeated full-order traversal for each SKU/cluster.

The application should not perform separate full raw-order aggregation passes for demand and routes after PR1.

## 15. Data identity and privacy

Daily analytical cells contain only business aggregation identities:

- SKU;
- day;
- origin/destination cluster;
- quantities/counts.

Do not add buyer name, phone, email, address, shipment number or other PII to daily analytical contracts.

## 16. Files in scope

Expected production scope:

```text
CREATE backend/analytics/daily.py
MODIFY backend/analytics/__init__.py
MODIFY backend/analytics/demand.py
MODIFY backend/analytics/routes.py
MODIFY backend/application.py
```

Expected test scope:

```text
CREATE tests/analytics/test_daily_facts.py
MODIFY tests/analytics/test_demand_routes.py
MODIFY tests/analytics/test_demand_estimate.py only if needed for equivalence proof
MODIFY tests/api/test_product_completion_acceptance.py only if needed for end-to-end invariant proof
```

## 17. Files/systems explicitly out of scope

Do not modify for PR1 unless a direct compile/import consequence requires a trivial reference update:

```text
frontend/**
backend/economics/**
backend/supply/**
optimizer behavior
Flow presentation contracts
Data diagnostics presentation
start.bat
portable bootstrap
```

Do not add dependencies.

## 18. Merge gate

PR1 is mergeable only when all are true:

1. daily demand and fulfillment contracts exist;
2. one canonical daily build is used by application orchestration;
3. donor dispatch does not inflate donor demand;
4. externally fulfilled demand remains owned by destination;
5. origin permutation leaves daily demand unchanged;
6. origin permutation leaves weekly demand unchanged;
7. origin permutation leaves demand estimate unchanged;
8. origin permutation leaves need unchanged;
9. origin permutation changes fulfillment/routes as expected;
10. fulfilled/in-progress/cancelled populations remain distinct;
11. existing weekly demand outputs are identical;
12. existing weekly route outputs are identical;
13. current incomplete ISO-week policy for weekly analytics is unchanged;
14. no daily matrix is added to browser snapshot;
15. no PII is added to analytical contracts;
16. focused tests pass;
17. full pytest passes;
18. existing JS syntax checks pass even though frontend is untouched;
19. Windows portable smoke passes;
20. no unrelated refactor or UI change is included.

## 19. What PR1 intentionally does not solve

PR1 does not implement:

- rolling 7-day locality;
- probable stockout episodes by date;
- precise episode route cleaning;
- extra logistics / margin / profit loss by episode;
- bounded Flow presentation aggregates;
- diagnostics aggregation;
- real-scale Flow UI.

Those responsibilities belong to PR2–PR5 in the parent design.
