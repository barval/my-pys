# Yandex Station Lite — приватный голосовой ассистент

**Версия:** v1.0 (ветка `v1.0`)
**Статус:** FLAI проверен, прошивка `.46` скачана и проверена, стенд
`lite-kit` отработал. Целевая колонка `192.168.1.101` сброшена, обновлена,
рутована, SSH и OTA настроены. **Quasar Bridge v0.6.2 установлен и здоров**,
`check-backends` показывает `LLM: ok`. Политика маршрутизации применена:
Яндекс — только сервисы, всё остальное — внешняя LLM. Осталось голосовое
тестирование.

Проект превращает Яндекс Станцию Лайт 1-го поколения в голосовую колонку,
где **Яндекс** отвечает только за погоду, время, музыку и умный дом, а все
остальные запросы уходят во **внешнюю LLM** с OpenAI-совместимым API (FLAI,
Ollama, vLLM, LM Studio или облачный сервис). Используется **Quasar Bridge**
в режиме `hybrid`: голос и распознавание речи по-прежнему облачные.

> Это не полная приватность: аудио всё равно уходит в облако Яндекса для
> распознавания и синтеза речи. Полностью локальный вариант — отдельный
> self-hosted бэкенд (`quasard`/`v3rt3p`), он выходит за рамки v1.0.

## Ключевые факты

| Что | Значение |
|---|---|
| Колонка | Яндекс Станция Лайт 1 (платформа `yandexmicro`) |
| IP колонки (текущий) | `192.168.1.101` — не хардкодить, ищется по MAC/ID |
| Device ID | `EXAMPLE000000000000000000000001` |
| MAC | `02:00:00:00:00:01` |
| Внешняя LLM | FLAI `http://192.168.1.2:5000/v1`, модель `flai-chat` (заменима) |
| Bridge → LLM | напрямую `http://192.168.1.2:5000/v1` |
| Маршрутизация | `default_route=llm`; Яндекс — погода/время/музыка/умный дом |
| FLAI GPU | NVIDIA RTX 5060 Ti 16 GB, Qwen3VL-8B Q4 |
| Quasar Bridge | v0.6.2, ARM64/ARMv7 |
| Root | DNS-метод + локальный стенд `lite-kit`, прошивка `.46` |
| SSH | порт `2222`, Dropbear |

## Структура репозитория

```
README.md                     этот файл
VERSION                       v1.0
docs/
  README.md                   индекс документации
  00-architecture.md          схема тракта, компоненты, порты
  01-findings.md              что выяснено о колонке, FLAI и сети
  02-plan.md                  план работ по этапам
  03-runbook.md               точные команды и порядок действий
  04-risks.md                 риски, ограничения и откат
  05-troubleshooting.md       диагностика типовых ошибок
config/
  flai.env.example            пример переменных внешней LLM
  router-routes.example.json  пример таблицы маршрутов роутера
  quasar-bridge-policy.json   политика: Яндекс-сервисы vs внешняя LLM
  quasar-bridge-notes.md      настройки Bridge и внешней LLM
  speakers/                   профили четырёх колонок (MAC/device ID/IP)
router/
  llm_router.py               локальный OpenAI-совместимый роутер
  Dockerfile                  контейнер без pip-зависимостей
  tests/                      тесты роутера
scripts/
  lib-env.sh                  общий загрузчик .env и профиля колонки
  router-init.sh              ключи колонок и secrets/router-routes.json
  start-router.sh             сборка и запуск llm-router
  stop-router.sh              остановка llm-router
  check-flai.sh               проверка LLM через роутер и замер ответа
  resolve-speaker.sh          поиск колонки по device ID/MAC, а не по IP
  fetch-firmware.sh           загрузка прошивки .46
  fetch-quasar-bridge.sh      офлайн-загрузка релиза Quasar Bridge
  bridge_install_pexpect.py   неинтерактивный мастер через PTY
  apply-bridge-routing.sh     применить политику маршрутизации
  start-lite-kit.sh           запуск стенда root в Docker
  stop-lite-kit.sh            остановка стенда
  post-root-ssh.sh            SSH + отключение OTA после root
  install-quasar-bridge.sh    установка Quasar Bridge по SSH
docker/
  lite-kit.Dockerfile         контейнер со стендом (dnsmasq + Python)
  docker-compose.lite-kit.yml
  docker-compose.router.yml   контейнер llm-router на 5002
vendor/
  lite-kit/                   снапшот krevetkqqq/lite-kit
  quasar-bridge/              снапшот skrashevich/quasar-bridge v0.6.2
  station-tools/              dropbear, dropbearkey, yandex-noupdate.sh
secrets/
  router-token-*              промежуточные ключи колонок (gitignored)
  flai-token-*                upstream-ключи FLAI (gitignored)
  router-routes.json          таблица маршрутов с ключами (gitignored)
```

## Быстрый старт (после подтверждения сброса)

1. Запустить LLM-роутер и проверить его:

   ```bash
   make router-init
   make router
   make check
   ```

2. Запустить стенд root:

   ```bash
   ./scripts/start-lite-kit.sh
   ```

3. На роутере `192.168.1.1` поставить DNS = `192.168.1.2`.

4. Сбросить колонку и привязать её в приложении, остановившись на экране Wi-Fi.
   Перед каждой следующей колонкой полностью закройте и снова откройте
   «Дом с Алисой» — иначе Bluetooth-сопряжение не проходит.

5. После появления ADB выполнить `./scripts/post-root-ssh.sh`.

6. Установить Quasar Bridge:

   ```bash
   ./scripts/install-quasar-bridge.sh
   ```

7. Проверить:

   - «Алиса, какая завтра погода?» — отвечает Яндекс.
   - «Алиса, почему небо голубое?» — отвечает FLAI.

Подробности — в `docs/03-runbook.md`.

## Несколько колонок

Профили колонок — это отдельные файлы окружения. Публичный пример лежит в
`config/speakers/example.env`; реальные профили храните в
`local/speakers/<имя>.env` — папка `local/` исключена из git.

| Пример профиля | IP | Device ID |
|---|---|---|
| `local/speakers/speaker-a.env` | `192.168.1.101` | `EXAMPLE...001` |
| `local/speakers/speaker-b.env` | `192.168.1.100` | `EXAMPLE...002` |
| `local/speakers/speaker-c.env` | `192.168.1.102` | `EXAMPLE...003` |
| `local/speakers/speaker-d.env` | `192.168.1.103` | `EXAMPLE...004` |

Имена и количество профилей произвольны: скрипты читают любой файл,
переданный через `SPEAKER_ENV`.

Для любой команды по конкретной колонке:

```bash
SPEAKER_ENV=local/speakers/speaker-b.env ./scripts/post-root-ssh.sh
SPEAKER_ENV=local/speakers/speaker-b.env ./scripts/install-quasar-bridge.sh --non-interactive
SPEAKER_ENV=local/speakers/speaker-b.env ./scripts/apply-bridge-routing.sh
SPEAKER_ENV=local/speakers/speaker-b.env make status
```

Без `SPEAKER_ENV` используются переменные из `local/.env` (или `.env` в
корне, если локального файла нет).

IP в профиле — только подсказка для ускорения поиска. Привязка идёт по
`SPEAKER_DEVICE_ID`/`SPEAKER_MAC`; `resolve-speaker.sh` проверяет MAC и не
использует IP как идентификатор колонки.

## LLM-роутер

Все колонки ходят на один адрес:

```text
http://192.168.1.2:5002/v1
```

Роутер по промежуточному ключу выбирает upstream: FLAI или любую другую
OpenAI-совместимую LLM. Колонку при смене провайдера трогать не нужно.
У всех четырёх маршрутов `primary` — FLAI; `fallback` пока не задан.

```bash
make router-init   # создать ключи колонок и secrets/router-routes.json
make router        # собрать и запустить контейнер llm-router
make router-status # health
make router-logs   # логи
```

Ключи лежат **только на хосте** в `secrets/` (gitignored, chmod 600):

| Колонка | Промежуточный ключ | Upstream-ключ FLAI |
|---|---|---|
| `speaker-a` | `secrets/router-token-speaker-a` | `secrets/flai-token-speaker-a` |
| `speaker-b` | `secrets/router-token-speaker-b` | `secrets/flai-token-speaker-b` |
| `speaker-c` | `secrets/router-token-speaker-c` | `secrets/flai-token-speaker-c` |
| `speaker-d` | `secrets/router-token-speaker-d` | `secrets/flai-token-speaker-d` |

`secrets/router-routes.json` — таблица маршрутов. Пример без секретов:
`config/router-routes.example.json`. Если upstream-ключ ещё не создан,
маршрут отвечает `503`, остальные колонки работают.

Профиль колонки указывает только на промежуточный ключ:

```env
LLM_BASE_URL=http://192.168.1.2:5002/v1
LLM_TOKEN_FILE=secrets/router-token-speaker-b
```

Записать адрес и ключ в колонку:

```bash
SPEAKER_ENV=local/speakers/speaker-b.env ./scripts/set-speaker-key.sh
```

Скрипт обновляет `QUASAR_LLM_BASE_URL`, `QUASAR_LLM_MODEL` и
`QUASAR_LLM_API_KEY` в `/data/opt/quasar-bridge/runtime.env`, затем
перезапускает Bridge.

### Fallback

У каждого маршрута может быть резервный upstream:

```json
"fallback": {
  "base_url": "https://api.example.com/v1",
  "api_key": "sk-...",
  "model": "qwen3-32b",
  "history": "client"
}
```

Если основной маршрут недоступен, отдаёт `429`/`5xx` или не ответил за
таймаут, запрос уходит в fallback. Тело пересобирается под его режим:
FLAI получает только текущий вопрос, обычная LLM — всю историю Bridge.
Изменения `secrets/router-routes.json` применяются без перезапуска.

Сейчас для всех четырёх маршрутов настроен fallback
**OrcaRouter Free**:

```text
base_url: https://api.orcarouter.ai/v1
model:    orcarouter/free
keys:     secrets/orca-token-speaker-a, -speaker-b, -speaker-c, -speaker-d
```

Ключи проверены: `/v1/models` отвечает `200`, модель `orcarouter/free`
доступна. Но free-тариф сейчас отдаёт `429 free_rate_limited` с
`Retry-After` около двух часов, поэтому fallback работает по остаточному
принципу — когда у OrcaRouter есть свободная ёмкость. FLAI остаётся
основным маршрутом.

### История и сессии

- `history=server` (FLAI): роутер отправляет **только последний вопрос** и
  стабильный `user`, историю хранит FLAI. System-промпт не отправляется:
  FLAI склеивает роли в один текст и может пересказывать служебные
  инструкции в ответе. Это же не даёт роутеру FLAI классифицировать длинный
  транскрипт вместо вопроса.
- Health-check `make check-backends` пишет в отдельную сессию
  `voice-health`, поэтому «Ответь одним словом: связь» не появляется в
  основном диалоге.
- `history=client` (обычная LLM): уходит окно Bridge — 6 ходов, 12k
  символов, TTL 5 минут.
- Сессия FLAI одна на колонку. После 30 минут простоя начинается новая.
  Автоматически остаются текущая и две предыдущие сессии.

### Краткость ответов

Для голоса роутер обрезает ответы любой LLM до **3 предложений / 400
символов** и убирает Markdown. Настройка — в начале
`secrets/router-routes.json`:

```json
"response": {
  "max_sentences": 3,
  "max_chars": 400,
  "strip_markdown": true
}
```

Обрезаются только не-stream ответы (`stream: false`); Bridge использует
именно такой режим.

Новый Bridge `0.6.2-chunked` присылает заголовок
`X-Quasar-Voice-Chunking: 1`. Для таких запросов роутер отдаёт до
**3000 символов**, а Bridge сам режет ответ на куски по ~500 символов
(до 6 кусков) и озвучивает их подряд. Старые Bridge без заголовка
продолжают получать 3/400.

Собрать кастомный Bridge:

```bash
./scripts/build-quasar-bridge.sh
```

Установщик автоматически берёт `v0.6.2-chunked`, если сборка есть в
`.cache/release-v0.6.2-chunked/`; явно задать версию можно через
`QUASAR_VERSION`.

Лимиты чанкинга на колонке:

```env
QUASAR_SPEECH_MAX_CHARS=500
QUASAR_SPEECH_MAX_CHUNKS=6
```

### Streaming-озвучка (пилот)

На `192.168.1.101` и `192.168.1.100` включён:

```env
QUASAR_STREAM_LLM=1
```

Bridge открывает streaming-сессию сразу, держит колонку пустыми
deferred-сообщениями каждые 3 секунды и начинает TTS с первого готового
предложения. Idle-таймаут SSE — 90 секунд, чтобы пережить поиск FLAI.

Если первого текста нет долго, Bridge говорит короткую фразу-заполнитель:
первая через **10 секунд**, затем каждые **15 секунд**. Список и тайминги
настраиваются:

```env
QUASAR_SPEECH_FILLER=1
QUASAR_SPEECH_FILLER_AFTER=10
QUASAR_SPEECH_FILLER_EVERY=15
QUASAR_SPEECH_FILLER_MAX=3
QUASAR_SPEECH_FILLERS="Секунду, ищу ответ.|Пока думаю.|Мне нужно чуть больше времени.|Ещё немного, и смогу сказать."
```

Заполнители замолкают, как только приходит первый реальный текст.
Остальные колонки пока работают в обычном chunked-режиме.

### Upstream-ключи FLAI

В FLAI созданы отдельные учётные записи:

| Пользователь | Комната |
|---|---|
| `speaker-a` | комната A |
| `speaker-b` | комната B |
| `speaker-c` | комната C |
| `speaker-d` | комната D |

Ключ кладётся в `secrets/flai-token-<профиль>` той колонки, которую вы
называете при настройке. Соответствие «профиль ↔ комната» **не задаётся по
IP**: `resolve-speaker.sh` ищет колонку по MAC/device ID, а ключ
подставляется в профиль после того, как вы скажете, какая это колонка.
Для уже настроенной `192.168.1.101` назначен `speaker-a`.

Сейчас ключи разложены по профилям как черновой вариант; при настройке
каждой следующей колонки соответствие уточняется. Формат:

```bash
printf '%s\n' 'flai-...' > secrets/flai-token-speaker-b
chmod 600 secrets/flai-token-speaker-b
```

После этого маршрут `speaker-b` станет доступен автоматически. Проверка:

```bash
SPEAKER_ENV=local/speakers/speaker-b.env ./scripts/check-flai.sh
SPEAKER_ENV=local/speakers/speaker-b.env make status
```

`make status` проверяет только процесс Bridge. `make check-backends`
дополнительно дергает LLM тестовым запросом «Ответь одним словом: связь».

## Безопасность

- `secrets/` исключён из git. Не коммитьте ключи роутера и upstream-ключи.
- FLAI слушает `0.0.0.0:5000`; не публикуйте порт в интернет.
- SSH на колонке по умолчанию с пустым паролем. После настройки добавьте
  свой публичный ключ и уберите `-B` из Dropbear.
- Сброс стирает `/data` и отвязывает колонку от аккаунта.
- Прошивка `.46` скачивается со стороннего зеркала; проверяйте CRC32/SHA-256.

## Откат

На колонке по SSH:

```sh
sh /data/opt/quasar-bridge/app/control.sh rollback
reboot
sh /data/opt/quasar-bridge/app/uninstall.sh
```

Вернуть обновления Яндекса: `sh /data/opt/yandex-noupdate.sh restore`.
Остановить стенд: `./scripts/stop-lite-kit.sh`, вернуть DNS роутера.
