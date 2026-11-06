from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .profiles import NAME_RE

_MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{4,64}$")

_WRITE_ORDER = (
    "SPEAKER_NAME",
    "SPEAKER_IP",
    "SPEAKER_SUBNET",
    "SPEAKER_DEVICE_ID",
    "SPEAKER_MAC",
    "SPEAKER_ROOM",
    "SPEAKER_COLOR",
    "SPEAKER_MODEL",
    "SPEAKER_PLATFORM",
)


def validate_profile(name: str, ip: str, subnet: str, mac: str, device_id: str) -> None:
    if not NAME_RE.fullmatch(name):
        raise ValueError("Имя: латиница в нижнем регистре, цифры и дефис, от 1 до 64 символов")

    try:
        address = ipaddress.IPv4Address(ip)
    except ipaddress.AddressValueError as exc:
        raise ValueError("IP должен быть корректным IPv4-адресом") from exc
    if not address.is_private:
        raise ValueError("IP должен принадлежать частной сети")

    network_str = subnet if "/" in subnet else f"{subnet}.0/24"
    try:
        network = ipaddress.ip_network(network_str, strict=False)
    except ValueError as exc:
        raise ValueError("Подсеть некорректна") from exc
    if not network.is_private:
        raise ValueError("Подсеть должна быть частной")
    if network.num_addresses > 256:
        raise ValueError("Подсеть не должна содержать больше 256 адресов")

    mac = mac.lower().strip()
    if not _MAC_RE.fullmatch(mac):
        raise ValueError("MAC должен быть в формате aa:bb:cc:dd:ee:ff")

    if not _DEVICE_ID_RE.fullmatch(device_id):
        raise ValueError("Device ID: 4–64 латинских букв, цифр, точек, дефисов или подчёркиваний")


def _atomic_write(path: Path, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp", text=True
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def write_profile(directory: Path, values: dict[str, str]) -> Path:
    name = values.get("SPEAKER_NAME", "").strip()
    if not name:
        raise ValueError("Имя обязательно")

    directory = Path(directory)
    path = directory / f"{name}.env"

    ordered: dict[str, str] = {}
    for key in _WRITE_ORDER:
        value = values.get(key, "").strip()
        if key == "SPEAKER_PLATFORM" and not value:
            value = "yandexmicro"
        if value:
            ordered[key] = value

    lines = [f"{key}={value}\n" for key, value in ordered.items()]
    _atomic_write(path, "".join(lines))
    return path


def merge_profile_env(path: Path, values: dict[str, str]) -> None:
    path = Path(path)
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = original.splitlines(keepends=True)

    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            result.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in values:
            result.append(f"{key}={values[key]}\n")
            seen.add(key)
        else:
            result.append(line)

    for key, value in values.items():
        if key not in seen:
            result.append(f"{key}={value}\n")

    _atomic_write(path, "".join(result))


def archive_profile(settings: Any, name: str, *, route: dict | None) -> Path:
    if not NAME_RE.fullmatch(name):
        raise ValueError("Имя профиля некорректно")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = settings.state_dir / "deleted-profiles" / f"{timestamp}-{name}"
    dest.mkdir(parents=True, exist_ok=True)

    profile_path = settings.speakers_dir / f"{name}.env"
    if profile_path.exists():
        target = dest / "local" / "speakers" / f"{name}.env"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(profile_path), str(target))

    if route is not None:
        router_path = dest / "router.json"
        router_path.write_text(
            json.dumps({"routes": [route]}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        token_file = route.get("token_file", "")
        if token_file:
            source = settings.secrets_dir / Path(token_file).name
            if source.exists():
                target = dest / "secrets" / Path(token_file).name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))

    setup_path = settings.state_dir / "setup" / f"{name}.json"
    if setup_path.exists():
        target = dest / "webui-state" / "setup" / f"{name}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(setup_path), str(target))

    return dest
