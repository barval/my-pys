from __future__ import annotations

from webui.stand_control import run_action


def test_status_uses_docker_ps(monkeypatch, tmp_path):
    calls = {}

    class Result:
        returncode = 0
        stdout = "Up 2 minutes\n"
        stderr = ""

    def fake_run(argv, **kwargs):
        calls["argv"] = argv
        calls["cwd"] = kwargs.get("cwd")
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    status, payload = run_action("status", repo=tmp_path)
    assert status == 200
    assert payload["running"] is True
    assert calls["argv"][:2] == ["docker", "ps"]
    assert calls["cwd"] == str(tmp_path)


def test_start_requires_host_repo(monkeypatch, tmp_path):
    monkeypatch.delenv("HOST_REPO_PATH", raising=False)
    status, payload = run_action("start", repo=tmp_path)
    assert status == 500
    assert "HOST_REPO_PATH" in payload["error"]
