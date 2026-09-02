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
project-local `runtime/`. После его подготовки обычная работа не требует сети.

FastAPI слушает только `127.0.0.1:17843`. Отчёты и данные продавца обрабатываются
локально и не отправляются во внешние сервисы. `runtime/` можно пересоздать;
локальные артефакты `data/` при repair/rebuild не удаляются.

Если запуск сообщает код `RUNTIME_REPAIR_REQUIRED`, подключитесь к интернету и
снова запустите `start.bat`: повреждённый runtime будет пересоздан, а содержимое
`data/` сохранится. Полезные диагностические файлы —
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
3. **куда выгоднее положить следующий товар** — результат экономики,
   ограничений и оптимизации.

Отгрузка `Казань → Москва` является московским спросом, закрытым Казанью.
Product Completion развивает это разделение в полную цепочку принятия решения:

```text
Спрос
→ фактическое исполнение
→ искажения / stockout evidence
→ собственная оценка потребности
→ сравнение с Ozon
→ маршрутная экономика
→ Safe Plan / Calculated Plan
→ распределение по выбранному objective
```

Ozon recommendation служит внешним сигналом для сравнения и ограничивает
консервативный Safe Plan. Основной Calculated Plan опирается на собственную
потребность и физическую допустимость, а пользователь может оптимизировать его
по максимальной прибыли или максимальной марже. Ограничения recommendation
ceiling и единственного optimizer objective относились к завершённой runtime
migration и superseded новым Product Completion design для бизнес-логики.

## Разработка

Canonical automated test command целевой архитектуры:

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

### Текущий Product Completion

- [Product Completion design](docs/superpowers/specs/2026-09-02-ozon-fbo-product-completion-design.md)
- [DESIGN — визуальная система и UI](DESIGN.md)
- [UX-CONTRACT — обязательный UX-контракт](UX-CONTRACT.md)

Новый Product Completion implementation plan будет добавлен отдельно. Старые
MVP-планы не являются планом реализации Product Completion.

### Runtime architecture

- [Canonical SCOZ-lite portable architecture](docs/superpowers/specs/2026-08-20-scoz-lite-portable-architecture-design.md)
- [Codex Cloud environment](docs/superpowers/codex-cloud-environment.md)

SCOZ-lite design остаётся каноническим для runtime/technical architecture и не
отменяет бизнес-правила Product Completion.

### Historical documents

- [2026-08-19 business/analytical design](docs/superpowers/specs/2026-08-19-ozon-fbo-unit-economics-optimizer-design.md)
- [2026-08-19 browser-only implementation plan](docs/superpowers/plans/2026-08-19-mvp-implementation.md)
- [2026-08-20 SCOZ-lite MVP implementation plan PR1–PR8](docs/superpowers/plans/2026-08-20-scoz-lite-mvp-implementation.md)
