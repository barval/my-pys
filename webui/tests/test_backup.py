from __future__ import annotations

import json
import stat

import pytest

from webui.backup import (
    BackupError,
    create_backup,
    inspect_backup,
    resolve_backup,
    restore_backup,
)
from webui.settings import load_settings


def _write_router(path, routes):
    path.write_text(
        json.dumps(
            {
                "response": {"max_sentences": 3, "max_chars": 400},
                "routes": routes,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _route(name, model="flai-chat"):
    return {
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
            "model": model,
            "history": "server",
        },
        "fallback": None,
    }


def _make_root(root):
    (root / "local" / "speakers").mkdir(parents=True)
    (root / "local" / ".env").write_text("SPEAKER_NAME=speaker-a\n", encoding="utf-8")
    (root / "local" / "speakers" / "speaker-a.env").write_text(
        "SPEAKER_NAME=speaker-a\n"
        "SPEAKER_DEVICE_ID=EXAMPLE0001\n"
        "SPEAKER_MAC=02:00:00:00:00:01\n",
        encoding="utf-8",
    )
    (root / "local" / "speakers" / "speaker-b.env").write_text(
        "SPEAKER_NAME=speaker-b\n"
        "SPEAKER_DEVICE_ID=EXAMPLE0002\n"
        "SPEAKER_MAC=02:00:00:00:00:02\n",
        encoding="utf-8",
    )
    secrets = root / "secrets"
    secrets.mkdir()
    for name in ("router-token-speaker-a", "router-token-speaker-b"):
        (secrets / name).write_text(f"value-{name}\n", encoding="utf-8")
    for name in ("flai-token-speaker-a", "orca-token-speaker-a"):
        (secrets / name).write_text(f"value-{name}\n", encoding="utf-8")
    (secrets / "speaker_ed25519").write_text("ssh-private", encoding="utf-8")
    (secrets / "speaker_ed25519.pub").write_text("ssh-public", encoding="utf-8")
    (secrets / "webui-admin.hash").write_text("admin-hash", encoding="utf-8")
    (secrets / "webui-session.key").write_text("session-key", encoding="utf-8")
    _write_router(
        secrets / "router-routes.json",
        [_route("speaker-a"), _route("speaker-b")],
    )
    return load_settings(root=root, env={})


def test_create_all_backup_encrypts_and_lists_manifest(tmp_path):
    settings = _make_root(tmp_path)
    path = create_backup(settings, "all", "correct horse")
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    blob = path.read_bytes()
    assert b"value-router-token-speaker-a" not in blob
    assert b"ssh-private" not in blob

    manifest = inspect_backup(settings, path.name, "correct horse")
    assert manifest["scope"] == "all"
    assert "local/.env" in manifest["files"]
    assert "local/speakers/speaker-b.env" in manifest["files"]
    assert "secrets/router-token-speaker-a" in manifest["files"]
    assert "secrets/speaker_ed25519" in manifest["files"]
    assert "secrets/webui-session.key" not in manifest["files"]


def test_backup_includes_key_with_arbitrary_name(tmp_path):
    settings = _make_root(tmp_path)
    (settings.secrets_dir / "openrouter").write_text("value-openrouter\n", encoding="utf-8")
    path = settings.router_config
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["routes"][0]["primary"]["api_key_file"] = "openrouter"
    path.write_text(json.dumps(raw), encoding="utf-8")

    archive = create_backup(settings, "all", "correct horse")
    manifest = inspect_backup(settings, archive.name, "correct horse")
    assert "secrets/openrouter" in manifest["files"]


def test_wrong_passphrase_is_rejected(tmp_path):
    settings = _make_root(tmp_path)
    path = create_backup(settings, "all", "correct horse")
    with pytest.raises(BackupError):
        inspect_backup(settings, path.name, "wrong passphrase")


def test_restore_all_into_fresh_root(tmp_path):
    source = _make_root(tmp_path / "source")
    archive = create_backup(source, "all", "correct horse")

    target_root = tmp_path / "target"
    target_root.mkdir()
    target = load_settings(root=target_root, env={})
    summary = restore_backup(
        target, archive, "correct horse", confirm="REPLACE"
    )

    assert (target_root / "local" / "speakers" / "speaker-a.env").exists()
    assert (target_root / "secrets" / "router-token-speaker-a").exists()
    assert (target_root / "secrets" / "speaker_ed25519").exists()
    assert (target_root / "secrets" / "router-routes.json").exists()
    assert (target_root / "local" / ".env").exists()
    assert summary["scope"] == "all"
    assert list((target_root / "webui-state" / "restore-backups").iterdir())


def test_restore_single_keeps_other_routes(tmp_path):
    source = _make_root(tmp_path / "source")
    archive = create_backup(source, "speaker:speaker-a", "correct horse")

    target_root = tmp_path / "target"
    target_root.mkdir()
    target = _make_root(target_root)
    raw = json.loads((target_root / "secrets" / "router-routes.json").read_text())
    raw["routes"][0]["primary"]["model"] = "old-model"
    (target_root / "secrets" / "router-routes.json").write_text(
        json.dumps(raw) + "\n", encoding="utf-8"
    )

    restore_backup(target, archive, "correct horse", confirm="REPLACE")

    restored = json.loads(
        (target_root / "secrets" / "router-routes.json").read_text()
    )
    models = {route["name"]: route["primary"]["model"] for route in restored["routes"]}
    assert models["speaker-a"] == "flai-chat"
    assert models["speaker-b"] == "flai-chat"
    assert len(restored["routes"]) == 2


def test_speaker_backup_includes_arbitrary_key_names(tmp_path):
    source = _make_root(tmp_path / "source")
    (source.secrets_dir / "openrouter-token-speaker-a").write_text(
        "or-value\n", encoding="utf-8"
    )
    raw = json.loads(source.router_config.read_text(encoding="utf-8"))
    raw["routes"][0]["fallbacks"] = [
        {
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_file": "openrouter-token-speaker-a",
            "model": "some-model",
            "history": "client",
        }
    ]
    source.router_config.write_text(json.dumps(raw) + "\n", encoding="utf-8")

    archive = create_backup(source, "speaker:speaker-a", "correct horse")

    target_root = tmp_path / "target"
    target_root.mkdir()
    target = _make_root(target_root)
    restore_backup(target, archive, "correct horse", confirm="REPLACE")
    assert (target_root / "secrets" / "openrouter-token-speaker-a").exists()


def test_restore_requires_confirmation(tmp_path):
    settings = _make_root(tmp_path)
    archive = create_backup(settings, "all", "correct horse")
    with pytest.raises(BackupError):
        restore_backup(settings, archive, "correct horse", confirm="yes")


def test_all_backup_includes_panel_state(tmp_path):
    settings = _make_root(tmp_path)
    setup = settings.state_dir / "setup"
    setup.mkdir(parents=True, exist_ok=True)
    (settings.state_dir / "providers.json").write_text(
        '{"providers": []}', encoding="utf-8"
    )
    (setup / "speaker-a.json").write_text('{"step": 3}', encoding="utf-8")
    path = create_backup(settings, "all", "correct horse")
    names = inspect_backup(settings, path.name, "correct horse")["files"]
    assert "webui-state/providers.json" in names
    assert "webui-state/setup/speaker-a.json" in names


def test_speaker_backup_includes_setup_progress(tmp_path):
    settings = _make_root(tmp_path)
    setup = settings.state_dir / "setup"
    setup.mkdir(parents=True, exist_ok=True)
    (setup / "speaker-a.json").write_text('{"step": 3}', encoding="utf-8")
    path = create_backup(settings, "speaker:speaker-a", "correct horse")
    names = inspect_backup(settings, path.name, "correct horse")["files"]
    assert "webui-state/setup/speaker-a.json" in names


def test_backup_name_cannot_escape_directory(tmp_path):
    settings = _make_root(tmp_path)
    with pytest.raises(BackupError):
        resolve_backup(settings, "../escape.enc")
