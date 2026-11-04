#!/usr/bin/env bash
# Установка Quasar Bridge на колонку с ПК.
# По умолчанию — интерактивный мастер. С --non-interactive нужен SSH-ключ.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

IP="${SPEAKER_IP:-192.168.1.103}"
PORT="${SPEAKER_SSH_PORT:-2222}"
BASE="${FLAI_BASE_URL:-http://192.168.1.2:5000/v1}"
MODEL="${FLAI_MODEL:-flai-chat}"
TOKEN_FILE="${FLAI_TOKEN_FILE:-$ROOT/secrets/flai-token}"
[[ "$TOKEN_FILE" = /* ]] || TOKEN_FILE="$ROOT/$TOKEN_FILE"
KEY="$ROOT/secrets/speaker_ed25519"
NON_INTERACTIVE=0

for arg in "$@"; do
  case "$arg" in
    --non-interactive|-y) NON_INTERACTIVE=1 ;;
    -h|--help)
      sed -n '2,8p' "$0"
      exit 0
      ;;
    *)
      echo "Неизвестный аргумент: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ ! -r "$TOKEN_FILE" ]]; then
  echo "Нет ключа FLAI: $TOKEN_FILE" >&2
  exit 1
fi
TOKEN="$(<"$TOKEN_FILE")"
[[ -n "$TOKEN" ]] || { echo "Ключ FLAI пустой" >&2; exit 1; }

mkdir -p "$ROOT/.cache"
INSTALLER="$ROOT/.cache/install-quasar-bridge.sh"
echo "Скачивание установщика Quasar Bridge…"
curl -fL --connect-timeout 15 -o "$INSTALLER" \
  https://github.com/skrashevich/quasar-bridge/releases/latest/download/install.sh

if [[ "$NON_INTERACTIVE" -eq 0 ]]; then
  cat <<EOF

Интерактивный мастер. Ответы:

  Адрес API нейросети : $BASE
  Название модели     : $MODEL
  Ключ API            : содержимое $TOKEN_FILE
  API                 : 1 (Chat Completions)
  Home Assistant MCP  : Enter (не нужен)
  Подключить Алису    : y
  Перезагрузить       : y

Ключ можно посмотреть так: cat "$TOKEN_FILE"

EOF
  sh "$INSTALLER" root@"$IP" -p "$PORT"
  exit $?
fi

# --- неинтерактивный режим ---
if [[ ! -f "$KEY" ]]; then
  echo "Нет SSH-ключа: $KEY. Сначала выполните ./scripts/post-root-ssh.sh" >&2
  exit 1
fi
chmod 600 "$KEY"

eval "$(ssh-agent -s)" >/dev/null
ssh-add "$KEY" >/dev/null
trap 'ssh-agent -k >/dev/null 2>&1 || true' EXIT

SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -p "$PORT" -i "$KEY" root@"$IP")
"${SSH[@]}" true

BACKUP_DIR="$ROOT/backups/$(date +%F)-speaker"
mkdir -p "$BACKUP_DIR"
"${SSH[@]}" 'cat /system/vendor/quasar/quasar.cfg' > "$BACKUP_DIR/quasar.cfg.orig" 2>/dev/null || \
  echo "Не удалось сохранить quasar.cfg; продолжаю." >&2

has_config=0
if "${SSH[@]}" 'test -f /data/opt/quasar-bridge/config.json'; then
  has_config=1
  echo "На колонке уже есть config.json — мастеру будет передан ответ 'y' на изменение."
fi

echo "Установка Quasar Bridge…"
set +e
{
  if [[ "$has_config" -eq 1 ]]; then
    printf 'y\n'
  fi
  printf '%s\n' "$BASE" "$MODEL" "$TOKEN" "1" "" "y" "${REBOOT:-y}"
} | sh "$INSTALLER" root@"$IP" -p "$PORT"
rc=${PIPESTATUS[1]}
set -e

if [[ "$rc" -ne 0 ]]; then
  echo "Установщик завершился с кодом $rc (перезагрузка могла оборвать SSH)." >&2
fi

cat <<EOF

Проверка после перезагрузки:

  ssh -i "$KEY" -p "$PORT" root@$IP \\
    'pkg=/data/opt/quasar-bridge/app; sh "\$pkg/control.sh" status; sh "\$pkg/control.sh" check-backends'

Затем скажите:
  «Алиса, какая завтра погода?»              — Яндекс
  «Алиса, спроси нейросеть: почему небо голубое?» — FLAI

Backup: $BACKUP_DIR
EOF
