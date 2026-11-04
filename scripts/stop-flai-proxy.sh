#!/usr/bin/env bash
# Останавливает прокси нормализации служебных обращений.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if docker compose version >/dev/null 2>&1; then
  compose=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  compose=(docker-compose)
else
  echo "Нужен docker compose или docker-compose" >&2
  exit 1
fi

cd "$ROOT/docker"
"${compose[@]}" -f docker-compose.flai-proxy.yml down
