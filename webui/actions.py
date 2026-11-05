from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .profiles import Profile


class UnknownAction(ValueError):
    """Raised when an action is not in the allow-list."""


@dataclass(frozen=True)
class ActionSpec:
    key: str
    label: str
    scope: Literal["speaker", "host"]
    argv: tuple[str, ...]
    needs_profile: bool


SPEAKER_ACTIONS: dict[str, ActionSpec] = {
    "status": ActionSpec(
        key="status",
        label="Статус Bridge",
        scope="speaker",
        argv=("bash", "scripts/speaker-status.sh"),
        needs_profile=True,
    ),
    "check": ActionSpec(
        key="check",
        label="Проверить LLM",
        scope="speaker",
        argv=("bash", "scripts/check-flai.sh"),
        needs_profile=True,
    ),
    "key": ActionSpec(
        key="key",
        label="Записать ключ",
        scope="speaker",
        argv=("bash", "scripts/set-speaker-key.sh"),
        needs_profile=True,
    ),
    "routing": ActionSpec(
        key="routing",
        label="Применить routing",
        scope="speaker",
        argv=("bash", "scripts/apply-bridge-routing.sh"),
        needs_profile=True,
    ),
    "bridge": ActionSpec(
        key="bridge",
        label="Установить Bridge",
        scope="speaker",
        argv=("bash", "scripts/install-quasar-bridge.sh", "--non-interactive"),
        needs_profile=True,
    ),
    "root": ActionSpec(
        key="root",
        label="Подготовить root/SSH",
        scope="speaker",
        argv=("bash", "scripts/post-root-ssh.sh"),
        needs_profile=True,
    ),
}

HOST_ACTIONS: dict[str, ActionSpec] = {
    "firmware": ActionSpec(
        key="firmware",
        label="Скачать прошивку",
        scope="host",
        argv=("bash", "scripts/fetch-firmware.sh"),
        needs_profile=False,
    ),
    "router-start": ActionSpec(
        key="router-start",
        label="Запустить роутер",
        scope="host",
        argv=("bash", "scripts/start-router.sh"),
        needs_profile=False,
    ),
    "router-stop": ActionSpec(
        key="router-stop",
        label="Остановить роутер",
        scope="host",
        argv=("bash", "scripts/stop-router.sh"),
        needs_profile=False,
    ),
    "router-restart": ActionSpec(
        key="router-restart",
        label="Перезапустить роутер",
        scope="host",
        argv=(
            "docker",
            "compose",
            "-f",
            "docker/docker-compose.router.yml",
            "restart",
        ),
        needs_profile=False,
    ),
}


class CommandBuilder:
    def __init__(self, root: Path):
        self.root = Path(root)

    def build(
        self, action: str, profile: Profile | None
    ) -> tuple[list[str], dict[str, str]]:
        spec = SPEAKER_ACTIONS.get(action)
        if spec is not None:
            if profile is None:
                raise ValueError(f"action {action} requires a speaker profile")
            return list(spec.argv), {"SPEAKER_ENV": str(profile.path)}

        spec = HOST_ACTIONS.get(action)
        if spec is not None:
            if profile is not None:
                raise ValueError(f"action {action} does not accept a speaker profile")
            return list(spec.argv), {}

        raise UnknownAction(action)
