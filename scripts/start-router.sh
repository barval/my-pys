#!/usr/bin/env bash
# Собирает и запускает локальный LLM-роутер на 5002.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/router-state"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  COMPOSE=(docker-compose)
fi

"${COMPOSE[@]}" -f "$ROOT/docker/docker-compose.router.yml" up -d --build
"${COMPOSE[@]}" -f "$ROOT/docker/docker-compose.router.yml" ps
