# Shared env loader for project scripts.
# Usage: . "$ROOT/scripts/lib-env.sh"; load_project_env "$ROOT"
# Loads .env first, then an optional per-speaker profile from SPEAKER_ENV.
load_project_env() {
  local root="$1"
  if [[ -f "$root/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    . "$root/.env"
    set +a
  fi
  if [[ -n "${SPEAKER_ENV:-}" ]]; then
    local file="$SPEAKER_ENV"
    [[ "$file" = /* ]] || file="$root/$file"
    if [[ -f "$file" ]]; then
      set -a
      # shellcheck disable=SC1090
      . "$file"
      set +a
    else
      echo "Нет файла профиля колонки: $file" >&2
      return 1
    fi
  fi
}
