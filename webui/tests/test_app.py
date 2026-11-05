from __future__ import annotations

import json

import pytest

from webui.app import create_app
from webui.settings import load_settings


def test_healthz_is_public(tmp_path):
    app = create_app(load_settings(root=tmp_path, env={}))
    client = app.test_client()
    payload = client.get("/healthz").get_json()
    assert payload["status"] == "ok"
    assert payload["version"] == "2.0.0"


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


class FakeRunner:
    def __init__(self):
        self.actions = []

    def submit(self, action, profile):
        from types import SimpleNamespace

        self.actions.append((action, profile))
        return SimpleNamespace(id="job-1")


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
    assert "sk-router-" not in client.get("/keys").get_data(as_text=True)


def test_upstream_key_is_not_rendered(client, app, login, csrf):
    login()
    write_router_config(app.config["WEBUI_SETTINGS"].router_config)
    client.post(
        "/keys/upstream/speaker-a/flai",
        data={"value": "flai-very-secret"},
        headers={"X-CSRF-Token": csrf(client)},
    )
    assert "flai-very-secret" not in client.get("/keys").get_data(as_text=True)
    assert "flai-very-secret" not in client.get("/audit").get_data(as_text=True)


def test_audit_page_lists_login(client, login):
    login()
    body = client.get("/audit").get_data(as_text=True)
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
    assert "#7fb069" in body
    assert "Yandex Station Micro v1.2" in body


def test_speakers_page_has_logout_and_tabs(client, login):
    login()
    body = client.get("/speakers").get_data(as_text=True)
    assert "Выйти" in body
    assert "admin-tabs" in body
    assert "Администратор" in body


def test_login_redirects_authenticated_user(client, login):
    login()
    response = client.get("/login")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/speakers")


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
    admin_page = client.get("/speakers").get_data(as_text=True)
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
    body = client.get("/firmware").get_data(as_text=True)
    assert "Прошивка" in body
    assert "Скачать прошивку" in body
    assert "test-firmware.zip" in body
    assert "Найти колонку" in body
    assert "Настроить SSH/OTA" in body
    assert "Установить Bridge" in body
    assert "10.0.0.2" in body
    assert "http://10.0.0.2:5002/health" in body


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
    body = client.get("/router?probe=1").get_data(as_text=True)
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
    body = client.get("/router?probe=1").get_data(as_text=True)
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
