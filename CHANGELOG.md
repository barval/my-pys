# Changelog

Все заметные изменения проекта. Формат — Keep a Changelog,
версии — SemVer.

## [1.0.0] — 2026-11-04

Первая версия: подготовка инфраструктуры и документации.

### Added

- README с описанием проекта, ограничениями и быстрым стартом.
- `docs/01-findings.md`: результаты разведки колонки, FLAI и сети.
- `docs/02-plan.md`: этапы, критерии успеха, журнал решений.
- `docs/03-runbook.md`: пошаговые команды root, SSH, OTA, Bridge.
- `docs/04-risks.md`: риски, ограничения, откат.
- `docs/05-troubleshooting.md`: диагностика типовых ошибок.
- Скрипты `check-flai`, `fetch-firmware`, `start-lite-kit`,
  `stop-lite-kit`, `post-root-ssh`, `install-quasar-bridge`.
- Docker-стенд `lite-kit` с host-network: DNS 53, HTTP 80, HTTPS 443.
- Снапшоты `quasar-bridge` v0.6.2, `lite-kit` и station-tools.
- Конфигурационные примеры для FLAI и колонки.

### Verified

- Колонка `192.168.1.103` — `yandexmicro`, deviceId
  `EXAMPLE000000000000000000000004`.
- FLAI `http://192.168.1.2:5000/v1` отвечает; создан ключ
  `quasar-bridge` (префикс `flai-_XGpOA`).
- Простой ответ FLAI — 5,3–38,4 с (зависит от загрузки модели и чужих
  задач в общем инстансе); классификатор — 7,3 с / 31,8 с.
- Прошивка `.46` скачана с официального CDN и проверена:
  `size=66814464`, `crc32=371630625`,
  `sha256=74d4e8fae375b2ad1757761e01caf6be0209d216328ce1a942dbef38c8f20d11`.
- Контейнер `ysl-lite-kit` запущен; DNS `quasar.yandex.net`,
  `quasar.yandex.ru`, `scbh.yandex.net` → `192.168.1.2`;
  HTTPS 443 отвечает, порты 80/443/53 слушают.
- Порт `1961` (glagol) открыт, но требует облачный `conversationToken`.

### Pending

- Сброс колонки и получение root.
- Установка Dropbear, отключение OTA.
- Установка Quasar Bridge и голосовые тесты.
- Тег `v1.0` после успешной проверки на живой колонке.
