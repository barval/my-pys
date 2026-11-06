---
name: Deploying my-pys
description: Use when deploying, flashing, rooting, or operating the my-pys project (My Personal Yandex Station) in this repository — host Docker stack, Yandex Station Lite speakers, Quasar Bridge, LLM router, routes, upstream keys, local TTS, backups, and rollback.
---

# Deploying my-pys

## Overview

Run the whole project end to end: the Docker host stack (web UI, LLM router,
local TTS, narrow control sidecars), rooted Yandex Station Lite speakers with
Quasar Bridge, per-speaker routes and keys, and encrypted backups.

**Core principle: do one speaker at a time, verify after every phase, and never
run a destructive step without its gate.** All examples here use synthetic data
(`192.168.1.x`, `speaker-a`, `EXAMPLE...`). Never commit real IPs, MACs, device
IDs, tokens, room names, or speaker names — only `local/`, `secrets/`,
`backups/`, `webui-state/`, `router-state/` hold real values, and they are
gitignored.

## When to use

- First host deployment or adding a new speaker.
- Re-flashing / re-rooting a speaker, installing or updating Quasar Bridge.
- Changing routes, upstream keys, or the Bridge routing policy.
- Backups, restore, rollback, or "the speaker went silent".

## Safety gates (do not skip)

1. Identify the target by device ID/MAC, never by IP: `./scripts/resolve-speaker.sh`.
2. Power off every other `yandexmicro` speaker while the root stand runs — the
   stand with `run/downgrade` serves firmware and enables ADB to the whole LAN.
3. Reserve MAC→IP in DHCP for all speakers.
4. Save `local/`, `secrets/`, `backups/`; prefer an encrypted backup from the
   web UI before touching anything.
5. Never cut power during a firmware write.
6. Do not uninstall Bridge until `control.sh rollback` + `reboot` + Alice works.
7. Stop the stand and restore router DNS immediately after root.
8. Keep `secrets/*` at `0600`. Do not expose `5000/5002/8080/53/80/443` to
   the internet; the router and panel intentionally listen on the LAN.

## Workflow

1. Host stack → `references/deployment.md`
2. Speaker root + Quasar Bridge → `references/speakers.md`
3. Routes, keys, policy, backups, rollback → `references/routing-keys-backups.md`

## Quick reference

| Goal | Command |
|---|---|
| Panel stack (webui + tts + sidecars) | `make webui` |
| LLM router (separate compose) | `make router`, `make router-status`, `make router-logs` |
| Web UI password | `make webui-passwd` (after `make webui`) |
| Find a speaker | `./scripts/resolve-speaker.sh` |
| Root + SSH + OTA off | `SPEAKER_ENV=local/speakers/speaker-a.env ./scripts/post-root-ssh.sh` |
| Install Bridge | `SPEAKER_ENV=... ./scripts/install-quasar-bridge.sh --non-interactive` |
| Apply routing policy | `SPEAKER_ENV=... ./scripts/apply-bridge-routing.sh` |
| Write router token to speaker | `SPEAKER_ENV=... ./scripts/set-speaker-key.sh` |
| Verify one speaker | `SPEAKER_ENV=... make status` / `check-backends` / `routes` |
| Say text on a speaker | `docker exec -e SPEAKER_ENV=... -e SAY_TEXT="..." my-pys-webui bash scripts/say-text.sh` |

## Common mistakes

- Treating `SPEAKER_IP` as identity — it changes; device ID/MAC is the key.
- Flashing or rooting two speakers at once.
- Leaving the root stand up or forgetting to restore router DNS.
- Editing `vendor/` snapshots instead of the project's own files.
- Committing anything from `local/`, `secrets/`, `backups/`, `webui-state/`,
  or `router-state/`.
- Uninstalling Bridge before rollback (leaves the speaker mute).
