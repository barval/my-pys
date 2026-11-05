from __future__ import annotations

import json

import pytest

from router.llm_router import ConfigError
from webui.router_config import delete_route, read_config, save_config


@pytest.fixture
def router_fixture(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "router-token-speaker-a").write_text(
        "sk-router-test\n", encoding="utf-8"
    )
    path = secrets / "router-routes.json"
    path.write_text(
        json.dumps(
            {
                "response": {"max_sentences": 3, "max_chars": 400},
                "routes": [
                    {
                        "name": "speaker-a",
                        "token_file": "router-token-speaker-a",
                        "session": {
                            "mode": "server",
                            "user": "voice",
                            "idle_minutes": 30,
                            "cleanup_keep": 3,
                        },
                        "primary": {
                            "base_url": "http://127.0.0.1:5000/v1",
                            "api_key_file": "flai-token-speaker-a",
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


def test_save_config_rejects_invalid_and_keeps_original(router_fixture):
    path = router_fixture
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ConfigError):
        save_config(path, {"routes": []})
    assert path.read_text(encoding="utf-8") == before


def test_save_config_writes_valid_atomically(router_fixture):
    raw = read_config(router_fixture)
    raw["routes"][0]["primary"]["model"] = "new-model"
    save_config(router_fixture, raw)
    assert read_config(router_fixture)["routes"][0]["primary"]["model"] == "new-model"


def test_delete_missing_route_raises(router_fixture):
    with pytest.raises(KeyError):
        delete_route(read_config(router_fixture), "nope")
