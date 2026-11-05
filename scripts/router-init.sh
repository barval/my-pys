#!/usr/bin/env bash
# Создаёт промежуточные ключи колонок и secrets/router-routes.json.
# Существующий конфиг не перезаписывает: fallback-маршруты можно править вручную.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS="$ROOT/secrets"
mkdir -p "$SECRETS" "$ROOT/router-state"

for name in speaker-a speaker-b speaker-c speaker-d; do
  token_file="$SECRETS/router-token-$name"
  if [[ ! -s "$token_file" ]]; then
    token="$(python3 -c 'import secrets; print("sk-router-" + secrets.token_hex(24))')"
    printf '%s\n' "$token" > "$token_file"
    echo "Создан промежуточный ключ: secrets/router-token-$name"
  fi
  chmod 600 "$token_file"
done

config="$SECRETS/router-routes.json"
if [[ -f "$config" ]]; then
  echo "Конфиг уже существует: secrets/router-routes.json (не перезаписываю)"
else
  python3 - "$config" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
routes = []
for name in ("speaker-a", "speaker-b", "speaker-c", "speaker-d"):
    routes.append(
        {
            "name": name,
            "token_file": f"router-token-{name}",
            "session": {
                "mode": "server",
                "user": "voice",
                "idle_minutes": 30,
                "cleanup_keep": 3,
            },
            "primary": {
                "base_url": "http://192.168.1.2:5000/v1",
                "api_key_file": f"upstream-token-{name}",
                "model": "your-model",
                "history": "server",
                "timeout_seconds": 180,
                "fallback_on": [429, 500, 502, 503, 504],
            },
            "fallbacks": [],
        }
    )
path.write_text(json.dumps({"routes": routes}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  echo "Создан конфиг: secrets/router-routes.json"
fi
chmod 600 "$config"

for name in speaker-a speaker-b speaker-c speaker-d; do
  if [[ ! -s "$SECRETS/flai-token-$name" ]]; then
    echo "Внимание: нет upstream-ключа secrets/upstream-token-$name — маршрут $name будет отвечать 503." >&2
  fi
done
