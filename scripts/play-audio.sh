#!/usr/bin/env bash
# Копирует аудиофайл на колонку и проигрывает его:
# WAV — через aplay, остальное — через GStreamer (gst-launch-1.0).
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

EXT="${FILE##*.}"
if [[ "$EXT" = "$FILE" ]]; then
  EXT="bin"
fi
EXT="$(printf '%s' "$EXT" | tr 'A-Z' 'a-z' | tr -cd 'a-z0-9')"
[[ -n "$EXT" ]] || EXT="bin"
REMOTE="/tmp/my-pys-audio.${EXT}"

LOCAL_SIZE="$(wc -c < "$FILE" | tr -d ' ')"
LABEL="$IP"
if [[ -n "${SPEAKER_NAME:-}" ]]; then
  LABEL="$SPEAKER_NAME${SPEAKER_ROOM:+ — $SPEAKER_ROOM} ($IP)"
fi

SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -i "$KEY" -p "$PORT")

echo "Колонка: $LABEL"
echo "Файл:    $FILE ($LOCAL_SIZE байт)"

if ! "${SSH[@]}" root@"$IP" 'cat > '"$REMOTE" < "$FILE"; then
  die "Не удалось скопировать файл на $IP:$PORT. Проверьте питание, сеть и SSH-ключ."
fi

if [[ "${AUDIO_FILE_REMOVE:-0}" == "1" ]]; then
  rm -f "$FILE"
fi

cleanup() {
  "${SSH[@]}" root@"$IP" "rm -f '$REMOTE'" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [[ "$(head -c 4 "$FILE")" == "RIFF" ]]; then
  echo "Формат:  WAV (aplay)"
  if ! "${SSH[@]}" root@"$IP" "command -v aplay >/dev/null 2>&1"; then
    die "На колонке нет aplay — проиграть WAV нечем."
  fi
  if ! "${SSH[@]}" root@"$IP" "aplay -q '$REMOTE'"; then
    die "aplay завершился с ошибкой. Проверьте, что WAV — 16 бит PCM, и громкость колонки."
  fi
else
  echo "Формат:  сжатый (GStreamer)"
  if ! "${SSH[@]}" root@"$IP" "command -v gst-launch-1.0 >/dev/null 2>&1"; then
    die "На колонке нет gst-launch-1.0 — проиграть сжатый файл нечем."
  fi
  if ! "${SSH[@]}" root@"$IP" \
    "gst-launch-1.0 -q filesrc location='$REMOTE' ! decodebin ! audioconvert ! audioresample ! alsasink"; then
    die "GStreamer не смог декодировать файл. Поддерживаются MP3, OGG/Opus, FLAC, M4A/AAC."
  fi
fi

echo "Готово: колонка проиграла файл."
