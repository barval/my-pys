from __future__ import annotations

import json

from webui.router_control import restart


def test_restart_posts_to_sidecar(monkeypatch):
    calls = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"status": "restarted"}).encode()

    def fake_urlopen(request, timeout):
        calls["url"] = request.full_url
        calls["method"] = request.get_method()
        calls["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    status, body = restart("http://router-control:8081")
    assert status == 200
    assert "restarted" in body
    assert calls == {
        "url": "http://router-control:8081/restart",
        "method": "POST",
        "timeout": 30,
    }
