#!/usr/bin/env bash
# Запускает прокси, который отрезает «спроси у ФЛАЙ» перед FLAI.
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
"${compose[@]}" -f docker-compose.flai-proxy.yml up -d --build
sleep 2
"${compose[@]}" -f docker-compose.flai-proxy.yml ps
echo
echo "Проверка /v1/models через прокси:"
TOKEN_FILE="${LLM_TOKEN_FILE:-${FLAI_TOKEN_FILE:-$ROOT/secrets/flai-token}}"
[[ "$TOKEN_FILE" = /* ]] || TOKEN_FILE="$ROOT/$TOKEN_FILE"
if [[ -r "$TOKEN_FILE" ]]; then
  curl -sS --max-time 10 -o /dev/null -w 'HTTP %{http_code}\n' \
    -H "Authorization: Bearer $(<"$TOKEN_FILE")" \
    http://127.0.0.1:5001/v1/models || true
fi
echo "Прокси: http://192.168.1.2:5001/v1 -> http://127.0.0.1:5000"
