from __future__ import annotations

from flask import Flask, jsonify

from .auth import init_auth
from .settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or load_settings()
    app = Flask(
        __name__,
        template_folder=str(settings.templates_dir),
        static_folder=str(settings.static_dir),
    )
    app.config["WEBUI_SETTINGS"] = settings
    init_auth(app, settings)

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.get("/")
    def index():
        return "Web UI"

    return app
