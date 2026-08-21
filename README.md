# sklad_ozon

Локальное Windows-приложение для экономической проверки рекомендаций Ozon FBO
и оптимального распределения ограниченного запаса между кластерами.

> **Статус:** SCOZ-lite runtime реализован. Единственная пользовательская точка
> входа — `start.bat`; прямой запуск HTML через `file://` не поддерживается.

## Как запускать приложение

1. Download repository ZIP.
2. Extract it fully to a writable folder.
3. Double-click `start.bat`.
4. При первом запуске bootstrap может скачать официальный portable Python и
   закреплённые зависимости.
5. Браузер откроется автоматически только после готовности локального приложения.

Системный Python и Node/npm устанавливать не нужно, права администратора не
нужны, PATH не изменяется. Последующие запуски повторно используют проверенный
project-local `runtime/`. После его подготовки обычная работа не требует сети.

FastAPI слушает только `127.0.0.1:17843`. Отчёты и данные продавца обрабатываются
локально и не отправляются во внешние сервисы. `runtime/` можно пересоздать;
локальные артефакты `data/` при repair/rebuild не удаляются.

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
Миграция runtime не меняет lifecycle, PII boundary, incomplete-week policy,
stockout/distortion, clean routes, tariffs, tax/VAT/co-invest, feasibility,
counterfactual placement, recommendation ceilings или optimizer objective.

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
smoke, включая первый bootstrap, повторное использование runtime и loopback bind.

## Документы

- [Canonical SCOZ-lite architecture](docs/superpowers/specs/2026-08-20-scoz-lite-portable-architecture-design.md)
- [Canonical implementation plan PR1–PR8](docs/superpowers/plans/2026-08-20-scoz-lite-mvp-implementation.md)
- [Codex Cloud environment](docs/superpowers/codex-cloud-environment.md)
- [Historical business/analytical design](docs/superpowers/specs/2026-08-19-ozon-fbo-unit-economics-optimizer-design.md)
