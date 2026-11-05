# 03. Runbook

Пошаговый порядок. Выполнять с хоста `192.168.1.2` (этот репозиторий),
если не указано иное.

> **IP колонки может измениться.** Не хардкодьте его. Скрипты ищут колонку
> по `SPEAKER_DEVICE_ID`/`SPEAKER_MAC` через `./scripts/resolve-speaker.sh`.
> Если ниже в примере стоит конкретный IP — это текущий снимок, а не гарантия.

## 0. Проверка LLM-роутера

```bash
cd /path/to/my-pys
make router-init
make router
make router-status
make check
```

Ожидаемо:

- `GET /health` → `{"status":"ok",...}`;
- `GET /v1/models` через роутер → `200`;
- ответ на тестовый вопрос за 5–40 с;
- непустой русский текст, `finish_reason=stop`.

`make check-backends` и установщик Bridge пишут health-check
«Ответь одним словом: связь» в отдельную сессию `voice-health`, а не в
основной диалог колонки.

Если `401` — проверьте `secrets/router-token-<колонка>`. Если `503` —
нет upstream-ключа `secrets/upstream-token-<колонка>` или не настроен fallback.
Если `000` — контейнер `llm-router` не слушает `192.168.1.2:5002`.

Прямая проверка upstream (в обход роутера, пример):

```bash
curl -sS -H "Authorization: Bearer $(cat secrets/upstream-token-speaker-a)" \
  http://192.168.1.2:5000/v1/models | head -c 200
```

Имя файла ключа задаётся в `api_key_file` маршрута; это не обязательно
`upstream-token-*`.

## 0.1. Веб-панель

Дальше управление идёт через панель, но первичная прошивка всё равно
ручная.

```bash
make router        # LLM-роутер
make webui         # панель, router-control и stand-control
make webui-passwd  # задать пароль
```

Открыть `http://127.0.0.1:8080`. Доступ с других устройств:
`WEBUI_BIND=0.0.0.0 make webui`.

Вкладки:

- **Колонки** — статус, проверка LLM, ключ, routing, Bridge, SSH/OTA;
- **Прошивка** — скачать образ, запустить/остановить `lite-kit`, найти
  колонку, выполнить действия после root;
- **LLM-роутер** — primary и fallback отдельными строками, до 9
  запасных, смена порядка, проверка доступности;
- **Ключи** — промежуточные токены и upstream-ключи;
- **Бэкапы** — шифрованные архивы всей конфигурации или одной колонки;
- **Аудит** и **Пароль**.

Сброс кнопкой и привязка в «Дом с Алисой» остаются ручными. Панель
показывает чек-лист, но не нажимает кнопку.

## 1. Прошивка и стенд root

### 1.1. Скачать прошивку

```bash
./scripts/fetch-firmware.sh
```

Скрипт берёт файл с официального CDN Яндекса (зеркало lite-kit слишком
медленно отдаёт каталоги) и кладёт его в
`vendor/lite-kit/firmware/yandexmicro/0.369.1.46.4778262442.20261013.297.zip`,
рядом пишет `manifest.json`. Проверка:

```bash
ls -lh vendor/lite-kit/firmware/yandexmicro/
```

Ожидаемо: файл ~60–70 МБ. Если скачался маленький файл — зеркало отдало
ошибку; повторите запуск, скрипт умеет брать официальный URL из metadata.

### 1.2. Запустить стенд

```bash
./scripts/start-lite-kit.sh
```

Скрипт собирает контейнер `ysl-lite-kit`, запускает его с `network_mode: host`
и включает режим `run/downgrade`. Проверка DNS:

```bash
dig +short @192.168.1.2 quasar.yandex.net
```

Ожидаемо: `192.168.1.2`.

Проверка портов:

```bash
ss -lntup | grep -E ':(53|80|443)\b'
```

Ожидаемо: DNS на `192.168.1.2:53`, HTTP/HTTPS на `0.0.0.0:80/443`.
Порт `192.168.122.1:53` (libvirt) не мешает.

Логи:

```bash
docker logs -f ysl-lite-kit
tail -f vendor/lite-kit/log/server.log
tail -f vendor/lite-kit/log/dnsmasq.log
```

## 2. Роутер

Роутер: `http://192.168.1.1` (TP-Link).

> **Сначала выключите из розетки три другие станции: `192.168.1.100`, `192.168.1.102`, `192.168.1.103`.**
> Все они — `yandexmicro`. DNS-правило на роутере действует на всю сеть,
> и стенд может отдать прошивку или ADB-конфиг не только целевой колонке.
> После завершения root их можно включить обратно.
>
> Перед этим закрепите все четыре MAC → IP в DHCP (см. таблицу ниже),
> чтобы целевая колонка после сброса осталась на `192.168.1.101`.

1. «Дополнительные настройки» → «Сеть» → «DHCP-сервер».
2. **Предпочитаемый DNS-сервер** = `192.168.1.2`.
3. **Альтернативный DNS-сервер** — очистить.
4. Сохранить.

DHCP-резервации для всех четырёх станций:

| IP | MAC |
|---|---|
| `192.168.1.100` | `02:00:00:00:00:02` |
| `192.168.1.101` | `02:00:00:00:00:01` (целевая) |
| `192.168.1.102` | `02:00:00:00:00:03` |
| `192.168.1.103` | `02:00:00:00:00:04` |

Перезагружать роутер не нужно: новый DNS применяется к новым DHCP-запросам.
Колонка получит его после сброса и переподключения к Wi-Fi.

Проверка с ПК:

```bash
nslookup quasar.yandex.net 192.168.1.1
```

Ожидаемо: `192.168.1.2`. Но `dig @192.168.1.1` может показать старый
адрес Яндекса: это резолвер самого роутера, а не DHCP-опция, которую он
раздаёт клиентам. Надёжнее всего проверить по логу стенда после подключения
колонки.

Если роутер не даёт менять DNS — используйте раздачу Wi-Fi с Android и
DNS Changer, но для TP-Link это не нужно.

## 3. Сброс колонки

**Внимание:** сброс очищает `/data`, отвязывает колонку от аккаунта и
удаляет всё, что было установлено. Это обязательный шаг DNS-метода.

1. Отключите питание колонки, подождите несколько секунд.
2. Включите питание и **сразу** зажмите кнопку паузы (▶‖).
3. Держите 6–10 секунд, пока подсветка не станет жёлто-зелёной.
4. Отпустите: подсветка пульсирует голубым, колонка ждёт настройки.

## 4. Привязка в приложении

> **Важно для каждой следующей колонки:** перед сопряжением полностью
> закройте «Дом с Алисой» (свайпом из списка задач) и откройте заново.
> Без этого приложение видит колонку по Bluetooth, но не подключается.

1. Включите Bluetooth и геолокацию на телефоне.
2. **Выключите Wi-Fi на телефоне**, оставьте мобильный интернет и Bluetooth.
   Иначе приложение тоже пойдёт на локальный стенд, не примет его
   сертификат и настройка сорвётся.
3. «Дом с Алисой» → «+» → «Устройство с Алисой».
4. Дойдите до экрана «Выберите сеть Wi-Fi и введите пароль».
5. Введите сеть и пароль вручную, но **не нажимайте «Подключиться»**,
   пока DNS не указывает на `192.168.1.2`.
6. Нажмите «Подключиться».

Колонка сходит на стенд, получит `adbd.remoteActivation=true` и, если версия
отличается, скачает `.46`. В логе появится:

```
>>> [SYNC-REAL→] ... adbd: ... =on
```

Скачивание 67 МБ, установка и перезагрузка занимают несколько минут.
Не выдёргивайте питание.

## 5. ADB

```bash
adb connect "$(./scripts/resolve-speaker.sh):5555"
adb devices
adb shell id
```

Ожидаемо:

```
uid=0(root) gid=0(root) ...
```

Если `Connection refused`:

- проверьте, что DNS на роутере всё ещё `192.168.1.2`;
- `dig @192.168.1.2 quasar.yandex.net` → `192.168.1.2`;
- передёрните питание колонки;
- отключите на роутере фильтрацию DNS/AdGuard для этой сети;
- проверьте, что ПК и колонка не в гостевой сети с изоляцией клиентов.

## 6. SSH и отключение OTA

```bash
./scripts/post-root-ssh.sh
```

Скрипт:

- проверит root по ADB;
- создаст `secrets/speaker_ed25519`, если его нет;
- установит Dropbear и автозапуск `S99zdropbear`;
- добавит публичный ключ в `/root/.ssh/authorized_keys`;
- запустит `yandex-noupdate.sh` и заберёт backup в `backups/`;
- перезагрузит колонку.

После перезагрузки (1–2 минуты):

```bash
ssh -i secrets/speaker_ed25519 -p 2222 root@$(./scripts/resolve-speaker.sh) \
  'id; sh /data/opt/yandex-noupdate.sh status'
```

Ожидаемо:

```
uid=0(root) ...
launch.json : updatesd убран
applier     : заглушён
ota key     : подменён
```

Только после успешного входа по ключу уберите `-B` из
`/etc/init.d/S99zdropbear`:

```bash
ssh -i secrets/speaker_ed25519 -p 2222 root@$(./scripts/resolve-speaker.sh)
mount -o remount,rw /
sed -i 's/ -B / /' /etc/init.d/S99zdropbear
sync
mount -o remount,ro /
/etc/init.d/S99zdropbear restart
```

Проверьте вход по ключу ещё раз. Пустой пароль после этого работать не должен.

## 7. Quasar Bridge

### Подготовка релиза

```bash
./scripts/fetch-quasar-bridge.sh
```

Скрипт скачивает **v0.6.2** в `.cache/release-v0.6.2` и проверяет SHA-256.
Установщик использует локальную копию, поэтому не зависит от того, отдаст ли
GitHub release-assets файл за 15 секунд.

### LLM-роутер

Bridge подключается к локальному роутеру, а не напрямую к провайдеру:

```text
http://192.168.1.2:5002/v1
```

Перед установкой Bridge роутер должен быть запущен:

```bash
make router-init
make router
make router-status
```

Маршруты и цепочка `fallbacks` (до 9 запасных) лежат в
`secrets/router-routes.json`; изменения подхватываются без перезапуска.
Порядок fallback меняется стрелками ▲/▼ под именем маршрута в панели. Колонка при смене
upstream не меняется:
в её `runtime.env` остаются адрес роутера и промежуточный ключ
`secrets/router-token-<колонка>`.

### Chunked-Bridge для длинных ответов

Собрать кастомный Bridge (нужен Docker, Go на хосте не требуется):

```bash
./scripts/build-quasar-bridge.sh
```

Проверить доступность upstream можно без панели:

```bash
curl -s http://192.168.1.2:5002/health?probe=1 | python3 -m json.tool
```

Роутер дергает `GET /models` у каждого upstream с таймаутом 3 с.
Установщик автоматически выбирает `v0.6.2-chunked`, если сборка есть в
`.cache/release-v0.6.2-chunked/`. Явно:

```bash
SPEAKER_ENV=local/speakers/speaker-d.env \
  QUASAR_VERSION=v0.6.2-chunked \
  ./scripts/install-quasar-bridge.sh --non-interactive
```

Bridge режет ответ на куски по ~500 символов (до 6 кусков) и озвучивает
их подряд. Настройки — в `runtime.env` колонки:

```env
QUASAR_SPEECH_MAX_CHARS=500
QUASAR_SPEECH_MAX_CHUNKS=6
```

### Streaming-озвучка (пилот)

На `192.168.1.101` и `192.168.1.100` включено:

```env
QUASAR_STREAM_LLM=1
```

Bridge сразу открывает streaming-сессию, держит колонку keepalive-
сообщениями каждые 3 секунды и начинает TTS с первого готового
предложения. Idle-таймаут SSE — 90 секунд, чтобы пережить веб-поиск FLAI.
Если первый текст задерживается, через 10 секунд звучит первая
фраза-заполнитель, затем каждые 15 секунд:

```env
QUASAR_SPEECH_FILLER=1
QUASAR_SPEECH_FILLER_AFTER=10
QUASAR_SPEECH_FILLER_EVERY=15
QUASAR_SPEECH_FILLER_MAX=3
QUASAR_SPEECH_FILLERS="Секунду, ищу ответ.|Пока думаю.|Мне нужно чуть больше времени.|Ещё немного, и смогу сказать."
```

Остальные колонки работают в обычном chunked-режиме. Для отката
достаточно поставить `QUASAR_STREAM_LLM=0` и перезапустить Bridge.

### Вариант A. Интерактивно

```bash
./scripts/install-quasar-bridge.sh
```

Ответы мастера:

| Вопрос | Ответ |
|---|---|
| Адрес API нейросети | `http://192.168.1.2:5002/v1` |
| Название модели | `flai-chat` |
| Ключ API | содержимое `secrets/router-token-speaker-a` (для `192.168.1.101`) |
| API | `1` (Chat Completions) |
| Home Assistant MCP | Enter (не нужен) |
| Подключить Алису | `y` |
| Перезагрузить | `y` |

Ключ вводится скрыто. Скопировать его:

```bash
cat secrets/router-token-speaker-a
```

Для остальных колонок используйте `secrets/router-token-<колонка>`.

### Вариант B. Без ручного ввода

После того как SSH по ключу работает:

```bash
./scripts/install-quasar-bridge.sh --non-interactive
```

Скрипт поднимает `ssh-agent`, добавляет `secrets/speaker_ed25519` и проводит
официальный мастер через PTY (`scripts/bridge_install_pexpect.py`). Нужен
`python3-pexpect`. Если хотите не перезагружать сразу:

```bash
REBOOT=n ./scripts/install-quasar-bridge.sh --non-interactive
```

Важно: обычный `printf ... | sh install.sh` с `ssh -tt` не работает —
SSH закрывает соединение раньше, чем удалённый `setup.sh` успевает прочитать
ответы. Поэтому используется pexpect.

После установки проверьте/обновите `runtime.env` колонки:

```bash
SPEAKER_ENV=local/speakers/speaker-a.env ./scripts/set-speaker-key.sh
```

Скрипт выставит `QUASAR_LLM_BASE_URL`, `QUASAR_LLM_MODEL` и
`QUASAR_LLM_API_KEY` и перезапустит Bridge.

## 8. Политика маршрутизации

Применить политику:

```bash
./scripts/apply-bridge-routing.sh
```

Политика `config/quasar-bridge-policy.json`:

- `default_route = llm` — всё непопавшее уходит во внешнюю LLM;
- `yandex_services` — погода, время, таймеры, музыка, радио;
- `home_devices` — умный дом (пока Home Assistant не настроен, Яндекс);
- `speaker_playback` — пауза/продолжение/стоп;

`assistant_tools` оставлены выключенными: внешняя LLM сама решает, что ей
нужно. `local_progress` включён, чтобы колонка не молчала во время
ожидания.

Проверить маршрут без выполнения запроса:

```bash
set -a; . /data/opt/quasar-bridge/runtime.env; set +a
pkg=/data/opt/quasar-bridge/app
"$pkg/bin/quasar-bridge" -config /data/opt/quasar-bridge/config.json -route "какая погода завтра"
```

## 9. Проверка

Скажите колонке:

1. «Алиса, какая завтра погода?» — Яндекс.
2. «Алиса, который час?» — Яндекс.
3. «Алиса, включи музыку» / «найди песню …» — Яндекс.
4. «Алиса, включи свет в комнате A» — Яндекс (или Home Assistant).
5. «Алиса, почему небо голубое?» — внешняя LLM.
6. «Алиса, как дела в комнате A?» — внешняя LLM (камера, если настроена).

Ожидаемые маршруты можно проверить через `-route` (см. выше) или по логу:

```bash
make routes
```

Диагностика на колонке:

```bash
pkg=/data/opt/quasar-bridge/app
sh "$pkg/control.sh status"
sh "$pkg/control.sh check"
sh "$pkg/control.sh check-backends"
sh "$pkg/control.sh logs"
```

Веб-чат FLAI: `http://192.168.1.2:5000` — там видны сессии голосовых
запросов (пользователь `operator`).

### Как понять, кто ответил

Голос у Алисы и у FLAI один — синтез речи делает Яндекс. Поэтому на слух
это не всегда очевидно. Точный признак — лог Bridge:

```bash
ssh -i secrets/speaker_ed25519 -p 2222 root@$(./scripts/resolve-speaker.sh) \
  'tail -n 300 /data/opt/quasar-bridge/service.log' | grep native_route_decision
```

- `"route":"llm"` — ответила внешняя LLM;
- `"route":"yandex"` — ответила обычная Алиса;
- `"source":"rule"` — сработало правило (`yandex_services`,
  `home_devices` или `speaker_playback`);
- `"source":"default"` — сработал `default_route=llm`;
- `"source":"classifier"` в текущей политике не используется.

Подтверждение на стороне FLAI (если upstream — FLAI):

```bash
docker logs --since 10m flai-web 2>&1 | grep -E "query=|/v1/chat/completions"
```

Если в логе есть `query='ваш вопрос'` и `POST /v1/chat/completions 200`,
ответ действительно пришёл из FLAI. Для другой LLM смотрите её логи.

Быстрые команды: `make routes` и `make flai-log`.

## 10. Остальные три колонки

Для каждой колонки повторяется тот же путь: сброс → привязка → ADB → SSH/OTA
→ Bridge → политика. Делать **по одной**, чтобы не путать логи и приложение.

Профили:

```text
local/speakers/speaker-b.env    192.168.1.100  EXAMPLE-2...
local/speakers/speaker-c.env    192.168.1.102  EXAMPLE-3...
local/speakers/speaker-d.env 192.168.1.103  EXAMPLE-4...
```

Для выбранной колонки:

```bash
export SPEAKER_ENV=local/speakers/speaker-b.env

./scripts/post-root-ssh.sh
./scripts/install-quasar-bridge.sh --non-interactive
./scripts/apply-bridge-routing.sh
./scripts/set-speaker-key.sh
make status
```

Ключ upstream для профиля лежит в файле из `api_key_file` маршрута (например, `secrets/upstream-token-speaker-b`, см. таблицу в
README). Профиль уже содержит `LLM_TOKEN_FILE` с этим путём. Записать ключ
в колонку можно и отдельно:

```bash
SPEAKER_ENV=local/speakers/speaker-b.env ./scripts/set-speaker-key.sh
SPEAKER_ENV=local/speakers/speaker-b.env ./scripts/check-llm.sh
```

Сброс и привязка — как в шагах 3–4. Остальные колонки на это время
выключены. Уже готовую `192.168.1.101` можно оставить включённой, но для чистоты
лучше выключить на время настройки остальных.

## 11. После успеха

1. Остановить стенд:

   ```bash
   ./scripts/stop-lite-kit.sh
   ```

2. Вернуть DNS роутера в исходное состояние.

3. Проверить, что колонка и Алиса работают без стенда.

4. Сохранить backup:

   ```bash
   ls -la backups/
   ```

5. Закоммитить изменения и поставить тег `v2.0.0` (после проверки).

## 12. Откат

На колонке:

```sh
sh /data/opt/quasar-bridge/app/control.sh rollback
reboot
```

После успешного отката и проверки Алисы:

```sh
sh /data/opt/quasar-bridge/app/uninstall.sh
```

Вернуть OTA (если нужно):

```sh
sh /data/opt/yandex-noupdate.sh restore
```

Остановить стенд и вернуть DNS — см. шаг 10.

Если колонка не отвечает после правки `quasar.cfg`, верните копию:

```bash
adb push backups/<дата>/quasar.cfg.orig /system/vendor/quasar/quasar.cfg
adb shell sync
adb shell reboot
```

(Копия снимается установщиком Quasar Bridge в `/data/opt/quasar-bridge-backup`.)
