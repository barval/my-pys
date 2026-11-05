from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .profiles import Profile

COLOR_CHOICES = (
    ("beige", "Бежевый", "#d9c3a5"),
    ("green", "Зелёный", "#7fb069"),
    ("pink", "Розовый", "#ef8fb3"),
    ("red", "Красный", "#d9534f"),
    ("purple", "Фиолетовый", "#8e6bbf"),
    ("yellow", "Жёлтый", "#e6c229"),
    ("blue", "Голубой", "#4a90e2"),
    ("gray", "Серый", "#9aa0a6"),
    ("black", "Чёрный", "#2f2f2f"),
    ("white", "Белый", "#f2f2f2"),
)
COLOR_MAP = {key: value for key, _, value in COLOR_CHOICES}
COLOR_LABELS = {key: label for key, label, _ in COLOR_CHOICES}
_FALLBACK = [value for key, _, value in COLOR_CHOICES if key not in ("black", "white")]
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def color_hex(value: str, device_id: str) -> str:
    value = (value or "").strip()
    if value in COLOR_MAP:
        return COLOR_MAP[value]
    if _HEX_RE.fullmatch(value):
        return value.lower()
    digest = hashlib.sha256((device_id or "speaker").encode("utf-8")).digest()
    return _FALLBACK[digest[0] % len(_FALLBACK)]


def color_label(value: str) -> str:
    value = (value or "").strip()
    if value in COLOR_LABELS:
        return COLOR_LABELS[value]
    if value:
        return "свой цвет"
    return "авто"


def resolve_color(profile: Profile, override: dict | None = None) -> str:
    source = (override or {}).get("color") or profile.color
    return color_hex(source, profile.device_id)


def resolve_color_name(profile: Profile, override: dict | None = None) -> str:
    source = (override or {}).get("color") or profile.color
    return color_label(source)


def resolve_model(profile: Profile, override: dict | None = None) -> str:
    return (override or {}).get("model") or profile.model


def load_overrides(path: Path) -> dict[str, dict]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def save_override(
    path: Path,
    device_id: str,
    color: str,
    model: str,
) -> None:
    path = Path(path)
    data = load_overrides(path)
    data[device_id] = {"color": color.strip(), "model": model.strip()}
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
