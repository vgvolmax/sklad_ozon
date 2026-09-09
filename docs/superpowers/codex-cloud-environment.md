# Codex Cloud — среда проекта

## Active architecture

Перед любой реализацией Codex читает `AGENTS.md` и применяет активный precedence patch:

`docs/superpowers/specs/2026-09-09-api-first-roadmap-corrections.md`.

Codex implementation environment и end-user runtime — разные вещи. Canonical end-user flow:

```text
repository ZIP → extract → start.bat → project-local portable Python
→ FastAPI on 127.0.0.1:17843 → browser after /api/health
```

Committed frontend остаётся vanilla HTML/CSS/JavaScript без npm и build.
Ingestion и business logic выполняются Python, XLSX читается `openpyxl==3.1.5`,
а canonical automated command — `python -m pytest -q`.

## Что обязан проверять Codex

Codex запускает все доступные в его среде unit, integration, API и static checks,
включая точные команды текущего PR. Наличие системного Python в implementation
environment допустимо для тестов и не означает системную зависимость пользователя.

Network-dependent bootstrap official Windows embeddable Python и поведение
`.bat`/`.cmd` могут быть недоказуемы в Linux-среде Codex. Это не является причиной
для архитектурного workaround: authoritative portable acceptance выполняет
GitHub Actions Windows runner. Codex обязан явно записать непроверенную границу и
точную проверку, которую выполняет Windows CI.

## Сеть в API-first runtime

Нужно различать три режима сети:

```text
bootstrap runtime
→ может требовать интернет для первоначальной загрузки зависимостей

API-first рабочий режим
→ требует исходящий HTTPS к https://api-seller.ozon.ru
→ все вызовы идут только из localhost backend

FILES fallback
→ аналитический расчёт по локальным файлам может работать без Ozon API
→ live hand-off search / temporary draft validation всё равно требуют разблокированный Ozon API и сеть
```

Следовательно старое утверждение «после появления runtime обычная работа приложения сети не требует» больше не является общим контрактом для API-first режима.

Если в Codex Cloud нет внешней сети, это не разрешает заменять API-first архитектуру файловым merge, browser-side Ozon calls или другим backend. Network-dependent Ozon client behavior проверяется fake transport/unit tests; фактическая интеграция остаётся backend-only и fixed-host.

## Внешние ресурсы

Ограничение сети Codex не разрешает возвращать browser XLSX parsing, SheetJS, прямой `file://` runtime, другой backend или frontend toolchain.

GitHub CLI может отсутствовать или быть не авторизован. Это влияет только на публикацию, а не на архитектуру или качество проверок.

## Неизменное правило

**Environment limitations must not cause architecture drift.**

При ограничении нужно сообщить команду и ошибку, сохранить валидную проверенную
работу и передать Windows-specific acceptance в предусмотренный CI. Не добавлять
альтернативную архитектуру лишь ради особенностей Codex Cloud.
