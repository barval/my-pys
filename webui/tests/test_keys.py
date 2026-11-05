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
    value = rotate_router_token(tmp_path, "speaker-a")
    path = tmp_path / "router-token-speaker-a"
    assert value.startswith("sk-router-")
    assert path.read_text(encoding="utf-8").strip() == value
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_inventory_never_contains_value(tmp_path):
    write_secret(tmp_path, "flai-token-speaker-a", "super-secret")
    item = key_inventory(tmp_path, ["speaker-a"])[0]
    assert item.flai_token is True
    assert "super-secret" not in repr(item)


def test_secret_name_rejects_traversal(tmp_path):
    with pytest.raises(ValueError):
        write_secret(tmp_path, "../evil", "x")


def test_set_upstream_key_writes_private_file(tmp_path):
    set_upstream_key(tmp_path, "speaker-a", "flai", "flai-secret")
    path = tmp_path / "flai-token-speaker-a"
    assert path.read_text(encoding="utf-8").strip() == "flai-secret"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_set_upstream_key_rejects_unknown_provider(tmp_path):
    with pytest.raises(ValueError):
        set_upstream_key(tmp_path, "speaker-a", "other", "x")
