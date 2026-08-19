# sklad_ozon

Локальное HTML-приложение для экономической проверки рекомендаций Ozon FBO и оптимального распределения ограниченного товарного запаса между кластерами.

## Ключевой принцип

Приложение строго разделяет:

1. **где возник спрос** — кластер доставки;
2. **откуда Ozon физически закрыл спрос** — кластер отгрузки;
3. **куда выгоднее положить следующий доступный товар** — результат юнит-экономики, ограничений и оптимизации.

Историческая отгрузка `Казань → Москва` считается московским спросом, закрытым Казанью. Это позволяет ловить ситуации вероятного stockout локального кластера и не принимать аварийное межкластерное исполнение за нормальный локальный спрос кластера-донора.

## MVP

- FBO only;
- без Ozon API;
- без backend и аккаунтов;
- локальный импорт XLSX/CSV;
- работает офлайн из `file://`;
- тарифная матрица загружается пользователем и хранится локально;
- анализ спроса и маршрутов `кластер отгрузки → кластер доставки`;
- статус `Вероятный stockout` с объяснением;
- прогнозная юнит-экономика `SKU × кластер`;
- учёт ограничений складов;
- распределение ограниченного запаса с целью максимизации ожидаемой абсолютной прибыли.

## Документы

- [Архитектурная спецификация](docs/superpowers/specs/2026-08-19-ozon-fbo-unit-economics-optimizer-design.md)
- [План реализации по PR](docs/superpowers/plans/2026-08-19-mvp-implementation.md)

## План PR

1. Static offline foundation + canonical domain contracts.
2. Ozon operational imports + normalization + diagnostics.
3. Tariff/product imports + local persistence.
4. Demand, fulfillment and weekly route analytics.
5. Probable stockout detector + clean route profiles.
6. Tariff engine + expected logistics + spreadsheet-parity unit economics.
7. Warehouse feasibility + candidate scoring + limited-stock optimizer.
8. Complete UI workflow + explainability + offline release hardening.

Каждый PR имеет отдельный тестовый merge-gate; полные исходные отчёты продавца в репозиторий не коммитятся.
