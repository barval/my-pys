# Yandex Station Lite — приватный голосовой ассистент

**Версия:** v1.0 (ветка `v1.0`)
**Статус:** идёт подготовка. FLAI проверен, прошивка `.46` скачана и
проверена, стенд `lite-kit` запущен и отдаёт DNS `192.168.1.2`. Колонка
ещё не рутована. Следующий шаг — сброс и получение root.

Проект превращает Яндекс Станцию Лайт 1-го поколения в голосовую колонку,
которая сложные вопросы отправляет в локальную LLM **FLAI**, а музыку, погоду,
таймеры и умный дом оставляет Алисе. Используется **Quasar Bridge** в режиме
`hybrid`: голос и распознавание речи по-прежнему облачные, но ответы на
«спроси нейросеть» приходят из домашней сети.

> Это не полная приватность: аудио всё равно уходит в облако Яндекса для
> распознавания и синтеза речи. Полностью локальный вариант — отдельный
> self-hosted бэкенд (`quasard`/`v3rt3p`), он выходит за рамки v1.0.

## Ключевые факты

| Что | Значение |
|---|---|
| Колонка | Яндекс Станция Лайт 1 (платформа `yandexmicro`) |
| IP колонки | `192.168.1.103` |
| Device ID | `EXAMPLE000000000000000000000004` |
| MAC | `02:00:00:00:00:04` |
| FLAI | `http://192.168.1.2:5000/v1`, модель `flai-chat` |
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
  flai.env.example            пример переменных FLAI
  quasar-bridge-notes.md      настройки Quasar Bridge под FLAI
scripts/
  check-flai.sh               проверка FLAI и замер ответа
  fetch-firmware.sh           загрузка прошивки .46
  start-lite-kit.sh           запуск стенда root в Docker
  stop-lite-kit.sh            остановка стенда
  post-root-ssh.sh            SSH + отключение OTA после root
  install-quasar-bridge.sh    установка Quasar Bridge по SSH
docker/
  lite-kit.Dockerfile         контейнер со стендом (dnsmasq + Python)
  docker-compose.lite-kit.yml
vendor/
  lite-kit/                   снапшот krevetkqqq/lite-kit
  quasar-bridge/              снапшот skrashevich/quasar-bridge v0.6.2
  station-tools/              dropbear, dropbearkey, yandex-noupdate.sh
secrets/
  flai-token                  API-ключ FLAI (gitignored, chmod 600)
```

## Быстрый старт (после подтверждения сброса)

1. Проверить FLAI:

   ```bash
   ./scripts/check-flai.sh
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

## Безопасность

- `secrets/` исключён из git. Не коммитьте API-ключ FLAI.
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
