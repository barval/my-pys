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

5. После появления ADB выполнить `./scripts/post-root-ssh.sh`.

6. Установить Quasar Bridge:

   ```bash
   ./scripts/install-quasar-bridge.sh
   ```

7. Проверить:

   - «Алиса, какая завтра погода?» — отвечает Яндекс.
   - «Алиса, спроси нейросеть: почему небо голубое?» — отвечает FLAI.

Подробности — в `docs/03-runbook.md`.

## Несколько колонок

В сети четыре Станции Лайт. Профили лежат в `config/speakers/`:

| Профиль | IP | Device ID | Статус |
|---|---|---|---|
| `speaker-a.env` | `192.168.1.101` | `EXAMPLE-1...` | готово |
| `speaker-b.env` | `192.168.1.100` | `EXAMPLE-2...` | ожидает |
| `speaker-c.env` | `192.168.1.102` | `EXAMPLE-3...` | ожидает |
| `speaker-d.env` | `192.168.1.103` | `EXAMPLE-4...` | ожидает |

Для любой команды по конкретной колонке:

```bash
SPEAKER_ENV=local/speakers/speaker-b.env ./scripts/post-root-ssh.sh
SPEAKER_ENV=local/speakers/speaker-b.env ./scripts/install-quasar-bridge.sh --non-interactive
SPEAKER_ENV=local/speakers/speaker-b.env ./scripts/apply-bridge-routing.sh
SPEAKER_ENV=local/speakers/speaker-b.env make status
```

Без `SPEAKER_ENV` используется профиль из `.env` — сейчас это `speaker-a.env`
(колонка `192.168.1.101`).

## LLM-роутер

Все колонки ходят на один адрес:

```text
http://192.168.1.2:5002/v1
```

Роутер по промежуточному ключу выбирает upstream: FLAI или любую другую
OpenAI-совместимую LLM. Колонку при смене провайдера трогать не нужно.

```bash
make router-init   # создать ключи колонок и secrets/router-routes.json
make router        # собрать и запустить контейнер llm-router
make router-status # health
make router-logs   # логи
```

Ключи лежат **только на хосте** в `secrets/` (gitignored, chmod 600):

| Колонка | Промежуточный ключ | Upstream-ключ FLAI |
|---|---|---|
| `192.168.1.101` LG | `secrets/router-token-speaker-a` | `secrets/flai-token-speaker-a` |
| `192.168.1.100` LP | `secrets/router-token-speaker-b` | `secrets/flai-token-speaker-b` |
| `192.168.1.102` LN | `secrets/router-token-speaker-c` | `secrets/flai-token-speaker-c` |
| `192.168.1.103` EXAMPLE-4 | `secrets/router-token-speaker-d` | `secrets/flai-token-speaker-d` |

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

### История и сессии

- `history=server` (FLAI): роутер отправляет system + последний вопрос и
  стабильный `user`, историю хранит FLAI. Это не даёт роутеру FLAI
  классифицировать длинный транскрипт вместо вопроса.
- `history=client` (обычная LLM): уходит окно Bridge — 6 ходов, 12k
  символов, TTL 5 минут.
- Сессия FLAI одна на колонку. После 30 минут простоя начинается новая.
  Автоматически остаются текущая и две предыдущие сессии.

### Upstream-ключи FLAI

Ключи создаются в FLAI под отдельными пользователями `speaker-a`, `speaker-b`,
`speaker-c`, `speaker-d` и кладутся в `secrets/flai-token-*`. Формат:

```bash
printf '%s\n' 'flai-...' > secrets/flai-token-speaker-b
chmod 600 secrets/flai-token-speaker-b
```

После этого маршрут `lp` станет доступен автоматически. Проверка:

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
