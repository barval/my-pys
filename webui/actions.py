from __future__ import annotations

import sys
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
    "resolve": ActionSpec(
        key="resolve",
        label="Найти колонку",
        scope="speaker",
        argv=("bash", "scripts/resolve-speaker.sh"),
        needs_profile=True,
    ),
    "check": ActionSpec(
        key="check",
        label="Проверить LLM",
        scope="speaker",
        argv=("bash", "scripts/check-llm.sh"),
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
        label="Настроить SSH/OTA",
        scope="speaker",
        argv=("bash", "scripts/post-root-ssh.sh"),
        needs_profile=True,
    ),
    "adb": ActionSpec(
        key="adb",
        label="Проверить ADB и root",
        scope="speaker",
        argv=("bash", "scripts/adb-root-check.sh"),
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
    "stand-start": ActionSpec(
        key="stand-start",
        label="Запустить стенд",
        scope="host",
        argv=("bash", "scripts/start-lite-kit.sh"),
        needs_profile=False,
    ),
    "stand-stop": ActionSpec(
        key="stand-stop",
        label="Остановить стенд",
        scope="host",
        argv=("bash", "scripts/stop-lite-kit.sh"),
        needs_profile=False,
    ),
    "stand-status": ActionSpec(
        key="stand-status",
        label="Статус стенда",
        scope="host",
        argv=(
            "docker",
            "ps",
            "--filter",
            "name=ysl-lite-kit",
            "--format",
            "{{.Status}}",
        ),
        needs_profile=False,
    ),
}


class CommandBuilder:
    def __init__(
        self,
        root: Path,
        router_control: str = "host",
        sidecar_url: str = "http://127.0.0.1:8081",
        stand_control: str = "host",
        stand_url: str = "http://127.0.0.1:8082",
    ):
        self.root = Path(root)
        self.router_control = router_control
        self.sidecar_url = sidecar_url
        self.stand_control = stand_control
        self.stand_url = stand_url

    def build(
        self, action: str, profile: Profile | None
    ) -> tuple[list[str], dict[str, str]]:
        if self.stand_control == "sidecar" and action in (
            "stand-start",
            "stand-stop",
            "stand-status",
        ):
            return (
                [
                    sys.executable,
                    "-m",
                    "webui.stand_client",
                    action.removeprefix("stand-"),
                ],
                {"WEBUI_STAND_URL": self.stand_url},
            )

        if self.router_control == "sidecar":
            if action == "router-restart":
                return (
                    [sys.executable, "-m", "webui.router_control"],
                    {"WEBUI_SIDECAR_URL": self.sidecar_url},
                )
            if action in ("router-start", "router-stop"):
                raise UnknownAction(
                    f"{action} is not available in sidecar mode"
                )

        spec = SPEAKER_ACTIONS.get(action)
        if spec is not None:
            if profile is None:
                raise ValueError(f"action {action} requires a speaker profile")
            return list(spec.argv), {
                "SPEAKER_ENV": str(profile.path),
                # В контейнере ARP не видит LAN, MAC-проверка невозможна.
                "SPEAKER_TRUST_IP": "1",
            }

        spec = HOST_ACTIONS.get(action)
        if spec is not None:
            if profile is not None:
                raise ValueError(f"action {action} does not accept a speaker profile")
            return list(spec.argv), {}

        raise UnknownAction(action)
