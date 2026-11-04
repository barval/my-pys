#!/usr/bin/env bash
# Скачивает проверенную прошивку yandexmicro .46.
#
# Зеркало lite-kit отдаёт каталоги очень медленно, поэтому файл берётся
# напрямую с официального CDN Яндекса. URL и контрольные суммы зафиксированы
# для конкретной сборки; metadata с зеркала используется только как источник
# альтернативных URL.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

VERSION="${YANDEXMICRO_VERSION:-0.369.1.46.4778262442.20261013.297}"
EXPECTED_SIZE="${YANDEXMICRO_SIZE:-66814464}"
EXPECTED_CRC="${YANDEXMICRO_CRC32:-371630625}"
EXPECTED_SHA="${YANDEXMICRO_SHA256:-74d4e8fae375b2ad1757761e01caf6be0209d216328ce1a942dbef38c8f20d11}"

CDN_URL="https://cdnriqbxswemmatxzibl.svc.cdn.yandex.net/yandexmicro/ota/user/770338e8-a517-4642-a442-d26be2632873/${VERSION}.zip"
FALLBACK_URL="https://quasar.s3.yandex.net/yandexmicro/ota/user/770338e8-a517-4642-a442-d26be2632873/${VERSION}.zip"
MIRROR="${MIRROR_URL:-http://144.76.194.29:62891}"
FW_DIR="$ROOT/vendor/lite-kit/firmware/yandexmicro"
DEST="$FW_DIR/$VERSION.zip"
MANIFEST="$FW_DIR/manifest.json"

mkdir -p "$FW_DIR"

sha_of() { sha256sum "$1" | awk '{print $1}'; }
crc_of() {
  python3 - "$1" <<'PY'
import sys, zlib
crc = 0
with open(sys.argv[1], "rb") as fh:
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        crc = zlib.crc32(chunk, crc)
print(crc & 0xFFFFFFFF)
PY
}

ok_file() {
  [[ -s "$1" ]] || return 1
  [[ "$(wc -c < "$1")" = "$EXPECTED_SIZE" ]] || return 1
  [[ "$(crc_of "$1")" = "$EXPECTED_CRC" ]] || return 1
  [[ "$(sha_of "$1")" = "$EXPECTED_SHA" ]]
}

if [[ "${1:-}" != "--force" ]] && ok_file "$DEST"; then
  echo "Прошивка уже есть и проверена: $DEST"
  echo "size=$(wc -c < "$DEST") crc32=$EXPECTED_CRC"
  echo "sha256=$EXPECTED_SHA"
  exit 0
fi

# Попробовать взять альтернативные URL из metadata.json (быстрый запрос,
# в отличие от медленного листинга каталога).
urls=("$CDN_URL" "$FALLBACK_URL")
meta="$(mktemp)"
if curl -fsS --max-time 25 "$MIRROR/yandexmicro/$VERSION/metadata.json" -o "$meta" 2>/dev/null; then
  while IFS= read -r u; do
    [[ -n "$u" ]] && urls+=("$u")
  done < <(python3 - "$meta" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    raise SystemExit(0)
for key in ("downloadUrl", "fallbackUrl"):
    value = data.get(key)
    if value:
        print(value)
PY
)
fi
rm -f "$meta"

echo "Прошивка: yandexmicro $VERSION"
echo "Ожидается: $EXPECTED_SIZE байт, crc32 $EXPECTED_CRC"
echo "Скачивание с официального CDN (с докачкой)…"

downloaded=0
for url in "${urls[@]}"; do
  echo "  -> $url"
  if curl -fL --retry 5 --retry-delay 2 --connect-timeout 15 \
      --continue-at - --output "$DEST" "$url"; then
    if ok_file "$DEST"; then
      downloaded=1
      break
    fi
    echo "  файл скачан, но не совпал по размеру/CRC/SHA; пробую следующий URL" >&2
    rm -f "$DEST"
  else
    echo "  не удалось; пробую следующий URL" >&2
  fi
done

if [[ "$downloaded" -ne 1 ]]; then
  echo "Не удалось скачать проверенную прошивку." >&2
  echo "Проверьте URL вручную:" >&2
  printf '  %s\n' "${urls[@]}" >&2
  exit 1
fi

size="$(wc -c < "$DEST")"
crc="$(crc_of "$DEST")"
sha="$(sha_of "$DEST")"
cat > "$MANIFEST" <<JSON
{
  "platform": "yandexmicro",
  "version": "$VERSION",
  "filename": "$VERSION.zip",
  "size": $size,
  "crc32": $crc,
  "sha256": "$sha",
  "source": "yandex CDN",
  "note": "проверенная OTA .46 для локального стенда lite-kit"
}
JSON

echo
echo "Готово: $DEST"
echo "size=$size crc32=$crc"
echo "sha256=$sha"
echo "manifest: $MANIFEST"
