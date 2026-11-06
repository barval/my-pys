import pytest

from webui.profile_writer import merge_profile_env, validate_profile, write_profile

FIELDS = {
    "SPEAKER_NAME": "speaker-z",
    "SPEAKER_IP": "192.168.1.150",
    "SPEAKER_SUBNET": "192.168.1",
    "SPEAKER_DEVICE_ID": "EXAMPLE000000000000000000000099",
    "SPEAKER_MAC": "02:00:00:00:00:99",
    "SPEAKER_ROOM": "Комната Z",
    "SPEAKER_MODEL": "Яндекс Станция Лайт",
}


def test_write_profile_is_private_and_loadable(tmp_path):
    path = write_profile(tmp_path, FIELDS)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert "SPEAKER_MAC=02:00:00:00:00:99" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["../evil", "a/b", "A", "", "x" * 65])
def test_invalid_names_are_rejected(name):
    with pytest.raises(ValueError):
        validate_profile(name, "192.168.1.150", "192.168.1",
                         "02:00:00:00:00:99", "EXAMPLE000000000000000000000099")


def test_public_subnet_and_bad_mac_are_rejected():
    with pytest.raises(ValueError):
        validate_profile("speaker-z", "8.8.8.8", "8.8.8",
                         "02:00:00:00:00:99", "EXAMPLE000000000000000000000099")
    with pytest.raises(ValueError):
        validate_profile("speaker-z", "192.168.1.150", "192.168.1",
                         "not-a-mac", "EXAMPLE000000000000000000000099")


def test_merge_keeps_unrelated_lines(tmp_path):
    path = tmp_path / "speaker-z.env"
    path.write_text("# comment\nSPEAKER_IP=192.168.1.1\nFOO=bar\n", encoding="utf-8")
    merge_profile_env(path, {"SPEAKER_IP": "192.168.1.150", "LLM_TOKEN_FILE": "secrets/router-token-speaker-z"})
    body = path.read_text(encoding="utf-8")
    assert "FOO=bar" in body
    assert "# comment" in body
    assert "SPEAKER_IP=192.168.1.150" in body
    assert "LLM_TOKEN_FILE=secrets/router-token-speaker-z" in body
    assert body.count("SPEAKER_IP=") == 1


def test_archive_rejects_traversal_and_moves_files(settings, make_profile):
    from webui.profile_writer import archive_profile

    make_profile("speaker-a")
    with pytest.raises(ValueError):
        archive_profile(settings, "../evil", route=None)

    target = archive_profile(settings, "speaker-a", route=None)
    assert target.parent == settings.state_dir / "deleted-profiles"
    assert not (settings.speakers_dir / "speaker-a.env").exists()
    assert (target / "local" / "speakers" / "speaker-a.env").is_file()


def test_archive_profile_writes_appearance_json(settings, make_profile):
    from webui.profile_writer import archive_profile

    make_profile("speaker-a")
    appearance = {"color": "green", "model": "Yandex Station Micro"}
    target = archive_profile(
        settings, "speaker-a", route=None, appearance=appearance
    )
    path = target / "appearance.json"
    assert path.is_file()
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert "green" in path.read_text(encoding="utf-8")


def test_archive_profile_router_json_is_private(settings, make_profile):
    from webui.profile_writer import archive_profile

    make_profile("speaker-a")
    route = {"name": "speaker-a", "token_file": "router-token-speaker-a"}
    target = archive_profile(settings, "speaker-a", route=route)
    path = target / "router.json"
    assert path.is_file()
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_write_profile_rejects_newline_in_value(tmp_path):
    bad = dict(FIELDS, SPEAKER_ROOM="Комната\nZ")
    with pytest.raises(ValueError, match="Недопустимые символы"):
        write_profile(tmp_path, bad)


def test_write_profile_rejects_bad_name_in_values(tmp_path):
    bad = dict(FIELDS, SPEAKER_NAME="../evil")
    with pytest.raises(ValueError):
        write_profile(tmp_path, bad)


def test_merge_profile_env_rejects_newline(tmp_path):
    path = tmp_path / "speaker-z.env"
    path.write_text("SPEAKER_IP=192.168.1.1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Недопустимые символы"):
        merge_profile_env(path, {"SPEAKER_IP": "192.168.1.150\n1"})
