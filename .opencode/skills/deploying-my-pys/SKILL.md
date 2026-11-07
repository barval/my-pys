---
name: Deploying my-pys
description: Use when deploying, flashing, rooting, or operating the my-pys project (My personal Yandex Station) in this repository — host Docker stack, Yandex Station Lite speakers, Quasar Bridge, LLM router, routes, upstream keys, local TTS, backups, and rollback.
---

# Развёртывание my-pys

## Обзор

Проект целиком: Docker-стек хоста (веб-панель, LLM-роутер, локальный TTS,
узкие sidecar'ы управления), рутованные колонки Yandex Station Lite с
Quasar Bridge, маршруты и ключи на колонку, шифрованные резервные копии.

**Главный принцип: одна колонка за раз, проверка после каждого этапа и
никаких разрушительных шагов без подтверждения.** Все примеры — только
синтетические (`192.168.1.x`, `speaker-a`, `EXAMPLE...`). Никогда не
коммитьте реальные IP, MAC, device ID, токены, имена комнат и колонок: они
живут только в `local/`, `secrets/`, `backups/`, `webui-state/`,
`router-state/`, и эти каталоги исключены из git.

## Когда использовать

- Первое развёртывание хоста или добавление новой колонки.
- Перепрошивка, повторный root, установка или обновление Quasar Bridge.
- Смена маршрутов, upstream-ключей или политики маршрутизации Bridge.
- Резервные копии, восстановление, откат, «колонка замолчала».

## Первичная настройка: сначала панель

Новый маршрут — не ручной файл профиля, а мастер в веб-панели. Панель сама
создаёт `local/speakers/<имя>.env`, маршрут и токен, пишет ключ в колонку и
запускает задания с логом.

1. Поднимите стек: `make router`, `make webui`, `make webui-passwd` (см.
   `references/deployment.md`).
2. Откройте `http://127.0.0.1:8080` и войдите.
3. «Дополнительно → Подготовка хоста» (`/setup/prepare`): скачайте прошивку
   и запустите стенд. В DHCP/DNS роутера укажите DNS-сервер хоста — стенд
   должен подменить `quasar.yandex.net` и отдать колонке прошивку. После
   прошивки остановите стенд и верните прежний DNS.
4. «Колонки → Добавить колонку» (`/speakers/new`): найдите колонку по сети
   (`?scan=1`) или заполните IP, MAC и device ID вручную.
5. «Настроить» (`/speakers/<имя>/setup`): пройдите шаги 2–8 (шаг 1 в
   навигации ведёт на «Подготовку хоста») — привязка,
   поиск, root/ADB, SSH/OTA, маршрут и ключ, Quasar Bridge, проверка
   голосом.
6. «Модели и доступ» (`/access`): если шаг 6 требует провайдера или ключа, добавьте
   их там и вернитесь в мастер.
7. «Проверка» (`/test`): голос, LLM и Bridge для выбранной колонки.

Ручные команды ниже остаются для диагностики, отладки и случаев, когда
панель недоступна. Они делают то же самое, что кнопки мастера.

## Правила безопасности (не пропускать)

1. Определяйте цель по device ID/MAC, а не по IP:
   `./scripts/resolve-speaker.sh`.
2. Пока работает стенд с `run/downgrade`, выключите остальные колонки
   `yandexmicro`: стенд раздаёт прошивку и включает ADB всей локальной сети.
3. Закрепите MAC → IP в DHCP для всех колонок.
4. Сохраните `local/`, `secrets/`, `backups/`; перед любыми изменениями
   сделайте шифрованную копию в панели («Настройки → Резервные копии»).
5. Не выключайте питание во время записи прошивки.
6. Не удаляйте Bridge, пока `control.sh rollback` + `reboot` + голосовой
   ответ Алисы не проверены.
7. Сразу после root остановите стенд и верните DNS роутера.
8. Держите `secrets/*` с правами `0600`. Не открывайте
   `5000/5002/8080/53/80/443` в интернет: роутер и панель рассчитаны на
   локальную сеть.

## Порядок работы

1. Стек хоста → `references/deployment.md`
2. Root колонки и Quasar Bridge → `references/speakers.md`
3. Маршруты, ключи, политика, копии и откат →
   `references/routing-keys-backups.md`

## Быстрый справочник

| Задача | Команда |
|---|---|
| Стек панели (webui + tts + sidecar'ы) | `make webui` |
| LLM-роутер (отдельный compose) | `make router`, `make router-status`, `make router-logs` |
| Пароль веб-панели | `make webui-passwd` (после `make webui`) |
| Найти колонку | `./scripts/resolve-speaker.sh` |
| Root + SSH + OTA off | `SPEAKER_ENV=local/speakers/speaker-a.env ./scripts/post-root-ssh.sh` |
| Установить Bridge | `SPEAKER_ENV=... ./scripts/install-quasar-bridge.sh --non-interactive` |
| Применить политику маршрутизации | `SPEAKER_ENV=... ./scripts/apply-bridge-routing.sh` |
| Записать токен роутера в колонку | `SPEAKER_ENV=... ./scripts/set-speaker-key.sh` |
| Проверить одну колонку | `SPEAKER_ENV=... make status` / `check-backends` / `routes` |
| Сказать фразу на колонке | `docker exec -e SPEAKER_ENV=... -e SAY_TEXT="..." my-pys-webui bash scripts/say-text.sh` |

## Частые ошибки

- Считать `SPEAKER_IP` идентификатором: IP меняется, ключ — device ID/MAC.
- Прошивать или рутовать две колонки одновременно.
- Оставить стенд запущенным или забыть вернуть DNS роутера.
- Править снимки в `vendor/` вместо собственных файлов проекта.
- Коммитить что-либо из `local/`, `secrets/`, `backups/`, `webui-state/`
  или `router-state/`.
- Удалять Bridge до rollback — колонка останется немой.
- Заводить профиль и маршрут вручную при работающей панели: мастер сделает
  это согласованно и оставит лог задания.
