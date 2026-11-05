from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from router.llm_router import ConfigError, load_config


def read_config(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_config(path: Path) -> None:
    load_config(Path(path))


def save_config(path: Path, raw: dict[str, Any]) -> None:
    path = Path(path)
    if not isinstance(raw, dict) or not isinstance(raw.get("routes"), list):
        raise ConfigError("config must contain a 'routes' array")
    handle, temp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".router-routes.",
        suffix=".tmp",
        text=True,
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(raw, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        validate_config(temp)
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def upsert_route(raw: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(raw)
    routes = result.setdefault("routes", [])
    name = route.get("name")
    for index, item in enumerate(routes):
        if item.get("name") == name:
            routes[index] = copy.deepcopy(route)
            break
    else:
        routes.append(copy.deepcopy(route))
    return result


def delete_route(raw: dict[str, Any], name: str) -> dict[str, Any]:
    result = copy.deepcopy(raw)
    routes = result.get("routes", [])
    for index, item in enumerate(routes):
        if item.get("name") == name:
            del routes[index]
            return result
    raise KeyError(name)
