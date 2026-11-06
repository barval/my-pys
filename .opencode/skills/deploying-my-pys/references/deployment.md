# Host deployment

## Prerequisites

- Docker Engine with Compose on the host (examples use `192.168.1.2`).
- `curl`, `python3`, `sha256sum`, `dig` (`dnsutils`), `ss` (`iproute2`),
  `adb`, `ssh`, `ssh-keygen`.
- Free TCP/UDP `53`, `80`, `443`, and TCP `5002` on the host.
- Host and speakers on the same L2 network without client isolation.
- For non-interactive Bridge installs: `python3-pexpect`.

Never install the project's services directly on the host — only Docker.

## One-time host config

Host-level values live in `local/.env`; each speaker gets its own profile in
`local/speakers/<name>.env`. Both are gitignored.

```bash
cp config/llm.env.example local/.env
# add ROOT_STAND_IP=<host IP>, e.g. ROOT_STAND_IP=192.168.1.2

cp config/speaker.env.example local/speakers/speaker-a.env
# fill SPEAKER_IP, SPEAKER_SUBNET, SPEAKER_DEVICE_ID, SPEAKER_MAC,
# SPEAKER_ROOM, SPEAKER_COLOR, LLM_BASE_URL, LLM_TOKEN_FILE
```

Replace `192.168.1.2` with your host IP everywhere below. Profile names are
`[a-z0-9][a-z0-9-]{0,63}`; `SPEAKER_DEVICE_ID` and `SPEAKER_MAC` are required,
and the profile must set `LLM_BASE_URL` and `LLM_TOKEN_FILE` (used by Bridge
install and `set-speaker-key.sh`).

## LLM router

```bash
make router-init      # create intermediate tokens + secrets/router-routes.json
make router           # build and start llm-router on 192.168.1.2:5002
make router-status    # GET /health
make router-logs
make router-stop
```

`make router-init` creates routes and tokens for the names `speaker-a`…
`speaker-d` only. For any other profile name, add the route from the web UI
(«Маршруты»). `secrets/router-routes.json` maps each speaker token to a primary
and up to nine fallback upstreams. The router listens on the LAN `:5002` so the
speakers can reach it; do not forward that port to the internet.

## Web UI stack

```bash
make webui            # build first: webui + tts + router-control + stand-control
make webui-passwd     # then set the admin password (needs the built image)
curl -fsS http://127.0.0.1:8080/healthz
make webui-logs
make webui-stop
```

The panel binds to `127.0.0.1:8080`. For a remote operator, tunnel it:

```bash
ssh -N -L 8080:127.0.0.1:8080 user@host
```

The stack runs four services:

| Service | Role |
|---|---|
| `webui` | Flask panel, SSH/ADB/curl, profiles, routes, keys, backups |
| `router-control` | narrow sidecar: restart `llm-router` only |
| `stand-control` | narrow sidecar: start/stop/status `lite-kit` only |
| `tts` | local Piper TTS for the «Сказать» action; port 8083 internal only |

Only `webui` publishes a port (default `127.0.0.1:8080`). The first
`make webui` downloads the Piper voice model into the image; later builds use
the cache. Change the voice with
`--build-arg TTS_VOICE_PATH=ru/ru_RU/dmitri/medium --build-arg TTS_VOICE_NAME=ru_RU-dmitri-medium`.

## Lifecycle and updates

```bash
make router         # rebuild/restart the router only
make webui          # rebuild/restart the panel stack
make webui-stop
make router-test    # router tests
make webui-test     # web UI tests
make lint           # bash -n for scripts
```

After `git pull`: rebuild the part that changed. The web UI mounts the repo
read-only, but templates/CSS still need a container recreate (`make webui`)
and a browser hard refresh (`Ctrl+Shift+R`).

## Backups

Create an encrypted backup from the web UI («Бэкапы» → «Вся конфигурация» or a
single speaker) before any destructive work. See
`routing-keys-backups.md` for the restore and rollback procedure.
