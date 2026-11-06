# Маршруты, ключи, копии, откат

## Политика маршрутизации

Политика — `config/quasar-bridge-policy.json`. `default_route` — `llm`,
поэтому всё, что не совпало с правилом Яндекса, уходит в LLM-роутер;
классификатор не вызывается. Правила: `speaker_playback`, `speaker_controls`,
`yandex_intercom`, `home_devices`, `home_state`, `yandex_scenarios`,
`yandex_weekday`, `yandex_services` — все в Яндекс (или Home Assistant).

```bash
export SPEAKER_ENV=local/speakers/speaker-a.env
./scripts/apply-bridge-routing.sh
```

Скрипт вливает в `config.json` колонки только `default_route` и `rules`,
затем запускает `check`, `restart`, `status`, `check-backends`.

В панели политика видна в «Продвинутое → Политика Bridge»
(`/advanced/bridge`) только для чтения; кнопка «Применить» у колонки
запускает тот же routing.

Проверить маршрут без выполнения:

```bash
ssh -i secrets/speaker_ed25519 -p 2222 root@"$(./scripts/resolve-speaker.sh)"
set -a; . /data/opt/quasar-bridge/runtime.env; set +a
pkg=/data/opt/quasar-bridge/app
"$pkg/bin/quasar-bridge" -config /data/opt/quasar-bridge/config.json -route "какая погода завтра"
```

Кто ответил — из лога Bridge:

```bash
make routes   # tail native_route_decision
```

`route=llm` — внешняя LLM; `route=yandex` — Алиса; `source=rule` —
сработало правило; `source=default` — `default_route`.

## Ключи

Два уровня, которые нельзя смешивать:

```text
speaker runtime.env
  QUASAR_LLM_API_KEY=sk-router-...   промежуточный токен
        │
secrets/router-routes.json (маршрут по token_file)
  primary.api_key_file / fallbacks[].api_key_file   upstream-ключи
```

- Промежуточные токены: один на маршрут/колонку, файлы
  `secrets/router-token-<имя>`. Ротация — «Модели → Ключи → Сменить токен»
  (она же перезаписывает токен в колонку); `make key` только записывает
  текущий токен в колонку.
- Upstream-ключи: общий список в «Модели → Ключи → Upstream-ключи»:
  1. откройте раздел и добавьте ключ: имя файла (например,
     `openrouter-token-speaker-a`) и значение;
  2. значение пишется в `secrets/<файл>` с режимом `0600`, в реестре
     остаётся только имя файла;
  3. откройте «Модели → Маршруты», измените маршрут (или добавьте
     запасной), выберите новый ключ в списке «Ключ» для основного или
     запасного upstream и сохраните. Роутер сам перечитывает
     `secrets/router-routes.json`.

  Один ключ может использоваться несколькими маршрутами; используемый
  ключ удалить нельзя. Старые имена `api_key_file` импортируются в список
  автоматически.

Смена upstream-провайдера или ключа не требует трогать колонку. Смена
промежуточного токена требует `set-speaker-key.sh` или действия «Записать
ключ» / кнопки «Записать ключ в колонку».

Полный порядок на экране «Модели»: провайдер → ключ → маршрут → запись
ключа в колонку. Сырой JSON маршрутов доступен в
«Продвинутое → Маршруты» (`/advanced/routes`), значения секретов там
замаскированы.

## Копии и восстановление

Создание в панели: «Ещё → Резервные копии» → «Вся конфигурация» или одна
колонка, введите парольную фразу и скачайте архив. Фраза не сохраняется —
держите её, без неё архив не открыть. Архивы `.tar.gz.enc` (AES-GCM +
PBKDF2) лежат в `backups/config/` с режимом `0600`. Архив одной колонки
содержит профиль, фрагмент её маршрута и ключи этого маршрута.
`webui-session.key`, логи, `router-state` и аудит не включаются.
«Проверить» показывает манифест, не трогая рабочую конфигурацию.

Восстановление всегда сначала делает снимок текущего состояния в
`webui-state/restore-backups/<timestamp>/`, затем требует `REPLACE`. Полное
восстановление заменяет профили, ключи и конфиг роутера; одной колонки —
только её.

## Откат и восстановление

Откат endpoint Bridge (порядок важен):

```sh
pkg=/data/opt/quasar-bridge/app
sh "$pkg/control.sh" rollback && reboot      # Алиса снова говорит с Яндексом
# проверьте голос, затем:
sh "$pkg/uninstall.sh"                        # откажется, пока есть endpoint-backup.json
```

Правки root: `sh /data/opt/yandex-noupdate.sh restore && reboot` (OTA),
удалить `/etc/init.d/S99zdropbear` (SSH) или сделать сброс кнопкой.

Если колонка замолчала: проверьте `control.sh status` и `logs`; попробуйте
`control.sh rollback`; если SSH/ADB пропали — сброс кнопкой (очищает
`/data`) или перепрошивка со стенда. Никогда не выключайте питание во время
записи.

## Сказать фразу на колонке

В панели это «Проверка → Голос» (`/test#voice`, до 500 символов) или, в
продвинутом режиме, действие «Сказать» на карточке колонки. Скрипту нужен
внутренний сервис `tts`, поэтому запускайте его в контейнере `webui`:

```bash
docker exec -e SPEAKER_ENV=local/speakers/speaker-a.env -e SPEAKER_TRUST_IP=1 \
  -e SAY_TEXT="Приятного аппетита" my-pys-webui bash scripts/say-text.sh
```

Синтез — локальный Piper (`tts`), воспроизведение WAV на колонке через
`aplay` (есть в проверенной прошивке; проверьте `aplay -l`). Нужны
контейнер `tts` (`make webui`) и SSH-ключ.
