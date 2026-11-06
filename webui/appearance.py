from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .profiles import Profile

COLOR_CHOICES = (
    ("beige", "Капучино", "#d9a86f"),
    ("green", "Мята", "#22c1c3"),
    ("pink", "Фламинго", "#e63a86"),
    ("red", "Чили", "#e0353c"),
    ("purple", "Ультрафиолет", "#7c3fd8"),
    ("yellow", "Лимон", "#e3c63a"),
    ("blue", "Голубой", "#4a90e2"),
    ("gray", "Серый", "#9aa0a6"),
    ("black", "Чёрный", "#2f2f2f"),
    ("white", "Белый", "#f2f2f2"),
)
COLOR_MAP = {key: value for key, _, value in COLOR_CHOICES}
COLOR_LABELS = {key: label for key, label, _ in COLOR_CHOICES}
COLOR_ALIASES = {
    "beige": "beige",
    "cappuccino": "beige",
    "капучино": "beige",
    "бежевый": "beige",
    "green": "green",
    "mint": "green",
    "мята": "green",
    "бирюзовый": "green",
    "бирюзовая": "green",
    "зелёный": "green",
    "зеленый": "green",
    "pink": "pink",
    "flamingo": "pink",
    "фламинго": "pink",
    "розовый": "pink",
    "red": "red",
    "chili": "red",
    "чили": "red",
    "красный": "red",
    "purple": "purple",
    "ultraviolet": "purple",
    "ультрафиолет": "purple",
    "ультравиолет": "purple",
    "фиолетовый": "purple",
    "yellow": "yellow",
    "lemon": "yellow",
    "лимон": "yellow",
    "жёлтый": "yellow",
    "желтый": "yellow",
    "blue": "blue",
    "голубой": "blue",
    "gray": "gray",
    "grey": "gray",
    "серый": "gray",
    "black": "black",
    "чёрный": "black",
    "черный": "black",
    "white": "white",
    "белый": "white",
}
_FALLBACK = [value for key, _, value in COLOR_CHOICES if key not in ("black", "white")]
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def canonical_color(value: str) -> str:
    value = (value or "").strip().lower()
    if value in COLOR_ALIASES:
        return COLOR_ALIASES[value]
    if value in COLOR_MAP:
        return value
    if _HEX_RE.fullmatch(value):
        return value.lower()
    return ""


def color_hex(value: str, device_id: str) -> str:
    key = canonical_color(value)
    if key in COLOR_MAP:
        return COLOR_MAP[key]
    if _HEX_RE.fullmatch(key):
        return key
    digest = hashlib.sha256((device_id or "speaker").encode("utf-8")).digest()
    return _FALLBACK[digest[0] % len(_FALLBACK)]


def color_label(value: str) -> str:
    key = canonical_color(value)
    if key in COLOR_LABELS:
        return COLOR_LABELS[key]
    if key:
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


def remove_override(path: Path, device_id: str) -> None:
    path = Path(path)
    data = load_overrides(path)
    data.pop(device_id, None)
    if not data:
        try:
            path.unlink()
        except OSError:
            pass
        return
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
