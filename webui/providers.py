from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    base_url: str
    models: tuple[str, ...]


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    original = str(value).strip().lower()
    value = _SLUG_RE.sub("-", original)
    value = value.strip("-")
    value = re.sub(r"-+", "-", value)
    if not value:
        digest = hashlib.sha1(original.encode("utf-8")).hexdigest()[:6]
        return f"provider-{digest}"
    return value[:32].rstrip("-")


def _host_from_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    host = parsed.hostname or parsed.netloc or "provider"
    if parsed.port and str(parsed.port) not in host:
        host = f"{host}-{parsed.port}"
    return host


def _unique_id(base_url: str, used: set[str]) -> str:
    host = _host_from_url(base_url)
    candidate = slugify(host)
    if candidate not in used:
        return candidate
    index = 2
    while True:
        numbered = f"{candidate}-{index}"
        if numbered not in used:
            return numbered
        index += 1


def _extract_models(routes: Iterable[dict]) -> dict[str, set[str]]:
    buckets: dict[str, set[str]] = {}
    for route in routes:
        for upstream in [route.get("primary"), *(route.get("fallbacks") or [])]:
            if not isinstance(upstream, dict):
                continue
            base_url = upstream.get("base_url", "").strip()
            model = upstream.get("model", "").strip()
            if not base_url or not model:
                continue
            buckets.setdefault(base_url, set()).add(model)
    return buckets


def load_providers(path: Path, routes: Iterable[dict]) -> list[Provider]:
    path = Path(path)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            items = raw.get("providers") if isinstance(raw, dict) else raw
        except (OSError, ValueError):
            items = []
        providers: list[Provider] = []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                pid = str(item.get("id", "")).strip()
                name = str(item.get("name", "")).strip()
                base_url = str(item.get("base_url", "")).strip()
                models_raw = item.get("models", [])
                if not pid or not name or not base_url:
                    continue
                if not isinstance(models_raw, (list, tuple)):
                    continue
                models = tuple(str(m).strip() for m in models_raw if str(m).strip())
                providers.append(Provider(id=pid, name=name, base_url=base_url, models=models))
        return providers

    buckets = _extract_models(routes)
    used: set[str] = set()
    providers = []
    for base_url in sorted(buckets):
        pid = _unique_id(base_url, used)
        used.add(pid)
        providers.append(
            Provider(
                id=pid,
                name=pid,
                base_url=base_url,
                models=tuple(sorted(buckets[base_url])),
            )
        )
    save_providers(path, providers)
    return providers


def save_providers(path: Path, providers: Iterable[Provider]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            data = {
                "providers": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "base_url": p.base_url,
                        "models": list(p.models),
                    }
                    for p in providers
                ]
            }
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def upsert_provider(path: Path, provider: Provider) -> None:
    providers = load_providers(path, [])
    for index, item in enumerate(providers):
        if item.id == provider.id:
            providers[index] = provider
            break
    else:
        providers.append(provider)
    save_providers(path, providers)


def delete_provider(path: Path, provider_id: str) -> None:
    providers = load_providers(path, [])
    for index, item in enumerate(providers):
        if item.id == provider_id:
            del providers[index]
            save_providers(path, providers)
            return
    raise KeyError(provider_id)


def fetch_models(
    base_url: str,
    api_key: str | None,
    *,
    timeout: float = 5.0,
    opener=urllib.request.urlopen,
) -> list[str]:
    url = f"{base_url.rstrip('/')}/models"
    request = urllib.request.Request(url)
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    response = opener(request, timeout=timeout)
    if getattr(response, "status", None) != 200 and getattr(response, "getcode", lambda: 200)() != 200:
        code = getattr(response, "status", None) or getattr(response, "getcode", lambda: None)()
        raise ValueError(f"провайдер вернул код {code}")
    payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [str(item.get("id", "")).strip() for item in payload["data"] if str(item.get("id", "")).strip()]
    if isinstance(payload, list):
        return [str(item).strip() for item in payload if str(item).strip()]
    return []
