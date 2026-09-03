# PR4 — Real-Data Quality & Coverage — Design Brief

**Date:** 2026-09-03  
**Status:** approved scope/design brief; implementation plan follows after PR3 contracts are stable  
**Parent design:** `docs/superpowers/specs/2026-09-03-real-data-demand-stockout-flow-design.md`

## 1. Purpose

Make incomplete real-data analysis understandable and actionable instead of exposing a raw repeated technical log.

Real manual testing produced repeated messages such as:

```text
MISSING_ARTICLE_TO_SKU
WORKSHEET_DIMENSION_REPAIRED
INCOMPLETE_LOGISTICS_COVERAGE
MISSING_TARIFF
MISSING_SELLER_AVAILABLE_STOCK
MISSING_PRODUCT_ECONOMICS
```

The current frontend prints every diagnostic object individually. That is useful for developers but not for an operator.

PR4 has two responsibilities:

1. classify whether real missing coverage is caused by genuine missing source data or bounded normalization/import/mapping defects;
2. expose grouped user-facing data-quality states while preserving raw diagnostics for technical inspection.

## 2. Do not hide genuine missing data

The fix is not to default missing values to zero or fabricate coverage.

Examples:

- no matching tariff → route economics remains incomplete;
- no seller available stock → physical planning remains unavailable for affected SKU;
- no product economics → unit economics remains unavailable;
- unresolved cluster mapping → affected calculations remain blocked.

UI improvement must make the gap clearer, not make incomplete calculations look complete.

## 3. Diagnostic grouping model

Group repeated diagnostics by user-actionable cause.

A grouped diagnostic should carry equivalent fields:

```text
severity
user_title
user_explanation
primary_code
related_codes[]
affected_count
affected_entity_type
affected_entities[]
blocks[]
action_hint
```

Exact dataclass names are fixed in the PR4 implementation plan.

Raw `DiagnosticView` objects remain available under a technical disclosure.

## 4. Causal grouping

Do not show both a root cause and every repeated consequence at equal prominence.

Example:

```text
MISSING_TARIFF × 34
→ INCOMPLETE_LOGISTICS_COVERAGE
→ unit/route economics unavailable
```

Primary user message:

```text
34 маршрута без тарифа
Экономика этих маршрутов не рассчитана.
```

The aggregate blocker may be retained as technical detail but should not become another giant primary warning.

## 5. Required user-facing groups

### 5.1 Missing tariff coverage

Primary message equivalent to:

```text
34 маршрута без тарифа
Экономика этих маршрутов не рассчитана.
[Посмотреть маршруты]
```

Affected entities must identify exact `origin → destination` and, where relevant, SKU/volume context needed to diagnose why the tariff did not match.

### 5.2 Missing seller stock

Primary message equivalent to:

```text
7 SKU без доступного остатка продавца
План для этих товаров не рассчитан полностью.
[Посмотреть SKU]
```

Do not treat missing stock as zero stock.

### 5.3 Missing product economics

Primary message equivalent to:

```text
9 SKU отсутствуют в Юнитке
Юнит-экономика и размещение для них недоступны.
[Посмотреть SKU]
```

### 5.4 Unitka article outside current SKU universe

`MISSING_ARTICLE_TO_SKU` should normally be a non-blocking warning when the Unitka simply contains more assortment than the active Ozon SKU universe.

Primary message equivalent to:

```text
18 статей Юнитки не относятся к текущему SKU universe
На расчёт остальных товаров не влияет.
```

Affected article list is available on expansion.

### 5.5 Worksheet dimension repaired

`WORKSHEET_DIMENSION_REPAIRED` is technical recovery evidence when import succeeded.

Primary message equivalent to:

```text
25 диапазонов Excel автоматически восстановлены при чтении.
```

It must not occupy dozens of primary warning lines.

## 6. Severity language

Use operator-facing categories rather than raw backend severity alone:

```text
КРИТИЧНО / БЛОКИРУЕТ
ПРЕДУПРЕЖДЕНИЕ
ТЕХНИЧЕСКАЯ ИНФОРМАЦИЯ
```

A group is blocking only for the calculations it actually blocks. Avoid implying that one missing route tariff invalidates every unrelated SKU.

## 7. Coverage investigation

Before UI grouping is considered complete, PR4 must inspect actual affected identities to answer:

- is `MISSING_TARIFF` caused by truly missing tariff rows or canonical-cluster mismatch;
- is `MISSING_SELLER_AVAILABLE_STOCK` caused by a source gap or wrong SKU mapping;
- is `MISSING_PRODUCT_ECONOMICS` caused by truly absent Unitka rows or article/SKU identity mismatch.

If the issue is a bounded normalization/import/mapping defect, PR4 may repair it with regression tests.

If investigation reveals a separate major tariff/source-model defect, do not inflate PR4. Create a dedicated corrective PR before PR5.

## 8. Data screen information hierarchy

The user-facing Data screen should follow this hierarchy:

```text
Качество расчёта

КРИТИЧНО
- grouped blocking causes

ПРЕДУПРЕЖДЕНИЯ
- grouped non-blocking causes

Техническая диагностика
[Показать raw diagnostics]
```

The primary layer should be bounded even if thousands of raw diagnostics exist.

## 9. Affected-entity drill-down

Each grouped issue may expand into a bounded/searchable list of exact affected entities.

Examples:

```text
route: Казань → Москва · SKU-1
sku: 39439 / SKU-1
article: 43135
worksheet/report source
```

Do not expose buyer/order PII.

## 10. Backend/frontend responsibility

Backend should perform causal grouping/counting where business meaning is required.

Frontend may render groups, expand details, search and sort affected entities.

Frontend must not infer that `INCOMPLETE_LOGISTICS_COVERAGE` is caused by `MISSING_TARIFF` by parsing English messages.

## 11. Copy contract

Primary user copy is Russian and action-oriented.

Raw codes stay in a technical disclosure.

Avoid primary messages such as:

```text
No tariff row matches this route. MISSING_TARIFF
```

when the system can say:

```text
Маршрут Казань → Москва не покрыт тарифами.
```

## 12. Required proofs

PR4 tests must prove:

1. 100 identical `MISSING_TARIFF` diagnostics become one grouped user issue with count 100;
2. affected route identities remain inspectable;
3. `INCOMPLETE_LOGISTICS_COVERAGE` is represented as a consequence, not duplicated as a peer flood;
4. missing stock remains unknown/blocked, not zero;
5. missing product economics remains blocked;
6. Unitka out-of-universe rows are non-blocking when appropriate;
7. worksheet repair messages collapse to one technical/info group;
8. different root causes do not merge incorrectly;
9. raw diagnostic codes remain available;
10. no PII appears in grouped affected entities;
11. real-scale diagnostic input produces bounded primary UI output.

## 13. Out of scope

PR4 does not:

- change demand or need formulas;
- change stockout episode detection;
- change financial impact math;
- redesign the full Flow screen;
- fabricate tariffs, stock or product economics;
- introduce a new frontend framework.

## 14. Merge gate

PR4 is mergeable only when:

- real coverage gaps are classified;
- bounded source/mapping defects found in scope have regressions;
- genuine missing data remains incomplete;
- grouped diagnostics expose counts and affected entities;
- root causes are more prominent than repeated consequences;
- Russian user copy replaces raw-message floods;
- raw technical diagnostics remain accessible;
- primary UI remains bounded at real scale;
- full pytest and Windows portable smoke are green.
