#!/usr/bin/env bash
# Проверка FLAI: список моделей + один голосовой запрос с замером времени.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

BASE="${FLAI_BASE_URL:-http://192.168.1.2:5001/v1}"
MODEL="${FLAI_MODEL:-flai-chat}"
TOKEN_FILE="${FLAI_TOKEN_FILE:-$ROOT/secrets/flai-token}"
[[ "$TOKEN_FILE" = /* ]] || TOKEN_FILE="$ROOT/$TOKEN_FILE"

if [[ ! -r "$TOKEN_FILE" ]]; then
  echo "Нет файла с ключом: $TOKEN_FILE" >&2
  exit 1
fi
TOKEN="$(<"$TOKEN_FILE")"
[[ -n "$TOKEN" ]] || { echo "Ключ пустой: $TOKEN_FILE" >&2; exit 1; }

echo "FLAI:  $BASE"
echo "Model: $MODEL"
echo "Key:   ${TOKEN:0:11}…"

models_code="$(curl -sS -o /tmp/flai-models.json -w '%{http_code}' --max-time 15 \
  -H "Authorization: Bearer $TOKEN" "$BASE/models" || true)"
echo "GET /models -> $models_code"
if [[ "$models_code" != "200" ]]; then
  echo "FLAI не принял ключ или недоступен. Тело ответа:" >&2
  head -c 500 /tmp/flai-models.json >&2 || true
  echo >&2
  exit 1
fi

python3 - "$BASE" "$TOKEN" "$MODEL" <<'PY'
import json
import sys
import time
import urllib.error
import urllib.request

base, token, model = sys.argv[1:4]
body = {
    "model": model,
    "messages": [
        {
            "role": "system",
            "content": (
                "Ты голосовой помощник пользователя. Отвечай по-русски, кратко "
                "и по существу, обычно до трёх предложений. Ответ будет прочитан "
                "вслух: без Markdown и служебных рассуждений."
            ),
        },
        {"role": "user", "content": "Почему небо голубое?"},
    ],
}
req = urllib.request.Request(
    base.rstrip("/") + "/chat/completions",
    data=json.dumps(body).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + token,
    },
)
start = time.time()
try:
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.load(resp)
except urllib.error.HTTPError as exc:
    print(f"HTTP {exc.code}: {exc.read()[:500]!r}", file=sys.stderr)
    sys.exit(1)
except Exception as exc:  # noqa: BLE001 - диагностика важнее типа
    print(f"Ошибка запроса: {exc!r}", file=sys.stderr)
    sys.exit(1)

elapsed = time.time() - start
choice = (data.get("choices") or [{}])[0]
message = choice.get("message") or {}
content = (message.get("content") or "").strip()
print(f"Ответ за {elapsed:.1f} с, finish_reason={choice.get('finish_reason')!r}")
print(f"Токены: {data.get('usage')}")
if not content:
    print("Пустой ответ", file=sys.stderr)
    sys.exit(1)
print("---")
print(content[:1200])
PY
