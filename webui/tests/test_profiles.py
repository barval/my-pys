from __future__ import annotations

from webui.profiles import load_profiles, mask_secret, parse_env


def test_parse_env_ignores_comments_and_quotes(tmp_path):
    path = tmp_path / "speaker-a.env"
    path.write_text(
        '# c\nSPEAKER_NAME=speaker-a\nSPEAKER_MAC="02:00:00:00:00:01"\n',
        encoding="utf-8",
    )
    assert parse_env(path)["SPEAKER_MAC"] == "02:00:00:00:00:01"


def test_load_profiles_skips_example(tmp_path):
    (tmp_path / "example.env").write_text(
        "SPEAKER_NAME=example\n", encoding="utf-8"
    )
    (tmp_path / "speaker-a.env").write_text(
        "SPEAKER_NAME=speaker-a\n"
        "SPEAKER_DEVICE_ID=EXAMPLE0001\n"
        "SPEAKER_MAC=02:00:00:00:00:01\n",
        encoding="utf-8",
    )
    assert [p.name for p in load_profiles(tmp_path)] == ["speaker-a"]


def test_mask_secret_keeps_edges():
    assert mask_secret("EXAMPLE000000000000000000000001") == "EXAM...0001"
