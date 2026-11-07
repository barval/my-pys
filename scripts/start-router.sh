#!/usr/bin/env bash
# Собирает и запускает локальный LLM-роутер на 5002.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/router-state"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Нужен docker compose или docker-compose" >&2
  exit 1
fi

"${COMPOSE[@]}" -f "$ROOT/docker/docker-compose.router.yml" up -d --build
"${COMPOSE[@]}" -f "$ROOT/docker/docker-compose.router.yml" ps
