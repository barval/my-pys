from __future__ import annotations

from webui.audit import record


def test_audit_redacts_tokens(tmp_path):
    path = tmp_path / "audit.jsonl"
    record(
        path,
        "admin",
        "keys.rotate",
        "speaker-a",
        "ok",
        "sk-router-abcdefghijklmnop",
        secrets_dir=tmp_path,
    )
    assert "sk-router-abcdefghijklmnop" not in path.read_text(encoding="utf-8")
    assert "***" in path.read_text(encoding="utf-8")


def test_audit_redacts_short_secrets(tmp_path):
    path = tmp_path / "audit.jsonl"
    (tmp_path / "short-key").write_text("shortkey", encoding="utf-8")
    record(
        path,
        "admin",
        "keys.rotate",
        "speaker-a",
        "ok",
        "value shortkey",
        secrets_dir=tmp_path,
    )
    assert "shortkey" not in path.read_text(encoding="utf-8")


def test_audit_appends_json_lines(tmp_path):
    path = tmp_path / "audit.jsonl"
    record(path, "admin", "a", "t", "ok")
    record(path, "admin", "b", "t", "ok")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
