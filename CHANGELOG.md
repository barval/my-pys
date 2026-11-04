# Changelog

Все заметные изменения проекта. Формат — Keep a Changelog,
версии — SemVer.

## [Unreleased] — 2026-11-05

### Added

- Локальный LLM-роутер `llm-router` на `192.168.1.2:5002`:
  OpenAI-совместимые `/v1/chat/completions` и `/v1/models`, выбор
  upstream по промежуточному ключу колонки, hot reload конфига.
- Резервные (fallback) маршруты для каждого промежуточного ключа; при
  недоступности основного upstream запрос пересобирается под режим
  резервного (`history=client|server`).
- Режимы истории: `server` (FLAI хранит историю, роутер отправляет только
  текущий вопрос) и `client` (обычная LLM получает окно Bridge).
- Сессии FLAI: одна на колонку, ротация после 30 минут простоя,
  автоматическая чистка — остаются текущая и две предыдущие.
- `scripts/router-init.sh`, `scripts/start-router.sh`,
  `scripts/stop-router.sh`, `config/router-routes.example.json`,
  `docker/docker-compose.router.yml`, `make router*`.
- Профили колонок и `.env` переведены на адрес роутера и промежуточные
  ключи `secrets/router-token-*`.
- `scripts/set-speaker-key.sh` теперь записывает в Bridge адрес роутера,
  модель и промежуточный ключ.
- `history=server` больше не отправляет system-промпт: FLAI склеивает роли
  и мог цитировать служебные инструкции в ответе. Health-check вынесен в
  отдельную сессию `voice-health` и не засоряет основной диалог.
- Роутер обрезает не-stream ответы любой LLM до 3 предложений / 400
  символов и убирает Markdown (`response` в конфиге).
- Тесты роутера: `router/tests/test_router.py` (14 тестов).
- FLAI назначен `primary` для всех четырёх маршрутов; upstream-ключи
  разложены по учётным записям `speaker-a`, `speaker-b`, `speaker-c`, `speaker-d`.
- Для всех четырёх маршрутов настроен fallback OrcaRouter Free
  (`https://api.orcarouter.ai/v1`, модель `orcarouter/free`, ключи
  `secrets/orca-token-*`). Ключи валидны, но free-тариф может отдавать
  `429 free_rate_limited`.

### Changed

- `check-flai.sh` проверяет LLM через роутер, а не напрямую FLAI.
- `README.md` и `docs/03-runbook.md` описывают роутер, fallback и
  управление сессиями.
- В runbook и troubleshooting добавлено: перед Bluetooth-сопряжением каждой
  следующей колонки полностью закрывать и заново открывать «Дом с Алисой».

## [1.0.0] — 2026-11-04

Первая версия: подготовка инфраструктуры и документации.

### Added

- README с описанием проекта, ограничениями и быстрым стартом.
- `docs/01-findings.md`: результаты разведки колонки, FLAI и сети.
- `docs/02-plan.md`: этапы, критерии успеха, журнал решений.
- `docs/03-runbook.md`: пошаговые команды root, SSH, OTA, Bridge.
- `docs/04-risks.md`: риски, ограничения, откат.
- `docs/05-troubleshooting.md`: диагностика типовых ошибок.
- Скрипты `check-flai`, `resolve-speaker`, `fetch-firmware`,
  `start-lite-kit`, `stop-lite-kit`, `post-root-ssh`,
  `install-quasar-bridge`.
- `resolve-speaker.sh` ищет колонку по `device_id`/MAC, IP — только
  подсказка. Все установочные скрипты используют его вместо хардкода IP.
- `fetch-quasar-bridge.sh` скачивает проверенный релиз v0.6.2 в локальный
  кэш; установка больше не зависит от доступности GitHub release-assets.
- `bridge_install_pexpect.py` проводит официальный мастер через PTY:
  обычный pipe с `ssh -tt` закрывался раньше, чем `setup.sh` читал ответы.
- `install-quasar-bridge.sh --non-interactive` теперь использует этот
  драйвер и локальный релиз.
- Политика `config/quasar-bridge-policy.json`: `default_route = llm`;
  Яндекс обрабатывает только погоду, время, музыку, таймеры и умный дом.
- Переменные `LLM_*` (endpoint, upstream, модель, ключ) с алиасами
  `FLAI_*`: вместо FLAI подойдёт любая OpenAI-совместимая LLM.
- Профили `config/speakers/*.env` и `scripts/lib-env.sh`: все команды
  принимают `SPEAKER_ENV=...` и находят колонку по MAC/device ID.
  Без профиля используется `.env` (`192.168.1.101`).
- Персональные ключи FLAI по колонкам: `secrets/flai-token-speaker-a`, `-lp`,
  `-ln`, `-l00fq`; профили содержат `LLM_TOKEN_FILE`.
- `scripts/set-speaker-key.sh` записывает ключ в
  `/data/opt/quasar-bridge/runtime.env` на колонке и перезапускает Bridge.
- `make status` больше не вызывает LLM; health-probe «Ответь одним словом:
  связь» вынесен в `make check-backends`, чтобы не засорять историю FLAI.
- `conversation_log` включает журнал распознанных фраз и ответов для
  диагностики маршрутизации.
- Подтверждён целевой сценарий с камерой: FLAI делает
  `camera_snapshot(room=kab)`, Qwen3VL описывает снимок, Bridge передаёт
  текст в Yandex TTS, Алиса озвучивает.
- Bridge подключается к внешней LLM напрямую; прокси и вырезание
  «спроси у ФЛАЙ» удалены. Служебное обращение больше не обрабатывается.
- Внешняя LLM получает распознанный текст без слова «Алиса»; остальной
  текст передаётся как есть.
- Docker-стенд `lite-kit` с host-network: DNS 53, HTTP 80, HTTPS 443.
- Снапшоты `quasar-bridge` v0.6.2, `lite-kit` и station-tools.
- Конфигурационные примеры для FLAI и колонки.

### Verified

- Колонка `192.168.1.101` — `yandexmicro`, deviceId
  `EXAMPLE000000000000000000000001`.
- FLAI `http://192.168.1.2:5000/v1` отвечает; создан ключ
  `quasar-bridge` (префикс `flai-_XGpOA`).
- Простой ответ FLAI — 5,3–38,4 с (зависит от загрузки модели и чужих
  задач в общем инстансе); классификатор проверялся, но в текущей политике
  не используется.
- Прошивка `.46` скачана с официального CDN и проверена:
  `size=66814464`, `crc32=371630625`,
  `sha256=74d4e8fae375b2ad1757761e01caf6be0209d216328ce1a942dbef38c8f20d11`.
- Контейнер `ysl-lite-kit` запущен; DNS `quasar.yandex.net`,
  `quasar.yandex.ru`, `scbh.yandex.net` → `192.168.1.2`;
  HTTPS 443 отвечает, порты 80/443/53 слушают.
- Порт `1961` (glagol) открыт, но требует облачный `conversationToken`.
- Целевая колонка `192.168.1.101` (`EXAMPLE-1...`, MAC
  `02:00:00:00:00:01`) сброшена, получила `.46` и ADB с `uid=0(root)`.
- После живой проверки цель исправлена: сначала предполагалась
  `EXAMPLE-4...` на `192.168.1.103`, но физически настроена `EXAMPLE-1...` на `192.168.1.101`.
  Остальные три станции выключены и не затрагивались.
- Установлен Dropbear на `2222`, добавлен SSH-ключ, OTA отключён
  (`updatesd` не запущен), пустой пароль `-B` убран.
- Quasar Bridge v0.6.2 установлен, `check-backends`: `LLM: ok`.
- Маршруты проверены через `-route`:
  погода/время/музыка/будильник/радио → `yandex`;
  свет → `home` → `yandex` (Home Assistant не настроен);
  «почему небо голубое» → `llm` / `default`;

### Pending

- Голосовые тесты по матрице из `docs/03-runbook.md`.
- Тег `v1.0` после успешной проверки на живой колонке.
- Тег `v1.0` после успешной проверки на живой колонке.
