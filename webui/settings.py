from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class Settings:
    root: Path
    speakers_dir: Path
    secrets_dir: Path
    router_config: Path
    state_dir: Path
    templates_dir: Path
    static_dir: Path
    admin_hash_file: Path
    session_key_file: Path
    host: str
    port: int
    job_timeout: int
    max_workers: int
    router_control: str
    sidecar_url: str
    router_health_url: str
    stand_control: str
    stand_url: str
    stand_ip: str
    router_display_url: str
    router_health_display_url: str


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key.strip():
            values[key.strip()] = value
    return values


def load_settings(
    root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Settings:
    values = os.environ if env is None else env
    if root is not None:
        root_path = Path(root)
    else:
        root_path = Path(values.get("WEBUI_ROOT", Path.cwd()))
    root_path = root_path.expanduser().resolve()

    package_dir = Path(__file__).resolve().parent
    secrets_dir = root_path / "secrets"
    router_control = values.get("WEBUI_ROUTER_CONTROL", "host")
    if router_control not in ("host", "sidecar"):
        raise ValueError("WEBUI_ROUTER_CONTROL must be host or sidecar")
    stand_control = values.get("WEBUI_STAND_CONTROL", "host")
    if stand_control not in ("host", "sidecar"):
        raise ValueError("WEBUI_STAND_CONTROL must be host or sidecar")
    project_env: dict[str, str] = {}
    for candidate in (root_path / "local" / ".env", root_path / ".env"):
        if candidate.is_file():
            project_env = _read_env_file(candidate)
            break
    stand_ip = values.get("ROOT_STAND_IP") or project_env.get("ROOT_STAND_IP", "")
    llm_base_url = values.get("LLM_BASE_URL") or project_env.get(
        "LLM_BASE_URL", ""
    )
    if not stand_ip:
        stand_ip = "192.168.1.2"
    router_display_url = llm_base_url or f"http://{stand_ip}:5002/v1"
    parsed = urlsplit(router_display_url)
    router_health_display_url = urlunsplit(
        (parsed.scheme or "http", parsed.netloc, "/health", "", "")
    )
    router_health_url = values.get("WEBUI_ROUTER_HEALTH_URL") or (
        "http://llm-router:5002/health"
        if router_control == "sidecar"
        else "http://127.0.0.1:5002/health"
    )
    return Settings(
        root=root_path,
        speakers_dir=root_path / "local" / "speakers",
        secrets_dir=secrets_dir,
        router_config=secrets_dir / "router-routes.json",
        state_dir=root_path / "webui-state",
        templates_dir=package_dir / "templates",
        static_dir=package_dir / "static",
        admin_hash_file=secrets_dir / "webui-admin.hash",
        session_key_file=secrets_dir / "webui-session.key",
        host=values.get("WEBUI_HOST", "127.0.0.1"),
        port=int(values.get("WEBUI_PORT", "8080")),
        job_timeout=int(values.get("WEBUI_JOB_TIMEOUT", "600")),
        max_workers=int(values.get("WEBUI_MAX_WORKERS", "2")),
        router_control=router_control,
        sidecar_url=values.get(
            "WEBUI_SIDECAR_URL", "http://127.0.0.1:8081"
        ),
        router_health_url=router_health_url,
        stand_control=stand_control,
        stand_url=values.get("WEBUI_STAND_URL", "http://127.0.0.1:8082"),
        stand_ip=stand_ip,
        router_display_url=router_display_url,
        router_health_display_url=router_health_display_url,
    )
