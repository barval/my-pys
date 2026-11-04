#!/usr/bin/env bash
# Находит целевую колонку по device ID и MAC, а не по IP.
# Печатает IPv4 и завершается 0. IP — только подсказка, если MAC совпал.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

DEVICE_ID="${SPEAKER_DEVICE_ID:-}"
MAC="${SPEAKER_MAC:-}"
SUBNET="${SPEAKER_SUBNET:-192.168.1}"
HINT="${SPEAKER_IP:-}"

if [[ -z "$DEVICE_ID" || -z "$MAC" ]]; then
  echo "Задайте SPEAKER_DEVICE_ID и SPEAKER_MAC (config/speaker.env.example)" >&2
  exit 1
fi
MAC="$(printf '%s' "$MAC" | tr 'A-F' 'a-f')"

is_ipv4() {
  [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]
}

mac_of() {
  ip neigh show "$1" 2>/dev/null | awk '{print tolower($5); exit}'
}

verify_mac() {
  local ip="$1"
  [[ -n "$ip" ]] || return 1
  ping -c1 -W1 "$ip" >/dev/null 2>&1 || true
  [[ "$(mac_of "$ip")" == "$MAC" ]]
}

# 1. Явная подсказка SPEAKER_IP — только если MAC совпал.
if [[ -n "$HINT" ]] && is_ipv4 "$HINT" && verify_mac "$HINT"; then
  echo "$HINT"
  exit 0
fi

# 2. mDNS: в имени уже есть device ID.
HOSTNAME="yandexmicro-${DEVICE_ID}.local"
if command -v avahi-resolve >/dev/null 2>&1; then
  ip="$(timeout 3 avahi-resolve -n "$HOSTNAME" 2>/dev/null | awk '{print $2}' | grep -E '^([0-9]{1,3}\.){3}[0-9]{1,3}$' | head -1 || true)"
  if is_ipv4 "${ip:-}"; then
    # Уточняем ARP; если запись ещё не появилась, доверяем mDNS device ID.
    ping -c1 -W1 "$ip" >/dev/null 2>&1 || true
    seen="$(mac_of "$ip")"
    if [[ -z "$seen" || "$seen" == "$MAC" ]]; then
      echo "$ip"
      exit 0
    fi
  fi
fi

# 3. Текущая ARP-таблица по MAC.
ip="$(ip neigh | awk -v mac="$MAC" 'tolower($5)==mac {print $1; exit}')"
if is_ipv4 "${ip:-}" && verify_mac "$ip"; then
  echo "$ip"
  exit 0
fi

# 4. Быстрый sweep подсети, затем снова ARP по MAC.
seq 1 254 | xargs -P 64 -I{} sh -c "ping -c1 -W1 ${SUBNET}.{} >/dev/null 2>&1" || true
ip="$(ip neigh | awk -v mac="$MAC" 'tolower($5)==mac {print $1; exit}')"
if is_ipv4 "${ip:-}" && verify_mac "$ip"; then
  echo "$ip"
  exit 0
fi

echo "Колонка не найдена: device_id=$DEVICE_ID mac=$MAC subnet=$SUBNET" >&2
exit 1
