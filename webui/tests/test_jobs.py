from __future__ import annotations

import pytest

from webui.actions import CommandBuilder, UnknownAction
from webui.jobs import JobRunner


class FakeBuilder:
    def __init__(self, argv):
        self.argv = argv

    def build(self, action, profile):
        return list(self.argv), {}


def test_job_runs_and_captures_output(tmp_path, make_profile):
    runner = JobRunner(tmp_path, FakeBuilder(["bash", "-c", "echo ready"]))
    job = runner.submit("status", make_profile("speaker-a"))
    runner.wait(job.id, timeout=5)
    assert runner.get(job.id).status == "succeeded"
    assert "ready" in runner.tail(job.id)[0]


def test_same_target_jobs_do_not_overlap(tmp_path, make_profile):
    runner = JobRunner(
        tmp_path,
        FakeBuilder(["bash", "-c", "sleep 0.2; echo done"]),
    )
    first = runner.submit("status", make_profile("speaker-a"))
    second = runner.submit("status", make_profile("speaker-a"))
    runner.wait(first.id, timeout=5)
    runner.wait(second.id, timeout=5)
    assert runner.get(first.id).finished_at <= runner.get(second.id).started_at


def test_unknown_action_does_not_create_job(tmp_path):
    runner = JobRunner(tmp_path, CommandBuilder(tmp_path))
    with pytest.raises(UnknownAction):
        runner.submit("nope", None)


def test_unfinished_job_is_marked_interrupted(tmp_path, make_profile):
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    log = jobs_dir / "abc.log"
    log.write_text("", encoding="utf-8")
    (jobs_dir / "abc.json").write_text(
        '{"id":"abc","action":"status","target":"speaker-a","status":"running",'
        '"created_at":"2026-01-01T00:00:00+00:00","started_at":"2026-01-01T00:00:00+00:00",'
        f'"finished_at":null,"exit_code":null,"log_path":"{log}"}}',
        encoding="utf-8",
    )
    runner = JobRunner(tmp_path, FakeBuilder(["bash", "-c", "true"]))
    assert runner.get("abc").status == "interrupted"
