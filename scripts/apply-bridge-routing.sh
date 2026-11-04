#!/usr/bin/env bash
# Применяет правило explicit_llm_phrase к config.json на колонке.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

IP="$("$ROOT/scripts/resolve-speaker.sh")"
RULE="$ROOT/config/quasar-bridge-routing.json"
TMP_OLD="$(mktemp)"
TMP_NEW="$(mktemp)"
trap 'rm -f "$TMP_OLD" "$TMP_NEW"' EXIT

ssh -o BatchMode=yes -i "$ROOT/secrets/speaker_ed25519" -p "${SPEAKER_SSH_PORT:-2222}" \
  root@"$IP" 'cat /data/opt/quasar-bridge/config.json' > "$TMP_OLD"

python3 - "$TMP_OLD" "$TMP_NEW" "$RULE" "$ROOT/vendor/quasar-bridge/config.example.json" <<'PY'
import json
import sys

old, new, rule_path, example_path = sys.argv[1:5]
cfg = json.load(open(old, encoding="utf-8"))
rule = json.load(open(rule_path, encoding="utf-8"))

if "routing" not in cfg:
    cfg["routing"] = json.load(open(example_path, encoding="utf-8"))["routing"]

rules = [r for r in cfg["routing"].get("rules", []) if r.get("name") != rule["name"]]
rules.insert(0, rule)
cfg["routing"]["rules"] = rules
json.dump(cfg, open(new, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("rules:", len(rules))
print("first:", rules[0]["name"])
print("terms:", ", ".join(rules[0]["match"]["contains_any"]))
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
