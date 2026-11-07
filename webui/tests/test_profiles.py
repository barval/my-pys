from __future__ import annotations

from webui.profiles import NAME_RE, load_profiles, mask_secret, parse_env


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


def test_load_profiles_skips_invalid_file(tmp_path):
    (tmp_path / "speaker-a.env").write_text(
        "SPEAKER_NAME=speaker-a\n"
        "SPEAKER_DEVICE_ID=EXAMPLE0001\n"
        "SPEAKER_MAC=02:00:00:00:00:01\n",
        encoding="utf-8",
    )
    (tmp_path / "broken.env").write_text(
        "SPEAKER_NAME=broken\n", encoding="utf-8"
    )
    assert [p.name for p in load_profiles(tmp_path)] == ["speaker-a"]


def test_profile_name_length_allows_router_token_prefix():
    assert NAME_RE.fullmatch("a" * 51)
    assert not NAME_RE.fullmatch("a" * 52)


def test_mask_secret_keeps_edges():
    assert mask_secret("EXAMPLE000000000000000000000001") == "EXAM...0001"


def test_profile_model_and_color_defaults(tmp_path):
    (tmp_path / "speaker-a.env").write_text(
        "SPEAKER_NAME=speaker-a\n"
        "SPEAKER_DEVICE_ID=EXAMPLE0001\n"
        "SPEAKER_MAC=02:00:00:00:00:01\n",
        encoding="utf-8",
    )
    profile = load_profiles(tmp_path)[0]
    assert profile.model == "Яндекс Станция Лайт"
    assert profile.color == ""
    assert profile.room == ""


def test_profile_reads_model_and_color(tmp_path):
    (tmp_path / "speaker-a.env").write_text(
        "SPEAKER_NAME=speaker-a\n"
        "SPEAKER_DEVICE_ID=EXAMPLE0001\n"
        "SPEAKER_MAC=02:00:00:00:00:01\n"
        "SPEAKER_MODEL=Yandex Station Micro v1.2\n"
        "SPEAKER_COLOR=green\n",
        encoding="utf-8",
    )
    profile = load_profiles(tmp_path)[0]
    assert profile.model == "Yandex Station Micro v1.2"
    assert profile.color == "green"


def test_profile_reads_room(tmp_path):
    (tmp_path / "speaker-a.env").write_text(
        "SPEAKER_NAME=speaker-a\n"
        "SPEAKER_DEVICE_ID=EXAMPLE0001\n"
        "SPEAKER_MAC=02:00:00:00:00:01\n"
        "SPEAKER_ROOM=Комната A\n",
        encoding="utf-8",
    )
    assert load_profiles(tmp_path)[0].room == "Комната A"
