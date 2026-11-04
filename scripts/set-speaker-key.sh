#!/usr/bin/env bash
# Записывает API-ключ внешней LLM из профиля колонки в runtime.env и
# перезапускает Bridge. Ключ хранится только на хосте и на колонке.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib-env.sh
. "$ROOT/scripts/lib-env.sh"
load_project_env "$ROOT"

IP="$("$ROOT/scripts/resolve-speaker.sh")"
PORT="${SPEAKER_SSH_PORT:-2222}"
KEY="$ROOT/secrets/speaker_ed25519"
TOKEN_FILE="${LLM_TOKEN_FILE:-${FLAI_TOKEN_FILE:-$ROOT/secrets/flai-token-speaker-a}}"
[[ "$TOKEN_FILE" = /* ]] || TOKEN_FILE="$ROOT/$TOKEN_FILE"

if [[ ! -r "$TOKEN_FILE" ]]; then
  echo "Нет файла с ключом: $TOKEN_FILE" >&2
  echo "Создайте его: chmod 600, содержимое — API-ключ FLAI." >&2
  exit 1
fi
TOKEN="$(<"$TOKEN_FILE")"
[[ -n "$TOKEN" ]] || { echo "Ключ пустой: $TOKEN_FILE" >&2; exit 1; }

echo "Колонка: $IP"
echo "Ключ:    ${TOKEN:0:11}… ($TOKEN_FILE)"

KEY_LINE="QUASAR_LLM_API_KEY=\"$TOKEN\""
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -i "$KEY" -p "$PORT" root@"$IP" "
set -e
f=/data/opt/quasar-bridge/runtime.env
if grep -q '^QUASAR_LLM_API_KEY=' \"\$f\"; then
  sed -i 's|^QUASAR_LLM_API_KEY=.*|$KEY_LINE|' \"\$f\"
else
  printf '%s\n' '$KEY_LINE' >> \"\$f\"
fi
chmod 600 \"\$f\"
pkg=/data/opt/quasar-bridge/app
sh \"\$pkg/control.sh\" restart
sleep 2
sh \"\$pkg/control.sh\" status
sh \"\$pkg/control.sh\" check-backends
" 2>&1 | tr -d '\r'
