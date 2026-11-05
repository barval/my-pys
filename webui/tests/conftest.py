from __future__ import annotations

import pytest

from webui.app import create_app
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
