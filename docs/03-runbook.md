# 03. Runbook

Пошаговый порядок. Выполнять с хоста `192.168.1.2` (этот репозиторий),
если не указано иное.

> **IP колонки может измениться.** Не хардкодьте его. Скрипты ищут колонку
> по `SPEAKER_DEVICE_ID`/`SPEAKER_MAC` через `./scripts/resolve-speaker.sh`.
> Если ниже в примере стоит конкретный IP — это текущий снимок, а не гарантия.

## 0. Проверка FLAI

```bash
cd /home/GIT/GITEA/BARVAL-MY/my-pys
./scripts/check-flai.sh
```

Ожидаемо:

- `GET /v1/models` → `200`;
- ответ на тестовый вопрос за 5–40 с;
- непустой русский текст, `finish_reason=stop`.

Если `401` — проверьте `secrets/flai-token`. Если `000` — FLAI не слушает
`192.168.1.2:5000`.

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

### Endpoint внешней LLM

Bridge подключается напрямую к OpenAI-совместимому endpoint. По умолчанию:

```text
http://192.168.1.2:5000/v1
```

Для другой LLM поменяйте `LLM_BASE_URL`, `LLM_MODEL` и ключ в `.env`,
затем переустановите/перезапустите Bridge.

### Вариант A. Интерактивно

```bash
./scripts/install-quasar-bridge.sh
```

Ответы мастера:

| Вопрос | Ответ |
|---|---|
| Адрес API нейросети | `http://192.168.1.2:5000/v1` |
| Название модели | `flai-chat` |
| Ключ API | содержимое `secrets/flai-token` |
| API | `1` (Chat Completions) |
| Home Assistant MCP | Enter (не нужен) |
| Подключить Алису | `y` |
| Перезагрузить | `y` |

Ключ вводится скрыто. Скопировать его:

```bash
cat secrets/flai-token
```

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
make status
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

5. Закоммитить изменения и поставить тег `v1.0` (после проверки).

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
