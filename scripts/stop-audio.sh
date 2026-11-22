#!/usr/bin/env bash
# Останавливает воспроизведение на колонке: завершает aplay, запущенный
# кнопкой «Сказать» или проверкой аудиофайлом.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib-env.sh
. "$ROOT/scripts/lib-env.sh"
load_project_env "$ROOT"

die() {
  echo "$*" >&2
  exit 1
}

KEY="$ROOT/secrets/speaker_ed25519"
[[ -r "$KEY" ]] || die "Нет SSH-ключа: $KEY. Сначала выполните ./scripts/post-root-ssh.sh"
PORT="${SPEAKER_SSH_PORT:-2222}"

IP="$("$ROOT/scripts/resolve-speaker.sh")" || die \
  "Колонка не найдена. Проверьте SPEAKER_DEVICE_ID/SPEAKER_MAC, питание и сеть."

LABEL="$IP"
if [[ -n "${SPEAKER_NAME:-}" ]]; then
  LABEL="$SPEAKER_NAME${SPEAKER_ROOM:+ — $SPEAKER_ROOM} ($IP)"
fi

SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
  -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 \
  -i "$KEY" -p "$PORT")

echo "Колонка: $LABEL"

if ! "${SSH[@]}" root@"$IP" '
pids=$(pidof aplay 2>/dev/null || true)
if [ -z "$pids" ]; then
  echo "aplay не запущен"
  exit 0
fi
kill $pids 2>/dev/null || true
sleep 1
pids=$(pidof aplay 2>/dev/null || true)
if [ -n "$pids" ]; then
  kill -9 $pids 2>/dev/null || true
fi
echo "воспроизведение остановлено"
'; then
  die "Не удалось остановить звук на $IP:$PORT. Проверьте питание, сеть и SSH-ключ."
fi
