# FLAI для Quasar Bridge

FLAI уже развёрнут на `192.168.1.2`. Переменные ниже используются
скриптами репозитория; скопируйте файл в `.env` и поправьте при необходимости.

```bash
cp config/flai.env.example .env
```

| Переменная | Значение по умолчанию | Что значит |
|---|---|---|
| `FLAI_BASE_URL` | `http://192.168.1.2:5000/v1` | OpenAI-совместимый endpoint |
| `FLAI_MODEL` | `flai-chat` | FLAI игнорирует поле, но клиент обязан его передать |
| `FLAI_TOKEN_FILE` | `secrets/flai-token` | Файл с Bearer-ключом |

Ключ создан в веб-интерфейсе FLAI:

- пользователь: `operator`;
- имя: `quasar-bridge`;
- префикс: `flai-_XGpOA`.

Проверка:

```bash
./scripts/check-flai.sh
```

## Почему не `qwen3:30b-a3b` из документации Quasar Bridge

В документации Quasar Bridge советуют Ollama-модель без рассуждений.
У нас не Ollama, а FLAI: он сам выбирает модель по типу запроса. Поле
`model` игнорируется, поэтому `flai-chat` — просто удобное имя.

## Ограничения FLAI, важные для Bridge

1. `response_format` игнорируется. JSON получается только потому, что
   системный промпт классификатора прямо просит JSON.
2. `temperature`, `max_tokens`, `chat_template_kwargs` игнорируются.
3. `tools`, `tool_choice`, `functions` игнорируются. Поэтому инструменты
   Quasar Bridge (`assistant_tools`) не могут вызывать функции через FLAI;
   их лучше держать выключенными.
4. Сложный запрос может идти 30–40 с. Таймаут Bridge — 60 с, классификатора —
   8 с по умолчанию.
5. FLAI хранит сессии. Голосовые запросы появляются в веб-чате.
6. `model` в ответе всегда `flai-chat`.

## Фразы для вызова FLAI

Правило `explicit_llm_phrase` (файл `config/quasar-bridge-routing.json`)
стоит первым в `routing.rules` и отправляет в FLAI запросы, содержащие:

- `спроси у нейросети`
- `спроси у своей модели`
- `спроси у нейронки`
- `спроси нейросеть`
- `спроси свою модель`
- `спроси флай`
- `спроси у флай`

Применить/обновить:

```bash
./scripts/apply-bridge-routing.sh
```

Важно: `спроси у нейросети` не совпадало со встроенным правилом
`спроси нейросеть`; именно поэтому нужен отдельный `explicit_llm_phrase`.
Фразу «спроси ФЛАЙ» ASR обычно приводит к нижнему регистру, поэтому в
правиле хранятся строчные варианты.

Если запрос после этого всё равно уходит Алисе, проверьте:

```bash
make routes
```

`route="yandex"` означает, что правило не сработало или запрос распознан
иначе. Тогда смотрите `conversation_log` и добавляйте реальную формулировку.

## Камера в FLAI — это целевой сценарий

Так и задумано: **FLAI описывает снимок камеры текстом, Алиса произносит
этот текст**. Цепочка:

```
«Алиса, спроси ФЛАЙ: как дела в комнате A?»
  → Quasar Bridge (правило explicit_llm_phrase)
  → FLAI /v1/chat/completions
  → camera_snapshot(room=kab)
  → flai-room-snapshot-api /snapshot/kab
  → Qwen3VL описывает изображение
  → текст возвращается в Bridge
  → Yandex TTS озвучивает ответ голосом Алисы
```

В логах FLAI это выглядит так:

```text
Tool call: camera_snapshot({'room': 'kab'})
Request to camera: http://flai-room-snapshot-api:5000/snapshot/kab
Successfully got snapshot from camera kab
Tool result: {"success": true, "room": "комната A", "description": "..."}
```

Проверка маршрута на колонке — `make routes`: должно быть
`route="llm"`. Ответ Bridge — `make flai-log` / журнал разговоров.
Если камера недоступна, FLAI вернёт ошибку, и Bridge скажет, что не
получилось получить ответ локальной модели.

## Отдельный пользователь FLAI (рекомендуется позже)

Чтобы голосовые запросы не смешивались с личной историей:

1. В FLAI: «Администрирование» → «Пользователи» → создать `alice`.
2. Войти как `alice`, создать API-ключ `quasar-bridge`.
3. Заменить `secrets/flai-token`.
4. Перезапустить Bridge:
   `sh /data/opt/quasar-bridge/app/control.sh restart`.

Пока используется `operator`, чтобы не менять настройки FLAI перед первым
тестом.
