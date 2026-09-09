# PR-A Supply Facts & Pack Multiplicity Implementation Plan

> Implement task-by-task with TDD. Read `AGENTS.md` and the canonical API-first shipment design first.

**Goal:** add seller-local pack multiplicity and normalized operational supply facts needed by the whole-pack layer, without changing existing demand/Need/Safe/Calculated Plan semantics.

## Global invariants

- Existing analytics and seller-stock resolver stay unchanged.
- Pack multiplicity is seller-local evidence from supplier workbook.
- Missing/conflicting multiplicity never defaults to `1`.
- API mode uses API placement-zone/supply facts from PR-API2.
- FILES mode may retain restrictions workbook as dated conservative evidence only.
- Restrictions `Рекомендуемая поставка на 56 дней` is reference/diagnostic only; it never replaces current analytical Ozon recommendation or feeds `calculate_need()`.

---

## Task 1 — supplier article normalization

**Create/modify:** supplier packaging importer + focused tests.

Canonical article normalization:

```text
"40750" → "40750"
40750 → "40750"
40750.0 → "40750"
40750.5 → invalid/diagnostic
blank → invalid
```

Trim string identifiers but do not numeric-coerce arbitrary alphanumeric articles.

Tests must include integer-like Excel numeric cells explicitly.

---

## Task 2 — parse pack multiplicity

Source contract:

```text
sheet: Прайс списком
КОД → seller article
Упак → positive integer to the right of '/'
```

Examples:

```text
72/6 → 6
36/6 → 6
54/9 → 9
100+/1 → 1
```

`Оглавление!КРАТНОСТЬ` is not product multiplicity.

Add immutable result/evidence contract carrying:

```text
article
pack_multiple: int | None
source row/value
diagnostic reasons
```

Duplicate identical evidence may collapse; conflicting positive values are blocking for that article.

---

## Task 3 — normalized supply facts

Define/extend immutable operational evidence for each `SKU × destination cluster` with fields needed downstream, including:

```text
sku
article
cluster_id
placement_zone_kind
placement_zones
fallback restriction eligibility/capacity evidence where FILES mode provides it
restriction report date when known
```

API placement-zone evidence is authoritative for API-mode current pre-checks. Do not infer zones from dimensions.

FILES restriction capacity semantics remain conservative dated snapshot evidence:

```text
any allowed unlimited warehouse → cluster unlimited
else max positive finite allowed value
all allowed zero → zero
no usable allowed evidence → unknown/ineligible
```

Do not sum warehouse maxima.

---

## Task 4 — join pack evidence to product/SKU identity

Join supplier multiplicity by normalized seller article while preserving canonical SKU identity.

If one seller article maps to multiple Ozon SKUs:
- do not collapse the SKUs;
- the same pack multiple may be attached when article evidence is unambiguous;
- retain identity diagnostic for downstream UI/export safeguards.

Missing article mapping or conflicting multiplicity makes operational quantity incomplete for affected SKU but does not invalidate historical demand/Need.

---

## Task 5 — regression gate

Add tests for:
- `40750.0 → "40750"`;
- non-integer numeric article rejected;
- missing/conflicting multiplicity;
- placement-zone unknown/multiple preservation;
- FILES restriction zero/unlimited/finite aggregation;
- restrictions 56-day recommendation cannot alter Safe/Calculated/Need;
- no second seller-stock resolver introduced.

Run focused supply/import tests, then:

```bash
python -m pytest tests/analytics tests/decision tests/supply -q
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
python -m pytest -q
```

Acceptance: every operational SKU has explicit pack evidence or a causal blocker; no silent `×1`, identity drift or analytical formula change exists.