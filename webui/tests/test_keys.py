from __future__ import annotations

import stat

import pytest

from webui.keys import (
    add_upstream_key,
    delete_upstream_key,
    key_inventory,
    rotate_router_token,
    set_upstream_key,
    upstream_key_list,
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


def _routes():
    return [
        {
            "name": "speaker-a",
            "primary": {"api_key_file": "flai-token-speaker-a"},
            "fallbacks": [],
        }
    ]


def test_registry_imports_keys_referenced_by_routes(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    write_secret(secrets, "flai-token-speaker-a", "secret")
    registry = tmp_path / "upstream-keys.json"
    items = upstream_key_list(registry, secrets, _routes())
    assert [(item.label, item.file) for item in items] == [
        ("flai-token-speaker-a", "flai-token-speaker-a")
    ]
    assert items[0].exists is True
    assert items[0].used_by == ("speaker-a",)


def test_add_upstream_key_writes_secret_and_registry(tmp_path):
    secrets = tmp_path / "secrets"
    registry = tmp_path / "upstream-keys.json"
    add_upstream_key(registry, secrets, "Orca free", "orca-token-1", "orca-secret")
    path = secrets / "orca-token-1"
    assert path.read_text(encoding="utf-8").strip() == "orca-secret"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    items = upstream_key_list(registry, secrets, [])
    assert [(item.label, item.file) for item in items] == [
        ("Orca free", "orca-token-1")
    ]


def test_add_upstream_key_rejects_duplicate_file(tmp_path):
    registry = tmp_path / "upstream-keys.json"
    add_upstream_key(registry, tmp_path, "one", "orca-token-1", "a")
    with pytest.raises(ValueError):
        add_upstream_key(registry, tmp_path, "two", "orca-token-1", "b")


def test_delete_upstream_key_refuses_used_key(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    registry = tmp_path / "upstream-keys.json"
    write_secret(secrets, "flai-token-speaker-a", "secret")
    upstream_key_list(registry, secrets, _routes())
    with pytest.raises(ValueError):
        delete_upstream_key(registry, secrets, "flai-token-speaker-a", _routes())
    assert (secrets / "flai-token-speaker-a").exists()


def test_delete_unused_upstream_key_removes_secret(tmp_path):
    secrets = tmp_path / "secrets"
    registry = tmp_path / "upstream-keys.json"
    add_upstream_key(registry, secrets, "free", "orca-token-1", "a")
    delete_upstream_key(registry, secrets, "orca-token-1", [])
    assert not (secrets / "orca-token-1").exists()
    assert upstream_key_list(registry, secrets, []) == []
