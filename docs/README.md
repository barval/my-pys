# Документация

| Документ | О чём |
|---|---|
| [00-architecture.md](00-architecture.md) | схема голосового тракта, компоненты, порты |
| [01-findings.md](01-findings.md) | исторические находки о колонке, LLM и сети |
| [02-plan.md](02-plan.md) | этапы, критерии успеха, журнал решений |
| [03-runbook.md](03-runbook.md) | пошаговые команды |
| [04-risks.md](04-risks.md) | риски, ограничения, откат |
| [05-troubleshooting.md](05-troubleshooting.md) | диагностика ошибок |
| [06-flai-all-cameras-api-bug.md](06-flai-all-cameras-api-bug.md) | баг FLAI API: пустой content у all-cameras |
| [07-webui.md](07-webui.md) | веб-панель: Docker, вход, разделы, бэкапы, прошивка |

Документы 01, 02 и 06 описывают историю этапа v1.0. Актуальное
состояние v2.0 — в README и `07-webui.md`.

Связанные файлы:

- [README.md](../README.md) — обзор и быстрый старт.
- [.opencode/skills/deploying-my-pys/](../.opencode/skills/deploying-my-pys/SKILL.md)
  — навык для ИИ-агента: развёртывание, прошивка, маршруты, ключи, бэкапы.
- [config/quasar-bridge-notes.md](../config/quasar-bridge-notes.md) —
  настройки Bridge под любую OpenAI-совместимую LLM.
- [vendor/README.md](../vendor/README.md) — версии сторонних проектов.
- [CONTRIBUTING.md](../CONTRIBUTING.md) — правила работы с репозиторием.
- [SECURITY.md](../SECURITY.md) — секреты и модель угроз.
