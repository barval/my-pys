#!/usr/bin/env bash
# Синтезирует текст локальным TTS и проигрывает его на колонке через aplay.
# Текст передаётся в SAY_TEXT, чтобы не светиться в списке процессов.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib-env.sh
. "$ROOT/scripts/lib-env.sh"
load_project_env "$ROOT"

TEXT="${SAY_TEXT:-${1:-}}"
if [[ -z "${TEXT//[[:space:]]/}" ]]; then
  echo "Пустой текст: нечего произносить." >&2
  exit 1
fi

TTS_URL="${SAY_TTS_URL:-http://tts:8083/say}"
IP="$("$ROOT/scripts/resolve-speaker.sh")"
PORT="${SPEAKER_SSH_PORT:-2222}"
KEY="$ROOT/secrets/speaker_ed25519"
WAV="$(mktemp)"

cleanup() {
  rm -f "$WAV"
}
trap cleanup EXIT

echo "Колонка: $IP"
echo "TTS:     $TTS_URL"
echo "Текст:   $TEXT"

TTS_URL="$TTS_URL" SAY_TEXT="$TEXT" python3 - "$WAV" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

out = sys.argv[1]
request = urllib.request.Request(
    os.environ["TTS_URL"],
    data=json.dumps({"text": os.environ["SAY_TEXT"]}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace")
    raise SystemExit(f"TTS вернул HTTP {exc.code}: {detail}")
except urllib.error.URLError as exc:
    raise SystemExit(
        f"TTS недоступен по адресу {os.environ['TTS_URL']}: {exc.reason}. "
        "Проверьте контейнер my-pys-tts (make webui)."
    )
if not data[:4] == b"RIFF":
    raise SystemExit("TTS вернул не WAV")
with open(out, "wb") as handle:
    handle.write(data)
PY

SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -i "$KEY" -p "$PORT")
"${SSH[@]}" root@"$IP" 'cat > /tmp/my-pys-say.wav' < "$WAV"
"${SSH[@]}" root@"$IP" 'aplay -q /tmp/my-pys-say.wav; rm -f /tmp/my-pys-say.wav'
echo "Готово: колонка произнесла текст."
