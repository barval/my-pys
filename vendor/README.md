# Vendor snapshots

Эти каталоги — снапшоты сторонних проектов. Они нужны, чтобы установка
не зависела от доступности GitHub и чтобы версии были зафиксированы.
Не редактируйте их без причины; изменения оформляйте отдельным коммитом
с описанием, зачем отступили от upstream.

## quasar-bridge

- Upstream: https://github.com/skrashevich/quasar-bridge
- Версия: **v0.6.2**
- Коммит: `1e7f76d`
- Лицензия: Apache-2.0 (`vendor/quasar-bridge/LICENSE`)
- Что внутри: исходники, `packaging/speaker`, примеры конфигурации,
  документация.
- Используется: установщик и бинарники ставятся на колонку; исходники
  нужны для чтения настроек и диагностики.

## lite-kit

- Upstream: https://github.com/krevetkqqq/lite-kit
- Коммит: `8a82ff3`
- Лицензия: MIT (`vendor/lite-kit/LICENSE`)
- Что внутри: DNS/HTTPS-стенд, сертификаты, скрипты запуска и загрузки
  прошивки.
- Прошивка в репозиторий не входит: `vendor/lite-kit/firmware/**/*.zip`
  исключены `.gitignore` и скачиваются `scripts/fetch-firmware.sh`.
- Проверенная версия для `yandexmicro`:
  `0.369.1.46.4778262442.20261013.297`.
- Файл скачивается с официального CDN Яндекса скриптом
  `scripts/fetch-firmware.sh`; контрольные суммы зафиксированы в скрипте
  и в `manifest.json`.

## station-tools

Взято из https://github.com/Marker284/yandex-station-extended
(коммит `4429bcf`), только необходимое:

| Файл | Назначение | Лицензия/источник |
|---|---|---|
| `bin/dropbear` | SSH-сервер для armhf | upstream-репозиторий |
| `bin/dropbearkey` | генерация host key | upstream-репозиторий |
| `yandex-noupdate.sh` | отключение OTA | upstream-репозиторий |
| `S99zdropbear` | init-скрипт автозапуска | написано для этого проекта по инструкции вики |

Полную вики не копировали: она весит ~79 МБ и быстро меняется. Основные
команды и порядок — в `docs/03-runbook.md`.

## Как обновлять

1. Зафиксируйте текущий коммит: `git -C vendor/<name> rev-parse --short HEAD`.
2. Скачайте новую версию во временный каталог.
3. Сравните `git diff --no-index` или `diff -ru`.
4. Проверьте, что наши скрипты всё ещё совместимы (особенно
   `packaging/speaker/setup.sh` и `config/dnsmasq.conf.tpl`).
5. Обновите этот файл и `CHANGELOG.md`.
6. Проверьте на живой колонке только после чтения diff.
