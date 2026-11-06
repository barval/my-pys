from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Iterable

from .profiles import Profile


def load_subnets(path: Path) -> list[str]:
    """Читает список подсетей хоста, собранный scripts/host-subnets.sh."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [
        item
        for item in data
        if isinstance(item, str) and "/" in item
    ]


def subnet_prefixes(subnets: Iterable[str]) -> list[str]:
    """Оставляет сети /24 и возвращает префиксы вида 192.168.1."""
    result: set[str] = set()
    for item in subnets:
        try:
            network = ipaddress.ip_network(item, strict=False)
        except ValueError:
            continue
        if network.version != 4 or network.prefixlen != 24:
            continue
        result.add(str(network.network_address).rsplit(".", 1)[0])
    return sorted(result)


def fallback_prefixes(profiles: Iterable[Profile]) -> list[str]:
    """Подсети из уже настроенных профилей — если файла хоста ещё нет."""
    result: set[str] = set()
    for profile in profiles:
        value = (profile.subnet or "").strip()
        if value:
            result.add(value)
    return sorted(result)
