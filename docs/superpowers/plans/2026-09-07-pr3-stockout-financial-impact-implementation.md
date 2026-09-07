# PR3 Stockout Financial Impact — Implementation Plan

**Goal:** quantify current-route versus local-counterfactual economics on exact
PR2 episode dates and expose only bounded, PII-free backend presentation data.

## Task 1 — Extract the per-unit counterfactual core

1. Add failing parity, negative-sign, missing-data, and feasibility tests for
   `RouteCounterfactual` and the existing observed-period adapter.
2. Run `tests/economics/test_route_opportunity.py` and confirm RED.
3. Extract `calculate_route_counterfactual`; retain every existing
   `RouteOpportunity` field and observed-quantity meaning in the adapter.
4. Run the focused test GREEN and review the diff for duplicated formulas.

## Task 2 — Calculate exact episode impact

1. Add failing tests for exact route math, affected-date filtering, local versus
   external quantities, two donors, current-week scope, negative results, and
   fail-closed aggregation without partial money.
2. Run `tests/economics/test_stockout_impact.py` and confirm RED.
3. Implement immutable route, aggregate, and episode contracts in
   `backend/economics/stockout_impact.py`, using a local 40-digit half-even
   Decimal context and counterfactual core.
4. Run focused tests GREEN and review quantity bases and reason propagation.

## Task 3 — Build bounded presentation aggregates

1. Add failing tests for destination/day weighting and boundedness, deterministic
   episode/donor ordering, two-SKU profit-over-price weighting, reconciliation,
   missing product identity/economics, negative signs, and PII exclusion.
2. Run `tests/decision/test_stockout_impact_presentation.py` and confirm RED.
3. Add the named immutable view contracts and implement pure conversion in
   `backend/decision/impact.py`; never expose raw daily route/SKU matrices.
4. Run focused tests GREEN and review all presentation arithmetic.

## Task 4 — Integrate application and snapshot

1. Add failing application/API acceptance tests proving episode visibility,
   observed-audit immutability, demand/Need invariance, bounded wire output, and
   PII safety.
2. Build episode impacts only after products, settings, tariffs, and canonical
   placement feasibility exist; add the bounded presentation to the snapshot.
3. Run API and snapshot tests GREEN; verify no frontend production file changed.

## Task 5 — Verification and review

1. Run all required focused pytest commands, then `python -m pytest -q`.
2. Run four `node --check` commands, `python -m compileall backend`,
   `git diff --check`, and inspect `git status --short`.
3. Review `main...HEAD` against all PR3 invariants, fix every critical or
   important finding, rerun verification, commit, push, and open one PR.
4. Wait for fresh final-HEAD Python, JavaScript, full-pytest, and Windows portable
   smoke CI before declaring the PR merge-ready.

