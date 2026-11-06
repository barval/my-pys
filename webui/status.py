from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

ACTION_FIELDS = {"resolve": "online", "status": "bridge", "check": "llm"}


@dataclass(frozen=True)
class SpeakerStatus:
    at: str
    online: bool | None = None
    bridge: bool | None = None
    llm: bool | None = None


def _valid_optional_bool(value) -> bool:
    return value is None or isinstance(value, bool)


def load_status(path: Path) -> dict[str, SpeakerStatus]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, SpeakerStatus] = {}
    for name, record in data.items():
        if not isinstance(record, dict):
            continue
        if not isinstance(record.get("at"), str):
            continue
        if not all(_valid_optional_bool(record.get(field)) for field in ("online", "bridge", "llm")):
            continue
        try:
            result[name] = SpeakerStatus(
                at=record["at"],
                online=record.get("online"),
                bridge=record.get("bridge"),
                llm=record.get("llm"),
            )
        except (TypeError, ValueError):
            continue
    return result


def save_status(path: Path, statuses: dict[str, SpeakerStatus]) -> None:
    data = {name: asdict(status) for name, status in statuses.items()}
    directory = path.parent
    descriptor, temp_name = tempfile.mkstemp(dir=str(directory), suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def sync_from_jobs(path: Path, jobs: Iterable) -> dict[str, SpeakerStatus]:
    statuses = dict(load_status(path))
    relevant: list = []
    for job in jobs:
        action = getattr(job, "action", None)
        target = getattr(job, "target", None)
        finished_at = getattr(job, "finished_at", None)
        exit_code = getattr(job, "exit_code", None)
        if action not in ACTION_FIELDS:
            continue
        if not target:
            continue
        if not finished_at:
            continue
        if exit_code is None:
            continue
        relevant.append(job)
    changed = False
    for job in sorted(relevant, key=lambda item: getattr(item, "finished_at")):
        action = getattr(job, "action", None)
        target = getattr(job, "target", None)
        finished_at = getattr(job, "finished_at", None)
        exit_code = getattr(job, "exit_code", None)
        field = ACTION_FIELDS[action]
        current = statuses.get(target)
        if current is None or finished_at > current.at:
            values = {field: exit_code == 0, "at": finished_at}
            if current is not None:
                values.setdefault("online", current.online)
                values.setdefault("bridge", current.bridge)
                values.setdefault("llm", current.llm)
            statuses[target] = SpeakerStatus(**values)
            changed = True
    if changed:
        save_status(path, statuses)
    return statuses
