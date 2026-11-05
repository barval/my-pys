from __future__ import annotations

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from .actions import CommandBuilder, SPEAKER_ACTIONS
from .auth import init_auth
from .jobs import JobRunner
from .profiles import load_profiles, mask_secret
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

    profiles = {profile.name: profile for profile in load_profiles(settings.speakers_dir)}
    runner = JobRunner(
        settings.state_dir,
        CommandBuilder(settings.root),
        max_workers=settings.max_workers,
        timeout=settings.job_timeout,
    )
    app.extensions["profiles"] = profiles
    app.extensions["jobs"] = runner

    def get_profile(name: str):
        profile = profiles.get(name)
        if profile is None:
            abort(404)
        return profile

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.get("/")
    def index():
        return redirect(url_for("speakers_page"))

    @app.get("/speakers")
    def speakers_page():
        return render_template(
            "speakers.html",
            profiles=sorted(profiles.values(), key=lambda item: item.name),
            mask=mask_secret,
        )

    @app.get("/speakers/<name>")
    def speaker_page(name: str):
        profile = get_profile(name)
        jobs = [
            job
            for job in app.extensions["jobs"].list(limit=100)
            if job.target == profile.name
        ][:10]
        return render_template(
            "speaker.html",
            profile=profile,
            actions=SPEAKER_ACTIONS.values(),
            jobs=jobs,
            mask=mask_secret,
        )

    @app.post("/speakers/<name>/actions/<action>")
    def speaker_action(name: str, action: str):
        profile = get_profile(name)
        if action not in SPEAKER_ACTIONS:
            abort(404)
        job = app.extensions["jobs"].submit(action, profile)
        return redirect(url_for("job_page", job_id=job.id), code=303)

    @app.get("/jobs/<job_id>")
    def job_page(job_id: str):
        job = app.extensions["jobs"].get(job_id)
        if job is None:
            abort(404)
        text, offset = app.extensions["jobs"].tail(job_id, 0)
        return render_template("job.html", job=job, text=text, offset=offset)

    @app.get("/jobs/<job_id>/log")
    def job_log(job_id: str):
        job = app.extensions["jobs"].get(job_id)
        if job is None:
            abort(404)
        text, offset = app.extensions["jobs"].tail(job_id, 0)
        return render_template(
            "job_log.html",
            job=job,
            text=text,
            offset=offset,
        )

    return app
