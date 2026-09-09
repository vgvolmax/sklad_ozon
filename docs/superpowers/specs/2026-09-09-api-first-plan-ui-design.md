# API-First Plan UI — Frontend Design Premium Contract

**Date:** 2026-09-09  
**Status:** APPROVED / ACTIVE UI TARGET  
**Scope:** frontend consequences of `2026-09-09-ozon-api-first-shipment-planner-design.md`  
**Supersedes:** archived 2026-09-08 article-first Plan amendment for active implementation.  
**Runtime note:** root `DESIGN.md` / `UX-CONTRACT.md` continue to describe the currently shipped UI until PR-E changes runtime; PR-E must update both root contracts in the same changeset.

## 1. Design intent

Preserve the existing Sklad Ozon visual identity. This is not a rebrand.

Keep:

- light engineering-console register;
- existing semantic palette and tokens;
- Golos Text / JetBrains Mono roles;
- compact data density;
- decision-line signature `Ozon → Наша потребность → План`;
- four top-level sections: `План`, `Потоки спроса`, `Экономика`, `Данные`;
- historical Flow as its own analytical mode.

Do not add gradients, glass, dark-dashboard language, decorative KPI mosaics or Ozon-brand imitation.

The new memorable operational element is the **shipment manifest**: a restrained logistics worksheet showing exact date/method/clusters/quantity and Ozon evidence state.

## 2. Canonical UI ownership

New recurring behaviors have one owner each:

```text
OzonConnectionPanel
CredentialVaultDialog
SourceModePanel
ArticlePlanSelector
PlanProductWorkspace
ShipmentIntentForm
HandoffPointSelector
ShipmentManifest
OzonValidationStatus
```

They may be implemented as shared functions in the existing vanilla `SkladOzon` namespace. Equivalent screen-local variants are prohibited.

Reuse existing shared SearchField, Notice, ProgressPanel, button/input styling, scrollbar baseline and Flow primitives.

## 3. `Данные` — API first hierarchy

The default screen starts with Ozon connection/source state, not a wall of upload controls.

Desktop structure:

```text
Данные

┌─ Ozon API ───────────────────────────────────────────────────┐
│ ● Подключено                         Синхронизировано 08:31  │
│ Client-Id ···4821                                           │
│ [Обновить данные] [Заблокировать] [Заменить подключение]    │
└──────────────────────────────────────────────────────────────┘

Данные Ozon
Заказы                    ✓ 08:31
Остатки FBO               ✓ 08:31
Поставки в пути           ✓ 08:31
Остаток продавца          ✓ 08:31
Кластеры / склады         ✓ 08:31
Зоны размещения           ✓ 08:31

Наши данные
Юнитка                    ✓ актуальна
Кратность поставщика      ✓ актуальна

Резервный режим
[Использовать ручной импорт]
```

The Ozon panel is a work-status surface, not a decorative card.

## 4. Credential vault flows

### 4.1 First setup

Use an app-owned form/dialog:

```text
Подключить Ozon API

Client-Id
[________________________]

API-Key
[••••••••••••••••••••••] [Показать]

Пароль хранилища
[••••••••••••••]

Повторите пароль
[••••••••••••••]

Пароль понадобится после каждого запуска приложения.
Если пароль будет утерян, подключение нужно настроить заново.

[Сохранить и проверить подключение]
```

Rules:

- API key and passwords are masked by default;
- `Показать` exists only while entering/replacing a new API key;
- never show the saved key again;
- no browser-native validation bubbles;
- invalid fields keep values, expose inline correction text and `aria-invalid`;
- busy button geometry is stable;
- setup success replaces the form with connection status;
- setup failure never logs/displays the API key.

### 4.2 Locked after restart

```text
Ozon API
○ Хранилище заблокировано

Пароль
[••••••••••••••]
[Разблокировать]
```

Wrong password:

```text
Не удалось разблокировать хранилище.
Проверьте пароль и попробуйте ещё раз.
```

Do not expose cryptographic terms to the end user.

### 4.3 Unlocked session

```text
● Подключено
Client-Id ···4821
Хранилище разблокировано для этой сессии
```

Actions:

```text
Обновить данные
Заблокировать
Заменить подключение
```

No automatic inactivity lock. Manual lock and process exit end the unlocked session.

## 5. Source mode UX

API is the primary mode. FILES is a reserve workflow, not a peer toggle.

Do not render a casual radio/toggle like:

```text
API | Excel
```

Primary state:

```text
Основной источник: Ozon API
[Использовать ручной импорт]
```

Entering manual mode must explain before switching:

```text
Ручной импорт используется как резервный режим.
Данные API и файлов в одном расчёте не смешиваются.
Live-проверка поставок зависит от разблокированного Ozon API.
```

After explicit switch:

```text
Источник расчёта: ручной импорт
```

File upload controls then become visible. Returning to API mode is another explicit action.

Never silently fall back after API failure.

## 6. Sync progress and freshness

`Обновить данные` initiates one explicit sync operation. Show stable progress with business stages, for example:

```text
Обновляем данные Ozon
3 из 6 · Остатки FBO
```

The previous successful source snapshot remains available and visibly marked stale while refresh runs/fails.

Required data states:

```text
Актуально
Обновляется
Устарело
Недоступно
Неполные данные
Ручной источник
```

Show three distinct timestamps when relevant:

```text
Данные Ozon обновлены
План рассчитан
Варианты Ozon проверены
```

Do not collapse all freshness into one timestamp.

## 7. `План → Товары`

### 7.1 Master/detail

The current giant `SKU × cluster` primary table is replaced.

```text
┌───────────────────────┬───────────────────────────────────────┐
│ Поиск                 │ 40750 · Герметик анаэробный 250 мл  │
│ Фильтры               │ SKU 3118873729                      │
│                       │ Кратность 6 · Остаток 186           │
│ 40750                 ├───────────────────────────────────────┤
│ 40749                 │ Ozon → Потребность → План           │
│ 40748                 │                                       │
│ ...                   ├───────────────────────────────────────┤
│                       │ Кластеры выбранного артикула          │
│                       │                                       │
│                       ├───────────────────────────────────────┤
│                       │ Его назначенные отгрузки              │
└───────────────────────┴───────────────────────────────────────┘
```

One selector item = one article/SKU. Full product name appears once in selected context, not repeated per cluster.

No primary `Открыть детали` on every cluster row.

### 7.2 Left selector

Each item shows only information useful for choosing context:

```text
40750 · короткое имя
SKU secondary
К поставке 102 шт. · 6 кластеров
```

At most one concise warning badge.

Search matches article/SKU/name, is local/immediate and has an explicit clear button.

### 7.3 Product header

```text
article + full product name
SKU
Кратность
Наш resolved остаток
Доступно полными упаковками
Объём/шт.
Зона / качество зоны
Источник/актуальность данных
```

Unknown is `Не рассчитано`, never frontend zero fallback.

### 7.4 Decision line

Preserve the visual signature:

```text
Ozon → Наша потребность → План
```

When exact API Ozon recommendation is unavailable, show:

```text
Ozon: нет сопоставимого API-сигнала
Потребность 101 → Аналитический план 101 → К поставке 102
```

Do not fabricate a replacement recommendation.

### 7.5 Cluster table

Default columns:

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

This table belongs only to the selected article and owns its local overflow/pagination.

Rounding is explicit:

```text
17 → 18 шт.
кратность 6
```

## 8. `План → Отгрузки` — user intent first

The user specifies intent rather than inventing Ozon availability.

Canonical form:

```text
Период поставки
[15.09.2026] — [25.09.2026]

Способы
☑ ПВЗ
☑ СЦ
☑ Прямая

Точки отгрузки
[Новая Рига, ПВЗ …                 ×]
[Хоругвино, СЦ …                  ×]
[Добавить точку]

Кластеры
14 выбрано [Изменить]

Кластеров в одной поставке
Желательно [3]
Максимум  [5]

[Найти варианты в Ozon]
```

Changing any field marks shipment results stale only. It must not trigger backend work automatically.

## 9. Handoff point selector

Cross-dock candidates require a concrete Ozon point. The user chooses from API-returned hand-off points.

Selector behavior:

- searchable by name/address;
- point type visible (`ПВЗ`, `СЦ`, etc.);
- selected point ID is backend/business identity;
- user may save preferred non-secret point IDs/order;
- no free-form warehouse ID input in normal UX;
- a missing required point prevents `Найти варианты` with inline guidance.

DIRECT does not require a cross-dock point.

## 10. Temporary draft disclosure

`Найти варианты в Ozon` is a safe-but-external operation and must say what happens:

```text
Для проверки приложение создаст временные черновики в Ozon.
Реальные заявки на поставку не создаются.
```

This copy is visible near the action; no repetitive confirmation modal is required for every run.

## 11. Candidate / checked / real lifecycle

The UI must distinguish three concepts.

### 11.1 `Кандидат`

Locally generated, not yet sent to Ozon.

### 11.2 `Проверено Ozon`

Temporary draft validation has returned and current timeslot evidence is available.

### 11.3 Real supply

Not represented as a completed app state in this milestone.

Forbidden copy before future PR-F:

```text
Поставка создана
Забронировано
Заявка подтверждена
```

A timeslot discovered for a temporary draft may be labelled:

```text
Окно доступно при проверке 08:47
```

not `забронировано`.

## 12. Shipment manifests

Validated option example:

```text
18 сентября · ПВЗ
Москва · Пермь · Казань

1 930 шт. · 824 л · 17 SKU

Ozon
✓ Состав принят
✓ Доступно окно 14:00–18:00
≈ 3 дня до размещения
Проверено сегодня, 08:47

[Скачать шаблоны Ozon]
```

The manifest is a logistics document, not a KPI card. Use hierarchy, hairline separators and existing tokens; avoid big icons/colors.

Rejected/partial option:

```text
18 сентября · ПВЗ
34 SKU принято
2 SKU не принято Ozon

40750 · Казань
<human-readable Ozon reason>

[Показать детали]
```

Rejections remain in context and are never silently removed.

## 13. Error/state vocabulary

User-facing distinctions must follow backend causal states:

```text
Ozon отклонил состав
Нет доступных окон в выбранный период
Ozon временно ограничил частоту проверок
Не удалось связаться с Ozon
Результат создания временного черновика неизвестен
Не подходит по локальному ограничению
```

Do not turn network/service failure into product rejection.

## 14. PVZ copy

Before Ozon validation:

```text
Предварительно подходит для ПВЗ
```

After successful Ozon draft/timeslot validation:

```text
Состав принят Ozon · окно найдено
```

Still keep operational note when relevant:

```text
Перед фактической отгрузкой проверьте упаковку, число/вес коробов
и требования выбранной точки в Ozon.
```

Do not claim the local item-volume calculation validates final packed cargo.

## 15. Manual export

Every validated exportable manifest exposes one action:

```text
Скачать шаблоны Ozon
```

One cluster → XLSX. Multiple clusters → one ZIP containing per-cluster XLSX.

Export errors stay local to the chosen manifest; the validated schedule remains visible.

## 16. Async resilience

All API operations follow the existing production behavior contract:

- stable control geometry while busy;
- duplicate submit prevention;
- previous successful data/analysis/validation stays visible during refresh;
- stale-response protection by request/run ID;
- cancel superseded local search immediately;
- persistent correction-oriented errors for failures needing action;
- toasts may acknowledge but never hold the only error detail;
- no browser `alert/confirm/prompt`.

## 17. Accessibility / responsive

Target WCAG 2.2 AA.

Use native semantic buttons, labels, inputs, checkboxes and tables where appropriate. All icon-only controls have accessible names. Focus remains visible.

At 200% zoom/narrow desktop:

```text
article selector
↓
selected article detail
```

rather than squeezing two unusable columns.

Shipment intent fields stack logically. Manifest actions remain reachable. Root page must not use `overflow:hidden` to fake fit.

## 18. Root contract migration

PR-E must update root `DESIGN.md` and `UX-CONTRACT.md` in the same changeset as runtime UI so they become the durable post-migration contracts.

Until then:

- this file is authoritative for target API-first Plan/Data behavior;
- root docs remain evidence of currently shipped visual/runtime patterns;
- archived 2026-09-08 UI docs are not implementation sources.

## 19. UI acceptance

Using realistic data (100+ articles, 20+ clusters):

```text
vault setup/unlock/lock is keyboard usable and never reveals saved API key
API sync status and source mode are always obvious
manual fallback is explicit and never silently mixed with API
article appears once in selector, not once per cluster
search 40750 isolates one selected context immediately
cluster table has local overflow, not page-wide horizontal sprawl
shipment form requires concrete hand-off point for cross-dock
editing shipment intent does not auto-call backend
Find variants explains temporary drafts and never claims real supply creation
candidate vs Ozon-checked states are visibly distinct
Ozon rejection/no-slot/rate-limit/network errors remain distinct
previous successful result stays visible when stale/refresh fails
200% zoom remains operable
Flow/Economics/Data sibling routes remain usable after shared CSS changes
```
