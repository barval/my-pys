#!/usr/bin/env bash
# Проверяет доступ по ADB и наличие root на колонке.
# Печатает вывод adb shell id и завершается 0, только если в нём есть uid=0(root).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib-env.sh
. "$ROOT/scripts/lib-env.sh"
load_project_env "$ROOT"

IP="$(bash "$ROOT/scripts/resolve-speaker.sh")"
ADB_PORT="${SPEAKER_ADB_PORT:-5555}"
DEVICE="$IP:$ADB_PORT"

echo "Подключаемся к $DEVICE..."
adb connect "$DEVICE"

OUTPUT="$(adb -s "$DEVICE" shell id)"
echo "$OUTPUT"

if echo "$OUTPUT" | grep -q 'uid=0(root)'; then
  echo "Root получен."
  exit 0
fi

echo "Root не получен: выполните шаг 2 установщика прошивки." >&2
exit 1
