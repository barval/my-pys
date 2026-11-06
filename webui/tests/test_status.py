from pathlib import Path
from types import SimpleNamespace

from webui.status import load_status, save_status, sync_from_jobs


def job(action, target, code, finished, status="succeeded"):
    return SimpleNamespace(action=action, target=target, status=status,
                           exit_code=code, finished_at=finished)


def test_sync_maps_actions_to_fields(tmp_path):
    path = tmp_path / "speaker-status.json"
    result = sync_from_jobs(path, [
        job("resolve", "speaker-a", 0, "2026-11-06T10:00:00+00:00"),
        job("status", "speaker-a", 1, "2026-11-06T10:01:00+00:00"),
    ])
    assert result["speaker-a"].online is True
    assert result["speaker-a"].bridge is False
    assert result["speaker-a"].at == "2026-11-06T10:01:00+00:00"


def test_newer_job_wins_and_unknown_actions_ignored(tmp_path):
    path = tmp_path / "speaker-status.json"
    sync_from_jobs(path, [job("resolve", "speaker-a", 0, "2026-11-06T10:00:00+00:00")])
    result = sync_from_jobs(path, [
        job("resolve", "speaker-a", 1, "2026-11-06T11:00:00+00:00"),
        job("say", "speaker-a", 0, "2026-11-06T12:00:00+00:00"),
    ])
    assert result["speaker-a"].online is False


def test_save_and_load_round_trip(tmp_path):
    from webui.status import SpeakerStatus

    path = tmp_path / "speaker-status.json"
    save_status(path, {"speaker-a": SpeakerStatus("2026-11-06T10:00:00+00:00", True)})
    assert load_status(path)["speaker-a"].online is True
    assert oct(path.stat().st_mode & 0o777) == "0o600"
