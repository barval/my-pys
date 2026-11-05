#!/usr/bin/env bash
# Собирает кастомный Quasar Bridge с чанкингом длинных ответов.
# Требуется Docker; Go на хосте не нужен.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${QUASAR_VERSION:-v0.6.2-chunked}"
BASE_VERSION="v0.6.2"
STOCK="$ROOT/.cache/release-$BASE_VERSION/quasar-bridge-linux-arm64.tar.gz"
DEST="$ROOT/.cache/release-$VERSION"
BUILD="$ROOT/.cache/qbridge-build"

if [[ ! -s "$STOCK" ]]; then
  echo "Нет базового релиза: $STOCK" >&2
  echo "Сначала выполните: ./scripts/fetch-quasar-bridge.sh" >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "Нужен Docker для сборки arm64." >&2
  exit 1
fi

if ! rm -rf "$BUILD" 2>/dev/null; then
  # Предыдущие ручные сборки могли оставить root-owned файлы в кэше модулей.
  docker run --rm -v "$BUILD":/clean alpine \
    sh -c 'rm -rf /clean/* /clean/.[!.]* /clean/..?* 2>/dev/null || true'
  rmdir "$BUILD" 2>/dev/null || true
fi
mkdir -p "$BUILD/src" "$BUILD/gomod" "$BUILD/gocache" "$BUILD/release" "$DEST"
cp -a "$ROOT/vendor/quasar-bridge/." "$BUILD/src/"

echo "== сборка linux/arm64 =="
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$BUILD/src":/src \
  -v "$BUILD/gomod":/gomod \
  -v "$BUILD/gocache":/gocache \
  -w /src \
  -e HOME=/tmp \
  -e GOMODCACHE=/gomod \
  -e GOCACHE=/gocache \
  -e GOFLAGS=-mod=mod \
  -e CGO_ENABLED=0 \
  -e GOOS=linux \
  -e GOARCH=arm64 \
  golang:1.27 \
  go build -trimpath -ldflags '-s -w' -o /src/quasar-bridge-arm64 ./cmd/quasar-bridge

tar xzf "$STOCK" -C "$BUILD/release"
install -m 755 "$BUILD/src/quasar-bridge-arm64" "$BUILD/release/bin/quasar-bridge"
printf '0.6.2-chunked\n' > "$BUILD/release/VERSION"
printf 'arm64\n' > "$BUILD/release/ARCH"

tar czf "$DEST/quasar-bridge-linux-arm64.tar.gz" -C "$BUILD/release" .
(cd "$DEST" && sha256sum quasar-bridge-linux-arm64.tar.gz > quasar-bridge-linux-arm64.tar.gz.sha256)
echo "Готово: $DEST/quasar-bridge-linux-arm64.tar.gz"
