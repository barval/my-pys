#!/usr/bin/env bash
# Записывает адрес LLM-роутера и промежуточный ключ из профиля колонки в
# runtime.env и перезапускает Bridge. Ключ хранится только на хосте и на колонке.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib-env.sh
. "$ROOT/scripts/lib-env.sh"
load_project_env "$ROOT"

IP="$("$ROOT/scripts/resolve-speaker.sh")"
PORT="${SPEAKER_SSH_PORT:-2222}"
KEY="$ROOT/secrets/speaker_ed25519"
TOKEN_FILE="${LLM_TOKEN_FILE:-${FLAI_TOKEN_FILE:-$ROOT/secrets/router-token-example}}"
[[ "$TOKEN_FILE" = /* ]] || TOKEN_FILE="$ROOT/$TOKEN_FILE"
BASE="${LLM_BASE_URL:-${FLAI_BASE_URL:-http://192.168.1.2:5002/v1}}"
MODEL="${LLM_MODEL:-${FLAI_MODEL:-flai-chat}}"

if [[ ! -r "$TOKEN_FILE" ]]; then
  echo "Нет файла с ключом: $TOKEN_FILE" >&2
  echo "Создайте его: chmod 600, содержимое — ключ LLM-роутера (sk-router-…)." >&2
  exit 1
fi
TOKEN="$(<"$TOKEN_FILE")"
[[ -n "$TOKEN" ]] || { echo "Ключ пустой: $TOKEN_FILE" >&2; exit 1; }

echo "Колонка: $IP"
echo "LLM:     $BASE"
echo "Модель:  $MODEL"
echo "Ключ:    ${TOKEN:0:11}… ($TOKEN_FILE)"

ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -i "$KEY" -p "$PORT" root@"$IP" 'sh -s' <<EOF 2>&1 | tr -d '\r'
set -e
f=/data/opt/quasar-bridge/runtime.env
touch "\$f"
tmp="\$f.tmp"
grep -v -E '^(QUASAR_LLM_BASE_URL|QUASAR_LLM_MODEL|QUASAR_LLM_API_KEY)=' "\$f" > "\$tmp" || true
cat >> "\$tmp" <<'ENV'
QUASAR_LLM_BASE_URL="$BASE"
QUASAR_LLM_MODEL="$MODEL"
QUASAR_LLM_API_KEY="$TOKEN"
ENV
mv "\$tmp" "\$f"
chmod 600 "\$f"
pkg=/data/opt/quasar-bridge/app
sh "\$pkg/control.sh" restart
sleep 2
sh "\$pkg/control.sh" status
sh "\$pkg/control.sh" check-backends
EOF
