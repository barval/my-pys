#!/usr/bin/env bash
# Останавливает локальный LLM-роутер.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Нужен docker compose или docker-compose" >&2
  exit 1
fi

"${COMPOSE[@]}" -f "$ROOT/docker/docker-compose.router.yml" down
