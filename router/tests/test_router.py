import json
import sys
import threading
import time
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import llm_router as r  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class UpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        self.server.seen.append(
            {
                "path": self.path,
                "body": json.loads(raw) if raw else None,
                "auth": self.headers.get("Authorization"),
            }
        )
        status, payload, stream = self.server.behavior(self.server.seen[-1])
        if stream:
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for chunk in payload:
                data = chunk.encode()
                self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
        else:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def log_message(self, *args):
        pass


def start_upstream(behavior):
    server = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    server.behavior = behavior
    server.seen = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def stop(server):
    server.shutdown()
    server.server_close()


def write_config(tmp_path, primary_url, fallback_url=None, token="sk-router-test"):
    secrets = tmp_path / "secrets"
    secrets.mkdir(exist_ok=True)
    (secrets / "router-token-speaker-a").write_text(token, encoding="utf-8")
    (secrets / "flai-token-speaker-a").write_text("flai-key", encoding="utf-8")
    (secrets / "fallback-token-speaker-a").write_text("fallback-key", encoding="utf-8")
    route = {
        "name": "speaker-a",
        "token_file": "router-token-speaker-a",
        "session": {"mode": "server", "user": "voice", "idle_minutes": 30, "cleanup_keep": 3},
        "primary": {
            "base_url": primary_url,
            "api_key_file": "flai-token-speaker-a",
            "model": "flai-chat",
            "history": "server",
            "timeout_seconds": 10,
            "fallback_on": [429, 500, 502, 503, 504],
        },
    }
    if fallback_url:
        route["fallback"] = {
            "base_url": fallback_url,
            "api_key_file": "fallback-token-speaker-a",
            "model": "qwen3-32b",
            "history": "client",
            "timeout_seconds": 10,
            "fallback_on": [429, 500, 502, 503, 504],
        }
    config = {"routes": [route]}
    path = secrets / "router-routes.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def start_router(config_path, state_path):
    server = r.RouterServer(("127.0.0.1", 0), r.ConfigStore(config_path), r.SessionManager(state_path))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def post(port, token, body, path="/v1/chat/completions", extra_headers=None):
    conn = HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if extra_headers:
        headers.update(extra_headers)
    conn.request("POST", path, json.dumps(body), headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, data


# ---------------------------------------------------------------------------
# Config and request shaping
# ---------------------------------------------------------------------------


def test_config_resolves_relative_secret_files(tmp_path):
    config_path = write_config(tmp_path, "http://127.0.0.1:1/v1")
    config = r.load_config(config_path)

    route = config.by_token("sk-router-test")
    assert route is not None
    assert route.name == "speaker-a"
    assert route.primary.api_key == "flai-key"
    assert route.primary.history == "server"
    assert route.session.idle_minutes == 30


def test_server_history_sends_only_last_user(tmp_path):
    config = r.load_config(write_config(tmp_path, "http://127.0.0.1:1/v1"))
    route = config.by_token("sk-router-test")
    body = {
        "model": "flai-chat",
        "messages": [
            {"role": "system", "content": "voice"},
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "new question"},
        ],
        "metadata": {"session_id": "do-not-use"},
        "stream": False,
    }

    payload = r.build_payload(route.primary, body, "voice-2")

    assert payload["messages"] == [{"role": "user", "content": "new question"}]
    assert payload["user"] == "voice-2"
    assert payload["model"] == "flai-chat"
    assert "session_id" not in payload.get("metadata", {})
    assert body["messages"][1]["content"] == "old question"


def test_health_probe_is_detected():
    probe = {"messages": [{"role": "user", "content": "Ответь одним словом: связь"}]}
    normal = {"messages": [{"role": "user", "content": "Кто ты"}]}
    with_system = {
        "messages": [
            {"role": "system", "content": "voice"},
            {"role": "user", "content": "Ответь одним словом: связь"},
        ]
    }

    assert r.is_health_probe(probe) is True
    assert r.is_health_probe(normal) is False
    assert r.is_health_probe(with_system) is False


def test_client_history_keeps_everything(tmp_path):
    config = r.load_config(write_config(tmp_path, "http://127.0.0.1:1/v1"))
    route = config.by_token("sk-router-test")
    body = {
        "model": "client-model",
        "messages": [
            {"role": "system", "content": "voice"},
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "new"},
        ],
    }

    client = r.Upstream(base_url="http://127.0.0.1:1/v1", api_key="x", model="flai-chat", history="client")
    payload = r.build_payload(client, body, "voice")

    assert payload["messages"] == body["messages"]
    assert payload["model"] == "flai-chat"


def test_response_policy_defaults(tmp_path):
    config = r.load_config(write_config(tmp_path, "http://127.0.0.1:1/v1"))
    assert config.response.max_sentences == 3
    assert config.response.max_chars == 400
    assert config.response.strip_markdown is True
    assert config.response_chunked.max_sentences == 100
    assert config.response_chunked.max_chars == 3000


def test_config_reads_chunked_policy(tmp_path):
    path = write_config(tmp_path, "http://127.0.0.1:1/v1")
    raw = json.loads(path.read_text())
    raw["response"] = {"chunked": {"max_sentences": 50, "max_chars": 1000}}
    path.write_text(json.dumps(raw))

    config = r.load_config(path)

    assert config.response_chunked.max_sentences == 50
    assert config.response_chunked.max_chars == 1000


def test_shorten_text_keeps_three_sentences_and_strips_markdown():
    policy = r.ResponsePolicy(max_sentences=3, max_chars=400, strip_markdown=True)
    text = "**Первое** предложение. Второе [ссылка](https://example.com). Третье `код`. Четвёртое."

    assert r.shorten_text(text, policy) == "Первое предложение. Второе ссылка. Третье код."


def test_shorten_text_caps_characters_without_cutting_words():
    policy = r.ResponsePolicy(max_sentences=10, max_chars=50, strip_markdown=True)
    text = "очень длинное предложение " * 20

    result = r.shorten_text(text, policy)

    assert len(result) <= 50
    assert result.endswith("…")
    assert not result.rstrip("…").endswith(" ")


def test_apply_response_policy_rewrites_only_content():
    policy = r.ResponsePolicy(max_sentences=3, max_chars=400, strip_markdown=True)
    payload = {
        "choices": [{"message": {"role": "assistant", "content": "Раз. Два. Три. Четыре."}}],
        "usage": {"total_tokens": 7},
    }

    result = json.loads(r.apply_response_policy(json.dumps(payload).encode(), policy))

    assert result["choices"][0]["message"]["content"] == "Раз. Два. Три."
    assert result["usage"] == {"total_tokens": 7}


def test_config_reloads_when_upstream_key_appears(tmp_path):
    config_path = write_config(tmp_path, "http://127.0.0.1:1/v1")
    key_file = tmp_path / "secrets" / "flai-token-speaker-a"
    key_file.unlink()
    store = r.ConfigStore(config_path)

    assert store.get().by_token("sk-router-test").primary.available is False
    key_file.write_text("flai-key", encoding="utf-8")
    assert store.get().by_token("sk-router-test").primary.available is True


def test_session_rotates_after_thirty_minutes_idle(tmp_path):
    config = r.load_config(write_config(tmp_path, "http://127.0.0.1:1/v1"))
    route = config.by_token("sk-router-test")
    clock = FakeClock()
    manager = r.SessionManager(tmp_path / "state.json", clock=clock)

    assert manager.user_for(route) == "voice"
    clock.now += 29 * 60
    assert manager.user_for(route) == "voice"
    clock.now += 31 * 60
    assert manager.user_for(route) == "voice-1"
    assert manager.user_for(route) == "voice-1"


def test_select_stale_sessions_keeps_newest_three():
    sessions = [
        {"id": str(i), "title": "flai:conv:x", "created_at": f"2026-11-04T2{i}:00:00"}
        for i in range(5)
    ]

    stale = r.select_stale_sessions(sessions, {"flai:conv:x"}, keep=3)

    assert sorted(stale) == ["0", "1"]


def test_select_stale_sessions_ignores_other_routes():
    sessions = [
        {"id": "a", "title": "flai:conv:other", "created_at": "2026-11-04T23:00:00"},
        {"id": "b", "title": "flai:conv:x", "created_at": "2026-11-04T22:00:00"},
    ]

    assert r.select_stale_sessions(sessions, {"flai:conv:x"}, keep=3) == []


# ---------------------------------------------------------------------------
# HTTP proxy and failover
# ---------------------------------------------------------------------------


def test_unknown_token_is_rejected(tmp_path):
    primary = start_upstream(lambda seen: (200, {"ok": True}, False))
    router = start_router(write_config(tmp_path, f"http://127.0.0.1:{primary.server_port}/v1"), tmp_path / "state.json")
    try:
        status, data = post(router.server_port, "wrong", {"messages": [{"role": "user", "content": "hi"}]})
        assert status == 401
        assert json.loads(data)["error"]["type"] == "router_error"
    finally:
        stop(router)
        stop(primary)


def test_primary_503_falls_back_and_rebuilds_client_history(tmp_path):
    primary = start_upstream(lambda seen: (503, {"error": "down"}, False))
    fallback = start_upstream(
        lambda seen: (200, {"choices": [{"message": {"role": "assistant", "content": "from fallback"}}]}, False)
    )
    config_path = write_config(
        tmp_path,
        f"http://127.0.0.1:{primary.server_port}/v1",
        f"http://127.0.0.1:{fallback.server_port}/v1",
    )
    router = start_router(config_path, tmp_path / "state.json")
    body = {
        "messages": [
            {"role": "system", "content": "voice"},
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "new"},
        ],
        "stream": False,
    }
    try:
        status, data = post(router.server_port, "sk-router-test", body)
        assert status == 200
        assert "from fallback" in data.decode()

        primary_body = primary.seen[0]["body"]
        assert primary_body["messages"] == [{"role": "user", "content": "new"}]
        assert primary_body["user"] == "voice"

        fallback_body = fallback.seen[0]["body"]
        assert fallback_body["messages"] == body["messages"]
        assert fallback_body["model"] == "qwen3-32b"
    finally:
        stop(router)
        stop(primary)
        stop(fallback)


def test_second_fallback_is_used_when_first_fails(tmp_path):
    primary = start_upstream(lambda seen: (503, {"error": "primary"}, False))
    first = start_upstream(lambda seen: (503, {"error": "first"}, False))
    second = start_upstream(
        lambda seen: (200, {"choices": [{"message": {"role": "assistant", "content": "from second"}}]}, False)
    )
    config_path = write_config(
        tmp_path,
        f"http://127.0.0.1:{primary.server_port}/v1",
        f"http://127.0.0.1:{first.server_port}/v1",
    )
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    route = raw["routes"][0]
    route["fallbacks"] = [
        route.pop("fallback"),
        {
            "base_url": f"http://127.0.0.1:{second.server_port}/v1",
            "api_key_file": "fallback-token-speaker-a",
            "model": "second-model",
            "history": "client",
            "timeout_seconds": 10,
            "fallback_on": [429, 500, 502, 503, 504],
        },
    ]
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    router = start_router(config_path, tmp_path / "state.json")
    try:
        status, data = post(
            router.server_port,
            "sk-router-test",
            {"messages": [{"role": "user", "content": "hi"}]},
        )
        assert status == 200
        assert "from second" in data.decode()
        assert second.seen[0]["body"]["model"] == "second-model"
    finally:
        stop(router)
        stop(primary)
        stop(first)
        stop(second)


def test_primary_400_does_not_fall_back(tmp_path):
    primary = start_upstream(lambda seen: (400, {"error": "bad request"}, False))
    fallback = start_upstream(lambda seen: (200, {"ok": True}, False))
    config_path = write_config(
        tmp_path,
        f"http://127.0.0.1:{primary.server_port}/v1",
        f"http://127.0.0.1:{fallback.server_port}/v1",
    )
    router = start_router(config_path, tmp_path / "state.json")
    try:
        status, _ = post(router.server_port, "sk-router-test", {"messages": [{"role": "user", "content": "hi"}]})
        assert status == 400
        assert fallback.seen == []
    finally:
        stop(router)
        stop(primary)
        stop(fallback)


def test_stream_is_proxied(tmp_path):
    def behavior(seen):
        return 200, ['data: {"delta":"hello"}\n\n', "data: [DONE]\n\n"], True

    primary = start_upstream(behavior)
    router = start_router(write_config(tmp_path, f"http://127.0.0.1:{primary.server_port}/v1"), tmp_path / "state.json")
    try:
        status, data = post(
            router.server_port,
            "sk-router-test",
            {"messages": [{"role": "user", "content": "hi"}], "stream": True},
        )
        assert status == 200
        assert b"hello" in data
        assert b"[DONE]" in data
    finally:
        stop(router)
        stop(primary)


def test_proxy_shortens_long_non_stream_answer(tmp_path):
    primary = start_upstream(
        lambda seen: (
            200,
            {"choices": [{"message": {"role": "assistant", "content": "Раз. Два. Три. Четыре."}}]},
            False,
        )
    )
    router = start_router(write_config(tmp_path, f"http://127.0.0.1:{primary.server_port}/v1"), tmp_path / "state.json")
    try:
        status, data = post(
            router.server_port,
            "sk-router-test",
            {"messages": [{"role": "user", "content": "расскажи"}]},
        )
        assert status == 200
        assert json.loads(data)["choices"][0]["message"]["content"] == "Раз. Два. Три."
    finally:
        stop(router)
        stop(primary)


def test_chunking_header_allows_long_answer(tmp_path):
    primary = start_upstream(
        lambda seen: (
            200,
            {"choices": [{"message": {"role": "assistant", "content": "Раз. Два. Три. Четыре."}}]},
            False,
        )
    )
    router = start_router(write_config(tmp_path, f"http://127.0.0.1:{primary.server_port}/v1"), tmp_path / "state.json")
    try:
        status, data = post(
            router.server_port,
            "sk-router-test",
            {"messages": [{"role": "user", "content": "расскажи"}]},
            extra_headers={"X-Quasar-Voice-Chunking": "1"},
        )
        assert status == 200
        assert json.loads(data)["choices"][0]["message"]["content"] == "Раз. Два. Три. Четыре."
    finally:
        stop(router)
        stop(primary)


def test_health_probe_uses_separate_session(tmp_path):
    primary = start_upstream(
        lambda seen: (200, {"choices": [{"message": {"role": "assistant", "content": "связь"}}]}, False)
    )
    router = start_router(write_config(tmp_path, f"http://127.0.0.1:{primary.server_port}/v1"), tmp_path / "state.json")
    try:
        status, _ = post(
            router.server_port,
            "sk-router-test",
            {"messages": [{"role": "user", "content": "Ответь одним словом: связь"}]},
        )
        assert status == 200
        assert primary.seen[0]["body"]["user"] == "voice-health"
    finally:
        stop(router)
        stop(primary)


def test_health_does_not_require_token(tmp_path):
    primary = start_upstream(lambda seen: (200, {"ok": True}, False))
    router = start_router(write_config(tmp_path, f"http://127.0.0.1:{primary.server_port}/v1"), tmp_path / "state.json")
    try:
        conn = HTTPConnection("127.0.0.1", router.server_port, timeout=5)
        conn.request("GET", "/health")
        response = conn.getresponse()
        data = json.loads(response.read())
        assert response.status == 200
        assert data["status"] == "ok"
        assert data["routes"][0]["name"] == "speaker-a"
    finally:
        stop(router)
        stop(primary)
