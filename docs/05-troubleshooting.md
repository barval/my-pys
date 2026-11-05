# 05. Диагностика

> IP колонки может быть случайным. Всегда сначала проверяйте
> `./scripts/resolve-speaker.sh`: он ищет по device ID и MAC, а не по IP.

## Веб-панель показывает старый интерфейс

Файлы шаблонов могли обновиться, но контейнер работает со старым
процессом. Проверьте версию:

```bash
curl -s http://127.0.0.1:8080/healthz
```

Если версии нет или она старая:

```bash
git pull --ff-only
make webui
```

Затем `Ctrl+Shift+R` в браузере. `make webui` пересоздаёт контейнер и
сбрасывает кеш шаблонов.

## Не входит в веб-панель

- `503` на форме входа — нет `secrets/webui-admin.hash`. Задайте пароль:
  `make webui-passwd`.
- Пароль не подходит — смените его тем же `make webui-passwd`.
- Сессия сброшена — удалите `secrets/webui-session.key` и перезапустите
  панель.
- Панель не стартует — `make webui-logs`, проверьте, что Docker и
  `HOST_REPO_PATH` доступны.

## Задание висит «Выполняется…»

Страница задания обновляется автоматически каждые 2 секунды, пока
задание не завершится. Если обновления нет:

- проверьте `docker logs my-pys-webui`;
- откройте `webui-state/jobs/<id>.json` и `<id>.log`;
- если задание `queued`, перед ним может быть другое задание на тот же
  target (`speaker-a` или `host`);
- перезапустите панель, если задание осталось `running` после падения.

## Стенд lite-kit не запускается из панели

- `stand-control` требует `HOST_REPO_PATH`. Запускайте через `make webui`
  или задайте `HOST_REPO_PATH=$(pwd)` для compose.
- Проверьте логи: `docker logs my-pys-stand-control`.
- Docker socket должен быть доступен пользователю контейнера:
  `DOCKER_GID=$(stat -c '%g' /var/run/docker.sock) make webui`.
- Если в задании `HOST_REPO_PATH is not set`, панель запущена без Makefile.
- Перед запуском стенда должна быть скачана прошивка: `make firmware` или
  кнопка «Скачать прошивку».

## «Проверить доступность» оставляет статус «не проверено»

Скорее всего, контейнер `llm-router` старый и не поддерживает
`GET /health?probe=1`. Пересоберите роутер:

```bash
make router
```

Проверьте:

```bash
curl -s 'http://127.0.0.1:5002/health?probe=1' | python3 -m json.tool
```

В ответе должны быть поля `primary` и `fallbacks` со `state`. Если их
нет — роутер всё ещё старый.

## Проверка доступности показывает ошибку, хотя LLM работает

Проверка дергает `GET {base_url}/models` с таймаутом 3 секунды. Некоторые
провайдеры не поддерживают `/models` или отвечают на него иначе, хотя
`/chat/completions` работает. Проверьте вручную:

```bash
curl -sS -H "Authorization: Bearer $(cat secrets/upstream-token-speaker-a)" \
  http://192.168.1.2:5000/v1/models | head -c 200
```

Если чат работает, а `/models` — нет, ориентируйтесь на реальные запросы
и логи роутера, а не только на статус проверки.

## Восстановление бэкапа

- Без `REPLACE` восстановление не начнётся.
- Перед заменой создаётся снапшот в `webui-state/restore-backups/`.
- Неверный пароль или повреждённый архив — операция отменяется, файлы не
  меняются.
- После восстановления профили перечитываются автоматически, роутер
  подхватывает конфиг без перезапуска.

## Обновление Bridge: scp и порт 8443

- `scp` может упасть с `sftp-server: not found`: в Dropbear нет SFTP.
  Копируйте файл через stdin:
  ```bash
  ssh -i secrets/speaker_ed25519 -p 2222 root@IP \
    'cat > /data/opt/quasar-bridge/app/bin/quasar-bridge.new' < binary
  ```
- `control.sh restart` может ответить
  `Port 8443 already serves another bridge; stop its old launcher first`.
  Остановите старый процесс и запустите снова:
  ```bash
  killall quasar-bridge
  sh /data/opt/quasar-bridge/app/control.sh start
  ```
- Если установщик упал на проверке LLM, сначала проверьте
  `./scripts/check-llm.sh` с нужным профилем. Иногда это транзиентный
  сбой; после успешной проверки установку можно повторить или заменить
  только бинарник.

## Колонка видна по Bluetooth, но приложение не подключается

Симптом: «Дом с Алисой» находит `Yandex Station Lite ...`, затем пишет
«Не получилось подключить колонку по Bluetooth».

**Самая частая причина — приложение не перезапустили после предыдущей
колонки.** Полностью закройте «Дом с Алисой» (свайпом из списка задач) и
откройте заново. Это нужно делать перед сопряжением каждой следующей
колонки.

Если не помогло:

1. Выключить и включить Bluetooth на телефоне. Если в системном списке
   есть старое сопряжение `Yandex Station Lite ...` — «Забыть».
2. Выключить Bluetooth на остальных телефонах и планшетах: колонка держит
   одно BLE-соединение.
3. Передёрнуть питание колонки на 10 секунд, дождаться мигания.
4. Android: разрешить «Устройства рядом» и «Местоположение»; iPhone:
   включить Bluetooth и «Локальная сеть» для приложения.
5. Телефон в 20–30 см от колонки, без чехла, Wi-Fi на телефоне выключен.
6. Если не помогает — попробовать другой телефон, чтобы отделить проблему
   телефона от BLE-стека колонки.

Проверить, что колонка рекламируется по BLE, можно с хоста:

```bash
timeout 15 bluetoothctl --timeout 10 scan on | grep -i 'Yandex Station'
```

## ADB не подключается

Симптом: `adb connect "$(./scripts/resolve-speaker.sh):5555"` → `Connection refused` или
`unable to connect`.

1. Колонка и ПК в одной сети, без изоляции клиентов.
2. DNS роутера = `192.168.1.2`:
   ```bash
   nslookup quasar.yandex.net 192.168.1.1
   dig +short @192.168.1.2 quasar.yandex.net
   ```
   Если `dig @192.168.1.1` показывает настоящий IP Яндекса, это ещё не
   значит, что DHCP-опция неверная: так отвечает резолвер роутера. Новый DNS
   применится к колонке при следующем DHCP-запросе (после сброса).
3. Стенд работает:
   ```bash
   docker ps --filter name=ysl-lite-kit
   docker logs --tail=100 ysl-lite-kit
   tail -n 100 vendor/lite-kit/log/server.log
   ```
4. В логе есть `>>> [SYNC-REAL→]` и `adbd: ... =on`.
5. Отключите DNS-фильтры (AdGuard, Яндекс.DNS) для этой сети.
6. Передёрните питание колонки.

Если в логе TLS-ошибка `unknown_ca` — колонка не доверяет стенду. Это
бывает на новых сборках без отката. Убедитесь, что включён `run/downgrade`
и в `firmware/yandexmicro/` лежит `.46`.

## ADB есть, но не root

Проверьте:

```bash
adb shell id
```

Должно быть `uid=0(root)`. Если `uid=2000(shell)` — это не тот ADB-режим;
перечитайте `docs/01-findings.md` и лог `get_sync_info`. Не продолжайте
установку SSH, пока root не подтверждён.

## SSH не пускает

```bash
ssh -vvv -i secrets/speaker_ed25519 -p 2222 root@$(./scripts/resolve-speaker.sh)
```

- `Connection refused` — Dropbear не запущен. Через ADB:
  `adb shell '/etc/init.d/S99zdropbear start'`, лог
  `/data/opt/etc/dropbear/dropbear.log`.
- `Permission denied` — ключ не попал в `/root/.ssh/authorized_keys` или
  в Dropbear остался `-B` и он не принимает ключ. Проверьте права:
  `700` на каталог, `600` на файл.
- После `mount -o remount,ro /` ключ должен сохраниться.

## Установщик Quasar Bridge завершился кодом 255, каталога нет

Симптом: `install-quasar-bridge.sh` пишет `Shared connection closed`,
возвращает `255`, а `/data/opt/quasar-bridge` на колонке не появляется.

Причина: установщик запускает `setup.sh` через `ssh -tt`, а неинтерактивные
ответы подавались обычным pipe. SSH закрывал соединение раньше, чем
`setup.sh` успевал прочитать первую строку, поэтому установка отменялась.

Решение: использовать `./scripts/install-quasar-bridge.sh --non-interactive`
— он проводит мастер через PTY (`bridge_install_pexpect.py`). Локальный
релиз скачивается `./scripts/fetch-quasar-bridge.sh` и не зависит от
таймаутов GitHub.

## Внешняя LLM недоступна

Симптом: `check-backends` не проходит, в логах Bridge `LLM returned HTTP 000`
или `connection refused`.

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.1.2:5000/v1/models \
  -H "Authorization: Bearer $(cat secrets/upstream-token)"
```

- Upstream LLM не отвечает — проверьте `http://192.168.1.2:5000/health`.
- Bridge смотрит не туда — в `/data/opt/quasar-bridge/runtime.env`
  должно быть `QUASAR_LLM_BASE_URL="http://192.168.1.2:5000/v1"`,
  затем `control.sh restart`.
- Для другой LLM проверьте `LLM_BASE_URL`, `LLM_MODEL` и ключ.

## Quasar Bridge: «Проверка нейросети не проходит»

Проверьте с ПК:

```bash
./scripts/check-llm.sh
```

Типовые ответы:

| Ошибка | Причина | Что делать |
|---|---|---|
| `HTTP 401` | Неверный/отозванный ключ | Создать новый ключ у провайдера, обновить файл из `api_key_file` |
| `HTTP 400` | Неверное тело запроса | Проверить `llm_api` = `chat_completions`, модель `flai-chat` |
| `HTTP 000` / timeout | LLM недоступна | Проверить `http://192.168.1.2:5000/health` и `./scripts/check-llm.sh` |
| `LLM returned no answer` | Пустой ответ | Проверить upstream вручную, `check-backends` |
| `LLM returned HTTP 429` | Лимит провайдера | Подождать, уменьшить частоту |
| `finish_reason=length` | Обрезка ответа | Проверить модель/промпт провайдера |
| Ответ дольше 60 с | Долгий reasoning | Выбрать более быструю модель, не грузить GPU |

На колонке:

```bash
pkg=/data/opt/quasar-bridge/app
sh "$pkg/control.sh" check
sh "$pkg/control.sh" check-backends
sh "$pkg/control.sh" logs
```

## Bridge не стартует после перезагрузки

```bash
ls -l /etc/init.d/S96quasar-bridge
sh /data/opt/quasar-bridge/app/control.sh status
```

Если файла нет — установка не завершила автозапуск. Переустановите или
создайте init-скрипт по upstream-инструкции. Если Алиса замолчала —
`control.sh rollback` и `reboot`.

## ARM64: `Exec format error`

Ядро Лайт 1 — aarch64, но userspace armhf. Статический ARM64-бинарник
должен работать. Если нет:

1. Скачайте ARMv7-архив из релиза Quasar Bridge.
2. Распакуйте на колонке в `/data/opt/quasar-bridge/app`.
3. Проверьте `uname -m` (должно быть `aarch64` или `armv7l`).
4. Запустите `control.sh restart`.

## FLAI долго думает / очередь

FLAI сериализует GPU-задачи. Если одновременно идёт генерация картинки
или видео, голосовой запрос ждёт. Проверьте:

```bash
docker ps --filter name=flai-
nvidia-smi
docker logs --tail=100 flai-web
```

Для голоса лучше не запускать тяжёлые задачи. При необходимости создайте
отдельного пользователя FLAI с более простыми настройками.

## Колонка отвечает как обычно

- Установщик не применил подключение: `sh /data/opt/quasar-bridge/app/control.sh apply` и `reboot`.
- Все не-сервисные запросы должны идти в LLM: проверьте
  `default_route` и правила в `config.json`.
- Проверить конкретную фразу:
  ```bash
  set -a; . /data/opt/quasar-bridge/runtime.env; set +a
  pkg=/data/opt/quasar-bridge/app
  "$pkg/bin/quasar-bridge" -config /data/opt/quasar-bridge/config.json -route "ваша фраза"
  ```
- Если сервисная фраза ушла в LLM — дополните `yandex_services`, `home_devices` или
  `yandex_intercom` и примените `./scripts/apply-bridge-routing.sh`.
- Проверьте `config.json` и `runtime.env` на колонке.

## Вернуть всё

См. `docs/04-risks.md`. Сначала `control.sh rollback`, потом `uninstall.sh`,
затем вернуть OTA и DNS.
