#!/usr/bin/env bash
# Применяет политику маршрутизации: Яндекс — только сервисы, всё остальное — LLM.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

IP="$("$ROOT/scripts/resolve-speaker.sh")"
POLICY="$ROOT/config/quasar-bridge-policy.json"
EXAMPLE="$ROOT/vendor/quasar-bridge/config.example.json"
TMP_OLD="$(mktemp)"
TMP_NEW="$(mktemp)"
trap 'rm -f "$TMP_OLD" "$TMP_NEW"' EXIT

ssh -o BatchMode=yes -i "$ROOT/secrets/speaker_ed25519" -p "${SPEAKER_SSH_PORT:-2222}" \
  root@"$IP" 'cat /data/opt/quasar-bridge/config.json' > "$TMP_OLD"

python3 - "$TMP_OLD" "$TMP_NEW" "$POLICY" "$EXAMPLE" <<'PY'
import json
import sys

old, new, policy_path, example_path = sys.argv[1:5]
cfg = json.load(open(old, encoding="utf-8"))
policy = json.load(open(policy_path, encoding="utf-8"))
example = json.load(open(example_path, encoding="utf-8"))["routing"]

# Keep classifier/refusal defaults from upstream, replace only routing policy.
routing = dict(example)
routing["default_route"] = policy["default_route"]
routing["rules"] = policy["rules"]
cfg["routing"] = routing

json.dump(cfg, open(new, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("default_route:", routing["default_route"])
print("rules:", ", ".join(rule["name"] for rule in routing["rules"]))
PY

ssh -T -o BatchMode=yes -i "$ROOT/secrets/speaker_ed25519" -p "${SPEAKER_SSH_PORT:-2222}" \
  root@"$IP" 'cat > /data/opt/quasar-bridge/config.json && chmod 600 /data/opt/quasar-bridge/config.json' < "$TMP_NEW"

ssh -o BatchMode=yes -i "$ROOT/secrets/speaker_ed25519" -p "${SPEAKER_SSH_PORT:-2222}" root@"$IP" '
pkg=/data/opt/quasar-bridge/app
sh "$pkg/control.sh" check
sh "$pkg/control.sh" restart
sleep 2
sh "$pkg/control.sh" status
sh "$pkg/control.sh" check-backends
' 2>&1 | tr -d '\r'
