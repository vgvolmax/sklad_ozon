# UX Contract

## Status and precedence

This root contract is the durable cross-screen behavior contract for the shipped API-first application.

Read current/target behavior in this order:

1. `docs/superpowers/specs/2026-09-09-ozon-api-first-shipment-planner-design.md` for active business/data/operational ownership;
2. `docs/superpowers/specs/2026-09-09-api-first-plan-ui-design.md` for `План` / `Данные` behavior;
3. this file for durable cross-screen behavior and current runtime baseline;
4. `DESIGN.md` for visual identity/tokens.

There is no active correction/amendment overlay.

The superseded selected-network / PlanningSnapshot workflow is not an active future requirement. Do not reconstruct `SupplyNetworkSelector`, network-only replan, selected-network coverage planning or old `План размещения` behavior from Git history/archive.

The root contract describes the shipped PR-E runtime. Historical wide-Plan and selected-network workflows are not supported.

## Product context

- Audience: owner/manager planning Ozon FBO placement and shipments.
- Primary jobs: compare Ozon vs own demand model; inspect demand/fulfillment geography; get Calculated Plan; convert it into whole-pack shipment quantities; choose real seller/handoff points and observed Ozon windows; export exact manual templates.
- Locale: `ru-RU`.
- Register: dense professional operational UI, not marketing.
- Accessibility target: WCAG 2.2 AA; all functions remain reachable at 200% zoom.

## Visual contract

- `DESIGN.md` owns approved visual identity/tokens.
- Runtime remains committed vanilla HTML/CSS/JavaScript.
- Preserve light engineering-console language, compact spacing, stable geometry and semantic color roles.
- `Ozon → Наша потребность → План` remains the signature comparison line.
- No gradients, glassmorphism, dark-dashboard language, decorative KPI mosaics or Ozon-brand imitation.
- Color is never the only carrier of status.

## Canonical navigation

Top-level routes remain exactly:

```text
План
Потоки спроса
Экономика
Данные
```

Inside `План`:

```text
Товары | Отгрузки
```

Historical `Потоки спроса` remains a first-class analytical route and is not a shipment scheduler.

## Shared behavior ownership

Recurring behavior must have one shared owner. Equivalent screen-local copies are prohibited.

Existing/shared owners include concepts equivalent to:

```text
SearchField
Notice/status
ProgressPanel
DataTable/table framing
FormState
FlowView
RankedBars where already used
```

API-first PR-E adds/standardizes:

```text
OzonConnectionPanel
CredentialVaultDialog
SourceModePanel
PlanEntitySelector
PlanProductWorkspace
PlanClusterWorkspace
ShipmentIntentForm
SellerWarehouseSelector
HandoffPointSelector
ShipmentManifest
OzonValidationStatus
OzonConnectionDiagnostic
```

`OzonConnectionDiagnostic` is the shared manual and pre-sync preflight. It
shows the sequential DNS, protected-connection, Seller API and API-permission
checks with separate elapsed times. A failed check leaves later checks visibly
not run and, when invoked by `Обновить данные`, states that data synchronization
was not started. Only a fully ready preflight may continue into streaming sync;
successful Seller API authorization and application readiness remain distinct.

The old `SupplyNetworkSelector` is not an active future owner.

## Component behavior baseline

All enabled interactive controls provide stable:

```text
default
hover
focus-visible
active/selected
disabled
busy
error
```

Busy state must not change control geometry. Errors are persistent and correction-oriented. Toasts may acknowledge, but never hold the only actionable failure detail.

Use semantic native buttons, labels, inputs, checkboxes and tables where appropriate. No browser `alert`, `confirm` or `prompt` for normal product flows.

## Async/stale-response contract

External/source/analysis/shipment actions are explicit user actions.

Required behavior:
- duplicate submit prevention;
- request/run identity so stale responses cannot replace newer state;
- previous successful result stays visible during refresh and recoverable failure;
- edited draft values remain available for correction/retry;
- source refresh, analysis recalculation and shipment validation own separate freshness states;
- Ozon/API failure never silently switches to FILES mode.

## Data-source UX

API is the primary operational source. FILES is an explicit reserve workflow, not an automatic peer toggle.

`Данные` hierarchy:

```text
Ozon connection/session
→ source basis/freshness by business domain
→ local Unitka / pack inputs
→ explicit manual FILES fallback
```

API and FILES domains are not mixed inside one analysis run.

Secrets never appear in long-lived frontend state, URL, Project JSON, logs or source snapshots.

Keep distinct:

```text
Данные Ozon обновлены
План рассчитан
Варианты Ozon проверены
```

API `source_as_of` is backend-owned and read-only in UI. API history depth is backend policy, not an everyday UI control.

Source failures expose a correction-oriented cause when safe structured evidence exists. Scoped SKU incompleteness is distinguishable from global endpoint failure: globally available evidence with affected SKU identities is shown as partial, not fully available or globally failed.

The API source-status list covers API data only. Recommendation is uploaded in
`Данные` alongside Unitka as `Доступность товаров · рекомендации Ozon` for an
API-backed calculation. This is the sole allowed recommendation-channel XLSX
exception; the separate FILES mode remains the reserve analytical workflow.
The form preserves both selected files during unrelated renders and identifies
the current API snapshot date. The recommendation file is optional: without it,
the calculated plan remains available and Ozon comparison is unknown. Selecting the XLSX immediately starts backend validation against the current API
SKU and cluster catalogs. The file shows accepted/excluded rows, SKU/cluster counts,
report dates, horizon and diagnostics before calculation. Pending or invalid selected
files block calculation; retry and remove actions stay next to the upload. Removing
the optional file restores the own-model workflow. Changing the API snapshot or
horizon revalidates the retained upload; stale asynchronous responses cannot authorize
calculation. Final analysis independently repeats the same validation rules.
A horizon or business-date mismatch keeps the own-model plan available and
explains why the Ozon comparison is unavailable. No stale API recommendation
status or remote recommendation request is shown during source refresh.

A failed refresh keeps the previous successful source evidence separate from diagnostics for the failed attempt. The project cluster-mapping editor remains reachable from `Данные` in both API and FILES modes.

## Ozon connection/vault UX

First setup collects Client-Id, masked API-Key, vault password and confirmation. Saved API key is never shown again. Restart asks only for vault password.

Unlocked connection view exposes masked Client-Id suffix and actions to refresh, lock and replace connection.

No inactivity auto-lock in active scope.

Wrong password/auth/network failures preserve entered values where safe and provide specific recovery steps.

## Article-first Plan contract

Presentation is article-first; canonical state identity is SKU:

```text
selectedSku = stable item identity
article = primary seller-facing label
```

Never collapse multiple Ozon SKUs sharing one article.

Left selector is bounded and shows one item per SKU-backed product context. Search matches article/SKU/name with explicit clear.

Selected-product header shows identity once plus pack multiple, resolved seller stock, whole-pack available, unit volume, zone evidence and freshness.

Unknown = `Не рассчитано`, never frontend zero fallback.

Decision line keeps `Ozon → Наша потребность → План`. If no exact comparable Ozon signal exists, say so explicitly instead of substituting another metric.

Selected-SKU cluster table default fields:

```text
Кластер
FBO
В пути
Ozon
Потребность
Аналитический план
Кратность
К поставке
Объём
Зона
Статус
```

Pack rounding is visible but not a warning by itself.

## Shipment intent contract

Controls:

```text
date range
allowed methods
selected destination clusters
preferred/max clusters per shipment
seller warehouse when cross-dock requires selection
remote handoff point selection
explicit Найти варианты в Ozon action
```

Editing controls marks shipment state dirty only and makes no automatic API call.

Initial cluster scope:
- first complete positive ShippablePlan → all positive complete clusters selected;
- after explicit user change → preserve surviving IDs; newly appearing clusters unselected.

Selected scope is filter-only over existing all-cluster ShippablePlan and never reallocates stock.

## SellerWarehouseSelector contract

Seller warehouses come from current source snapshot.

Cross-dock rules:

```text
0 active → blocking unavailable
1 active → resolved automatically / shown as fixed context
>1 active → user must choose Склад отправления
```

DIRECT does not require the cross-dock seller warehouse field.

Persisted ID is preference only; backend validates current active identity. Do not expose contacts/courier comments.

## HandoffPointSelector contract

Handoff points are remote Ozon search results, not bulk catalog data.

```text
<4 trimmed chars → no request
>=4 → ~300 ms debounced localhost search
```

Required:
- IME-safe input;
- stale-response protection;
- explicit clear;
- previous selected points remain visible during search failure;
- show returned name/address/point type;
- no free-form warehouse-ID input;
- preferred IDs after restart are unresolved preferences until backend search evidence resolves them;
- cross-dock action blocked until required IDs resolve.

## Candidate/validation lifecycle

Keep three concepts distinct:

```text
Кандидат
Проверено Ozon
реальная заявка на поставку
```

Current milestone implements only first two. It may create temporary drafts for checking and does not create a real supply request.

Near `Найти варианты в Ozon` disclose that temporary drafts may be created and real supply requests are not created.

Forbidden success copy before future PR-F:

```text
Поставка создана
Забронировано
Заявка подтверждена
```

Observed timeslot may say `Окно доступно при проверке`.

## Shipment manifest contract

Validated option is a restrained logistics worksheet, not decorative KPI card.

Show when available:

```text
date / method
seller warehouse for cross-dock
concrete handoff point
clusters
accepted qty / estimated item volume / SKU count
Ozon acceptance state
timeslot evidence
optional travel time
checked timestamp
placement-zone composition / manual packing note
```

Rejected/partial items remain visible with article/SKU/cluster/qty and human-readable cause.

Keep causal states distinct:

```text
Ozon отклонил состав
Нет доступных окон
Ozon ограничил частоту проверок
Не удалось связаться с Ozon
Результат создания временного черновика неизвестен
Не подходит по локальному ограничению
Склад отправления недоступен/не выбран
Точка отгрузки устарела/не разрешена
```

Network failure must not render as product rejection.

## PVZ and placement zones

PVZ 1000 L is candidate-total estimated item-volume pre-check.

Before validation use `Предварительно подходит для ПВЗ`.

Passing does not prove packed volume, box count, per-box weight or exact point acceptance.

Placement-zone evidence is backend-owned and survives into candidate/manifest. Multiple zones may produce manual packing guidance; frontend never fabricates boxes/pallets or recomputes compatibility.

## Export UX

Only backend-validated/exportable ranked options expose `Скачать шаблоны Ozon`.

One cluster → XLSX; multiple → ZIP. Browser never generates/repairs quantities.

Backend same-article identity/pack conflicts fail closed; export failure stays local to the manifest and does not erase validated evidence.

## Flow/Economics contracts

Historical Flow remains focused/bounded and preserves destination/origin/SKU semantics. Every visual relationship has exact text equivalent; origin is fulfillment evidence, not future demand ownership.

Economics keeps current mathematical ownership. Shipment ranking is operational/service-level; customer-delivery route costs are not seller→Ozon inbound tariff evidence.

The Economics workspace initially groups the same observed delivered-route rows by
SKU. One SKU expansion is a single highlighted surface containing its cluster
breakdown; expanding a cluster creates a nested highlighted surface. Its
`Где заказали` and `Откуда отгрузили` cuts are two views of the same routes,
not additive totals. The separate route list always repeats article, SKU,
origin and destination. Search, bounded load-more and partial coverage remain
visible in both views. Opening a SKU enters a selected-article view: other articles
return only after collapse. Its cluster region owns bounded vertical scrolling with
overscroll containment; the article context and sticky collapse action stay reachable.
The selected article's own history remains available. Collapse restores the prior
list/window position and disclosure focus; Escape outside editors/charts also closes.
Scenario redraws retain the cluster scroll. If a changed selection excludes the SKU,
the view returns to the list. No global document/body scroll lock is introduced.

A small copy button beside the exact SKU is independent of disclosure, has an
accessible name, and deliberately has no visual hover tooltip. It announces a small
anchored success popup only after clipboard write succeeds. Denial offers manual
copying; superseded async clicks cannot announce a success for the latest failed click.

Margin and ROI targets, selected pricing goal and planned DRR are local
scenario preferences. Python calculates weighted route averages, commission,
modeled target shortfall and a price at unchanged rates/logistics. Planned DRR
only affects prospective price. Read-only real DRR recalculates current
margin, ROI and modeled shortfall on the same observed route mix without
mutating the analysis snapshot. Unknown real DRR shows `n/a` and its reason,
but applies an explicit `В расчёте 0 %` assumption. A SKU
without observed routes remains visible with an unknown shortfall and price.
Economics uses delivered postings by acceptance date inside an inclusive selected
interval from loaded observations, including the loaded current week. Plan/Flow
retain their completed-week window. This is not a confirmed buyout or Ozon payout
ledger. The UI names the calculation and observation bounds and labels its shortfall as modeled,
not as actual financial loss for the current month. A tariff step, a new
price's effect on demand are outside this scenario. Uploaded advertising spend
is joined strictly by SKU; import results disclose matched article/name/SKU.
A missing route blocks a universal price recommendation.

Commission is displayed as percent with rubles per unit immediately below it.
Actual evidence uses teal above purple plan/target values, with explicit labels;
colors alone do not convey the distinction. Necessary price is below seller price,
margin/ROI above their goals. Below-goal status remains textual. Actual financial
values are still the existing model based on the immutable snapshot, not a payout
statement. Advertising amount/period details remain inspectable below DRR. The
minimum positive price to reach the chosen goal may be lower than the current price;
lowering has a green amount plus explicit down arrow/delta and a separate filter.
Unreachable/incomplete goals stay unknown. The scenario does not model new demand
or tariffs after a price change.

A compact card follows the selected interval and search/filter: current-rate
profit on delivered routes before advertising, available uploaded advertising
spend for the same selection/interval, and their difference once. Pre-ad profit
is calculated independently, never by subtracting spend from the already DRR-adjusted
per-unit profit. Unreported expense is unknown; reported zero is known zero.
Partial route/history profit and known-advertising SKU counts remain explicit.
This is a model after known uploaded expenses, not a complete payout statement.

Each product row ends with a compact, independently expandable daily panel for
SPP, buyer price and orders. All three charts use the same calendar for the loaded
order period, without inheriting the completed-week/delivered route filter.
The selected interval also owns advertising DRR and Excel. Day/week controls
change chart buckets only: ISO weeks run Monday–Sunday with clipped edges and
unit-weighted price/SPP means. Table and viewport positions, editor focus and
expanded SKU panels survive redraws. Full-width 3px separators distinguish SKUs.
FBO customer prices omitted by list endpoints are recovered with optional posting
detail requests in a separate background job. Demand/source synchronization remains
usable immediately. Visible SKU prices get priority, charts poll while their prices
are pending, and immutable price evidence is bound to the source/credential context.
Account changes and newer refreshes discard obsolete results. Only validated price
numbers, SKU, lifecycle and hashed references enter the account-scoped cache.
Orders means ordered units of all lifecycle states and channels. Daily SPP is the
quantity-weighted average of each order's `(seller-buyer)/seller`; buyer price is
the quantity-weighted unit price. Price and SPP have independent valid-price
coverage. A missing pair leaves known daily means visible with covered-unit counts,
never silently presents them as complete and never manufactures prices. Incomplete
history cannot manufacture zero-order days. Both lines use observed min/max bounds,
center constant values and break at missing days. Hover, touch and keyboard expose
date/mean SPP/mean buyer price/orders, with arrow/Home/End/Escape support, visible
focus and a popup constrained by the visible table viewport. Loading, missing
evidence and retryable errors stay local to the panel. Visible SKU histories are
requested in bounded batches; old snapshot responses cannot overwrite new ones.
Raw history prices/records stay server-side; only daily aggregates reach the browser.

Each cached API order channel carries an optional price-normalization version.
Legacy channels refresh their existing loaded history once on normal refresh;
subsequent complete channels resume the 28-day overlap even if Ozon genuinely
omits prices. Historical money is joined by canonical SKU; blank canonical fields
may use explicit matching financial evidence, malformed/non-RUB evidence cannot.

Cost is a visible, editable column, including when other economics evidence is
incomplete. Enter or leaving the field saves the cost atomically to Project
schema v5 (`data/project.json`); the field shows pending, source and persistent
failure with retry, retaining the failed draft. The article-level directory
keeps manual costs ahead of later Unitka imports; consistent imported costs
are saved only with a successful analysis commit. The next analysis consumes
these costs. An existing Economics snapshot can immediately show a cost scenario,
while Plan is marked stale and shipment preparation/export requires recalculation.
Cost changes during an analysis or shipment check cannot commit an old result.
Older Project schemas v1–v4 migrate without losing existing mappings or quantities.

Economics has separate downloads for the stored cost directory and a compact
Excel report. Python owns the common search/filter selection used by the displayed
rows, summary and XLSX. The report includes every matching SKU, independent of
the bounded display/load-more limit. An empty selection disables download. It has
one SKU per row and only
article, product, current price, planned/real/applied DRR, margin, ROI, target margin,
required price, commission rubles per unit, interval/quantity and exact SKU.
Required price follows the selected margin/ROI goal; target margin
remains the explicit margin setting. Missing values stay blank, rates/money are
numeric. Shared/blank articles are allowed; missing or repeated SKU identity blocks
export instead of merging rows. Draft cost edits, a failed scenario or pending
calculation disable report download. Export failures remain separate, allowing retry
without disabling a valid report. A changed pending selection cannot offer an old
download. Search is IME-safe, debounced with immediate clear/Enter, and ignores stale
responses. No route detail sheets are exported.

## Responsive/zoom

Plan's compact table and inline evidence preserve all exact values and working-plan actions in both perspectives. Each line remains `SKU × destination_cluster_id`; context selection never changes shipment scope.

Flow search restores focus after rendering so typing can continue. Context
summary labels follow the selected origin/destination role, and exact route
selection continues to own the timeline and SKU breakdown.

Data preparation steps come from the active source and selected/validated
inputs. The optional recommendations XLSX never becomes a prerequisite for
the own-model calculation. Source diagnostics and economic settings can be
collapsed; setting a field error reveals its containing disclosure. A normal
source/status refresh must not recreate the analysis form or clear file
selections. Pack editing/import/export and mappings remain actionable in the
secondary panel.

Desktop/laptop primary. At narrow width/200% zoom:
- the horizontal context strip and controls reflow above full-width detail;
- tables own horizontal overflow;
- root page must not use `overflow:hidden` to fake fit;
- shipment controls stack logically;
- manifest actions remain reachable.

## Shipped API-first ownership

The runtime, `DESIGN.md`, and this contract agree on:

```text
API-first Data hierarchy
SKU-backed article-first Plan
SellerWarehouseSelector
remote HandoffPointSelector
shipment intent / temporary validation lifecycle
candidate-total PVZ semantics
zone composition/manual packing guidance
backend export
no selected-network future workflow
no real supply creation
```

The user remains the final actor and completes the real supply manually in Ozon.

## Кратность упаковки

Раздел «Данные» содержит постоянный справочник кратности по артикулу: поиск по артикулу, inline-редактирование, импорт и экспорт XLSX, а также сброс override к прайсу РТП или к неизвестной кратности. Юнитка не является источником кратности. Источник показывается как «Вручную», «Импорт», «Прайс РТП» или «Не задано». Новое inline-значение считается сохранённым только после ответа backend; ошибки остаются рядом с действием.

Изменение справочника в PR1 не меняет уже рассчитанный план. Будущее применение выполняется отдельно для каждой строки `SKU × кластер`, без объединения потребностей разных кластеров.

## Working Plan editing

- The Plan table distinguishes `Рекомендация` from editable `К поставке`, and shows signed `Δ` plus volume calculated from the working quantity.
- `−` and `+` move by exactly one known pack. Direct input commits on Enter and cancels on Escape; invalid input is never rounded or saved. Zero is an explicit valid decision.
- Manual lines say `вручную`, automatic lines say `авто`, and a manual line offers `К нашему расчёту`, which deletes the override and Ozon selection rather than copying a value.
- The compact summary exposes ready, attention, manual, and orphan counts. Product and cluster perspectives share one authoritative server response.
- In API mode, the Ozon column identifies the exact `Рекомендуемая поставка` value from the uploaded Ozon XLSX with source horizon and report dates. Its exact quantity, the manager-selected source, and the final working quantity remain distinct. Ozon may be selected only when backend evidence and quality gates allow it; return to the own model is always available on a selected line. The per-view bulk action names suitable and skipped rows and reports server results.
- After source selection, the backend changes `working_plan_id` and invalidates candidate, validation and export results. The manager can download a separate provenance worksheet; the Ozon import template keeps its existing three columns.
- A changed recommendation preserves the manual decision and calls out the change. Stock/capacity conflicts preserve individually valid entries but block execution. Working Plan load failure never falls back to browser-calculated quantities.


## Plan context cards and inline evidence (2026-09-30)

The approved Plan prototype replaces the permanent sidebar with one horizontal
context strip (`PlanWorkspace` in `plan_workspace.js`). Product IDs are SKU;
cluster IDs are destination cluster identities from the analysis. Duplicate
articles remain separate SKU cards. Switching perspective preserves each
selection and changes presentation only. Search is immediate, IME-safe and
has a clear action; it filters cards without changing the opened context.
Card attention/manual filters are independent of the selected table's filters.
A native `AppDialog` full picker searches all contexts and paginates at 100;
selection clears incompatible strip filters so the chosen context is visible.
The strip caps rendering at 120 plus its selected matching item, exposes arrows,
visible scrollbars, arrow/Home/End focus navigation and Enter/Space selection.

The compact table retains exact FBO/inbound/orders/Ozon/Need/analytical values,
pack multiple, server working quantity, delta, volume and concise status.
Expanding a line colors its row and all evidence as one surface. Evidence
contains full identity, all reasons, zones, unit volume, seller stock, original
whole-pack system recommendation and current selected-source recommendation,
plus the existing source choice/reset actions. Unknown quantity differs from
explicit zero. Qualified known subtotal is displayed alongside unknown count;
attention/blocked statuses remain explicit and never claim shipment acceptance.
Working Plan load failure leaves quantities unknown without browser fallback.

Enter commits exact integers through the existing backend; Escape cancels.
IME composition never submits. Invalid or server-rejected input stays beside
an associated field error. Only successful server responses change quantities.
Global mutation/stale guards remain authoritative and shipment evidence is
invalidated by successful edits or source choice. Table/strip scroll and focus
survive render. Bulk actions name and confirm the exact selected context and
row-filter scope; accepting our calculation explicitly removes manual quantities and Ozon selections in that scope. Global reset names both quantities and sources. Source bulk confirms the eligible/skipped scope; returning to our model preserves manual quantities. A confirmation captures analysis and working-plan identities and is rejected after replacement or invalidation.
Global override reset has a separate confirmation. Single-line editing remains
reversible through the existing server reset; no browser undo ledger is added.
`AppDialog` in `components.js` owns native modal focus, Escape, title, close and
focus restoration; its shared styling uses existing tokens.

Opening Shipments leaves its real intent, active warehouse/handoff search,
explicit validation, temporary-draft disclosure and export flow unchanged.
It performs no Ozon request merely because a context or a tab was selected.
Browser acceptance lives in `tests/browser/plan_workspace_smoke.py`: production
assets with synthetic response contracts, external requests blocked, desktop,
narrow/reflow, source disclosure, editing/error/retry, exact bulk scope, keyboard
and modal restoration. Existing backend and Flow tests remain required.

## Economics advertising evidence

The optional advertising batch picker lives only on Economics. Match by SKU;
article is a display label. The normalized campaign/SKU/day expense directory
is atomic and persists across restarts. A repeated report is idempotent; a
corrected report replaces overlapping campaign dates. Different campaigns add
expense while all-order revenue is counted once per SKU/day. Per-file results
retain failed files for retry and list unmatched SKU. Failed writes preserve
the previous directory. Deleting a campaign uses shared AppDialog confirmation.

The row label is `Реальный`, read-only, never a fallback to scenario/local
preferences. Overall DRR uses all posting states and FBO/FBS seller revenue
over the expense dates, never attributed sales or averaged vendor percentages.
Missing complete evidence means `n/a`; the current Economics model applies
0% with an explicit assumption label, preserving margin/ROI/shortfall when
all other route inputs are complete. Unknown source expense remains unknown.
Planned DRR remains editable and drives target pricing independently. Ad
imports do not change Data uploads, source mode, Demand, Need or Plan.
