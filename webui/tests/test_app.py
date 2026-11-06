from __future__ import annotations

import json
import subprocess

import pytest

from webui.app import create_app
from webui.settings import load_settings


def test_healthz_is_public(tmp_path):
    app = create_app(load_settings(root=tmp_path, env={}))
    client = app.test_client()
    payload = client.get("/healthz").get_json()
    assert payload["status"] == "ok"
    assert payload["version"] == "2.1.0"


def test_speaker_page_shows_full_identifiers(client, login):
    login()
    response = client.get("/speakers/speaker-a")
    body = response.get_data(as_text=True)
    assert "EXAMPLE000000000000000000000001" in body
    assert "02:00:00:00:00:01" in body


def test_speaker_action_creates_job(client, app, login, csrf):
    login()
    app.extensions["jobs"] = FakeRunner()
    response = client.post(
        "/speakers/speaker-a/actions/status",
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert response.status_code == 303
    assert "/jobs/" in response.headers["Location"]


def test_unknown_speaker_returns_404(client, login):
    login()
    assert client.get("/speakers/nope").status_code == 404


def test_speaker_page_has_say_dialog(client, login, csrf):
    login()
    client.post("/mode", data={"mode": "advanced", "next": "/"},
                headers={"X-CSRF-Token": csrf(client)})
    body = client.get("/speakers/speaker-a").get_data(as_text=True)
    assert "Сказать" in body
    assert 'action="/speakers/speaker-a/say"' in body


def test_say_creates_job_with_text(client, app, login, csrf):
    login()
    runner = FakeRunner()
    app.extensions["jobs"] = runner
    response = client.post(
        "/speakers/speaker-a/say",
        data={"text": "Приятного аппетита"},
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert response.status_code == 303
    assert "/jobs/" in response.headers["Location"]
    action, target, argv, env = runner.commands[0]
    assert action == "say"
    assert target == "speaker-a"
    assert argv == ["bash", "scripts/say-text.sh"]
    assert env["SAY_TEXT"] == "Приятного аппетита"
    assert env["SPEAKER_TRUST_IP"] == "1"


def test_say_rejects_empty_text(client, app, login, csrf):
    login()
    response = client.post(
        "/speakers/speaker-a/say",
        data={"text": "   "},
        headers={"X-CSRF-Token": csrf(client)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Введите текст" in response.get_data(as_text=True)


class FakeRunner:
    def __init__(self):
        self.actions = []
        self.commands = []

    def submit(self, action, profile):
        from types import SimpleNamespace

        self.actions.append((action, profile))
        return SimpleNamespace(id="job-1")

    def submit_command(self, action, target, argv, env):
        from types import SimpleNamespace

        self.commands.append((action, target, argv, env))
        return SimpleNamespace(id="job-2")


def write_router_config(path, name="speaker-a"):
    secrets = path.parent
    secrets.mkdir(parents=True, exist_ok=True)
    (secrets / f"router-token-{name}").write_text("sk-router-test\n", encoding="utf-8")
    path.write_text(
        json.dumps(
            {
                "response": {"max_sentences": 3, "max_chars": 400},
                "routes": [
                    {
                        "name": name,
                        "token_file": f"router-token-{name}",
                        "session": {
                            "mode": "server",
                            "user": "voice",
                            "idle_minutes": 30,
                            "cleanup_keep": 3,
                        },
                        "primary": {
                            "base_url": "http://127.0.0.1:5000/v1",
                            "api_key_file": f"flai-token-{name}",
                            "model": "flai-chat",
                            "history": "server",
                        },
                        "fallback": None,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def fake_router_http(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"status":"ok","routes":[{"name":"speaker-a","available":true}]}'

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: Response(),
    )


def test_router_health_returns_routes(client, login, fake_router_http):
    login()
    payload = client.get("/router/health").get_json()
    assert payload["routes"][0]["name"] == "speaker-a"


def test_route_edit_rejects_invalid_model(client, app, login, csrf):
    login()
    path = write_router_config(app.config["WEBUI_SETTINGS"].router_config)
    before = path.read_text(encoding="utf-8")
    response = client.post(
        "/router/routes/speaker-a",
        data={"model": ""},
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert response.status_code == 400
    assert path.read_text(encoding="utf-8") == before


def test_router_restart_submits_host_job(client, app, login, csrf):
    login()
    runner = FakeRunner()
    app.extensions["jobs"] = runner
    response = client.post(
        "/router/restart",
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert response.status_code == 303
    assert runner.actions == [("router-restart", None)]


def test_route_edit_saves_valid_route(client, app, login, csrf):
    login()
    path = write_router_config(app.config["WEBUI_SETTINGS"].router_config)
    response = client.post(
        "/router/routes/speaker-a",
        data={
            "token_file": "router-token-speaker-a",
            "base_url": "http://127.0.0.1:5000/v1",
            "api_key_file": "flai-token-speaker-a",
            "model": "new-model",
            "history": "server",
            "timeout_seconds": "180",
        },
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert response.status_code == 302
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["routes"][0]["primary"]["model"] == "new-model"


def test_rotated_token_is_shown_once(client, app, login, csrf):
    login()
    write_router_config(app.config["WEBUI_SETTINGS"].router_config)
    response = client.post(
        "/keys/router/speaker-a/rotate",
        headers={"X-CSRF-Token": csrf(client)},
        follow_redirects=True,
    )
    assert "sk-router-" in response.get_data(as_text=True)
    assert "sk-router-" not in client.get("/access").get_data(as_text=True)


def test_rotation_writes_new_token_to_speaker(
    client, app, login, csrf, tmp_path
):
    login()
    write_router_config(app.config["WEBUI_SETTINGS"].router_config)
    profile_path = tmp_path / "local" / "speakers" / "speaker-a.env"
    profile_path.write_text(
        profile_path.read_text(encoding="utf-8")
        + "LLM_TOKEN_FILE=secrets/router-token-speaker-a\n",
        encoding="utf-8",
    )
    runner = FakeRunner()
    app.extensions["jobs"] = runner
    response = client.post(
        "/keys/router/speaker-a/rotate",
        headers={"X-CSRF-Token": csrf(client)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert [action for action, _ in runner.actions] == ["key"]
    assert runner.actions[0][1].name == "speaker-a"
    body = response.get_data(as_text=True)
    assert "Запись в колонку speaker-a запущена" in body
    assert "/jobs/job-1" in body


def test_upstream_key_is_not_rendered(client, app, login, csrf):
    login()
    write_router_config(app.config["WEBUI_SETTINGS"].router_config)
    client.post(
        "/keys/upstream/flai-token-speaker-a",
        data={"value": "flai-very-secret"},
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert "flai-very-secret" not in client.get("/access").get_data(as_text=True)
    assert "flai-very-secret" not in client.get(
        "/audit", follow_redirects=True
    ).get_data(as_text=True)


def test_upstream_key_can_be_added_from_keys_page(client, app, login, csrf):
    login()
    response = client.post(
        "/keys/upstream",
        data={
            "file": "orca-token-free",
            "value": "orca-secret",
        },
        headers={"X-CSRF-Token": csrf(client)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "orca-token-free" in body
    assert "orca-secret" not in body
    path = app.config["WEBUI_SETTINGS"].secrets_dir / "orca-token-free"
    assert path.read_text(encoding="utf-8").strip() == "orca-secret"
    assert path.stat().st_mode & 0o777 == 0o600


def test_route_form_lists_existing_upstream_keys(client, app, login, csrf):
    login()
    client.post(
        "/keys/upstream",
        data={"file": "orca-token-free", "value": "x"},
        headers={"X-CSRF-Token": csrf(client)},
    )
    body = client.get("/router/routes/new").get_data(as_text=True)
    assert 'name="api_key_file"' in body
    assert '<option value="orca-token-free"' in body


def test_used_upstream_key_cannot_be_deleted(client, app, login, csrf):
    login()
    write_router_config(app.config["WEBUI_SETTINGS"].router_config)
    path = app.config["WEBUI_SETTINGS"].secrets_dir / "flai-token-speaker-a"
    path.write_text("key\n", encoding="utf-8")
    client.post(
        "/keys/upstream/flai-token-speaker-a/delete",
        headers={"X-CSRF-Token": csrf(client)},
        follow_redirects=True,
    )
    assert path.exists()
    assert "flai-token-speaker-a" in client.get("/access").get_data(as_text=True)


def test_audit_page_lists_login(client, login):
    login()
    body = client.get("/audit", follow_redirects=True).get_data(as_text=True)
    assert "auth.login" in body


def test_route_edit_rejects_path_in_api_key_file(client, app, login, csrf):
    login()
    path = write_router_config(app.config["WEBUI_SETTINGS"].router_config)
    before = path.read_text(encoding="utf-8")
    response = client.post(
        "/router/routes/speaker-a",
        data={
            "token_file": "router-token-speaker-a",
            "base_url": "http://127.0.0.1:5000/v1",
            "api_key_file": "../../etc/passwd",
            "model": "flai-chat",
            "history": "server",
            "timeout_seconds": "180",
        },
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert response.status_code == 400
    assert path.read_text(encoding="utf-8") == before


class EchoBuilder:
    def __init__(self, command):
        self.command = command

    def build(self, action, profile):
        return ["bash", "-c", self.command], {}


def test_job_log_redacts_secret(client, app, login):
    from webui.jobs import JobRunner

    login()
    settings = app.config["WEBUI_SETTINGS"]
    secret = "super-secret-value-that-is-long"
    settings.secrets_dir.mkdir(parents=True, exist_ok=True)
    (settings.secrets_dir / "flai-token-speaker-a").write_text(
        secret, encoding="utf-8"
    )
    runner = JobRunner(
        settings.state_dir,
        EchoBuilder(f"echo {secret}"),
    )
    app.extensions["jobs"] = runner
    job = runner.submit("status", app.extensions["profiles"]["speaker-a"])
    runner.wait(job.id, timeout=5)
    body = client.get(f"/jobs/{job.id}").get_data(as_text=True)
    assert secret not in body
    assert "***" in body


def test_backup_page_requires_login(client):
    assert client.get("/backup").status_code == 302


def test_backup_create_and_download(client, app, login, csrf):
    from webui.backup import list_backups

    login()
    response = client.post(
        "/backup/create",
        data={
            "scope": "all",
            "passphrase": "correct horse",
            "confirm": "correct horse",
        },
        headers={"X-CSRF-Token": csrf(client)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert ".tar.gz.enc" in response.get_data(as_text=True)

    settings = app.config["WEBUI_SETTINGS"]
    name = list_backups(settings)[0].name
    download = client.get(f"/backup/download/{name}")
    assert download.status_code == 200
    assert download.headers["Cache-Control"] == "no-store"


def test_backup_restore_requires_replace(client, app, login, csrf):
    from webui.backup import list_backups

    login()
    profile = app.config["WEBUI_SETTINGS"].root / "local" / "speakers" / "speaker-a.env"
    original = profile.read_text(encoding="utf-8")
    client.post(
        "/backup/create",
        data={
            "scope": "all",
            "passphrase": "correct horse",
            "confirm": "correct horse",
        },
        headers={"X-CSRF-Token": csrf(client)},
    )
    profile.write_text("CHANGED\n", encoding="utf-8")
    name = list_backups(app.config["WEBUI_SETTINGS"])[0].name
    response = client.post(
        "/backup/restore",
        data={
            "backup": name,
            "passphrase": "correct horse",
            "confirm": "",
        },
        headers={"X-CSRF-Token": csrf(client)},
        follow_redirects=True,
    )
    assert "REPLACE" in response.get_data(as_text=True)
    assert profile.read_text(encoding="utf-8") == "CHANGED\n"
    profile.write_text(original, encoding="utf-8")


def test_backup_restore_all_from_stored_archive(client, app, login, csrf):
    from webui.backup import list_backups

    login()
    settings = app.config["WEBUI_SETTINGS"]
    profile = settings.root / "local" / "speakers" / "speaker-a.env"
    original = profile.read_text(encoding="utf-8")
    client.post(
        "/backup/create",
        data={
            "scope": "all",
            "passphrase": "correct horse",
            "confirm": "correct horse",
        },
        headers={"X-CSRF-Token": csrf(client)},
    )
    name = list_backups(settings)[0].name
    profile.write_text("CHANGED\n", encoding="utf-8")
    response = client.post(
        "/backup/restore",
        data={
            "backup": name,
            "passphrase": "correct horse",
            "confirm": "REPLACE",
        },
        headers={"X-CSRF-Token": csrf(client)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert profile.read_text(encoding="utf-8") == original


def test_change_password_rejects_wrong_current(client, login, csrf):
    login()
    response = client.post(
        "/password",
        data={
            "current": "wrong",
            "new": "new correct horse",
            "confirm": "new correct horse",
        },
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert response.status_code == 400


def test_change_password_updates_login(client, login, csrf):
    login()
    response = client.post(
        "/password",
        data={
            "current": "correct horse",
            "new": "new correct horse",
            "confirm": "new correct horse",
        },
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    client.get("/login")
    old = client.post(
        "/login",
        data={
            "password": "correct horse",
            "csrf_token": csrf(client),
        },
    )
    assert old.status_code == 401

    client.get("/login")
    new = client.post(
        "/login",
        data={
            "password": "new correct horse",
            "csrf_token": csrf(client),
        },
    )
    assert new.status_code == 302


def test_speaker_page_shows_model_and_color(client, login):
    login()
    body = client.get("/speakers/speaker-a").get_data(as_text=True)
    assert "Яндекс Станция Лайт" in body
    assert "Комната A" in body
    assert "speaker-icon" in body
    assert 'viewBox="0 0 64 58"' in body


def test_speaker_appearance_updates_color_and_model(client, app, login, csrf):
    login()
    response = client.post(
        "/speakers/speaker-a/appearance",
        data={"color": "green", "model": "Yandex Station Micro v1.2"},
        headers={"X-CSRF-Token": csrf(client)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "#22c1c3" in body
    assert "Yandex Station Micro v1.2" in body


def test_speakers_page_has_logout_and_tabs(client, login):
    login()
    body = client.get("/").get_data(as_text=True)
    assert "Выйти" in body
    assert "topbar" in body
    assert "Администратор" in body


def test_login_redirects_authenticated_user(client, login):
    login()
    response = client.get("/login")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_home_lists_speaker_cards(client, login):
    login()
    body = client.get("/").get_data(as_text=True)
    assert "speaker-a" in body
    assert "Комната A" in body
    assert 'href="/access"' in body
    assert 'href="/test"' in body
    assert 'href="/more"' in body


def test_legacy_speakers_url_redirects(client, login):
    login()
    response = client.get("/speakers")
    assert response.status_code == 301
    assert response.headers["Location"].endswith("/")


def test_home_search_filters_cards(client, login):
    login()
    assert "speaker-a" in client.get("/?q=02:00").get_data(as_text=True)
    assert "speaker-a" not in client.get("/?q=zzz").get_data(as_text=True)


def test_home_shows_cached_status(client, app, login):
    from webui.status import save_status, SpeakerStatus

    login()
    settings = app.config["WEBUI_SETTINGS"]
    save_status(
        settings.state_dir / "speaker-status.json",
        {"speaker-a": SpeakerStatus("2026-11-06T10:00:00+00:00", True, False)},
    )
    body = client.get("/").get_data(as_text=True)
    assert "онлайн" in body
    assert "Bridge не отвечает" in body
    assert 'class="status ok"' in body


def test_home_shows_offline_status(client, app, login):
    from webui.status import save_status, SpeakerStatus

    login()
    settings = app.config["WEBUI_SETTINGS"]
    save_status(
        settings.state_dir / "speaker-status.json",
        {"speaker-a": SpeakerStatus("2026-11-06T10:00:00+00:00", False)},
    )
    body = client.get("/").get_data(as_text=True)
    assert "не в сети" in body
    assert 'class="status bad"' in body


def test_home_shows_unknown_status_when_no_record(client, login):
    login()
    body = client.get("/").get_data(as_text=True)
    assert "не проверялась" in body
    assert 'class="status unknown"' in body


def test_speaker_page_shows_cached_status(client, app, login):
    from webui.status import save_status, SpeakerStatus

    login()
    settings = app.config["WEBUI_SETTINGS"]
    save_status(
        settings.state_dir / "speaker-status.json",
        {"speaker-a": SpeakerStatus("2026-11-06T10:00:00+00:00", True, False)},
    )
    body = client.get("/speakers/speaker-a").get_data(as_text=True)
    assert "онлайн" in body
    assert "Bridge не отвечает" in body
    assert 'class="status ok"' in body


def test_mode_switch_sets_cookie(client, login, csrf):
    login()
    response = client.post(
        "/mode", data={"mode": "advanced"}, headers={"X-CSRF-Token": csrf(client)}
    )
    assert response.status_code == 303
    assert response.headers["Set-Cookie"].startswith("ui_mode=advanced")


def test_advanced_nav_is_hidden_in_simple_mode(client, login):
    login()
    assert 'href="/advanced"' not in client.get("/").get_data(as_text=True)


def test_create_route_generates_token(client, app, login, csrf):
    login()
    path = write_router_config(app.config["WEBUI_SETTINGS"].router_config)
    response = client.post(
        "/router/routes/new",
        data={
            "name": "speaker-b",
            "base_url": "http://127.0.0.1:5000/v1",
            "api_key_file": "flai-token-speaker-b",
            "model": "flai-chat",
            "history": "server",
            "timeout_seconds": "180",
        },
        headers={"X-CSRF-Token": csrf(client)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    saved = json.loads(path.read_text(encoding="utf-8"))
    names = {route["name"] for route in saved["routes"]}
    assert names == {"speaker-a", "speaker-b"}
    token_file = app.config["WEBUI_SETTINGS"].secrets_dir / "router-token-speaker-b"
    assert token_file.exists()
    assert "sk-router-" in response.get_data(as_text=True)


def test_fallback_is_added_edited_and_deleted(client, app, login, csrf):
    login()
    path = write_router_config(app.config["WEBUI_SETTINGS"].router_config)
    form = {
        "base_url": "https://api.orcarouter.ai/v1",
        "api_key_file": "orca-token-speaker-a",
        "model": "orcarouter/free",
        "history": "client",
        "timeout_seconds": "180",
    }
    response = client.post(
        "/router/routes/speaker-a/fallback/new",
        data=form,
        headers={"X-CSRF-Token": csrf(client)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "запасной 1" in body

    saved = json.loads(path.read_text(encoding="utf-8"))
    route = saved["routes"][0]
    assert len(route["fallbacks"]) == 1
    assert "fallback" not in route

    edited = dict(form, model="orcarouter/other")
    client.post(
        "/router/routes/speaker-a/fallback/0",
        data=edited,
        headers={"X-CSRF-Token": csrf(client)},
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["routes"][0]["fallbacks"][0]["model"] == "orcarouter/other"

    client.post(
        "/router/routes/speaker-a/fallback/0/delete",
        headers={"X-CSRF-Token": csrf(client)},
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["routes"][0]["fallbacks"] == []


def test_project_title_in_login_and_admin(client, login):
    login_page = client.get("/login").get_data(as_text=True)
    assert "Моя Яндекс Станция" in login_page
    login()
    admin_page = client.get("/").get_data(as_text=True)
    assert "Колонки — Моя Яндекс Станция" in admin_page
    assert "Моя Яндекс Станция" in admin_page


def test_firmware_page_requires_login(client):
    assert client.get("/firmware").status_code == 302


def test_firmware_page_lists_files_and_actions(client, app, login):
    login()
    fw_dir = (
        app.config["WEBUI_SETTINGS"].root
        / "vendor"
        / "lite-kit"
        / "firmware"
        / "yandexmicro"
    )
    fw_dir.mkdir(parents=True)
    (fw_dir / "test-firmware.zip").write_bytes(b"x")
    response = client.get("/firmware", follow_redirects=True)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Прошивка" in body
    assert "Скачать прошивку" in body
    assert "test-firmware.zip" in body
    assert "Запустить стенд" in body
    assert "Подготовьте хост" in body


def test_firmware_download_submits_host_job(client, app, login, csrf):
    login()
    runner = FakeRunner()
    app.extensions["jobs"] = runner
    response = client.post(
        "/firmware/actions/firmware",
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert response.status_code == 303
    assert "/jobs/" in response.headers["Location"]
    assert runner.actions == [("firmware", None)]


def test_running_job_page_auto_refreshes(client, app, login):
    from pathlib import Path
    from types import SimpleNamespace

    login()
    job = SimpleNamespace(
        id="job-1",
        action="stand-status",
        target="host",
        status="running",
        exit_code=None,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at=None,
        created_at="2026-01-01T00:00:00+00:00",
        log_path=Path("/tmp/job.log"),
    )

    class Runner:
        def get(self, job_id):
            return job

        def tail(self, job_id, offset=0):
            return "working", 7

    app.extensions["jobs"] = Runner()
    body = client.get("/jobs/job-1").get_data(as_text=True)
    assert 'http-equiv="refresh"' in body
    assert "working" in body

    job.status = "succeeded"
    body = client.get("/jobs/job-1").get_data(as_text=True)
    assert 'http-equiv="refresh"' not in body


def test_fallback_limit_is_nine(client, app, login, csrf):
    login()
    path = write_router_config(app.config["WEBUI_SETTINGS"].router_config)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["routes"][0]["fallbacks"] = [
        {
            "base_url": f"https://api{i}.example/v1",
            "api_key_file": "fallback-token-speaker-a",
            "model": f"m{i}",
            "history": "client",
        }
        for i in range(9)
    ]
    path.write_text(json.dumps(data), encoding="utf-8")

    response = client.post(
        "/router/routes/speaker-a/fallback/new",
        data={
            "base_url": "https://api-extra.example/v1",
            "api_key_file": "fallback-token-speaker-a",
            "model": "extra",
            "history": "client",
        },
        headers={"X-CSRF-Token": csrf(client)},
        follow_redirects=True,
    )
    assert "лимит 9" in response.get_data(as_text=True)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert len(saved["routes"][0]["fallbacks"]) == 9


def test_fallback_order_can_be_changed(client, app, login, csrf):
    login()
    path = write_router_config(app.config["WEBUI_SETTINGS"].router_config)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["routes"][0]["fallbacks"] = [
        {
            "base_url": f"https://api{i}.example/v1",
            "api_key_file": "fallback-token-speaker-a",
            "model": f"m{i}",
            "history": "client",
        }
        for i in range(2)
    ]
    path.write_text(json.dumps(data), encoding="utf-8")

    client.post(
        "/router/routes/speaker-a/fallback/0/move",
        data={"direction": "down"},
        headers={"X-CSRF-Token": csrf(client)},
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert [item["model"] for item in saved["routes"][0]["fallbacks"]] == ["m1", "m0"]

    client.post(
        "/router/routes/speaker-a/fallback/1/move",
        data={"direction": "up"},
        headers={"X-CSRF-Token": csrf(client)},
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert [item["model"] for item in saved["routes"][0]["fallbacks"]] == ["m0", "m1"]


def test_router_probe_shows_colored_upstream_status(client, app, login, monkeypatch):
    login()
    write_router_config(app.config["WEBUI_SETTINGS"].router_config)

    class Response:
        def __init__(self, payload):
            self.payload = payload
            self.status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    ok_payload = {
        "status": "ok",
        "routes": [
            {
                "name": "speaker-a",
                "available": True,
                "primary": {"state": "ok", "http": 200},
                "fallbacks": [],
            }
        ],
    }
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *args, **kwargs: Response(ok_payload)
    )
    body = client.get("/access?probe=1").get_data(as_text=True)
    assert "health-ok" in body
    assert "ok · HTTP 200" in body

    error_payload = {
        "status": "ok",
        "routes": [
            {
                "name": "speaker-a",
                "available": False,
                "primary": {"state": "unreachable"},
                "fallbacks": [],
            }
        ],
    }
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *args, **kwargs: Response(error_payload)
    )
    body = client.get("/access?probe=1").get_data(as_text=True)
    assert "health-err" in body
    assert "недоступен" in body


def test_primary_and_first_fallback_can_swap(client, app, login, csrf):
    login()
    path = write_router_config(app.config["WEBUI_SETTINGS"].router_config)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["routes"][0]["primary"]["model"] = "primary-model"
    data["routes"][0]["fallbacks"] = [
        {
            "base_url": "https://api0.example/v1",
            "api_key_file": "fallback-token-speaker-a",
            "model": "fallback-model",
            "history": "client",
        }
    ]
    path.write_text(json.dumps(data), encoding="utf-8")

    client.post(
        "/router/routes/speaker-a/primary/move",
        data={"direction": "down"},
        headers={"X-CSRF-Token": csrf(client)},
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    route = saved["routes"][0]
    assert route["primary"]["model"] == "fallback-model"
    assert route["fallbacks"][0]["model"] == "primary-model"

    client.post(
        "/router/routes/speaker-a/fallback/0/move",
        data={"direction": "up"},
        headers={"X-CSRF-Token": csrf(client)},
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    route = saved["routes"][0]
    assert route["primary"]["model"] == "primary-model"
    assert route["fallbacks"][0]["model"] == "fallback-model"


def test_reorder_returns_to_the_route_anchor(client, app, login, csrf):
    login()
    path = write_router_config(app.config["WEBUI_SETTINGS"].router_config)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["routes"][0]["fallbacks"] = [
        {
            "base_url": f"https://api{i}.example/v1",
            "api_key_file": "fallback-token-speaker-a",
            "model": f"m{i}",
            "history": "client",
        }
        for i in range(2)
    ]
    path.write_text(json.dumps(data), encoding="utf-8")

    response = client.post(
        "/router/routes/speaker-a/fallback/0/move",
        data={"direction": "down"},
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("#route-speaker-a-fallback-1")

    response = client.post(
        "/router/routes/speaker-a/primary/move",
        data={"direction": "down"},
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("#route-speaker-a")

    body = client.get("/access").get_data(as_text=True)
    assert 'id="route-speaker-a"' in body
    assert 'id="route-speaker-a-fallback-0"' in body


def test_create_profile_from_panel(client, login, csrf, settings):
    login()
    response = client.post("/speakers/new", headers={"X-CSRF-Token": csrf(client)}, data={
        "name": "speaker-z", "ip": "192.168.1.150", "subnet": "192.168.1",
        "mac": "02:00:00:00:00:99",
        "device_id": "EXAMPLE000000000000000000000099",
        "room": "Комната Z", "color": "blue",
        "model": "Яндекс Станция Лайт",
    })
    assert response.status_code == 303
    assert (settings.speakers_dir / "speaker-z.env").is_file()
    assert client.get("/speakers/speaker-z").status_code == 200


def test_create_profile_rejects_bad_name(client, login, csrf, settings):
    login()
    response = client.post("/speakers/new", headers={"X-CSRF-Token": csrf(client)},
                           data={"name": "../evil", "ip": "192.168.1.150",
                                 "subnet": "192.168.1", "mac": "02:00:00:00:00:99",
                                 "device_id": "EXAMPLE000000000000000000000099"})
    assert response.status_code == 400
    assert not (settings.speakers_dir / "evil.env").exists()
    assert not (settings.state_dir / "deleted-profiles").exists()


def test_delete_profile_requires_name_confirm(client, login, csrf, settings):
    login()
    response = client.post("/speakers/speaker-a/delete", headers={"X-CSRF-Token": csrf(client)},
                           data={"confirm": "wrong"})
    assert response.status_code == 400
    assert (settings.speakers_dir / "speaker-a.env").exists()
    response = client.post("/speakers/speaker-a/delete", headers={"X-CSRF-Token": csrf(client)},
                           data={"confirm": "speaker-a"})
    assert response.status_code == 303
    assert not (settings.speakers_dir / "speaker-a.env").exists()
    assert (settings.state_dir / "deleted-profiles").exists()


def test_delete_profile_moves_appearance_to_trash(client, login, csrf, settings):
    from webui.appearance import save_override

    login()
    app_settings = settings
    appearance_path = app_settings.state_dir / "speaker-appearance.json"
    save_override(appearance_path, "EXAMPLE000000000000000000000001", "green", "Custom Model")
    response = client.post(
        "/speakers/speaker-a/delete",
        headers={"X-CSRF-Token": csrf(client)},
        data={"confirm": "speaker-a"},
    )
    assert response.status_code == 303
    trash = list((settings.state_dir / "deleted-profiles").glob("*"))
    assert len(trash) == 1
    appearance_json = trash[0] / "appearance.json"
    assert appearance_json.is_file()
    assert "green" in appearance_json.read_text(encoding="utf-8")


def test_create_profile_rejects_injection_in_room(client, login, csrf, settings):
    login()
    response = client.post("/speakers/new", headers={"X-CSRF-Token": csrf(client)}, data={
        "name": "speaker-z", "ip": "192.168.1.150", "subnet": "192.168.1",
        "mac": "02:00:00:00:00:99",
        "device_id": "EXAMPLE000000000000000000000099",
        "room": "Комната\nZ", "color": "blue",
        "model": "Яндекс Станция Лайт",
    })
    assert response.status_code == 400
    assert not (settings.speakers_dir / "speaker-z.env").exists()


def test_create_profile_rejects_invalid_color(client, login, csrf, settings):
    login()
    response = client.post("/speakers/new", headers={"X-CSRF-Token": csrf(client)}, data={
        "name": "speaker-z", "ip": "192.168.1.150", "subnet": "192.168.1",
        "mac": "02:00:00:00:00:99",
        "device_id": "EXAMPLE000000000000000000000099",
        "room": "Комната Z", "color": "not-a-color",
        "model": "Яндекс Станция Лайт",
    })
    assert response.status_code == 400
    assert not (settings.speakers_dir / "speaker-z.env").exists()


def test_scan_lists_found_speaker(client, login, monkeypatch):
    from webui.discovery import Discovered
    login()
    monkeypatch.setattr("webui.app.scan", lambda subnet: [Discovered(
        "192.168.1.150", "02:00:00:00:00:99",
        "EXAMPLE000000000000000000000099", "Яндекс Станция Лайт",
        "yandexmicro-EXAMPLE000000000000000000000099")])
    body = client.get("/speakers/new?scan=1").get_data(as_text=True)
    assert "192.168.1.150" in body


def test_speaker_new_without_scan_skips_discovery(client, login, monkeypatch):
    login()

    def boom(subnet):
        raise AssertionError("scan не должен запускаться без ?scan=1")

    monkeypatch.setattr("webui.app.scan", boom)
    assert client.get("/speakers/new").status_code == 200


def test_speaker_new_scan_shows_subnet_error(client, login, monkeypatch):
    login()

    def bad(subnet):
        raise ValueError("Нужна приватная сеть не больше 254 адресов")

    monkeypatch.setattr("webui.app.scan", bad)
    body = client.get("/speakers/new?scan=1&subnet=10.0.0.0/16").get_data(as_text=True)
    assert "Нужна приватная сеть" in body


def test_scan_marks_hosts_without_adb(client, login, monkeypatch):
    from webui.discovery import Discovered
    login()
    monkeypatch.setattr("webui.app.scan", lambda subnet: [Discovered(
        "192.168.1.152", "", "", "", "")])
    body = client.get("/speakers/new?scan=1").get_data(as_text=True)
    assert "192.168.1.152 — ADB недоступен, заполните поля вручную" in body
    assert "Это моя колонка" not in body


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(subprocess.TimeoutExpired(["adb"], 5), id="timeout"),
        pytest.param(FileNotFoundError("adb"), id="missing-adb"),
    ],
)
def test_scan_page_survives_runner_failure(client, login, monkeypatch, exc):
    from webui.discovery import scan as real_scan
    login()

    def boom(argv):
        raise exc

    monkeypatch.setattr("webui.app.scan", lambda subnet: real_scan(subnet, runner=boom))
    response = client.get("/speakers/new?scan=1&subnet=192.168.1.0/30")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "192.168.1.1 — ADB недоступен, заполните поля вручную" in body


def test_scan_page_shows_russian_error_for_bad_subnet(client, login):
    login()
    response = client.get("/speakers/new?scan=1&subnet=192.168.1.500")
    assert response.status_code == 200
    assert "Некорректная подсеть" in response.get_data(as_text=True)


def test_access_page_lists_upstream_keys(client, app, login, csrf, settings):
    login()
    client.post(
        "/keys/upstream",
        data={"file": "orca-token-free", "value": "orca-secret"},
        headers={"X-CSRF-Token": csrf(client)},
    )
    body = client.get("/access").get_data(as_text=True)
    assert "orca-token-free" in body
    assert "orca-secret" not in body


def test_provider_probe_rejects_arbitrary_file(client, app, login, csrf, settings, monkeypatch):
    from webui.providers import Provider, save_providers
    login()
    save_providers(settings.state_dir / "providers.json",
                   [Provider("flai", "FLAI", "http://10.0.0.2:5000/v1", ("m",))])
    (settings.secrets_dir / "secret-file").write_text("leaked-secret", encoding="utf-8")
    captured = {}
    def capture(base_url, api_key, **kwargs):
        captured["key"] = api_key
        return []
    monkeypatch.setattr("webui.app.fetch_models", capture)
    response = client.post(
        "/access/providers/flai/probe",
        data={"api_key_file": "secret-file"},
        headers={"X-CSRF-Token": csrf(client)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert captured.get("key") is None


def test_simple_fallback_preserves_timeout(client, app, login, csrf, settings):
    from webui.providers import Provider, save_providers
    login()
    save_providers(settings.state_dir / "providers.json",
                   [Provider("fb", "Fallback", "http://10.0.0.3:5000/v1", ("fallback-model",))])
    write_router_config(settings.router_config)
    response = client.post(
        "/router/routes/speaker-a/fallback/new",
        headers={"X-CSRF-Token": csrf(client)},
        data={
            "provider_id": "fb", "model": "fallback-model",
            "api_key_file": "fallback-token-speaker-a",
            "timeout_seconds": "77", "history": "client",
        },
    )
    assert response.status_code == 302
    saved = json.loads(settings.router_config.read_text(encoding="utf-8"))["routes"][0]
    assert saved["fallbacks"][0]["timeout_seconds"] == 77


def test_provider_create_rejects_duplicate_slug(client, login, csrf, settings):
    from webui.providers import load_providers
    login()
    response = client.post(
        "/access/providers/new",
        headers={"X-CSRF-Token": csrf(client)},
        data={"name": "Alpha", "base_url": "http://10.0.0.2:5000/v1", "models": "m1"},
    )
    assert response.status_code == 302
    response = client.post(
        "/access/providers/new",
        headers={"X-CSRF-Token": csrf(client)},
        data={"name": "Alpha", "base_url": "http://10.0.0.3:5000/v1", "models": "m2"},
    )
    assert response.status_code == 400
    providers = load_providers(settings.state_dir / "providers.json", [])
    assert len(providers) == 1
    assert providers[0].base_url == "http://10.0.0.2:5000/v1"


def test_route_list_has_write_key_button(client, app, login, csrf, settings):
    login()
    write_router_config(settings.router_config)
    body = client.get("/access").get_data(as_text=True)
    assert 'action="/access/routes/speaker-a/write-key"' in body
    assert "Записать ключ в колонку" in body


def test_access_page_has_three_sections(client, login):
    login()
    body = client.get("/access").get_data(as_text=True)
    for anchor in ('id="providers"', 'id="keys"', 'id="routes"'):
        assert anchor in body


def test_legacy_router_and_keys_redirect(client, login):
    login()
    assert client.get("/router").status_code == 301
    assert client.get("/keys").status_code == 301


def test_route_from_provider_renders_token_once(client, app, login, csrf, settings):
    from webui.providers import Provider, save_providers
    login()
    save_providers(settings.state_dir / "providers.json",
                   [Provider("flai", "FLAI", "http://10.0.0.2:5000/v1", ("flai-chat",))])
    response = client.post("/router/routes/new", headers={"X-CSRF-Token": csrf(client)}, data={
        "name": "speaker-a", "provider_id": "flai", "model": "flai-chat",
        "api_key_file": "flai-token-speaker-a",
    })
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "sk-router-" in body
    config = json.loads(settings.router_config.read_text(encoding="utf-8"))
    primary = config["routes"][0]["primary"]
    assert primary["base_url"] == "http://10.0.0.2:5000/v1"
    assert "sk-router-" not in client.get("/access").get_data(as_text=True)


def test_simple_route_form_hides_technical_fields_and_preserves_them(
        client, app, login, csrf, settings):
    from webui.providers import Provider, save_providers
    login()
    save_providers(settings.state_dir / "providers.json",
                   [Provider("local", "Local", "http://127.0.0.1:5000/v1", ("flai-chat", "new-model"))])
    write_router_config(settings.router_config)
    raw = json.loads(settings.router_config.read_text(encoding="utf-8"))
    raw["routes"][0]["session"]["idle_minutes"] = 45
    raw["routes"][0]["primary"]["timeout_seconds"] = 99
    raw["routes"][0]["primary"]["history"] = "client"
    raw["routes"][0]["fallbacks"] = [{
        "base_url": "http://10.0.0.3:5000/v1",
        "api_key_file": "fallback-token-speaker-a",
        "model": "fallback-model",
        "history": "client",
        "timeout_seconds": 60,
    }]
    settings.router_config.write_text(json.dumps(raw), encoding="utf-8")
    body = client.get("/access/routes/speaker-a").get_data(as_text=True)
    assert "Таймаут" not in body
    assert "token_file" not in body
    assert 'type="hidden" name="timeout_seconds"' in body
    response = client.post(
        "/router/routes/speaker-a",
        headers={"X-CSRF-Token": csrf(client)},
        data={
            "provider_id": "local", "model": "new-model",
            "api_key_file": "flai-token-speaker-a",
            "timeout_seconds": "99", "history": "client",
        },
    )
    assert response.status_code == 302
    saved = json.loads(settings.router_config.read_text(encoding="utf-8"))["routes"][0]
    assert saved["session"]["idle_minutes"] == 45
    assert saved["primary"]["timeout_seconds"] == 99
    assert saved["primary"]["history"] == "client"
    assert saved["primary"]["model"] == "new-model"
    assert saved["primary"]["api_key_file"] == "flai-token-speaker-a"
    assert saved["fallbacks"][0]["model"] == "fallback-model"
