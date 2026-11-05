from __future__ import annotations

import json

from webui.stand_client import request


def test_request_posts_to_sidecar(monkeypatch):
    calls = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"status": "ok"}).encode()

    def fake_urlopen(req, timeout):
        calls["url"] = req.full_url
        calls["method"] = req.get_method()
        calls["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    status, body = request("start", "http://stand-control:8082")
    assert status == 200
    assert "ok" in body
    assert calls["url"] == "http://stand-control:8082/start"
    assert calls["method"] == "POST"
