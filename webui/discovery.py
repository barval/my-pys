"""Поиск колонок в локальной сети: ping-sweep, затем опрос через ADB."""

from __future__ import annotations

import ipaddress
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

_MAC_RE = re.compile(r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}")


@dataclass(frozen=True)
class Discovered:
    ip: str
    mac: str
    device_id: str
    model: str
    hostname: str
    profile_name: str = ""


def parse_subnet(value: str) -> list[str]:
    value = value.strip()
    if not value:
        raise ValueError("Укажите подсеть")
    if "/" not in value:
        value = f"{value}.0/24"
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise ValueError(f"Некорректная подсеть: {value}") from exc
    if not network.is_private or network.num_addresses > 256:
        raise ValueError("Нужна приватная сеть не больше 254 адресов")
    return [str(ip) for ip in network.hosts()]


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=5)


def _adb(runner, target: str, *command: str) -> str:
    return runner(["adb", "-s", target, "shell", *command]).stdout.strip()


def _mac(text: str) -> str:
    match = _MAC_RE.search(text)
    return match.group(0).lower() if match else ""


def probe_host(ip: str, *, runner=_run, adb_port: int = 5555) -> Discovered | None:
    try:
        if runner(["ping", "-c", "1", "-W", "1", ip]).returncode != 0:
            return None
        target = f"{ip}:{adb_port}"
        if "connected" not in runner(["adb", "connect", target]).stdout:
            return Discovered(ip, "", "", "", "")
        device_id = _adb(runner, target, "getprop", "ro.serialno")
        if not device_id:
            return Discovered(ip, "", "", "", "")
        model = _adb(runner, target, "getprop", "ro.product.model")
        mac = _mac(_adb(runner, target, "cat", "/sys/class/net/wlan0/address"))
        if not mac:
            mac = _mac(_adb(runner, target, "ip", "address", "show", "dev", "wlan0"))
    except (subprocess.SubprocessError, OSError):
        # Висящий adb (таймаут) или отсутствующие ping/adb на хосте панели:
        # адрес считаем живым, но с недоступным ADB, а не роняем весь скан.
        return Discovered(ip, "", "", "", "")
    return Discovered(ip, mac, device_id, model, f"yandexmicro-{device_id}")


def _ip_key(device: Discovered) -> tuple[int, ...]:
    return tuple(int(part) for part in device.ip.split("."))


def merge_known_profiles(devices: list[Discovered], profiles) -> list[Discovered]:
    """Дополняет найденные адреса данными профилей и поднимает их наверх."""
    by_ip = {profile.ip: profile for profile in profiles if profile.ip}
    merged: list[Discovered] = []
    for device in devices:
        profile = by_ip.get(device.ip)
        if profile is not None:
            device = Discovered(
                ip=device.ip,
                mac=device.mac or profile.mac,
                device_id=device.device_id or profile.device_id,
                model=device.model or profile.model,
                hostname=device.hostname,
                profile_name=profile.name,
            )
        merged.append(device)
    merged.sort(key=lambda item: (not bool(item.profile_name or item.device_id), _ip_key(item)))
    return merged


def scan(
    subnet: str, *, runner=_run, workers: int = 32, adb_port: int = 5555
) -> list[Discovered]:
    hosts = parse_subnet(subnet)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        found = pool.map(
            lambda ip: probe_host(ip, runner=runner, adb_port=adb_port), hosts
        )
    devices = [device for device in found if device is not None]
    devices.sort(key=_ip_key)
    return devices
