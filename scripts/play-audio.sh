#!/usr/bin/env bash
# Проигрывает аудиофайл на колонке. WAV стримится в aplay как есть,
# остальное сначала конвертируется в WAV на хосте через ffmpeg.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib-env.sh
. "$ROOT/scripts/lib-env.sh"
load_project_env "$ROOT"

die() {
  echo "$*" >&2
  exit 1
}

FILE="${AUDIO_FILE:-${1:-}}"
[[ -n "$FILE" ]] || die "Укажите файл: AUDIO_FILE=/path/sound.wav ./scripts/play-audio.sh"
[[ -f "$FILE" ]] || die "Файл не найден: $FILE"
[[ -s "$FILE" ]] || die "Файл пустой: $FILE"

KEY="$ROOT/secrets/speaker_ed25519"
[[ -r "$KEY" ]] || die "Нет SSH-ключа: $KEY. Сначала выполните ./scripts/post-root-ssh.sh"
PORT="${SPEAKER_SSH_PORT:-2222}"

IP="$("$ROOT/scripts/resolve-speaker.sh")" || die \
  "Колонка не найдена. Проверьте SPEAKER_DEVICE_ID/SPEAKER_MAC, питание и сеть."

LABEL="$IP"
if [[ -n "${SPEAKER_NAME:-}" ]]; then
  LABEL="$SPEAKER_NAME${SPEAKER_ROOM:+ — $SPEAKER_ROOM} ($IP)"
fi

WAV="$FILE"
CONVERTED=""
if [[ "$(head -c 4 "$FILE" 2>/dev/null)" != "RIFF" ]]; then
  command -v ffmpeg >/dev/null 2>&1 || die \
    "Файл не WAV, а ffmpeg на хосте не найден. Конвертируйте в WAV 16 бит PCM или установите ffmpeg."
  CONVERTED="$(mktemp --suffix=.wav)"
  echo "Формат:  конвертация в WAV через ffmpeg"
  if ! ffmpeg -v error -y -i "$FILE" -ac 2 -ar 48000 -c:a pcm_s16le "$CONVERTED"; then
    die "ffmpeg не смог декодировать $FILE. Поддерживаются MP3, OGG/Opus, FLAC, M4A/AAC."
  fi
  WAV="$CONVERTED"
else
  echo "Формат:  WAV"
fi

cleanup() {
  [[ -n "$CONVERTED" ]] && rm -f "$CONVERTED"
  if [[ "${AUDIO_FILE_REMOVE:-0}" == "1" ]]; then
    rm -f "$FILE"
  fi
}
trap cleanup EXIT

SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
  -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 \
  -i "$KEY" -p "$PORT")

echo "Колонка: $LABEL"
echo "Файл:    $FILE ($(wc -c < "$FILE" | tr -d ' ') байт)"

if ! "${SSH[@]}" root@"$IP" 'command -v aplay >/dev/null 2>&1'; then
  die "На колонке нет aplay — проиграть звук нечем."
fi

if ! "${SSH[@]}" root@"$IP" 'aplay -q -' < "$WAV"; then
  die "aplay завершился с ошибкой. Проверьте громкость колонки и формат WAV."
fi

echo "Готово: колонка проиграла файл."
