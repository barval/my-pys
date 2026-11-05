from __future__ import annotations

import json
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


# ---------------------------------------------------------------------------
# Registry of upstream keys
# ---------------------------------------------------------------------------

# Keys are first-class: a key exists once and any route can reference its file.
# The registry stores only labels and file names, never values.


@dataclass(frozen=True)
class UpstreamKeyEntry:
    label: str
    file: str
    exists: bool
    used_by: tuple[str, ...]


def _load_registry(path: Path) -> list[dict[str, str]]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("keys") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        file = str(item.get("file", "")).strip()
        try:
            validate_secret_name(file)
        except ValueError:
            continue
        if file in seen:
            continue
        seen.add(file)
        label = str(item.get("label", "")).strip() or file
        entries.append({"label": label[:80], "file": file})
    return entries


def save_registry(path: Path, entries: Iterable[dict[str, str]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    with open(temp, "w", encoding="utf-8") as stream:
        json.dump({"keys": list(entries)}, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def key_usage(routes: Iterable[dict]) -> dict[str, list[str]]:
    usage: dict[str, list[str]] = {}
    for route in routes:
        name = str(route.get("name", ""))
        upstreams = [route.get("primary"), *(route.get("fallbacks") or [])]
        for upstream in upstreams:
            if not isinstance(upstream, dict):
                continue
            file = str(upstream.get("api_key_file", "")).strip()
            if file:
                usage.setdefault(file, []).append(name)
    return usage


def sync_registry(
    entries: list[dict[str, str]], routes: Iterable[dict]
) -> list[dict[str, str]]:
    """Register files already referenced by routes, so old configs keep working."""
    known = {entry["file"] for entry in entries}
    for file in key_usage(routes):
        if file in known:
            continue
        try:
            validate_secret_name(file)
        except ValueError:
            continue
        entries.append({"label": file, "file": file})
        known.add(file)
    return entries


def upstream_key_list(
    registry_path: Path,
    secrets_dir: Path,
    routes: Iterable[dict],
) -> list[UpstreamKeyEntry]:
    routes = list(routes)
    entries = _load_registry(registry_path)
    synced = sync_registry(list(entries), routes)
    if synced != entries:
        save_registry(registry_path, synced)
    usage = key_usage(routes)
    secrets_dir = Path(secrets_dir)
    return [
        UpstreamKeyEntry(
            label=entry["label"],
            file=entry["file"],
            exists=_present(secrets_dir / entry["file"]),
            used_by=tuple(usage.get(entry["file"], ())),
        )
        for entry in synced
    ]


def add_upstream_key(
    registry_path: Path,
    secrets_dir: Path,
    label: str,
    key_file: str,
    value: str,
) -> str:
    key_file = key_file.strip()
    validate_secret_name(key_file)
    if not value.strip():
        raise ValueError("key value must not be empty")
    entries = _load_registry(registry_path)
    if any(entry["file"] == key_file for entry in entries):
        raise ValueError("ключ с таким файлом уже добавлен")
    write_secret(secrets_dir, key_file, value.strip())
    entries.append({"label": label.strip()[:80] or key_file, "file": key_file})
    save_registry(registry_path, entries)
    return key_file


def delete_upstream_key(
    registry_path: Path,
    secrets_dir: Path,
    key_file: str,
    routes: Iterable[dict],
) -> None:
    validate_secret_name(key_file)
    usage = key_usage(routes).get(key_file, [])
    if usage:
        raise ValueError("ключ используется маршрутами: " + ", ".join(usage))
    entries = [
        entry
        for entry in _load_registry(registry_path)
        if entry["file"] != key_file
    ]
    save_registry(registry_path, entries)
    try:
        (Path(secrets_dir) / key_file).unlink()
    except FileNotFoundError:
        pass
