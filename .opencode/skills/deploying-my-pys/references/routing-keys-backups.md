# Routing, keys, backups, rollback

## Routing policy

The policy is `config/quasar-bridge-policy.json`. `default_route` is `llm`, so
everything that is not matched by a Yandex rule goes to the LLM router; the
classifier is not called. Rules: `speaker_playback`, `speaker_controls`,
`yandex_intercom`, `home_devices`, `home_state`, `yandex_scenarios`,
`yandex_weekday`, `yandex_services` — all to Yandex (or Home Assistant).

```bash
export SPEAKER_ENV=local/speakers/speaker-a.env
./scripts/apply-bridge-routing.sh
```

The script merges only `default_route` and `rules` into the speaker's
`config.json`, runs `check`, `restart`, `status`, `check-backends`.

Verify a route without executing it:

```bash
ssh -i secrets/speaker_ed25519 -p 2222 root@"$(./scripts/resolve-speaker.sh)"
set -a; . /data/opt/quasar-bridge/runtime.env; set +a
pkg=/data/opt/quasar-bridge/app
"$pkg/bin/quasar-bridge" -config /data/opt/quasar-bridge/config.json -route "какая погода завтра"
```

Who answered, from the Bridge log:

```bash
make routes   # tail native_route_decision
```

`route=llm` — the external LLM; `route=yandex` — Alice; `source=rule` — a
matched rule; `source=default` — `default_route`.

## Keys

Two levels, never mixed:

```text
speaker runtime.env
  QUASAR_LLM_API_KEY=sk-router-...   intermediate token
        │
secrets/router-routes.json (route by token_file)
  primary.api_key_file / fallbacks[].api_key_file   upstream keys
```

- Intermediate tokens: one per route/speaker, files `secrets/router-token-<name>`.
  Rotate from «Ключи» (it also rewrites the speaker) or `make key`.
- Upstream keys: a shared list on «Ключи → Upstream-ключи»:
  1. open «Ключи → Upstream-ключи» and add a key: a file name
     (e.g. `openrouter-token-speaker-a`) and the value;
  2. the value is written to `secrets/<file>` with mode `0600` — only the file
     name is kept in the registry;
  3. open «Маршруты», edit the route (or add a fallback), pick the new key in
     the «Ключ» dropdown for the primary or a fallback, and save. The router
     reloads `secrets/router-routes.json` itself.

  One key can be used by several routes; a used key cannot be deleted. Old
  `api_key_file` names are imported into the list automatically.

Changing an upstream provider or key requires no speaker changes. Changing an
intermediate token requires `set-speaker-key.sh` or the «Записать ключ» action.

## Backups and restore

Create from the web UI: «Бэкапы» → «Вся конфигурация» or a single speaker,
enter a passphrase, and download the archive. The passphrase is not stored —
keep it, you need it to restore. Archives are `.tar.gz.enc` (AES-GCM + PBKDF2)
in `backups/config/`, mode `0600`. The single-speaker archive contains the
profile, its route fragment, and the keys referenced by that route.
`webui-session.key`, logs, `router-state`, and audit are excluded.
«Проверить» shows the manifest without touching live config.

Restore always snapshots the current state under
`webui-state/restore-backups/<timestamp>/`, then asks for `REPLACE`. A full
restore replaces profiles, keys, and the router config; a single-speaker restore
updates only that speaker.

## Rollback and recovery

Bridge endpoint rollback (order matters):

```sh
pkg=/data/opt/quasar-bridge/app
sh "$pkg/control.sh" rollback && reboot      # Alice talks to Yandex again
# verify voice, then:
sh "$pkg/uninstall.sh"                        # refuses while endpoint-backup.json exists
```

Root changes: `sh /data/opt/yandex-noupdate.sh restore && reboot` (OTA), remove
`/etc/init.d/S99zdropbear` (SSH), or do the button reset.

If the speaker went mute: check `control.sh status` and `logs`; try
`control.sh rollback`; if SSH/ADB are gone, do the button reset (clears `/data`)
or reflash from the stand. Never cut power during a write.

## Say text on a speaker

The web UI exposes it as «Действия → Сказать» (text up to 500 characters).
The script must reach the internal `tts` service, so run it inside the `webui`
container:

```bash
docker exec -e SPEAKER_ENV=local/speakers/speaker-a.env -e SPEAKER_TRUST_IP=1 \
  -e SAY_TEXT="Приятного аппетита" my-pys-webui bash scripts/say-text.sh
```

Synthesises with the local Piper service (`tts`) and plays the WAV on the
speaker with `aplay` (present in the tested firmware; check with `aplay -l`).
Needs the `tts` container (`make webui`) and the SSH key.
