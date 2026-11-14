#!/usr/bin/env bash
# Переключает тип TTS на колонке: облачный TTS Яндекса или локальный Piper.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib-env.sh
. "$ROOT/scripts/lib-env.sh"
load_project_env "$ROOT"

MODE="${SPEAKER_TTS:-cloud}"
case "$MODE" in
  cloud|piper) ;;
  *)
    echo "Неизвестный тип TTS: $MODE (ожидается cloud или piper)" >&2
    exit 1
    ;;
esac

IP="$("$ROOT/scripts/resolve-speaker.sh")"
PORT="${SPEAKER_SSH_PORT:-2222}"
KEY="$ROOT/secrets/speaker_ed25519"
BASE="${LLM_BASE_URL:-${FLAI_BASE_URL:-http://192.168.1.2:5002/v1}}"
HOST="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.urlsplit(sys.argv[1]).hostname or "")' "$BASE")"
if [[ -z "$HOST" ]]; then
  echo "Не удалось определить адрес хоста из LLM_BASE_URL=$BASE" >&2
  exit 1
fi
PIPER_URL="http://$HOST:${TTS_PORT:-8083}"

echo "Колонка: $IP"
echo "Тип TTS: $MODE"

ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -i "$KEY" -p "$PORT" root@"$IP" 'sh -s' <<EOF 2>&1 | tr -d '\r'
set -e
f=/data/opt/quasar-bridge/runtime.env
touch "\$f"
tmp="\$f.tmp"
grep -v -E '^(QUASAR_TTS_PIPER_URL|QUASAR_TTS_PIPER_MAX_CHARS)=' "\$f" > "\$tmp" || true
if [ "$MODE" = piper ]; then
  cat >> "\$tmp" <<'ENV'
QUASAR_TTS_PIPER_URL="$PIPER_URL"
QUASAR_TTS_PIPER_MAX_CHARS=900
ENV
fi
mv "\$tmp" "\$f"
chmod 600 "\$f"
pkg=/data/opt/quasar-bridge/app
sh "\$pkg/control.sh" restart
sleep 2
sh "\$pkg/control.sh" status
EOF
