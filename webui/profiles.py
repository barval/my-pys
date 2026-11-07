from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,50}$")
LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Profile:
    name: str
    path: Path
    ip: str
    subnet: str
    mac: str
    device_id: str
    ssh_port: int
    adb_port: int
    platform: str
    model: str
    color: str
    room: str


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_profiles(directory: Path) -> list[Profile]:
    directory = Path(directory)
    profiles: list[Profile] = []
    for path in sorted(directory.glob("*.env")):
        if path.name == "example.env":
            continue
        try:
            name = path.stem
            if not NAME_RE.fullmatch(name):
                raise ValueError(f"invalid profile name: {path.name}")
            values = parse_env(path)
            device_id = values.get("SPEAKER_DEVICE_ID", "").strip()
            mac = values.get("SPEAKER_MAC", "").strip()
            if not device_id or not mac:
                raise ValueError(
                    f"profile {path.name}: SPEAKER_DEVICE_ID and SPEAKER_MAC are required"
                )
            platform = values.get("SPEAKER_PLATFORM", "yandexmicro").strip()
            model = values.get("SPEAKER_MODEL", "").strip()
            if not model:
                model = (
                    "Яндекс Станция Лайт"
                    if platform == "yandexmicro"
                    else platform
                )
            profiles.append(
                Profile(
                    name=name,
                    path=path.resolve(),
                    ip=values.get("SPEAKER_IP", "").strip(),
                    subnet=values.get("SPEAKER_SUBNET", "").strip(),
                    mac=mac,
                    device_id=device_id,
                    ssh_port=int(values.get("SPEAKER_SSH_PORT", "2222")),
                    adb_port=int(values.get("SPEAKER_ADB_PORT", "5555")),
                    platform=platform,
                    model=model,
                    color=values.get("SPEAKER_COLOR", "").strip().lower(),
                    room=values.get("SPEAKER_ROOM", "").strip(),
                )
            )
        except (OSError, ValueError) as exc:
            # Битый профиль не должен ронять панель и остальные колонки.
            LOG.warning("профиль %s пропущен: %s", path.name, exc)
    return profiles
