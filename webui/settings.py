from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


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
    )
