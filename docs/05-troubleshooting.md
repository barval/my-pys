# 05. Диагностика

> IP колонки может быть случайным. Всегда сначала проверяйте
> `./scripts/resolve-speaker.sh`: он ищет по device ID и MAC, а не по IP.

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

## Прокси 5001 недоступен

Симптом: `check-backends` не проходит, в логах Bridge `LLM returned HTTP 000`
или `connection refused`.

```bash
docker ps --filter name=flai-invocation-proxy
docker logs --tail=50 flai-invocation-proxy
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5001/v1/models \
  -H "Authorization: Bearer $(cat secrets/flai-token)"
```

- `5001` не слушает — `./scripts/start-flai-proxy.sh`.
- `502` — прокси работает, но FLAI на `5000` недоступен; проверьте
  `http://127.0.0.1:5000/health`.
- Bridge всё ещё смотрит на `5000` — в
  `/data/opt/quasar-bridge/runtime.env` должно быть
  `QUASAR_LLM_BASE_URL="http://192.168.1.2:5001/v1"`, затем
  `control.sh restart`.

## Quasar Bridge: «Проверка нейросети не проходит»

Проверьте с ПК:

```bash
./scripts/check-flai.sh
```

Типовые ответы:

| Ошибка | Причина | Что делать |
|---|---|---|
| `HTTP 401` | Неверный/отозванный ключ | Создать новый ключ FLAI, обновить `secrets/flai-token` |
| `HTTP 400` | Неверное тело запроса | Проверить `llm_api` = `chat_completions`, модель `flai-chat` |
| `HTTP 000` / timeout | FLAI недоступен | Проверить `http://192.168.1.2:5000/health`, firewall |
| `LLM returned no answer` | Пустой ответ | Проверить FLAI вручную, `check-backends` |
| `LLM returned HTTP 429` | Лимит FLAI | Подождать, уменьшить частоту |
| `finish_reason=length` | Обрезка ответа | FLAI игнорирует `max_tokens`; проверить модель/промпт |
| Ответ дольше 60 с | Долгий reasoning | Уменьшить сложность, поднять таймаут классификатора, не грузить GPU |

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
- Нейросеть не выбрана: скажите «Алиса, спроси нейросеть: …».
- Классификатор вернул `yandex` или упал по таймауту — это нормально для
  простых вопросов; для сложных поднимите `timeout_ms`.
- Проверьте `config.json` и `runtime.env` на колонке.

## Вернуть всё

См. `docs/04-risks.md`. Сначала `control.sh rollback`, потом `uninstall.sh`,
затем вернуть OTA и DNS.
