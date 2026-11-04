#!/usr/bin/env bash
# Запускает lite-kit в Docker с host-network: DNS 53, HTTP 80, HTTPS 443.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

VERSION="${YANDEXMICRO_VERSION:-0.369.1.46.4778262442.20261013.297}"
FW="$ROOT/vendor/lite-kit/firmware/yandexmicro/$VERSION.zip"
if [[ ! -s "$FW" ]]; then
  echo "Нет прошивки: $FW" >&2
  echo "Сначала выполните: ./scripts/fetch-firmware.sh" >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  compose=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  compose=(docker-compose)
else
  echo "Нужен docker compose или docker-compose" >&2
  exit 1
fi

mkdir -p "$ROOT/vendor/lite-kit/run" "$ROOT/vendor/lite-kit/log"
cd "$ROOT/docker"
"${compose[@]}" -f docker-compose.lite-kit.yml up -d --build
sleep 2
"${compose[@]}" -f docker-compose.lite-kit.yml ps
echo
echo "--- последние строки логов ---"
"${compose[@]}" -f docker-compose.lite-kit.yml logs --tail=40 || true
echo
if command -v dig >/dev/null 2>&1; then
  echo "--- проверка DNS ---"
  dig +short +time=3 @192.168.1.2 quasar.yandex.net A || true
fi
echo
echo "Дальше: DNS роутера 192.168.1.1 = 192.168.1.2, затем сброс колонки."
echo "Логи: docker logs -f ysl-lite-kit"
