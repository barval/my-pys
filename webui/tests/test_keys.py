from __future__ import annotations

import stat

import pytest

from webui.keys import (
    key_inventory,
    rotate_router_token,
    set_upstream_key,
    write_secret,
)


def test_rotate_token_sets_mode_and_returns_value(tmp_path):
    value = rotate_router_token(tmp_path, "router-token-speaker-a")
    path = tmp_path / "router-token-speaker-a"
    assert value.startswith("sk-router-")
    assert path.read_text(encoding="utf-8").strip() == value
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_inventory_never_contains_value(tmp_path):
    write_secret(tmp_path, "upstream-token-speaker-a", "super-secret")
    route = {
        "name": "speaker-a",
        "token_file": "router-token-speaker-a",
        "primary": {"api_key_file": "upstream-token-speaker-a"},
        "fallbacks": [],
    }
    item = key_inventory(tmp_path, [route])[0]
    assert item.upstream[0].exists is True
    assert "super-secret" not in repr(item)


def test_secret_name_rejects_traversal(tmp_path):
    with pytest.raises(ValueError):
        write_secret(tmp_path, "../evil", "x")


def test_set_upstream_key_writes_private_file(tmp_path):
    set_upstream_key(tmp_path, "upstream-token-speaker-a", "flai-secret")
    path = tmp_path / "upstream-token-speaker-a"
    assert path.read_text(encoding="utf-8").strip() == "flai-secret"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_set_upstream_key_rejects_invalid_name(tmp_path):
    with pytest.raises(ValueError):
        set_upstream_key(tmp_path, "../evil", "x")
