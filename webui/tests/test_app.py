from __future__ import annotations

from webui.app import create_app
from webui.settings import load_settings


def test_healthz_is_public(tmp_path):
    app = create_app(load_settings(root=tmp_path, env={}))
    client = app.test_client()
    assert client.get("/healthz").get_json() == {"status": "ok"}


def test_speaker_page_masks_device_id(client, login):
    login()
    response = client.get("/speakers/speaker-a")
    body = response.get_data(as_text=True)
    assert "EXAM...0001" in body
    assert "EXAMPLE000000000000000000000001" not in body


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
    def submit(self, action, profile):
        from types import SimpleNamespace

        return SimpleNamespace(id="job-1")
