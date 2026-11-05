from __future__ import annotations

from flask import Flask, jsonify

from .settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or load_settings()
    app = Flask(
        __name__,
        template_folder=str(settings.templates_dir),
        static_folder=str(settings.static_dir),
    )
    app.config["WEBUI_SETTINGS"] = settings

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    return app
