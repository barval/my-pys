#!/usr/bin/env bash
# Скачивает релиз Quasar Bridge (по умолчанию v0.6.2) для офлайн-установки.
# GitHub release-assets иногда отваливается по IPv6/таймауту — используем -4.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib-env.sh
. "$ROOT/scripts/lib-env.sh"
load_project_env "$ROOT"

VERSION="${QUASAR_VERSION:-v0.6.2}"
ARCH="${QUASAR_ARCH:-arm64}"
DEST="$ROOT/.cache/release-$VERSION"
BASE="https://github.com/skrashevich/quasar-bridge/releases/download/$VERSION"
ARCHIVE="quasar-bridge-linux-$ARCH.tar.gz"

mkdir -p "$DEST"
cd "$DEST"

for f in "$ARCHIVE" "$ARCHIVE.sha256"; do
  if [[ -s "$f" ]]; then
    echo "Уже есть: $DEST/$f"
    continue
  fi
  echo "Скачивание $BASE/$f"
  curl -4 -fL --retry 3 --retry-delay 2 --connect-timeout 30 --max-time 300 \
    -o "$f" "$BASE/$f"
done

if ! sha256sum -c "$ARCHIVE.sha256"; then
  echo "Контрольная сумма не совпала. Удалите $DEST и повторите." >&2
  exit 1
fi

echo
echo "Готово: $DEST/$ARCHIVE"
echo "Установка: ./scripts/install-quasar-bridge.sh"
