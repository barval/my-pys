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
    )
