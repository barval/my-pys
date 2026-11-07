#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib-env.sh
. "$ROOT/scripts/lib-env.sh"
load_project_env "$ROOT"
IP="$("$ROOT/scripts/resolve-speaker.sh")"
KEY="$ROOT/secrets/speaker_ed25519"
PORT="${SPEAKER_SSH_PORT:-2222}"
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 -i "$KEY" -p "$PORT" root@"$IP" \
  'set -e
   pkg=/data/opt/quasar-bridge/app
   cat "$pkg/VERSION"
   sh "$pkg/control.sh" status
   sh "$pkg/control.sh" check-backends
   df -h /data | tail -1'
