# UX Contract

## Product context

- **Audience:** владелец/менеджер Ozon FBO, принимающий решения по размещению ограниченного товарного остатка.
- **Primary jobs:** сравнить Ozon с собственной оценкой спроса; понять реальную географию спроса и исполнения; выбрать операционную сеть кластеров поставки; увидеть стоимость origin→destination связок; проверить юнит-экономику; получить объяснимый физический план поставки.
- **Target market:** русскоязычная работа с Ozon FBO.
- **Active locale:** `ru-RU`.
- **Language/content register:** плотный рабочий интерфейс без маркетинговой лексики; пользовательские объяснения на русском, технические codes только в диагностике.
- **Timezone/calendar policy:** локальные даты отчётов отображаются как date-only без преобразования часового пояса; время импорта отображается в локальном времени приложения. ISO week используется только в аналитическом слое.
- **Accessibility target:** WCAG 2.2 AA.

## Business-context sources

| Domain / scope | Authoritative source | Source type | Reviewed date |
|---|---|---|---|
| Demand geography, fulfillment semantics, stockout/distortion, economics | `docs/superpowers/specs/2026-08-19-ozon-fbo-unit-economics-optimizer-design.md` | Historical business design; remains authoritative where not superseded | 2026-09-08 |
| Runtime/backend/frontend boundary | `docs/superpowers/specs/2026-08-20-scoz-lite-portable-architecture-design.md` | Canonical technical architecture | 2026-09-08 |
| Product Completion, own demand estimate, Safe/Calculated plans, route economics | `docs/superpowers/specs/2026-09-02-ozon-fbo-product-completion-design.md` | Canonical Product Completion design where later designs are not more specific | 2026-09-08 |
| Real-data demand/routing separation, stockout impact, bounded Flow | `docs/superpowers/specs/2026-09-03-real-data-demand-stockout-flow-design.md` | Canonical real-data roadmap | 2026-09-08 |
| Selected supply network, destination→origin coverage, replan semantics | `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md` | Canonical planning extension | 2026-09-08 |

This contract records frontend consequences only. Business formulas live in the canonical design documents and backend domain/application layer, not in frontend code.

## Visual contract

- **Project `DESIGN.md`:** `/DESIGN.md`.
- **Token ownership:** `frontend/assets/css/app.css` owns runtime semantic tokens after Product Completion migration; `DESIGN.md` mirrors accepted durable values. Screen-local duplicate tokens are forbidden.
- **Runtime design-system source:** plain CSS custom properties + shared vanilla JS/HTML primitives.
- **Supported themes:** light theme only for MVP; forced-colors/high-contrast must remain operable.
- **Design-context review policy:** any durable palette, typography, radius, density, visualization or interaction change updates `DESIGN.md`/this contract in the same change.
- Selected-network planning introduces no new visual identity; it extends the established dense logistics-console language.

## Canonical UI Map

The frontend must create each behavioral owner once and reuse it. Equivalent screen-local implementations are prohibited.

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Dataset table | `SkladOzon.DataTable` | this contract | plan / economics / diagnostics | unit + browser + keyboard |
| Search | `SkladOzon.SearchField` | this contract | local dataset / selector search | keyboard + clear behavior |
| Select | native `<select>` wrapped by shared field styling | this contract + DESIGN | native only while OS popup is accepted | keyboard + popup |
| Date | native `input[type=date]` in Data section | this contract | native | locale + keyboard |
| Form state | `SkladOzon.FormState` | this contract | import / scenario / dirty-applied state | validation + duplicate-submit |
| Supply network selector | `SkladOzon.SupplyNetworkSelector` | 2026-09-08 design + this contract | draft / applied | keyboard + dirty-state + failure recovery |
| Scrollbar | global application stylesheet | `DESIGN.md` | geometry exceptions only | computed style/browser |
| Toast/status | `SkladOzon.Notice` | this contract | success / warning / info / error | live region |
| Detail drawer | `SkladOzon.DetailDrawer` | this contract | SKU / route / coverage detail | focus + narrow viewport |
| Flow visualization | `SkladOzon.FlowView` | canonical product designs + DESIGN | historical destination/origin/SKU; planned coverage context | keyboard + text parity |
| Ranked bar breakdown | `SkladOzon.RankedBars` | canonical product designs + DESIGN | units / share / margin pp / profit rub | text parity + keyboard |
| Progress | `SkladOzon.ProgressPanel` | this contract | import / full analysis / network replan | async/failure browser test |

Table row multi-selection and CRUD destructive actions are not part of this product scope and therefore have no canonical owner yet.

## Component behavior

| Component | Default | Hover | Focus | Active/selected | Disabled | Busy | Error |
|---|---|---|---|---|---|---|---|
| Button | semantic label, stable size | deliberate surface change | visible focus ring | pressed state | non-interactive appearance + reason when non-obvious | same geometry + progress state | nearby persistent message |
| Search | value + clear button when non-empty | controls visible | focus ring | n/a | n/a | local search has no busy state | n/a |
| Input/select | label + current value | border emphasis | focus ring | n/a | visually distinct, no handler | form submit owns pending | inline text + `aria-invalid` |
| Supply network selector | applied summary + `Изменить` | clear action affordance | focus ring on trigger/checkbox/search | checkboxes represent draft only until successful recalc | unavailable cluster has explicit reason | selector stays editable until request starts; request locks apply action | previous applied network remains authoritative; draft preserved |
| Data table | stable columns/row height | row affordance only when interactive | focused controls visible | selected row/context distinct from hover | n/a | table frame remains stable | partial error does not destroy prior successful result |
| Cluster card | demand + local/external share + economics | indicates selectable | focus ring | clear selected border/marker | unavailable only with explanation | n/a | incomplete data shown as incomplete, not zero |
| Flow link/node | exact value always available in text | highlight relationship | keyboard target focus | selected path emphasized | non-computable link remains inspectable with incomplete badge | n/a | missing tariff/economics shown explicitly |
| Drawer | contextual read-only detail | n/a | focus begins at heading/first action | open state | n/a | sub-section pending preserves drawer | inline failure + retry |

## Dataset navigation

### Plan and economics tables

- Default local pagination: **50 rows/page**; choices **25 / 50 / 100**.
- The Plan view is rendered from one active immutable `AnalysisSnapshot` plus one active immutable `PlanningSnapshot` referencing that analysis. Pagination/filtering/sorting remain client-side over bounded presentation rows unless a future API contract changes ownership.
- Plan quantities come from the active `PlanningSnapshot`; upstream demand/need evidence comes from its referenced `AnalysisSnapshot`.
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

`Есть расхождение` is the primary analytical view but the application remembers the user's last selected filter rather than forcing it on every return.

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
3. User sets horizon, inbound flag and the global supply network. `MAX_MARGIN` remains fixed and is not a control.
4. Network checkbox edits are **draft only** and issue no request.
5. Any changed upstream input or network selection marks the visible result `Требуется пересчёт`; the previous applied result remains visible and must not be silently mixed with draft inputs.
6. User activates the single action `Пересчитать план`.
7. If only the network is dirty, the application performs downstream replan against the active AnalysisSnapshot. If any upstream analysis input is dirty, it performs full analysis and includes the current draft network.
8. Stable progress/busy state blocks duplicate submit without moving controls.
9. Full-analysis success atomically installs a new AnalysisSnapshot plus its initial PlanningSnapshot. Network-only success atomically installs a new PlanningSnapshot referencing the unchanged active AnalysisSnapshot.
10. Only after success does the draft network become applied/persisted. Failure preserves the previous applied analysis/planning result and keeps draft inputs for retry.
11. User reviews destination decisions and the physical origin supply roll-up; detail drawers provide evidence when needed.

## Decision-line contract

The canonical comparison sequence is always:

`Ozon → Наша потребность → План`

For a destination row, `План` means **final covered quantity of that destination target**, not physical inbound quantity into that destination cluster.

Where useful, show beneath it:

- `Δ шт.` and `Δ %` to Ozon;
- Ozon horizon and our selected horizon;
- warning `Горизонты различаются` when they are not directly comparable;
- expected profit and route-economic opportunity;
- explicit uncovered cause when coverage is incomplete.

Ozon values use the Ozon semantic visual role; our estimate and plan use the model role. Neither is labelled as an error merely because values differ.

## Physical supply roll-up

The Plan screen exposes an origin-oriented roll-up derived only from final coverage legs:

```text
Москва — поставить 600
  свой спрос        500
  другие кластеры   100
    Казань            50
    Тверь             30
    Ярославль         20
```

- Calculated Plan is the default roll-up and canonical `Наш план`.
- Safe Plan is a separately labelled conservative comparison and is never summed with Calculated Plan.
- Roll-up values are backend-owned; frontend only groups/renders presentation aggregates already supplied by the backend.
- A user can drill from origin total to destination composition without losing origin/destination identity.

## Uncovered-state vocabulary

The UI must keep three causes distinct:

- **Не покрыто выбранной сетью** — no selected physically feasible/tariff-complete origin or capacity.
- **Заблокировано правилами расчёта** — desired placement existed but economics/threshold eligibility failed.
- **Не хватило доступного товара** — placement was eligible but seller stock was exhausted.

Do not collapse these into one generic deficit state.

## SKU detail drawer

Drawer order is causal and fixed:

1. `Решение`
2. `Динамика спроса`
3. `Как исполняется спрос`
4. `Ozon vs наша модель`
5. `Экономика`
6. `Доказательства и диагностика`

The `Решение` area may include `Где лежит запас` coverage breakdown for the current destination.

The drawer is non-modal. Background content remains available; no focus trap or inert background. On open, focus moves to the drawer heading or first relevant control. On close, focus returns to the originating row/control.

Raw backend status/explanation codes may appear only in the final diagnostic disclosure. Main copy is localized human-readable reasoning.

## `Потоки спроса` contract

### Purpose

This is a first-class analytical mode for a human to inspect demand→fulfillment relationships visually. It is not hidden behind the stockout model and is not a debug screen.

### Top-level view separation

The Flow section separates evidence from decision:

```text
История | План размещения
```

`История` contains observed/clean historical fulfillment. `План размещения` contains planned coverage from the active PlanningSnapshot. Planned coverage is never represented as a third historical evidence source.

`План размещения` defaults to Calculated Plan. Safe Plan may be shown as an explicitly labelled comparison.

### Historical modes

- **По кластеру спроса:** select destination; inspect which origins fulfilled it.
- **По кластеру отгрузки:** select origin; inspect which destinations it fulfilled.
- **По артикулу:** select SKU/article; inspect its geographic demand and fulfillment pattern.

### Metric selector

The same visual structure can encode:

- `Штуки`
- `Доля спроса, %`
- `Потери маржи, п.п.`
- `Потери прибыли, ₽`

Changing metric changes the quantitative encoding, not the selected cluster/SKU context.

### Overview

Historical cluster cards show:

- total destination demand;
- local fulfillment share;
- external fulfillment share;
- donor count;
- current non-local route cost effect;
- local-placement opportunity in ₽ where computable.

Cards are comparison controls, not decorative KPIs.

### Focused historical flow view

For destination mode the selected destination is the central hub. Incoming origin connections show exactly who fulfilled the demand. For origin mode the selected origin is central and connections show destinations. For SKU mode, the view focuses on the SKU and its relevant clusters without attempting a global all-SKU network.

The global all-cluster Sankey/chord diagram is prohibited as the primary view.

Every link has a text equivalent including origin, destination, quantity, share and active metric. Link thickness/color cannot be the only source of information.

### Planned placement view

The planned view reuses the same bounded selected-context grammar but renders only PlanningSnapshot coverage aggregates. It must visually state that it is a recommendation/plan, not historical fulfillment.

For a selected origin it can show destinations whose demand is planned to be served there; for a selected destination it can show origins holding its planned serving stock.

No route-count-dependent unbounded canvas is allowed.

### Route selection

Selecting a historical route such as `Казань → Москва` opens route context without losing the main diagram. Historical route context shows:

- units on route;
- share of Moscow demand;
- route logistics cost ₽ and `% of realization`;
- current net margin;
- local Moscow→Moscow counterfactual margin if feasible/complete;
- margin delta in percentage points;
- profit opportunity in ₽;
- evidence completeness/confidence.

If local counterfactual is infeasible or economics/tariff coverage is incomplete, show `Не рассчитано` plus reason. Never coerce missing values to zero.

A selected planned coverage leg instead shows planned quantity, coverage type, direct tariff/economics, source of physical feasibility, and uncovered/eligibility reason where relevant.

### SKU breakdown inside a route

A selected historical route exposes ranked horizontal bars by SKU/article. Every bar shows exact text values:

- quantity;
- share of selected route;
- share of destination demand;
- route cost effect;
- margin/profit opportunity where available.

Bars are sortable through the metric selector and keyboard accessible. A compact accessible table/text list exposes the same values for assistive technology and precise inspection.

### Historical vs cleaned evidence

Inside `История`, the user can switch between `Наблюдаемое` and `Очищенное` evidence or view both side-by-side in the detail area. The UI always discloses which evidence source is driving a historical conclusion.

Historical shares remain informational and never become planned placement weights.

## Economics workflow

The main Plan table shows only decision-level economics: margin, profit/unit, expected plan profit, route-cost opportunity.

Detailed economics lives in the drawer and `Экономика` section. It exposes line items from realization through commissions, acquiring, FBO/logistics, advertising/services, taxes, cost, profit, margin and ROI.

For historical route analysis the user can compare `Фактическое исполнение` vs `Локальное размещение`. Both use the same non-route assumptions; only route/placement-dependent costs change according to backend contracts.

For planned coverage, economics comes from direct `origin → destination` planning contracts. The frontend never recomputes unit economics.

## Scenario controls

Canonical user inputs:

- horizon in days;
- `Учитывать поставки в пути` boolean flag;
- global `Сеть поставки` cluster selection.

The optimization strategy is fixed to margin priority and is not a user control.

### Supply network defaults and persistence

- First use with no persisted network: all current candidate clusters with at least one explicitly allowed SKU are selected.
- After successful calculation, the applied network persists in Project JSON.
- New clusters appearing in later restrictions data default unselected; the app never silently expands a persisted network.
- Missing/unresolved previously selected clusters are surfaced as a reconciliation warning.
- Checkbox edits remain draft until successful `Пересчитать план`.

No automatic safety-stock/buffer control exists. Users who want extra coverage increase the horizon.

Scenario/network edits never mutate imported data or an existing immutable snapshot.

## Upload/recalculation flow

| Operation | Trigger | Pending | Success destination | Success feedback | Failure recovery | Focus outcome |
|---|---|---|---|---|---|---|
| Full import + analysis | `Рассчитать` / `Пересчитать план` with upstream dirty state | stable progress panel; trigger busy/disabled | current section with new AnalysisSnapshot + initial PlanningSnapshot | persistent inline success state | preserve prior applied result + draft inputs; retry | result heading on first success; error summary on failure |
| Network-only replan | `Пересчитать план` with only network dirty | compact/stable recalculation progress; trigger busy/disabled | same Plan route with new PlanningSnapshot | applied-network summary updates after success | keep prior PlanningSnapshot applied; preserve draft network | plan heading / initiating control according to canonical focus behavior |
| Open SKU detail | row/link activation | none or local loading region | same route + drawer | none | inline drawer error if detail unavailable | drawer heading |
| Close SKU detail | Close/Escape | n/a | same table state | none | n/a | originating row/control |
| Change flow node/route | cluster/link activation | no full-page loading | same Flow route | selected context updates | missing detail shown inline | selected node/context heading |
| Search/filter | input/control | local synchronous update | same section | result count | no-results offers clear | remains in control |

## Forms and validation

- Product forms use `novalidate` and app-owned validation.
- Errors are inline text and associated through `aria-invalid`/`aria-describedby`.
- On submit failure, focus/scroll to first invalid field; long forms may include a concise error summary.
- Numeric scenario fields reject negative values and invalid numbers; units are visible in label/suffix.
- Supply-network search has an explicit clear button when non-empty.
- Network checkbox labels are real activation targets; keyboard and pointer behavior are equivalent.
- Duplicate analysis/replan submit is impossible while a run is active.
- File selections, draft network and other non-sensitive settings survive server/analysis errors.
- The current native date picker remains acceptable for the Data section; date-only values must not shift through timezone conversion.

## Feedback and diagnostics

- Routine success uses persistent inline state or shared notice; do not spam toasts after local filter/selection.
- Critical import/analysis/replan errors remain visible until corrected/retried.
- Raw stack traces/backend payloads never appear in product UI.
- Diagnostic codes are available in an expandable technical section with human-readable messages.
- Report freshness warnings remain visible near the data context and in Data section; stale/mismatched reports cannot silently appear current.
- Applied network, draft network and active analysis/planning IDs must never be visually conflated.

## Async and resilience

- Recalculation is pessimistic: previous successful applied result stays visible until the entire replacement succeeds.
- A network-only replan never mutates the active AnalysisSnapshot; it returns a new PlanningSnapshot referencing that analysis.
- A PlanningSnapshot response for an `analysis_snapshot_id` that is no longer active is stale and is discarded.
- Older/stale async completion must never overwrite newer applied state.
- Cancel/abort may be added when backend supports it; until then duplicate runs are blocked.
- A network/server failure does not clear imported file labels, scenario inputs, draft network or previous applied result.
- Loading/error regions reserve stable geometry.
- No browser `alert()`, `confirm()` or `prompt()`.

## Responsive/accessibility behavior

- Desktop is primary, but every function remains reachable at narrow width and 200% zoom.
- Real comparison tables use horizontal scrolling rather than silently becoming cards.
- The supply-network selection surface remains searchable and usable at narrow width without hiding selected state.
- Flow visualization may stack overview → visualization → context vertically on narrow windows; exact text data remains available even if the diagram is simplified.
- Visible keyboard focus is mandatory on navigation, filters, network trigger/search/checkboxes, cluster cards, flow nodes/links, bars, drawer actions and table controls.
- Tooltip is never the sole carrier of a value.
- `prefers-reduced-motion` removes nonessential transitions.

## Migration status

Product Completion and real-scale Flow are already being migrated into the canonical multi-section product. Selected-network planning extends that architecture rather than restoring legacy single-screen behavior.

Migration priorities for this feature:

1. preserve current demand/stockout/Flow owners;
2. add immutable PlanningSnapshot ownership without mutating AnalysisSnapshot;
3. create/reuse shared supply-network selection state;
4. add physical origin supply roll-up;
5. extend Flow with `История | План размещения` without changing historical evidence contracts;
6. keep formulas backend-owned and remove/deprecate any stale plan fields read from base analysis after replan.

Do not perform unrelated backend/frontend refactors as part of this migration.

## Verification

Before selected-network UI implementation is considered complete:

- run repository formatter/syntax/tests/CI commands actually configured by the repo;
- run Frontend Design Premium static project audit in strict mode when the skill runtime is available;
- lint/reconcile `DESIGN.md` when visual tokens/components change and verify runtime token mapping;
- browser-test success, loading, failure, empty/no-results and stale-report states;
- verify checkbox changes alone issue no recalculation request;
- verify the single `Пересчитать план` chooses full analysis vs network-only replan correctly;
- verify failed replan preserves previous applied plan and draft network;
- verify stale PlanningSnapshot responses cannot attach to a newer AnalysisSnapshot;
- keyboard-test navigation, network selector/search/checkboxes, search clear, table sorting/pagination, drawer open/close, flow node/link selection and metric selector;
- test one normal desktop width, one narrow width and 200% zoom;
- verify reduced motion and forced-colors/high-contrast operability;
- verify no raw backend code replaces user-facing explanation;
- verify historical `Потоки спроса` diagram/text totals still agree exactly;
- verify planned coverage totals agree with PlanningSnapshot conservation invariants.

## PR5 — Real-scale historical Flow contract

- Historical Flow is selected-context-first in destination, origin, and SKU modes; the selector is searchable, internally scrollable, and renders at most 100 rows.
- Historical overview contains at most eight exact backend-ranked routes and one non-interactive `Прочие` presentation row. `Прочие` is never a route or economics entity.
- The complete historical route list is searchable, paged at 100 exact rows, and selects only backend `route_key` values.
- `Собственный спрос` is always destination-owned demand. Origin context separately labels own destination demand, physical dispatch, same-cluster fulfillment, and other-cluster demand.
- `Динамика локальности` remains the signature fixed-height historical visual and consumes only backend destination daily series and episode intervals. Unknown local share creates a line gap, never a false zero.
- Daily values are paged at 50, episodes at 20, exact route SKU values at 100, and ranked SKU bars at 12.
- Missing economics is `Не рассчитано`; signed negative economics says that local placement is worse/has lower margin. A matching data-quality blocker provides a concise reason and `Открыть в «Данные»` action.
- Evidence changes routing interpretation, never own destination demand or factual timeline geography. No route-count-dependent SVG/canvas is permitted.
- Planned placement lives beside this contract under `История | План размещения`; it does not alter historical evidence-source semantics.
