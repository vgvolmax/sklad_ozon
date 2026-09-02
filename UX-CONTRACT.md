# UX Contract

## Product context

- **Audience:** владелец/менеджер Ozon FBO, принимающий решения по размещению ограниченного товарного остатка.
- **Primary jobs:** сравнить Ozon с собственной оценкой спроса; понять реальную географию спроса и исполнения; увидеть стоимость origin→destination связок; проверить юнит-экономику; получить объяснимый план поставки.
- **Target market:** русскоязычная работа с Ozon FBO.
- **Active locale:** `ru-RU`.
- **Language/content register:** плотный рабочий интерфейс без маркетинговой лексики; пользовательские объяснения на русском, технические codes только в диагностике.
- **Timezone/calendar policy:** локальные даты отчётов отображаются как date-only без преобразования часового пояса; время импорта отображается в локальном времени приложения. ISO week используется только в аналитическом слое.
- **Accessibility target:** WCAG 2.2 AA.

## Business-context sources

| Domain / scope | Authoritative source | Source type | Reviewed date |
|---|---|---|---|
| Demand geography, fulfillment semantics, stockout/distortion, economics | `docs/superpowers/specs/2026-08-19-ozon-fbo-unit-economics-optimizer-design.md` | Historical business design; remains authoritative where not superseded | 2026-09-02 |
| Runtime/backend/frontend boundary | `docs/superpowers/specs/2026-08-20-scoz-lite-portable-architecture-design.md` | Canonical technical architecture | 2026-09-02 |
| Product Completion, own demand estimate, hybrid plans, route economics, new UI | `docs/superpowers/specs/2026-09-02-ozon-fbo-product-completion-design.md` | Canonical Product Completion design | 2026-09-02 |

This contract records frontend consequences only. Business formulas live in the Product Completion design and backend domain/application layer, not in frontend code.

## Visual contract

- **Project `DESIGN.md`:** `/DESIGN.md`.
- **Token ownership:** current CSS is legacy until Product Completion migration. After migration, `frontend/assets/css/app.css` contains the single runtime semantic token block and `DESIGN.md` mirrors the accepted values. Screen-local duplicate tokens are forbidden.
- **Runtime design-system source:** plain CSS custom properties + shared vanilla JS/HTML primitives.
- **Supported themes:** light theme only for MVP; forced-colors/high-contrast must remain operable.
- **Design-context review policy:** any durable palette, typography, radius, density, visualization or interaction change updates `DESIGN.md`/this contract in the same change.

## Canonical UI Map

The current frontend has no reusable component system. Product Completion must create each owner once and reuse it. Equivalent screen-local implementations are prohibited.

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Dataset table | `SkladOzon.DataTable` | this contract | plan / economics / diagnostics | unit + browser + keyboard |
| Search | `SkladOzon.SearchField` | this contract | local dataset search | keyboard + clear behavior |
| Select | native `<select>` wrapped by shared field styling | this contract + DESIGN | native only while OS popup is accepted | keyboard + popup |
| Date | native `input[type=date]` in Data section | this contract | native | locale + keyboard |
| Form | `SkladOzon.FormState` | this contract | import/settings/scenario | validation + duplicate-submit |
| Scrollbar | global application stylesheet | `DESIGN.md` | geometry exceptions only | computed style/browser |
| Toast/status | `SkladOzon.Notice` | this contract | success / warning / info / error | live region |
| Detail drawer | `SkladOzon.DetailDrawer` | this contract | SKU / route detail | focus + narrow viewport |
| Flow visualization | `SkladOzon.FlowView` | Product Completion design + DESIGN | destination / origin / SKU | keyboard + text parity |
| Ranked bar breakdown | `SkladOzon.RankedBars` | Product Completion design + DESIGN | units / share / margin pp / profit rub | text parity + keyboard |
| Progress | `SkladOzon.ProgressPanel` | this contract | import / analysis / recalculation | async/failure browser test |

Table row multi-selection and CRUD destructive actions are not part of the Product Completion scope and therefore have no canonical owner yet.

## Component behavior

| Component | Default | Hover | Focus | Active/selected | Disabled | Busy | Error |
|---|---|---|---|---|---|---|---|
| Button | semantic label, stable size | deliberate surface change | visible focus ring | pressed state | non-interactive appearance + reason when non-obvious | same geometry + progress state | nearby persistent message |
| Search | value + clear button when non-empty | controls visible | focus ring | n/a | n/a | local search has no busy state | n/a |
| Input/select | label + current value | border emphasis | focus ring | n/a | visually distinct, no handler | form submit owns pending | inline text + `aria-invalid` |
| Data table | stable columns/row height | row affordance only when interactive | focused controls visible | selected row/context distinct from hover | n/a | table frame remains stable | partial error does not destroy prior successful snapshot |
| Cluster card | demand + local/external share + economics | indicates selectable | focus ring | clear selected border/marker | unavailable only with explanation | n/a | incomplete data shown as incomplete, not zero |
| Flow link/node | exact value always available in text | highlight relationship | keyboard target focus | selected path emphasized | non-computable link remains inspectable with incomplete badge | n/a | missing tariff/economics shown explicitly |
| Drawer | contextual read-only detail | n/a | focus begins at heading/first action | open state | n/a | sub-section pending preserves drawer | inline failure + retry |

## Dataset navigation

### Plan and economics tables

- Default local pagination: **50 rows/page**; choices **25 / 50 / 100**.
- Dataset is a completed immutable analysis snapshot, so pagination/filtering/sorting are client-side unless a future API contract explicitly changes ownership.
- Single-column sort by default; Shift+click may add secondary sort only if implemented consistently by the shared table owner.
- 8+ visible columns require a `Колонки` chooser. User choice is stored locally.
- Search is local and immediate; no debounce is required while no network request is issued. Clear button clears immediately and restores focus.
- URL/search state preserves active section, committed search, filters, sort, page and page size where values are shareable. File paths/names and sensitive local values are never put in URL.
- Filter or search change resets page to 1. Page is clamped after dataset changes.
- Empty dataset differs from no-results state. No-results offers `Очистить фильтры`.
- Table body owns scrolling; toolbar/header/pagination remain in the table frame.

### Plan filters

Canonical fast filters:

- `Все`
- `Есть расхождение`
- `Вероятный дефицит`
- `Дорогая логистика`
- `Неполная экономика`
- `Заблокировано`

`Есть расхождение` is the primary analytical view but the application must remember the user's last selected filter rather than forcing it on every return.

## Navigation and route state

Top-level routes/sections:

1. `План`
2. `Потоки спроса`
3. `Экономика`
4. `Данные`

Implementation may use hash routing in the vanilla frontend. Route state must support Back/Forward and preserve section-specific filter state during the session.

Document titles:

- `План — Sklad Ozon`
- `Потоки спроса — Sklad Ozon`
- `Экономика — Sklad Ozon`
- `Данные — Sklad Ozon`

A SKU/route drawer does not change the document title unless a future decision makes it a bookmarkable route.

## Main decision workflow

1. User imports/validates data in `Данные`.
2. User opens `План`.
3. User chooses horizon in days, inbound-supply flag and optimization scenario.
4. Application shows the most recent successful snapshot until recalculation succeeds. Changed inputs make it visibly `Требуется пересчёт`; old and new values must never be silently mixed.
5. User activates `Пересчитать план`.
6. Stable progress area shows stage/message; duplicate submit is blocked.
7. On success the new immutable snapshot atomically replaces the old result.
8. On failure the previous successful result remains visible and is clearly labelled as previous; settings/file selections are preserved for retry.
9. User primarily reviews disagreement rows and opens a SKU detail drawer when evidence is needed.

## Decision-line contract

The canonical comparison sequence is always:

`Ozon → Наша потребность → План`

Where useful, show beneath it:

- `Δ шт.` and `Δ %` to Ozon;
- Ozon horizon and our selected horizon;
- a warning `Горизонты различаются`, when they are not directly comparable;
- expected profit and route-economic opportunity.

Ozon values use the Ozon semantic visual role; our estimate and plan use the model role. Neither is labelled as an error merely because values differ.

## SKU detail drawer

Drawer order is causal and fixed:

1. `Решение`
2. `Динамика спроса`
3. `Как исполняется спрос`
4. `Ozon vs наша модель`
5. `Экономика`
6. `Доказательства и диагностика`

The drawer is non-modal. Background content remains available; no focus trap or inert background. On open, focus moves to the drawer heading or first relevant control. On close, focus returns to the originating row/control.

Raw backend status/explanation codes may appear only in the final diagnostic disclosure. Main copy is localized human-readable reasoning.

## `Потоки спроса` contract

### Purpose

This is a first-class analytical mode for a human to inspect demand→fulfillment relationships visually. It is not hidden behind the stockout model and is not a debug screen.

### Modes

- **По кластеру спроса:** select destination; inspect which origins fulfill it.
- **По кластеру отгрузки:** select origin; inspect which destinations it fulfills.
- **По артикулу:** select SKU/article; inspect its geographic demand and fulfillment pattern.

### Metric selector

The same visual structure can encode:

- `Штуки`
- `Доля спроса, %`
- `Потери маржи, п.п.`
- `Потери прибыли, ₽`

Changing metric changes the quantitative encoding, not the selected cluster/SKU context.

### Overview

Cluster cards show:

- total destination demand;
- local fulfillment share;
- external fulfillment share;
- donor count;
- current non-local route cost effect;
- local-placement opportunity in ₽ where computable.

Cards are comparison controls, not decorative KPIs.

### Focused flow view

For destination mode the selected destination is the central hub. Incoming origin connections show exactly who fulfills the demand. For origin mode the selected origin is central and connections show destinations. For SKU mode, the view focuses on the SKU and its relevant clusters without attempting a global all-SKU network.

The global all-cluster Sankey/chord diagram is explicitly not the primary view.

Every link has a text equivalent including origin, destination, quantity, share and active metric. Link thickness/color cannot be the only source of information.

### Route selection

Selecting `Казань → Москва` opens route context without losing the main diagram. The context shows:

- units on route;
- share of Moscow demand;
- route logistics cost ₽ and `% of realization`;
- current net margin;
- local Moscow→Moscow counterfactual margin if feasible/complete;
- margin delta in percentage points;
- profit opportunity in ₽;
- evidence completeness/confidence.

If local counterfactual is infeasible or economics/tariff coverage is incomplete, show `Не рассчитано` plus reason. Never coerce missing values to zero.

### SKU breakdown inside a route

A selected route exposes ranked horizontal bars by SKU/article. Every bar shows exact text values:

- quantity;
- share of selected route;
- share of destination demand;
- route cost effect;
- margin/profit opportunity where available.

Bars are sortable through the metric selector and keyboard accessible. A compact accessible table/text list must expose the same values for assistive technology and precise inspection.

### Historical vs cleaned evidence

Where stockout cleaning changes interpretation, the user can switch between `Наблюдаемое` and `Очищенное` evidence or view both side-by-side in the detail area. The default business conclusion uses cleaned evidence when the Product Completion business rules deem it eligible; the UI must always disclose which evidence source is driving the conclusion.

## Economics workflow

The main Plan table shows only decision-level economics: margin, profit/unit, expected plan profit, route-cost opportunity.

Detailed economics lives in the drawer and `Экономика` section. It must expose line items from realization through commissions, acquiring, FBO/logistics, advertising/services, taxes, cost, profit, margin and ROI.

For route analysis the user can compare `Фактическое исполнение` vs `Локальное размещение`. Both use the same non-route assumptions; only route/placement-dependent costs change according to backend contracts. The frontend never recomputes the unit economics.

## Scenario controls

Canonical scenario inputs:

- horizon in days;
- `Учитывать поставки в пути` boolean flag;
- optimization objective: `Макс. прибыль` or `Макс. маржа`.

No automatic safety-stock/buffer control exists. Users who want extra coverage increase the horizon.

Scenario changes never mutate imported data. A completed analysis is an immutable snapshot with explicit settings and report metadata.

## Upload/background-job flow

| Operation | Trigger | Pending | Success destination | Success feedback | Failure recovery | Focus outcome |
|---|---|---|---|---|---|---|
| Import + analysis | `Рассчитать`/`Пересчитать план` | stable progress panel; trigger busy/disabled | current section with new snapshot | inline success status with elapsed time | preserve prior snapshot and input state; show retryable error | result heading on first success; error summary on failure |
| Open SKU detail | row/link activation | none or local loading region | same route + drawer | none | inline drawer error if detail unavailable | drawer heading |
| Close SKU detail | Close/Escape | n/a | same table state | none | n/a | originating row/control |
| Change flow node/route | cluster/link activation | no full-page loading | same Flow route | selected context updates | missing detail shown inline | selected node/context heading |
| Search/filter | input/control | local synchronous update | same section | result count | no-results offers clear | remains in control |

## Forms and validation

- Product forms use `novalidate` and app-owned validation.
- Errors are inline text and associated through `aria-invalid`/`aria-describedby`.
- On submit failure, focus/scroll to first invalid field; long forms may include a concise error summary.
- Numeric scenario fields reject negative values and invalid numbers; units are visible in label/suffix.
- Duplicate analysis submit is impossible while a run is active.
- File selections and non-sensitive settings survive server/analysis errors.
- The current native date picker remains acceptable for the Data section; date-only values must not shift through timezone conversion.

## Feedback and diagnostics

- Routine success uses persistent inline state or shared notice; do not spam toasts after every local filter/selection.
- Critical import/analysis errors remain visible until corrected/retried.
- Raw stack traces/backend payloads never appear in product UI.
- Diagnostic codes are available in an expandable technical section with human-readable messages.
- Report freshness warnings remain visible near the data context and in Data section; a stale/mismatched report cannot be silently presented as current.

## Async and resilience

- Analysis/recalculation is pessimistic: previous successful snapshot stays active until a full new snapshot succeeds.
- Older/stale async completion must never overwrite a newer run.
- Cancel/abort may be added when backend supports it; until then duplicate runs are blocked.
- A network/server failure does not clear imported file labels, scenario inputs or previous results.
- Loading/error regions reserve stable geometry.
- No browser `alert()`, `confirm()` or `prompt()`.

## Responsive/accessibility behavior

- Desktop is primary, but every function must remain reachable at narrow width and 200% zoom.
- Real comparison tables use horizontal scrolling rather than silently becoming cards.
- Flow visualization may stack overview → visualization → context vertically on narrow windows; exact text data remains available even if the diagram is simplified.
- Visible keyboard focus is mandatory on navigation, filters, cluster cards, flow nodes/links, bars, drawer actions and table controls.
- Tooltip is never the sole carrier of a value.
- `prefers-reduced-motion` removes nonessential transitions.

## Migration status

Current `frontend/index.html`, `frontend/assets/css/app.css` and `frontend/assets/js/app.js` are legacy single-screen implementations. Product Completion is an intentional migration, not a requirement to preserve existing visual structure.

Migration priorities:

1. introduce shared token/state/component owners;
2. move import/settings into `Данные`;
3. add top-level shell/routes;
4. build `План` decision flow;
5. build `Потоки спроса` visual analytical mode;
6. add economics/detail surfaces;
7. remove raw JSON from primary UI and leave codes in diagnostics only.

Do not perform unrelated backend refactors as part of this UI migration.

## Verification

Before UI implementation is considered complete:

- run repository formatter/syntax/tests/CI commands actually configured by the repo;
- run Frontend Design Premium static project audit in strict mode when the skill runtime is available;
- lint/reconcile `DESIGN.md` and verify runtime token mapping;
- browser-test success, loading, failure, empty/no-results and stale-report states;
- keyboard-test navigation, search clear, table sorting/pagination, drawer open/close, flow node/link selection and metric selector;
- test one normal desktop width, one narrow width and 200% zoom;
- verify reduced motion and forced-colors/high-contrast operability;
- verify no raw backend code replaces user-facing explanation;
- verify `Потоки спроса` diagram and text/breakdown totals agree exactly.
