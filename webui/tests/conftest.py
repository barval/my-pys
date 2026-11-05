from __future__ import annotations

import pytest

from webui.app import create_app
from webui.profiles import load_profiles
from webui.settings import load_settings


@pytest.fixture
def settings(tmp_path):
    return load_settings(root=tmp_path, env={})


@pytest.fixture
def app(settings):
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
            "SPEAKER_MAC=02:00:00:00:00:01\n",
            encoding="utf-8",
        )
        return load_profiles(directory)[0]

    return factory
