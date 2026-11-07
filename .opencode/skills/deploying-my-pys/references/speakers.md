# Колонки: прошивка, root, Quasar Bridge

Делайте ровно одну колонку за раз. Стенд с `run/downgrade` раздаёт прошивку
и ADB всем `yandexmicro` в локальной сети, поэтому остальные выключите.

Порядок для одной колонки: root/SSH → установка Bridge →
`set-speaker-key.sh` → `apply-bridge-routing.sh`. Скрипты ключа и routing
работают с запущенным Bridge, поэтому сначала установите его. Веб-панель
запускает эти скрипты в контейнере с `SPEAKER_TRUST_IP=1` (ARP там не
виден); задавайте её и при ручном запуске в контейнере.

В панели этот же порядок проходит мастер: «Колонки → Настроить», шаги 2–8
(шаг 1 в навигации ведёт на «Подготовку хоста»).
Ручные команды ниже нужны для диагностики и когда панель недоступна.

## 0. Профиль колонки

Проще всего создать его в панели: «Колонки → Добавить колонку»
(`/speakers/new`) — поиск по сети заполнит IP, MAC и device ID, а панель
запишет `local/speakers/<имя>.env`. Вручную:

```bash
cp config/speaker.env.example local/speakers/speaker-a.env
# заполните SPEAKER_IP, SPEAKER_SUBNET, SPEAKER_DEVICE_ID, SPEAKER_MAC,
# SPEAKER_ROOM, SPEAKER_COLOR, LLM_BASE_URL, LLM_TOKEN_FILE
```

## 1. Прошивка и стенд

```bash
./scripts/fetch-firmware.sh            # пишет vendor/lite-kit/firmware/yandexmicro/<версия>.zip
./scripts/start-lite-kit.sh            # docker compose up, network_mode: host
ss -lntup | grep -E ':(53|80|443)\b'
dig +short @192.168.1.2 quasar.yandex.net A     # -> 192.168.1.2
```

В DHCP роутера укажите предпочтительный DNS — хост (`192.168.1.2`),
альтернативный очистите, для MAC всех колонок сделайте резервирование.
Стенд слушает 53/80/443 и отдаёт сборку `.46`; он же включает ADB через
sync. То же самое в панели: «Дополнительно → Подготовка хоста» (`/setup/prepare`).

```bash
./scripts/stop-lite-kit.sh             # затем верните DNS роутера
```

## 2. Сброс и привязка

1. Отключите питание, включите и сразу зажмите кнопку паузы на 6–10 с,
   пока подсветка не станет жёлто-зелёной, затем отпустите. Сброс очищает
   `/data` и отвязывает аккаунт.
2. В «Дом с Алисой»: полностью перезапустите приложение, выключите Wi-Fi
   телефона, оставьте мобильный интернет и Bluetooth, добавьте устройство,
   введите пароль Wi-Fi и только потом нажмите подключение.
3. Колонка скачает сборку `.46` со стенда и включит ADB. Не выключайте
   питание.

В панели это шаг 2 мастера: действие выполняется вручную, панель только
фиксирует результат кнопкой «Готово».

## 3. ADB и root

```bash
export SPEAKER_ENV=local/speakers/speaker-a.env
adb connect "$(./scripts/resolve-speaker.sh):5555"
adb shell id          # должно быть uid=0(root); иначе остановитесь и смотрите логи стенда
```

Root появляется из sync-инъекции стенда и прошивки `.46` — отдельного
эксплойта нет. Если `uid=2000(shell)` — остановитесь. В панели это шаг 4,
кнопка «Проверить ADB и root» (`scripts/adb-root-check.sh`).

## 4. SSH и отключение OTA

```bash
export SPEAKER_ENV=local/speakers/speaker-a.env
./scripts/post-root-ssh.sh            # REBOOT=n пропускает перезагрузку
```

Скрипт проверяет `uid=0`, создаёт `secrets/speaker_ed25519`, ставит Dropbear
(`S99zdropbear`), отключает OTA (`yandex-noupdate.sh`), складывает резервную
копию `quasar.cfg` в `backups/<дата>-<SPEAKER_NAME>/` и перезагружает
колонку. После перезагрузки проверьте:

```bash
ssh -i secrets/speaker_ed25519 -p 2222 root@"$(./scripts/resolve-speaker.sh)" \
  'id; sh /data/opt/yandex-noupdate.sh status'
```

Только после успешного входа по ключу уберите `-B` у Dropbear (пустой
пароль):

```bash
ssh -i secrets/speaker_ed25519 -p 2222 root@"$(./scripts/resolve-speaker.sh)" \
  'mount -o remount,rw /; sed -i "s/ -B / /" /etc/init.d/S99zdropbear; sync; \
   mount -o remount,ro /; /etc/init.d/S99zdropbear restart'
```

Затем войдите по ключу снова и убедитесь, что пустой пароль больше не
работает. В панели это шаг 5, кнопка «Настроить SSH/OTA».

## 5. Quasar Bridge

```bash
./scripts/fetch-quasar-bridge.sh      # по умолчанию v0.6.2
./scripts/build-quasar-bridge.sh      # необязательная сборка chunked (Docker)
export SPEAKER_ENV=local/speakers/speaker-a.env
./scripts/install-quasar-bridge.sh --non-interactive     # или интерактивно
```

Установщику нужен `secrets/speaker_ed25519`; для неинтерактивного пути —
`python3-pexpect` (в образе `webui` уже установлен); сборка `-chunked` берётся из `.cache/`, если она там
есть. Он также читает `LLM_TOKEN_FILE` из профиля (запасной вариант —
`secrets/router-token-example`), поэтому профиль должен его задавать.
`make router-init` создаёт только `secrets/router-token-speaker-a`…`speaker-d`;
для других имён сначала создайте токен и маршрут в панели («Модели и доступ»
или шаг 6 мастера).

Интерактивный мастер спросит: URL роутера (`http://192.168.1.2:5002/v1`),
имя модели, промежуточный токен из `secrets/router-token-<имя>`, тип API
`1` (Chat Completions), пустой Home Assistant MCP, затем подключение Алисы
и перезагрузку. В панели это шаг 7, кнопка «Установить Bridge».

Проверка и управление:

```bash
ssh -i secrets/speaker_ed25519 -p 2222 root@"$(./scripts/resolve-speaker.sh)" \
  'pkg=/data/opt/quasar-bridge/app; sh "$pkg/control.sh" status; sh "$pkg/control.sh" check-backends'
```

| `control.sh` | Действие |
|---|---|
| `start` / `stop` / `restart` | управление процессом Bridge (ждёт `/healthz`) |
| `status` | PID + `/healthz` |
| `logs` | tail `service.log` |
| `check` / `check-backends` | конфиг / LLM + Home Assistant |
| `apply` | направить Алису на локальный Bridge; нужна перезагрузка |
| `rollback` | вернуть сохранённый endpoint Алисы; до удаления |

Если `Port 8443 already serves another bridge` — `killall quasar-bridge` и
`control.sh start`. Если `scp` падает (`sftp-server` нет), залейте бинарник
через `ssh ... 'cat > /path/binary'` со stdin.

## 6. Записать токен роутера

```bash
export SPEAKER_ENV=local/speakers/speaker-a.env
./scripts/set-speaker-key.sh
```

Пишет `QUASAR_LLM_BASE_URL`, `QUASAR_LLM_MODEL`, `QUASAR_LLM_API_KEY`
(промежуточный `sk-router-*`) в `runtime.env` колонки и перезапускает
Bridge. Ключи провайдеров колонка не видит. В панели это шаг 6
(«Создать маршрут и записать ключ») или кнопка «Ключ в колонку» на
экране «Модели и доступ».

## 7. Повторить

Выключите готовую колонку (или хотя бы уберите её), включите следующую и
повторите разделы 2–6. Когда все готовы: `stop-lite-kit.sh`, верните DNS
роутера, включите остальные и проверьте голосом.

Если мастер панели застрял, смотрите `/advanced/jobs` и раздел «Что делать,
если мастер застрял на шаге N» в `deployment.md`.
