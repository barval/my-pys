#!/usr/bin/env bash
# После получения root по ADB: SSH, ключ, отключение OTA, backup.
# Запускать только когда `adb shell id` уже показывает uid=0(root).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

ADB="${ADB:-adb}"
# IP не хардкодим: ищем по device ID/MAC, IP — только подсказка.
IP="$("$ROOT/scripts/resolve-speaker.sh")"
ADB_PORT="${SPEAKER_ADB_PORT:-5555}"
SERIAL="$IP:$ADB_PORT"
TOOLS="$ROOT/vendor/station-tools"
KEY="$ROOT/secrets/speaker_ed25519"
BACKUP_DIR="$ROOT/backups/$(date +%F)-speaker"

echo "== ADB =="
"$ADB" connect "$SERIAL"
id_out="$("$ADB" shell id | tr -d '\r')"
echo "$id_out"
if ! grep -q 'uid=0' <<<"$id_out"; then
  echo "ADB есть, но это не root. Останов." >&2
  exit 1
fi

echo "== SSH key =="
mkdir -p "$ROOT/secrets"
if [[ ! -f "$KEY" ]]; then
  ssh-keygen -t ed25519 -N "" -C "ysl-v1.0" -f "$KEY"
fi
chmod 600 "$KEY"
chmod 644 "$KEY.pub"

echo "== files =="
"$ADB" shell 'mkdir -p /data/opt/bin /data/opt/etc/dropbear /data/opt/backup'
"$ADB" push "$TOOLS/bin/dropbear" /data/opt/bin/dropbear >/dev/null
"$ADB" push "$TOOLS/bin/dropbearkey" /data/opt/bin/dropbearkey >/dev/null
"$ADB" push "$TOOLS/yandex-noupdate.sh" /data/opt/yandex-noupdate.sh >/dev/null
"$ADB" shell 'chmod +x /data/opt/bin/dropbear /data/opt/bin/dropbearkey /data/opt/yandex-noupdate.sh'
"$ADB" shell '/data/opt/bin/dropbearkey -t ed25519 -f /data/opt/etc/dropbear/hk_ed25519' >/dev/null 2>&1 || true

echo "== rootfs: init script and authorized_keys =="
"$ADB" shell 'mount -o remount,rw /'
"$ADB" push "$TOOLS/S99zdropbear" /etc/init.d/S99zdropbear >/dev/null
"$ADB" push "$KEY.pub" /data/local/tmp/authorized_keys >/dev/null
"$ADB" shell 'chmod +x /etc/init.d/S99zdropbear
mkdir -p /root/.ssh
chmod 700 /root/.ssh
cat /data/local/tmp/authorized_keys > /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
rm -f /data/local/tmp/authorized_keys
sync
mount -o remount,ro /'

echo "== backup quasar.cfg =="
mkdir -p "$BACKUP_DIR"
"$ADB" pull /system/vendor/quasar/quasar.cfg "$BACKUP_DIR/quasar.cfg.orig" >/dev/null 2>&1 || \
  echo "Не удалось забрать quasar.cfg (не критично на этом шаге)" >&2

echo "== OTA off =="
"$ADB" shell 'sh /data/opt/yandex-noupdate.sh'
"$ADB" shell 'sh /data/opt/yandex-noupdate.sh status' | tr -d '\r'

echo "== backup /data/opt/backup =="
"$ADB" pull /data/opt/backup "$BACKUP_DIR" >/dev/null 2>&1 || \
  echo "Backup не забрался; проверьте вручную: adb pull /data/opt/backup" >&2

if [[ "${REBOOT:-y}" = "n" ]]; then
  echo "REBOOT=n: перезагрузка пропущена."
else
  echo "== reboot =="
  "$ADB" shell reboot || true
fi

cat <<EOF

Готово. Дальше:
  1. Подождать 1–2 минуты.
  2. ssh -i "$KEY" -p ${SPEAKER_SSH_PORT:-2222} root@$IP
  3. sh /data/opt/yandex-noupdate.sh status
  4. После успешного входа по ключу убрать -B из /etc/init.d/S99zdropbear.

Backup: $BACKUP_DIR
EOF
