# PR36 Analysis API Review Fixes

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:systematic-debugging`, `superpowers:test-driven-development`, `superpowers:verification-before-completion`, and `superpowers:requesting-code-review` to fix the existing PR without redesigning Task 17.

**Goal:** Fix the four blocking review findings in existing PR #36, add real API integration coverage, and update the same PR without merging it.

**Architecture:** Keep Task 17 boundaries unchanged. Fix Decimal serialization at the API boundary, propagate logistics/economics failures into top-level diagnostics and `complete`, convert invalid user economics settings into controlled HTTP 400 responses, and add real TestClient coverage for the end-to-end multipart analysis flow.

**Tech Stack:** Python 3.13, FastAPI 0.139.2, pytest 8.4.2, httpx 0.28.1, Decimal, vanilla frontend.

**Existing PR:** #36 — `feat: connect local analysis API and UI`

**Previous expected PR head:** `cab619cf2d0c043886ceb713b4ae35b42fd891bc`

**Base:** `1b7b30eafbb3078db49ba446774e703b63cd305b`

---

## CODEX CLOUD / EXISTING PR

This is a review-fix pass for existing PR #36. It is **not** a new feature task.

Prefer running this as a follow-up inside the same Codex Cloud task/workspace that created PR #36.

Expected harness branch:

`codex/add-application-apis-and-connect-ui`

At start run only:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
```

If the workspace is already on the PR #36 harness-managed branch, stay there.

Do **not** run:

```text
git fetch
git checkout main
git pull
git switch -c
git branch -c
git worktree add
git remote change
git push
gh pr create
```

Do not create PR #37.

If the harness is not attached to PR #36 / the existing branch and cannot update it natively, stop. Do not reimplement the task on main and do not create another PR. Report the actual branch/HEAD instead.

---

## SUPERPOWERS

Use:

- `superpowers:systematic-debugging`
- `superpowers:test-driven-development`
- `superpowers:verification-before-completion`
- `superpowers:requesting-code-review`

State explicitly:

> I'm using systematic-debugging to fix the review blockers in existing PR #36.

---

# Root causes already identified

The existing implementation has four important review problems. Do not redesign Task 17. Fix these root causes directly.

---

# Blocker 1 — Decimal serialization loses precision

Current `backend/api.py` contains logic equivalent to:

```python
format(value.normalize(), "f")
```

`Decimal.normalize()` uses the active Decimal context and may round a high-precision value. The economics engine intentionally calculates with precision 40. Therefore the API wire serializer can silently truncate a correctly calculated result.

The following value must survive exactly:

```python
Decimal("1.123456789012345678901234567890123456789")
```

Expected serialized string:

```text
1.123456789012345678901234567890123456789
```

No lost digits.

## Fix Decimal serialization

Create a small private helper such as:

```python
_decimal_string(value: Decimal) -> str
```

It must:

- never convert `Decimal` to `float`;
- never call `Decimal.normalize()`;
- never quantize;
- never use arithmetic merely to format;
- never change the global Decimal context;
- produce fixed-point JSON strings;
- canonicalize trailing insignificant zeros;
- canonicalize negative zero to `"0"`.

A suitable implementation pattern is:

```python
text = format(value, "f")
if "." in text:
    text = text.rstrip("0").rstrip(".")
if text in {"", "-0"}:
    text = "0"
```

Use this from `wire()`.

Required examples:

```text
Decimal("10.250") -> "10.25"
Decimal("1000") -> "1000"
Decimal("1E+3") -> "1000"
Decimal("0.000") -> "0"
Decimal("-0.000") -> "0"
```

Most importantly, 40+ significant digits must survive exactly.

## Decimal regression test

Add a test which:

1. stores the current global Decimal context;
2. optionally sets a deliberately small global precision such as 10;
3. serializes:

```python
Decimal("1.123456789012345678901234567890123456789")
```

4. asserts the exact full string survives;
5. verifies the serializer did not modify the global context.

Use `try/finally` when temporarily changing the test context.

This test must fail against the previous PR head.

---

# Blocker 2 — Logistics / economics failures are not propagated to top-level diagnostics

Current `expected_logistics()` can produce:

- `MISSING_TARIFF`
- `AMBIGUOUS_TARIFF_MATCH`
- `PRICE_REQUIRED_FOR_TARIFF_LOOKUP`
- `NO_ROUTE_PROFILE`

and corresponding coverage states:

- `complete`
- `partial`
- `none`
- `no_profile`

`UnitEconomicsResult` can then become `complete == False` with blockers such as:

- `INCOMPLETE_LOGISTICS_COVERAGE`
- `MISSING_PRICE`
- `MISSING_COST`
- `MISSING_COMMISSION_RATE`
- `UNSUPPORTED_TAX_SEMANTICS`

Current PR keeps these inside logistics/economics objects but does not reliably propagate the failure to top-level diagnostics and `analysis response["complete"]`.

This permits an invalid state:

```text
economics.complete == False
response["complete"] == True
```

That is a merge blocker.

## Fix diagnostic propagation

Keep the detailed objects where they already are.

Additionally surface actionable causes through `AnalysisResult.diagnostics`.

For every `ExpectedLogisticsResult` diagnostic, append an `AnalysisDiagnostic` containing:

- severity
- code
- message
- sku
- placement/origin cluster

Preserve destination context as well. You may extend `AnalysisDiagnostic` with:

```python
destination_cluster_id: str | None = None
```

if needed.

Example:

```python
AnalysisDiagnostic(
    severity=diagnostic.severity,
    code=diagnostic.code,
    message=diagnostic.message,
    sku=logistics.sku,
    cluster_id=logistics.origin_cluster_id,
    destination_cluster_id=diagnostic.destination_cluster_id,
)
```

Do not replace the original `ExpectedLogisticsResult.diagnostics`. This is additional top-level explainability.

## Economics blockers

When `UnitEconomicsResult.complete == False`, surface its blocker codes in top-level `AnalysisResult.diagnostics` as errors.

Use the existing canonical economics blocker codes directly. Do not invent replacements such as `ECONOMICS_FAILED_GENERIC`.

Examples:

- `MISSING_PRICE`
- `MISSING_COST`
- `MISSING_COMMISSION_RATE`
- `INCOMPLETE_LOGISTICS_COVERAGE`
- `UNSUPPORTED_TAX_SEMANTICS`

Preserve `sku` and `placement_cluster_id`.

Do not recalculate economics.

## Top-level complete semantics

`POST /api/analysis` response field `complete` must be `False` if any of these are true:

- any top-level diagnostic has severity `"error"`;
- any evaluated `UnitEconomicsResult` has `complete == False`.

It may remain `True` only when the evaluated analysis is complete and there are no error diagnostics.

Warnings alone do not automatically make `complete` false unless an associated economics result is incomplete.

Do not hide incomplete placements. They remain in:

- `logistics`
- `economics`
- `placements`

with allocation zero where appropriate.

## Test — missing tariff

Create an actual `/api/analysis` integration test.

Use an otherwise valid SKU/candidate but omit the matching tariff.

Expected:

```text
HTTP 200
placement still visible
logistics coverage != complete
economics.complete == false
allocation == 0
response.complete == false
```

Top-level diagnostics must include the exact existing tariff cause such as:

```text
MISSING_TARIFF
```

and:

```text
INCOMPLETE_LOGISTICS_COVERAGE
```

Do not substitute tariff cost = 0.

---

# Blocker 3 — User input can escape as HTTP 500

Current transport parsing checks only that `EconomicsSettings` decimals are finite.

Example:

```text
acquiring_rate = 2
```

passes Decimal parsing but the economics engine later correctly rejects it because the rate must be <= 1.

That user input must not become an HTTP 500.

## Fix settings transport validation

Do not duplicate economics formulas. It is acceptable and required for the HTTP boundary to validate the simple accepted numeric domains of form fields.

Validate:

```text
acquiring_rate:   0 <= value <= 1
advertising_rate: 0 <= value <= 1
buyout_rate:      0 < value <= 1
income_tax_rate:  0 <= value <= 1
vat_rate:         0 <= value <= 1
co_invest_rate:   0 <= value <= 1
fixed_fbo_fee:    value >= 0
```

Optimizer thresholds remain different:

- `min_profit_per_unit`
- `min_margin_rate`
- `min_roi`

These only need to be finite `Decimal`.

Do not impose `0..1` or nonnegative ranges on optimizer thresholds.

For out-of-domain economics settings return HTTP 400 with stable shape:

```json
{
  "api_version": 1,
  "error": {
    "code": "INVALID_SETTING",
    "message": "...",
    "field": "<exact form field>"
  }
}
```

Malformed/non-finite Decimal remains `INVALID_DECIMAL`.

Invalid tax system remains `INVALID_TAX_SYSTEM`.

## Setting error tests

Using the actual API verify:

```text
acquiring_rate = "2"
-> HTTP 400
-> field == "acquiring_rate"

buyout_rate = "0"
-> HTTP 400
-> field == "buyout_rate"

fixed_fbo_fee = "-1"
-> HTTP 400

NaN
-> HTTP 400 INVALID_DECIMAL
```

But this must remain accepted by transport validation:

```text
min_profit_per_unit = "-100"
```

because optimizer thresholds may be permissive.

---

# Blocker 4 — Task 17 API flow is not actually tested

Current `tests/api/test_analysis.py` contains only lightweight serializer/frontend checks. It does not actually exercise:

- `POST /api/analysis`
- multipart files
- real importers
- `Kazan -> Moscow` direction
- Ozon recommendation semantics
- seller stock
- optimizer
- PII stripping
- 400/413 errors

Passing the previous suite therefore does not prove Task 17 works.

This review fix must add real API integration coverage.

## Use real ASGI API

Use:

```python
from fastapi.testclient import TestClient
from backend.main import app
```

and test the actual routes.

Do not call the endpoint function manually as a substitute for HTTP behavior.

GitHub Actions currently proves TestClient works with the pinned CI environment.

If the local Codex environment still has the known `httpx2` / TestClient collection limitation:

- do not modify requirements;
- do not remove or skip the integration tests;
- record the local environment blocker;
- rely on GitHub Actions as authoritative for these tests.

---

# Sanitized test data

Use small deterministic fixtures.

Reuse existing helpers such as:

```python
tests.helpers.xlsx_fixtures.make_xlsx
```

Do not add large binary files.

Do not add seller/customer PII to repository fixtures except clearly synthetic unique marker strings used by the PII regression.

Use completed historical dates, not the current ISO week.

---

# Test A — Happy-path `/api/analysis`

Create one minimal complete SKU analysis.

Example semantics:

```text
SKU = "SKU-1"
cluster = "Москва"
warehouse = "W-MSK"
Ozon recommendation = 3
Ozon available_quantity = 999
seller available stock = 5
restriction = allowed
historical fulfilled route = Москва -> Москва
matching tariff exists
complete product economics exists
```

POST `/api/analysis`.

Expected:

```text
HTTP 200
api_version == 1
complete == true
```

All required top-level keys exist:

- `api_version`
- `complete`
- `as_of`
- `metadata`
- `demand`
- `observed_routes`
- `clean_routes`
- `stockout_signals`
- `distortion_signals`
- `logistics`
- `economics`
- `placements`
- `allocations`
- `coverage`
- `diagnostics`

Expected placement:

```text
ozon_recommended_qty == 3
```

Expected allocation:

```text
3
```

This proves Ozon availability `999` is not recommendation and seller stock `5` does not allow allocation above Ozon recommendation `3`.

---

# Test B — Seller stock hard limit

Use:

```text
Ozon availability = 999
Ozon recommendation = 10
ProductEconomics.available_qty = 2
```

Expected total allocation:

```text
2
```

This proves Ozon availability is not seller stock.

---

# Test C — Directional invariant

Include a fulfilled order:

```text
origin = Казань
destination = Москва
```

Expected API demand:

```text
Москва
```

Expected route:

```text
origin_cluster_id == "Казань"
destination_cluster_id == "Москва"
```

Never report this as Kazan demand.

This is a blocking business invariant.

---

# Test D — Counterfactual Ozon zero

A relevant cluster has historical demand or route evidence but:

```text
recommended_quantity = 0
```

and positive economics.

Expected placement visible:

```text
ozon_recommended_qty == 0
```

Expected allocation:

```text
0
```

Do not hide the row.

---

# Test E — Identical warehouse recommendations

Availability:

```text
SKU-1 / W1 / Москва / recommended=10
SKU-1 / W2 / Москва / recommended=10
```

Expected cluster recommendation:

```text
10
```

not `20`.

---

# Test F — Conflicting recommendations

Availability:

```text
SKU-1 / W1 / Москва / recommended=10
SKU-1 / W2 / Москва / recommended=20
```

Expected:

```text
HTTP 200
diagnostics contain CONFLICTING_OZON_RECOMMENDATION
response.complete == false
Moscow automatic recommendation/allocation == 0
```

Never choose 10 or 20 silently. Never sum to 30.

---

# Test G — PII boundary

Upload orders CSV containing extra columns with unique markers:

```text
buyer_name = "PII_BUYER_12345"
phone = "PII_PHONE_12345"
email = "PII_EMAIL_12345"
address = "PII_ADDRESS_12345"
```

The orders importer should discard them.

Serialize the entire `/api/analysis` response to text.

Assert none of those marker values occur.

Also assert buyer/phone/email/address raw fields are absent.

---

# Test H — Import endpoint

Exercise at least the real availability import route:

```text
POST /api/import/availability
```

Assert:

```text
HTTP 200
api_version == 1
kind == "availability"
records
diagnostics
meta
record_sources
```

`recommended_quantity` must appear correctly.

Prefer parametrizing all five import routes if existing fixture helpers make that concise:

- availability
- restrictions
- orders
- tariffs
- product-economics

Do not create a generic production importer framework merely for the test.

---

# Test I — 413

Do not allocate a real 64+ MiB test fixture if unnecessary.

Use monkeypatch to temporarily lower:

```python
backend.api.MAX_UPLOAD_BYTES
```

Example:

```text
MAX_UPLOAD_BYTES = 4
```

Upload 5 bytes.

Expected:

```text
HTTP 413
error.code == "UPLOAD_TOO_LARGE"
correct field
```

---

# Test J — Missing field

POST incomplete multipart request.

Expected:

```text
HTTP 400
error.code == "MISSING_FIELD"
correct field
```

---

# Test K — Invalid date

Use:

```text
as_of = "not-a-date"
```

Expected:

```text
HTTP 400
error.code == "INVALID_DATE"
field == "as_of"
```

---

# Do not change existing business modules

Do not modify:

```text
backend/domain/*
backend/analytics/*
backend/economics/*
backend/supply/*
backend/project.py
backend/ingestion/*
```

except only if a newly written regression proves the existing Task 17 availability change itself is broken.

Expected review-fix files should normally be:

```text
backend/api.py
backend/application.py
tests/api/test_analysis.py
```

Frontend files should not need redesign.

---

# No dependency changes

Do not modify:

```text
requirements.txt
requirements-dev.txt
```

Do not add:

- httpx2
- pytest-asyncio
- new testing libraries
- new frontend packages

GitHub CI already runs the pinned environment.

---

# No UI redesign

Do not redesign:

```text
frontend/index.html
frontend/assets/css/app.css
frontend/assets/js/app.js
```

unless a failing Task 17 regression demonstrates an actual UI contract bug.

This pass is for correctness and test coverage.

---

# TDD sequence

First add failing regressions for:

1. full-precision Decimal wire serialization;
2. missing tariff -> complete false + top-level diagnostics;
3. invalid economics setting -> HTTP 400;
4. real happy-path `/api/analysis`;
5. directional Kazan -> Moscow;
6. recommendation != availability;
7. seller stock ceiling;
8. conflicting recommendation;
9. PII;
10. 413 / malformed transport.

Run the narrowest tests possible and verify they fail for the expected reasons.

Then implement the minimal fixes.

---

# Focused verification

Run:

```bash
python -m pytest \
  tests/api/test_analysis.py \
  tests/ingestion/test_availability.py -q
```

Expected: pass.

---

# API regression

Run:

```bash
python -m pytest tests/api -q
```

Expected: pass in an environment where TestClient dependencies are available.

---

# Core regression

Run:

```bash
python -m pytest \
  tests/analytics \
  tests/economics \
  tests/supply \
  tests/ingestion \
  tests/api -q
```

---

# Full regression

Run:

```bash
python -m pytest -q
```

Do not exclude directories.

If local Codex still fails only because its environment lacks the TestClient/httpx2 combination, record the exact error. Do not change dependencies. GitHub Actions must subsequently prove the full suite.

---

# Static checks

Run:

```bash
node --check frontend/assets/js/app.js

python -m py_compile \
  backend/application.py \
  backend/api.py

git diff --check
git status --short
```

---

# Review checklist

Before finalizing verify explicitly:

- [ ] Decimal serializer preserves >40-digit input
- [ ] no `Decimal.normalize()` in wire serialization
- [ ] no float conversion
- [ ] global Decimal context unchanged
- [ ] logistics diagnostics surfaced
- [ ] economics blockers surfaced
- [ ] incomplete economics cannot coexist with top-level `complete=true`
- [ ] invalid economics settings return 400
- [ ] negative optimizer threshold still allowed
- [ ] actual `/api/analysis` tested over HTTP
- [ ] Kazan -> Moscow remains Moscow demand
- [ ] Ozon availability != recommendation
- [ ] Ozon availability != seller stock
- [ ] recommendation repeated by warehouse is not summed
- [ ] conflicting recommendations fail closed
- [ ] counterfactual Ozon-zero gets allocation 0
- [ ] missing tariff does not become zero cost
- [ ] PII cannot appear in response
- [ ] oversized file returns 413
- [ ] no business formulas moved into API/UI
- [ ] analytics/economics/supply unchanged
- [ ] requirements unchanged

---

# Independent review

Use:

```text
superpowers:requesting-code-review
```

Review the incremental diff from:

```text
cab619cf2d0c043886ceb713b4ae35b42fd891bc
```

to the new HEAD.

The reviewer must specifically check the four original blockers:

1. Decimal precision
2. diagnostics/complete semantics
3. user-input 500 path
4. missing API integration tests

Fix all Critical/Important findings.

---

# Commit

Create one review-fix commit, suggested:

```text
fix: harden analysis API correctness
```

Do not squash/rewrite the original PR commit unless the Codex harness requires it.

---

# Update existing PR #36

Use the native Codex Cloud PR handoff to update existing PR #36.

Do not:

```text
run shell git push
create PR #37
merge PR #36
```

If native handoff shows an `Update PR` or equivalent action, use that.

---

# GitHub Actions

After the updated PR head is published, inspect Actions for that exact new head SHA.

Required:

```text
python-tests = success
windows-portable-smoke = success
```

For `python-tests`, confirm the logs actually show:

```bash
python -m pytest -q
```

with zero failures.

Do not rely on the previous green CI for `cab619cf...`. The new commit requires fresh CI.

---

# Final report

Return:

1. PR URL — must still be PR #36
2. branch
3. previous head `cab619cf2d0c043886ceb713b4ae35b42fd891bc`
4. new final head
5. review-fix commit SHA
6. exact changed files
7. Decimal regression input/output
8. proof no precision loss
9. proof global Decimal context unchanged
10. missing-tariff API result
11. resulting `response.complete`
12. resulting top-level diagnostic codes
13. invalid `acquiring_rate` result
14. invalid `buyout_rate` result
15. negative optimizer threshold result
16. happy-path `/api/analysis` allocation
17. availability vs recommendation proof
18. seller-stock limit proof
19. Kazan -> Moscow demand result
20. counterfactual-zero result
21. duplicate recommendation result
22. conflicting recommendation result
23. PII regression result
24. 413 result
25. focused pytest result
26. `tests/api` result
27. core regression result
28. full pytest result
29. `node --check` result
30. `git diff --check` result
31. independent review findings
32. fixes after review
33. GitHub Actions `python-tests` result
34. GitHub Actions `windows-portable-smoke` result
35. confirmation requirements unchanged
36. confirmation analytics unchanged
37. confirmation economics unchanged
38. confirmation supply unchanged
39. confirmation PR #36 remains UNMERGED.
