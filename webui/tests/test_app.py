from __future__ import annotations

from webui.app import create_app
from webui.settings import load_settings


def test_healthz_is_public(tmp_path):
    app = create_app(load_settings(root=tmp_path, env={}))
    client = app.test_client()
    assert client.get("/healthz").get_json() == {"status": "ok"}
