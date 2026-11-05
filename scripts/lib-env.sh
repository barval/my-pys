# Shared env loader for project scripts.
# Usage: . "$ROOT/scripts/lib-env.sh"; load_project_env "$ROOT"
# Loads local/.env (or .env), then an optional per-speaker profile from SPEAKER_ENV.
load_project_env() {
  local root="$1"
  local envfile
  for envfile in "$root/local/.env" "$root/.env"; do
    if [[ -f "$envfile" ]]; then
      set -a
      # shellcheck disable=SC1090
      . "$envfile"
      set +a
      break
    fi
  done
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
