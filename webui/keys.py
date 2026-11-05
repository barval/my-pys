from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_SECRET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass(frozen=True)
class UpstreamKey:
    label: str
    key_file: str
    exists: bool
    length: int


@dataclass(frozen=True)
class KeyStatus:
    route: str
    router_token: bool
    router_token_file: str
    router_token_length: int
    upstream: tuple[UpstreamKey, ...]


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


def _length(path: Path) -> int:
    try:
        return path.stat().st_size if _present(path) else 0
    except OSError:
        return 0


def key_inventory(
    secrets_dir: Path, routes: Iterable[dict]
) -> list[KeyStatus]:
    secrets_dir = Path(secrets_dir)
    items: list[KeyStatus] = []
    for route in routes:
        name = route.get("name", "")
        token_file = route.get("token_file", "")
        router_path = secrets_dir / token_file if token_file else None
        upstream: list[UpstreamKey] = []
        primary = route.get("primary") or {}
        entries: list[tuple[str, str]] = [
            ("основной", primary.get("api_key_file", ""))
        ]
        for index, fallback in enumerate(route.get("fallbacks") or [], start=1):
            entries.append(
                (f"запасной {index}", fallback.get("api_key_file", ""))
            )
        for label, key_file in entries:
            path = secrets_dir / key_file if key_file else None
            upstream.append(
                UpstreamKey(
                    label=label,
                    key_file=key_file,
                    exists=bool(path and _present(path)),
                    length=_length(path) if path else 0,
                )
            )
        items.append(
            KeyStatus(
                route=name,
                router_token=bool(router_path and _present(router_path)),
                router_token_file=token_file,
                router_token_length=_length(router_path) if router_path else 0,
                upstream=tuple(upstream),
            )
        )
    return items


def rotate_router_token(secrets_dir: Path, token_file: str) -> str:
    validate_secret_name(token_file)
    value = generate_router_token()
    write_secret(secrets_dir, token_file, value)
    return value


def set_upstream_key(
    secrets_dir: Path,
    key_file: str,
    value: str,
) -> None:
    validate_secret_name(key_file)
    if not value.strip():
        raise ValueError("key value must not be empty")
    write_secret(secrets_dir, key_file, value.strip())
