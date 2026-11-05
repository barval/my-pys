from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_SECRET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass(frozen=True)
class KeyStatus:
    route: str
    router_token: bool
    flai_token: bool
    orca_token: bool
    router_token_length: int


def validate_secret_name(name: str) -> None:
    if not _SECRET_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid secret name: {name}")


def write_secret(secrets_dir: Path, name: str, value: str) -> Path:
    validate_secret_name(name)
    secrets_dir = Path(secrets_dir)
    secrets_dir.mkdir(parents=True, exist_ok=True)
    path = secrets_dir / name
    if path.resolve().parent != secrets_dir.resolve():
        raise ValueError(f"secret escapes directory: {name}")
    temp = path.with_name(f".{name}.tmp")
    with open(temp, "w", encoding="utf-8") as stream:
        stream.write(value + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temp, 0o600)
    os.replace(temp, path)
    return path


def generate_router_token() -> str:
    return "sk-router-" + secrets.token_urlsafe(32)


def _present(path: Path) -> bool:
    try:
        return path.stat().st_size > 0
    except OSError:
        return False


def key_inventory(
    secrets_dir: Path, route_names: Iterable[str]
) -> list[KeyStatus]:
    secrets_dir = Path(secrets_dir)
    items: list[KeyStatus] = []
    for route in route_names:
        router = secrets_dir / f"router-token-{route}"
        length = router.stat().st_size if _present(router) else 0
        items.append(
            KeyStatus(
                route=route,
                router_token=_present(router),
                flai_token=_present(secrets_dir / f"flai-token-{route}"),
                orca_token=_present(secrets_dir / f"orca-token-{route}"),
                router_token_length=length,
            )
        )
    return items


def rotate_router_token(secrets_dir: Path, route_name: str) -> str:
    validate_secret_name(route_name)
    value = generate_router_token()
    write_secret(secrets_dir, f"router-token-{route_name}", value)
    return value


def set_upstream_key(
    secrets_dir: Path,
    route_name: str,
    provider: str,
    value: str,
) -> None:
    validate_secret_name(route_name)
    if provider not in ("flai", "orca"):
        raise ValueError(f"unknown provider: {provider}")
    if not value.strip():
        raise ValueError("key value must not be empty")
    write_secret(secrets_dir, f"{provider}-token-{route_name}", value.strip())
