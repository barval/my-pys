from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .actions import CommandBuilder
from .profiles import Profile


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass
class Job:
    id: str
    action: str
    target: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    exit_code: int | None
    log_path: Path


class JobRunner:
    def __init__(
        self,
        state_dir: Path,
        builder: CommandBuilder,
        max_workers: int = 2,
        timeout: int = 600,
    ):
        self.state_dir = Path(state_dir)
        self.jobs_dir = self.state_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.builder = builder
        self.timeout = timeout
        self._root = Path(getattr(builder, "root", Path.cwd()))
        self._lock = threading.RLock()
        self._locks: dict[str, threading.Lock] = {}
        self._lock_guard = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._events: dict[str, threading.Event] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._load()

    def _load(self) -> None:
        for path in self.jobs_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["log_path"] = Path(data["log_path"])
                job = Job(**data)
            except (OSError, ValueError, TypeError, KeyError):
                continue
            if job.status in ("queued", "running"):
                job.status = "interrupted"
                job.finished_at = _now()
                self._persist(job)
            event = threading.Event()
            if job.status in ("succeeded", "failed", "cancelled", "interrupted"):
                event.set()
            self._jobs[job.id] = job
            self._events[job.id] = event

    def _persist(self, job: Job) -> None:
        path = self.jobs_dir / f"{job.id}.json"
        data = asdict(job)
        data["log_path"] = str(job.log_path)
        temp = path.with_name(f"{path.name}.tmp")
        temp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)

    def _target_lock(self, target: str) -> threading.Lock:
        with self._lock_guard:
            return self._locks.setdefault(target, threading.Lock())

    def _set(self, job_id: str, **changes: Any) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in changes.items():
                setattr(job, key, value)
            self._persist(job)
            return job

    def submit(self, action: str, profile: Profile | None) -> Job:
        argv, env = self.builder.build(action, profile)
        target = profile.name if profile else "host"
        return self.submit_command(action, target, argv, env)

    def submit_command(
        self,
        action: str,
        target: str,
        argv: list[str],
        env: dict[str, str],
    ) -> Job:
        job_id = uuid.uuid4().hex
        log_path = self.jobs_dir / f"{job_id}.log"
        log_path.write_text("", encoding="utf-8")
        os.chmod(log_path, 0o600)
        job = Job(
            id=job_id,
            action=action,
            target=target,
            status="queued",
            created_at=_now(),
            started_at=None,
            finished_at=None,
            exit_code=None,
            log_path=log_path,
        )
        event = threading.Event()
        with self._lock:
            self._jobs[job_id] = job
            self._events[job_id] = event
            self._persist(job)
        self._pool.submit(self._run, job_id, argv, env, target)
        return job

    def _run(
        self,
        job_id: str,
        argv: list[str],
        env: dict[str, str],
        target: str,
    ) -> None:
        lock = self._target_lock(target)
        with lock:
            with self._lock:
                job = self._jobs[job_id]
                if job.status == "cancelled":
                    self._events[job_id].set()
                    return
            self._set(job_id, status="running", started_at=_now())
            full_env = os.environ.copy()
            full_env.update(env)
            log = open(self._jobs[job_id].log_path, "w", encoding="utf-8")
            proc: subprocess.Popen | None = None
            status = "failed"
            exit_code: int | None = None
            try:
                proc = subprocess.Popen(
                    argv,
                    cwd=str(self._root),
                    env=full_env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
                with self._lock:
                    self._procs[job_id] = proc
                exit_code = proc.wait(timeout=self.timeout)
                status = "succeeded" if exit_code == 0 else "failed"
            except subprocess.TimeoutExpired:
                if proc is not None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except OSError:
                        pass
                    proc.wait()
                log.write("\n[timeout]\n")
                status = "failed"
            except OSError as exc:
                log.write(f"\n[error] {exc}\n")
                status = "failed"
            finally:
                log.close()
                with self._lock:
                    self._procs.pop(job_id, None)
                    current = self._jobs[job_id]
                    if current.status == "cancelled":
                        status = "cancelled"
                    self._set(
                        job_id,
                        status=status,
                        exit_code=exit_code,
                        finished_at=_now(),
                    )
                    self._events[job_id].set()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit: int = 50) -> list[Job]:
        with self._lock:
            jobs = sorted(
                self._jobs.values(),
                key=lambda item: item.created_at,
                reverse=True,
            )
        return jobs[:limit]

    def tail(self, job_id: str, offset: int = 0) -> tuple[str, int]:
        job = self.get(job_id)
        if job is None:
            return "", offset
        try:
            data = job.log_path.read_bytes()
        except OSError:
            return "", offset
        return data[offset:].decode("utf-8", errors="replace"), len(data)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in (
                "succeeded",
                "failed",
                "cancelled",
                "interrupted",
            ):
                return False
            job.status = "cancelled"
            job.finished_at = _now()
            self._persist(job)
            proc = self._procs.get(job_id)
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
        self._events[job_id].set()
        return True

    def wait(self, job_id: str, timeout: float | None = None) -> Job:
        event = self._events.get(job_id)
        if event is not None:
            event.wait(timeout)
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job
