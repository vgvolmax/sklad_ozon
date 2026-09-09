# Codex Cloud — среда проекта

## Active architecture

Перед любой реализацией Codex читает `AGENTS.md` и только активные specs/plans, перечисленные там. Активного correction/amendment overlay больше нет.

Codex implementation environment и end-user runtime — разные вещи.

Canonical end-user flow:

```text
repository ZIP → extract → start.bat → project-local portable Python
→ FastAPI on 127.0.0.1:17843 → browser after /api/health
```

Committed frontend остаётся vanilla HTML/CSS/JavaScript без npm/build.
Ingestion и business logic выполняются Python; XLSX читается `openpyxl==3.1.5`; canonical automated command — `python -m pytest -q`.

## Что обязан проверять Codex

Codex запускает все доступные unit/integration/API/static checks, включая точные команды текущего implementation plan.

Наличие системного Python в implementation environment допустимо для тестов и не означает системную зависимость пользователя.

Network-dependent bootstrap official Windows embeddable Python и поведение `.bat`/`.cmd` могут быть недоказуемы в Linux-среде Codex. Это не разрешает architecture workaround: authoritative portable acceptance выполняет предусмотренный Windows CI/smoke. Codex обязан явно указать непроверенную границу и точную внешнюю проверку.

## Сеть в API-first runtime

Нужно различать:

```text
bootstrap runtime
→ может требовать интернет для первоначальной загрузки зависимостей

API-first рабочий режим
→ требует исходящий HTTPS к https://api-seller.ozon.ru
→ все Ozon вызовы идут только из localhost backend

FILES fallback
→ локальный аналитический расчёт по файлам может работать без Ozon API
→ remote handoff search / temporary draft validation всё равно требуют разблокированный Ozon API и сеть
```

Если в Codex Cloud нет внешней сети, это не разрешает заменять API-first архитектуру файловым merge, browser-side Ozon calls или другим backend.

Network-dependent Ozon behavior проверяется fake transport/unit tests. Актуальные endpoint contracts живут в canonical design + backend registry; не копировать endpoint strings во frontend/случайные модули.

## API-first временная политика

API source date/history принадлежат backend:

```text
business date offset = UTC+03:00
source_as_of = calendar date of backend sync timestamp converted with datetime.timezone(timedelta(hours=3))
initial orders lookback = 12 completed ISO weeks
bounded source-wide-gap backfill = 4-week steps, max 52 weeks
```

Не добавлять `zoneinfo`/`tzdata` только ради расчёта фиксированной московской business-date в portable runtime. Frontend/Codex implementation не должен вводить arbitrary API-mode historical `as_of` или shallow-history control.

## Внешние ресурсы

Ограничение сети Codex не разрешает возвращать browser XLSX parsing, SheetJS, прямой `file://` runtime, альтернативный backend или frontend toolchain.

GitHub CLI может отсутствовать/быть не авторизован. Это влияет только на публикацию, не на архитектуру/качество проверок.

## Неизменное правило

**Environment limitations must not cause architecture drift.**

При ограничении нужно сообщить команду и ошибку, сохранить валидную проверенную работу и передать Windows-specific acceptance в предусмотренный CI. Не добавлять альтернативную архитектуру ради особенностей Codex Cloud.