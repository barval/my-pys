from __future__ import annotations

import pytest

from webui.app import create_app
from webui.auth import hash_password
from webui.profiles import load_profiles
from webui.settings import load_settings


@pytest.fixture
def settings(tmp_path):
    settings = load_settings(root=tmp_path, env={})
    settings.secrets_dir.mkdir(parents=True, exist_ok=True)
    settings.admin_hash_file.write_text(hash_password("correct horse"), encoding="utf-8")
    return settings


@pytest.fixture
def login(client, csrf):
    def do():
        client.post(
            "/login",
            data={"password": "correct horse", "csrf_token": csrf(client)},
        )

    return do


@pytest.fixture
def csrf():
    def token(client):
        client.get("/login")
        with client.session_transaction() as session:
            return session["csrf"]

    return token


@pytest.fixture
def app(settings, make_profile):
    make_profile("speaker-a")
    app = create_app(settings)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_profile(tmp_path):
    def factory(name: str = "speaker-a"):
        directory = tmp_path / "local" / "speakers"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.env").write_text(
            f"SPEAKER_NAME={name}\n"
            "SPEAKER_IP=192.168.1.101\n"
            "SPEAKER_SUBNET=192.168.1\n"
            "SPEAKER_DEVICE_ID=EXAMPLE000000000000000000000001\n"
            "SPEAKER_MAC=02:00:00:00:00:01\n"
            "SPEAKER_ROOM=Комната A\n",
            encoding="utf-8",
        )
        return load_profiles(directory)[0]

    return factory
