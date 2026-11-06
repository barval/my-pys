from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Step:
    number: int
    key: str
    title: str
    hint: str


HOST_STEP = Step(
    number=1,
    key="prepare",
    title="Подготовьте хост",
    hint="Скачайте прошивку, запустите стенд и не забудьте вернуть DNS роутера после прошивки.",
)

STEPS: tuple[Step, ...] = (
    Step(number=2, key="bind", title="Сброс и привязка", hint="Включите колонку и привяжите её в приложении «Дом с Алисой»."),
    Step(number=3, key="discover", title="Найти колонку", hint="Панель найдёт колонку в локальной сети по Device ID и MAC."),
    Step(number=4, key="root", title="Root и ADB", hint="Проверьте, что на колонке доступен ADB с правами root."),
    Step(number=5, key="ssh", title="SSH и OTA", hint="Настройте SSH-подключение и отключите автоматические OTA-обновления."),
    Step(number=6, key="route", title="Маршрут и ключ", hint="Создайте маршрут в локальном роутере и запишите ключ в колонку."),
    Step(number=7, key="bridge", title="Quasar Bridge", hint="Установите Quasar Bridge на колонку."),
    Step(number=8, key="voice", title="Проверка голосом", hint="Проверьте, что колонка отвечает голосом через LLM."),
)

_STEP_KEYS = {step.key for step in STEPS}


@dataclass(frozen=True)
class Progress:
    step: int = 2
    done: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    last_job: str | None = None
    updated_at: str = ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _filter_keys(keys: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(key for key in keys if key in _STEP_KEYS)


def load_progress(path: Path, *, first_step: int = 2) -> Progress:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Progress(step=first_step, updated_at=_utc_now())
    if not isinstance(raw, dict):
        return Progress(step=first_step, updated_at=_utc_now())
    try:
        step = int(raw.get("step", first_step))
    except (TypeError, ValueError):
        step = first_step
    done = raw.get("done")
    skipped = raw.get("skipped")
    last_job = raw.get("last_job")
    if not isinstance(done, (list, tuple)):
        done = ()
    if not isinstance(skipped, (list, tuple)):
        skipped = ()
    return Progress(
        step=step,
        done=_filter_keys(tuple(done)),
        skipped=_filter_keys(tuple(skipped)),
        last_job=last_job if isinstance(last_job, str) else None,
        updated_at=raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else _utc_now(),
    )


def save_progress(path: Path, progress: Progress) -> None:
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
            json.dump(
                {
                    "step": progress.step,
                    "done": list(progress.done),
                    "skipped": list(progress.skipped),
                    "last_job": progress.last_job,
                    "updated_at": progress.updated_at or _utc_now(),
                },
                stream,
                ensure_ascii=False,
                indent=2,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def advance(progress: Progress, key: str, *, skipped: bool = False) -> Progress:
    if key not in _STEP_KEYS:
        return progress
    done = set(progress.done)
    skipped_set = set(progress.skipped)
    if skipped:
        skipped_set.add(key)
        done.discard(key)
    else:
        done.add(key)
        skipped_set.discard(key)
    completed = done | skipped_set
    next_step = 9
    for step in STEPS:
        if step.key not in completed:
            next_step = step.number
            break
    return replace(
        progress,
        step=next_step,
        done=tuple(sorted(done, key=lambda k: next(s.number for s in STEPS if s.key == k))),
        skipped=tuple(sorted(skipped_set, key=lambda k: next(s.number for s in STEPS if s.key == k))),
        last_job=progress.last_job,
        updated_at=_utc_now(),
    )


def step_by_number(number: int) -> Step | None:
    return next((step for step in STEPS if step.number == number), None)


def set_last_job(progress: Progress, job: str) -> Progress:
    return replace(progress, last_job=job, updated_at=_utc_now())
