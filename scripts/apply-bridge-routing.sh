#!/usr/bin/env bash
# Применяет политику маршрутизации: Яндекс — только сервисы, всё остальное — LLM.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib-env.sh
. "$ROOT/scripts/lib-env.sh"
load_project_env "$ROOT"

IP="$("$ROOT/scripts/resolve-speaker.sh")"
POLICY="$ROOT/config/quasar-bridge-policy.json"
EXAMPLE="$ROOT/vendor/quasar-bridge/config.example.json"
TMP_OLD="$(mktemp)"
TMP_NEW="$(mktemp)"
trap 'rm -f "$TMP_OLD" "$TMP_NEW"' EXIT

ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -i "$ROOT/secrets/speaker_ed25519" -p "${SPEAKER_SSH_PORT:-2222}" \
  root@"$IP" 'cat /data/opt/quasar-bridge/config.json' > "$TMP_OLD"

python3 - "$TMP_OLD" "$TMP_NEW" "$POLICY" "$EXAMPLE" <<'PY'
import json
import sys

old, new, policy_path, example_path = sys.argv[1:5]
cfg = json.load(open(old, encoding="utf-8"))
policy = json.load(open(policy_path, encoding="utf-8"))
example = json.load(open(example_path, encoding="utf-8"))["routing"]

# Сохраняем настройки классификатора и отказов upstream, меняем только routing.
routing = dict(example)
routing["default_route"] = policy["default_route"]
routing["rules"] = policy["rules"]
cfg["routing"] = routing

json.dump(cfg, open(new, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("default_route:", routing["default_route"])
print("rules:", ", ".join(rule["name"] for rule in routing["rules"]))
PY

ssh -T -o BatchMode=yes -o StrictHostKeyChecking=accept-new -i "$ROOT/secrets/speaker_ed25519" -p "${SPEAKER_SSH_PORT:-2222}" \
  root@"$IP" 'cat > /data/opt/quasar-bridge/config.json.new && chmod 600 /data/opt/quasar-bridge/config.json.new' < "$TMP_NEW"

ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -i "$ROOT/secrets/speaker_ed25519" -p "${SPEAKER_SSH_PORT:-2222}" root@"$IP" '
set -e
root=/data/opt/quasar-bridge
pkg=$root/app
cp -p "$root/config.json" "$root/config.json.bak"
mv "$root/config.json.new" "$root/config.json"
if ! sh "$pkg/control.sh" check; then
  mv "$root/config.json.bak" "$root/config.json"
  echo "Новый конфиг не прошёл проверку; восстановлен прежний." >&2
  exit 1
fi
if ! sh "$pkg/control.sh" restart; then
  mv "$root/config.json.bak" "$root/config.json"
  sh "$pkg/control.sh" restart || true
  echo "Bridge не перезапустился с новым конфигом; восстановлен прежний." >&2
  exit 1
fi
rm -f "$root/config.json.bak"
sleep 2
sh "$pkg/control.sh" status
sh "$pkg/control.sh" check-backends
' 2>&1 | tr -d '\r'
