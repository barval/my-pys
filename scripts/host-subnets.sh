#!/usr/bin/env bash
# Собирает IPv4-подсети интерфейсов хоста для выпадающего списка на экране
# «Добавить колонку». Запускается из `make webui`; на хосте нужен только `ip`
# (и, по возможности, `docker` — чтобы исключить подсети docker).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${HOST_SUBNETS_OUT:-$ROOT/webui-state/host-subnets.json}"
DUMP="${HOST_NET_DUMP:-}"

if [ -n "$DUMP" ]; then
  RAW="$(cat "$DUMP")"
else
  RAW="$(ip -o -4 addr show scope global)"
fi

DOCKER_NETS=""
if command -v docker >/dev/null 2>&1; then
  DOCKER_NETS="$(
    docker network ls -q 2>/dev/null |
      xargs -r -n1 docker network inspect --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}' 2>/dev/null |
      tr ' ' '\n' | sed '/^$/d' || true
  )"
fi

mkdir -p "$(dirname "$OUT")"
TMP="$(mktemp "$(dirname "$OUT")/.subnets.XXXXXX")"
trap 'rm -f "$TMP"' EXIT

SUBNETS="$(
  printf '%s\n' "$RAW" |
    awk '
      function ip2int(ip, a) {
        split(ip, a, ".")
        return a[1] * 16777216 + a[2] * 65536 + a[3] * 256 + a[4]
      }
      function int2ip(n) {
        return int(n / 16777216) "." int((n % 16777216) / 65536) "." int((n % 65536) / 256) "." (n % 256)
      }
      {
        for (i = 1; i <= NF; i++) {
          if ($i == "inet" && (i + 1) <= NF) {
            split($(i + 1), parts, "/")
            addr = parts[1]
            mask = parts[2] + 0
            if (mask < 0 || mask > 32) next
            size = 2 ^ (32 - mask)
            net = int(ip2int(addr) / size) * size
            print int2ip(net) "/" mask
          }
        }
      }
    ' |
    sed 's#^127\.#SKIP#; s#^169\.254\.#SKIP#' |
    grep -v '^SKIP' |
    { if [ -n "$DOCKER_NETS" ]; then grep -vxF -f <(printf '%s\n' "$DOCKER_NETS") || true; else cat; fi; } |
    grep -vE '^172\.(1[7-9]|2[0-9]|3[01])\.' |
    sort -u || true
)"

{
  printf '[\n'
  first=1
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    if [ "$first" -eq 1 ]; then
      printf '  "%s"' "$line"
      first=0
    else
      printf ',\n  "%s"' "$line"
    fi
  done <<< "$SUBNETS"
  printf '\n]\n'
} > "$TMP"

chmod 0600 "$TMP"
mv "$TMP" "$OUT"
