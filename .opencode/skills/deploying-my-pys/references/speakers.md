# Speakers: firmware, root, Quasar Bridge

Do exactly one speaker at a time. The stand with `run/downgrade` offers firmware
and ADB to every `yandexmicro` on the LAN, so power off the others first.

Order for one speaker: root/SSH → install Bridge → `set-speaker-key.sh` →
`apply-bridge-routing.sh`. The key and routing scripts act on the running
Bridge, so install it first. The web UI runs these scripts in a container with
`SPEAKER_TRUST_IP=1` (ARP is not visible there); set it too when running them
manually in a container.

## 1. Firmware and root stand

```bash
./scripts/fetch-firmware.sh            # writes vendor/lite-kit/firmware/yandexmicro/<version>.zip
./scripts/start-lite-kit.sh            # docker compose up, network_mode: host
ss -lntup | grep -E ':(53|80|443)\b'
dig +short @192.168.1.2 quasar.yandex.net A     # -> 192.168.1.2
```

Point the router DHCP "preferred DNS" at the host (`192.168.1.2`), clear the
alternate DNS, and add DHCP reservations for all speaker MACs. The stand listens
on 53/80/443 and serves the `.46` build; it also enables ADB via sync.

```bash
./scripts/stop-lite-kit.sh             # then restore router DNS
```

## 2. Reset and bind

1. Cut power, power on, immediately hold the pause button 6–10 s until the light
   turns yellow-green, then release. Reset clears `/data` and unbinds the
   account.
2. In «Дом с Алисой»: fully restart the app, disable phone Wi-Fi, keep mobile
   internet and Bluetooth, add the device, enter the Wi-Fi password, and only
   then press connect.
3. The speaker fetches the stand's `.46` build and enables ADB. Do not cut power.

## 3. ADB and root

```bash
export SPEAKER_ENV=local/speakers/speaker-a.env
adb connect "$(./scripts/resolve-speaker.sh):5555"
adb shell id          # must be uid=0(root); if not, stop and read the stand logs
```

Root comes from the stand's sync injection plus the `.46` firmware — there is no
separate exploit. If `uid=2000(shell)`, stop.

## 4. SSH and OTA off

```bash
export SPEAKER_ENV=local/speakers/speaker-a.env
./scripts/post-root-ssh.sh            # add REBOOT=n to skip the reboot
```

The script checks `uid=0`, creates `secrets/speaker_ed25519`, installs Dropbear
(`S99zdropbear`), disables OTA (`yandex-noupdate.sh`), backs up `quasar.cfg` into
`backups/<date>-<SPEAKER_NAME>/`, and reboots. After the reboot verify:

```bash
ssh -i secrets/speaker_ed25519 -p 2222 root@"$(./scripts/resolve-speaker.sh)" \
  'id; sh /data/opt/yandex-noupdate.sh status'
```

Only after key login works, remove Dropbear's `-B` (empty password):

```bash
ssh -i secrets/speaker_ed25519 -p 2222 root@"$(./scripts/resolve-speaker.sh)" \
  'mount -o remount,rw /; sed -i "s/ -B / /" /etc/init.d/S99zdropbear; sync; \
   mount -o remount,ro /; /etc/init.d/S99zdropbear restart'
```

Then log in by key again and confirm the empty password no longer works.

## 5. Quasar Bridge

```bash
./scripts/fetch-quasar-bridge.sh      # v0.6.2 by default
./scripts/build-quasar-bridge.sh      # optional custom chunked build (Docker)
export SPEAKER_ENV=local/speakers/speaker-a.env
./scripts/install-quasar-bridge.sh --non-interactive     # or interactive
```

The installer needs `secrets/speaker_ed25519`, uses `python3-pexpect` for the
non-interactive path, and installs the `-chunked` build if it is in `.cache/`.
It also reads `LLM_TOKEN_FILE` from the profile (fallback
`secrets/router-token-example`), so make sure the profile sets it.
`make router-init` creates only `secrets/router-token-speaker-a`…`speaker-d`;
for other names create the token and route in the web UI first.
Answer the interactive wizard with the router URL (`http://192.168.1.2:5002/v1`),
the model name, the intermediate token from `secrets/router-token-<name>`, API
type `1` (Chat Completions), empty Home Assistant MCP, then connect Alice and
reboot.

Verify and operate:

```bash
ssh -i secrets/speaker_ed25519 -p 2222 root@"$(./scripts/resolve-speaker.sh)" \
  'pkg=/data/opt/quasar-bridge/app; sh "$pkg/control.sh" status; sh "$pkg/control.sh" check-backends'
```

| `control.sh` | Action |
|---|---|
| `start` / `stop` / `restart` | manage the Bridge process (waits for `/healthz`) |
| `status` | PID + `/healthz` |
| `logs` | tail `service.log` |
| `check` / `check-backends` | config / LLM + Home Assistant |
| `apply` | point Alice at the local bridge; needs a reboot |
| `rollback` | restore the saved Alice endpoint; run before uninstalling |

If `Port 8443 already serves another bridge`, `killall quasar-bridge` and
`control.sh start`. If `scp` fails (`sftp-server` missing), push the binary with
`ssh ... 'cat > /path/binary'` from stdin.

## 6. Write the router token

```bash
export SPEAKER_ENV=local/speakers/speaker-a.env
./scripts/set-speaker-key.sh
```

Writes `QUASAR_LLM_BASE_URL`, `QUASAR_LLM_MODEL`, `QUASAR_LLM_API_KEY` (the
intermediate `sk-router-*`) into the speaker's `runtime.env` and restarts the
Bridge. The speaker never sees upstream provider keys.

## 7. Repeat

Power off the finished speaker (or at least keep it out of the way), power on the
next one, and repeat sections 2–6. When all are done: `stop-lite-kit.sh`,
restore router DNS, power the others back on, and test by voice.
