# sklad_ozon

Локальное Windows-приложение для экономической проверки рекомендаций Ozon FBO
и оптимального распределения ограниченного запаса между кластерами.

> **Статус:** SCOZ-lite runtime реализован. Единственная пользовательская точка
> входа — `start.bat`; прямой запуск HTML через `file://` не поддерживается.

## Как запускать приложение

1. Download repository ZIP.
2. Extract it fully to a writable folder.
3. Double-click `start.bat`.
4. Если runtime ещё не подготовлен, первая подготовка требует интернета: bootstrap
   скачивает официальный portable Python и закреплённые зависимости.
5. Браузер откроется автоматически только после готовности локального приложения.

Системный Python и Node/npm устанавливать не нужно, права администратора не
нужны, PATH не изменяется. Последующие запуски повторно используют проверенный
project-local `runtime/`. После его подготовки обычная работа текущего runtime
может выполняться локально; активный API-first roadmap 2026-09-09 добавляет
явное сетевое подключение к Ozon Seller API для синхронизации и проверки
вариантов поставки.

FastAPI слушает только `127.0.0.1:17843`. Текущий файловый runtime обрабатывает
отчёты локально. В API-first roadmap внешние запросы разрешены только backend-
клиенту Ozon на фиксированный `api-seller.ozon.ru`; секреты не передаются во
frontend. `runtime/` можно пересоздать; локальные артефакты `data/` при
repair/rebuild не удаляются.

Если запуск сообщает код `RUNTIME_REPAIR_REQUIRED`, подключитесь к интернету и
снова запустите `start.bat`: повреждённый runtime будет пересоздан, а содержимое
`data/` сохранено. Полезные диагностические файлы —
`data/startup_status.json` и `data/server_console.log`.

## Архитектура

sklad_ozon следует проверенным portable-паттернам
[SCOZ](https://github.com/vgvolmax/SCOZ), но намеренно проще:

- project-local Python 3.13.14, launcher и локальный FastAPI;
- Python/openpyxl ingestion для XLSX и stdlib `csv` для CSV;
- committed vanilla HTML/CSS/JavaScript без npm, build и framework;
- Project JSON вместо SQLite и generic persistence infrastructure;
- pytest для domain, ingestion, analytics, economics, optimizer и API.

Frontend является тонким presentation layer. Формулы, импорт и бизнес-правила
живут в Python functional core, а API routes остаются transport shell.

## Ключевой аналитический принцип

Приложение строго разделяет:

1. **где возник спрос** — delivery/destination cluster;
2. **откуда Ozon физически закрыл спрос** — origin/dispatch cluster;
3. **сколько нужно следующей поставки** — Product Completion;
4. **как операционно исполнить рассчитанную поставку** — API-first shipment planner.

Отгрузка `Казань → Москва` является московским спросом, закрытым Казанью.
Product Completion сохраняет эту семантику в цепочке принятия решения:

```text
Спрос
→ фактическое исполнение
→ искажения / stockout evidence
→ собственная оценка потребности
→ сравнение с Ozon
→ маршрутная экономика
→ Safe Plan / Calculated Plan
→ операционное исполнение рассчитанного плана
```

Ozon recommendation остаётся внешним сигналом сравнения, когда доступно точное
сопоставимое evidence. Основной Calculated Plan опирается на собственную
потребность и существующую физическую/экономическую модель. API-first roadmap
не переписывает demand/stockout/Need/Flow/economics; он меняет источники
оперативных данных и добавляет whole-pack planning, временную Ozon draft-
валидацию, актуальные timeslots и ручной XLSX/ZIP hand-off.

Финальное создание реальной заявки Ozon **не входит** в активный roadmap.

## Разработка

Canonical automated test command:

```bash
python -m pytest -q
```

Опциональная syntax-проверка committed frontend не делает Node пользовательской
зависимостью:

```bash
node --check frontend/assets/js/app.js
```

Portable Windows bootstrap проверяется authoritative Windows GitHub Actions
smoke, включая первый bootstrap, настоящее offline-переиспользование runtime,
отказ при offline-повреждении, online-восстановление, UI/assets, сохранность
`data/`, путь с пробелами, loopback bind и полную очистку тестовых процессов.

## Документы

### Активный API-first roadmap

- [Canonical API-first shipment planner design](docs/superpowers/specs/2026-09-09-ozon-api-first-shipment-planner-design.md)
- [API-first Plan/Data UI design](docs/superpowers/specs/2026-09-09-api-first-plan-ui-design.md)
- [Active implementation plans](docs/superpowers/plans/)
- [AGENTS — обязательный порядок чтения для Codex](AGENTS.md)

### Сохраняемая аналитическая база

- [Product Completion design](docs/superpowers/specs/2026-09-02-ozon-fbo-product-completion-design.md)
- [Real-data demand / stockout / Flow design](docs/superpowers/specs/2026-09-03-real-data-demand-stockout-flow-design.md)
- [DESIGN — текущая визуальная система и UI](DESIGN.md)
- [UX-CONTRACT — текущий обязательный UX-контракт](UX-CONTRACT.md)

`DESIGN.md` и `UX-CONTRACT.md` будут синхронно мигрированы в PR-E вместе с
реальным API-first UI, чтобы root-контракты не описывали ещё не поставленный
runtime.

### Runtime architecture

- [Canonical SCOZ-lite portable architecture](docs/superpowers/specs/2026-08-20-scoz-lite-portable-architecture-design.md)
- [Codex Cloud environment](docs/superpowers/codex-cloud-environment.md)

### Archive

Завершённые и superseded документы перемещены в
[`docs/superpowers/archive/`](docs/superpowers/archive/README.md).
Они не являются источником требований для активной разработки и не должны
читаться Codex без отдельного запроса на исторический аудит.
