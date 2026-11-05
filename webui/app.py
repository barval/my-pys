from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from router.llm_router import ConfigError

from .actions import CommandBuilder, HOST_ACTIONS, SPEAKER_ACTIONS
from .audit import record, redact
from .auth import init_auth
from .jobs import JobRunner
from .keys import key_inventory, rotate_router_token, set_upstream_key
from .profiles import load_profiles, mask_secret
from .router_config import delete_route, read_config, save_config, upsert_route
from .settings import Settings, load_settings

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_ROUTER_ACTIONS = {"router-start", "router-stop", "router-restart"}


def _route_from_form(form, name: str, existing: dict) -> dict:
    base_url = form.get("base_url", "").strip()
    model = form.get("model", "").strip()
    token_file = form.get("token_file", "").strip()
    history = form.get("history", "server").strip()
    api_key_file = form.get("api_key_file", "").strip()
    try:
        timeout_seconds = float(form.get("timeout_seconds", "180") or "180")
    except ValueError as exc:
        raise ValueError("timeout_seconds должен быть числом") from exc

    errors: list[str] = []
    if not model:
        errors.append("model обязателен")
    if not base_url.startswith(("http://", "https://")):
        errors.append("base_url должен начинаться с http:// или https://")
    if not token_file or Path(token_file).name != token_file:
        errors.append("token_file должен быть именем файла без каталогов")
    if api_key_file and Path(api_key_file).name != api_key_file:
        errors.append("api_key_file должен быть именем файла без каталогов")
    if history not in ("server", "client"):
        errors.append("history должен быть server или client")
    if errors:
        raise ValueError("; ".join(errors))

    fallback = None
    fallback_base = form.get("fallback_base_url", "").strip()
    if fallback_base:
        if not fallback_base.startswith(("http://", "https://")):
            raise ValueError("fallback_base_url должен быть http(s)-адресом")
        fallback_key_file = form.get("fallback_api_key_file", "").strip()
        if fallback_key_file and Path(fallback_key_file).name != fallback_key_file:
            raise ValueError(
                "fallback_api_key_file должен быть именем файла без каталогов"
            )
        fallback = {
            "base_url": fallback_base,
            "api_key_file": fallback_key_file,
            "model": form.get("fallback_model", "").strip(),
            "history": form.get("fallback_history", "client").strip(),
            "timeout_seconds": timeout_seconds,
        }

    primary = dict(existing.get("primary") or {})
    primary.update(
        {
            "base_url": base_url,
            "api_key_file": api_key_file,
            "model": model,
            "history": history,
            "timeout_seconds": timeout_seconds,
        }
    )
    session = dict(existing.get("session") or {})
    session.setdefault("mode", "server")
    session.setdefault("user", "voice")
    session.setdefault("idle_minutes", 30)
    session.setdefault("cleanup_keep", 3)
    return {
        "name": name,
        "token_file": token_file,
        "session": session,
        "primary": primary,
        "fallback": fallback,
    }


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
        CommandBuilder(
            settings.root,
            router_control=settings.router_control,
            sidecar_url=settings.sidecar_url,
        ),
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

    def router_config() -> dict:
        try:
            return read_config(settings.router_config)
        except (OSError, ValueError):
            return {"routes": []}

    def health() -> tuple[dict, int]:
        try:
            with urllib.request.urlopen(
                settings.router_health_url, timeout=2
            ) as response:
                return json.loads(response.read().decode("utf-8")), 200
        except Exception:
            return {"status": "unavailable", "routes": []}, 503

    def find_route(raw: dict, name: str) -> dict | None:
        for route in raw.get("routes", []):
            if route.get("name") == name:
                return route
        return None

    def audit(action: str, target: str, result: str = "ok", detail: str = "") -> None:
        record(
            settings.state_dir / "audit.jsonl",
            "admin",
            action,
            target,
            result,
            detail,
            secrets_dir=settings.secrets_dir,
        )

    def allowed_router_actions() -> set[str]:
        if settings.router_control == "sidecar":
            return {"router-restart"}
        return _ROUTER_ACTIONS

    def submit_host(action: str):
        if action not in allowed_router_actions():
            abort(404)
        job = app.extensions["jobs"].submit(action, None)
        audit(action, "router", detail=f"job={job.id}")
        return redirect(url_for("job_page", job_id=job.id), code=303)

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
        audit(f"speaker.{action}", profile.name, detail=f"job={job.id}")
        return redirect(url_for("job_page", job_id=job.id), code=303)

    @app.get("/jobs/<job_id>")
    def job_page(job_id: str):
        job = app.extensions["jobs"].get(job_id)
        if job is None:
            abort(404)
        text, offset = app.extensions["jobs"].tail(job_id, 0)
        text = redact(text, settings.secrets_dir)
        return render_template("job.html", job=job, text=text, offset=offset)

    @app.get("/jobs/<job_id>/log")
    def job_log(job_id: str):
        job = app.extensions["jobs"].get(job_id)
        if job is None:
            abort(404)
        text, offset = app.extensions["jobs"].tail(job_id, 0)
        return render_template("job_log.html", job=job, text=text, offset=offset)

    @app.get("/router")
    def router_page():
        payload, status = health()
        return render_template(
            "router.html",
            routes=router_config().get("routes", []),
            health=payload,
            health_status=status,
            actions={
                key: value
                for key, value in HOST_ACTIONS.items()
                if key in allowed_router_actions()
            },
        )

    @app.get("/router/health")
    def router_health():
        payload, status = health()
        return jsonify(payload), status

    @app.get("/router/routes/<name>")
    def route_edit(name: str):
        raw = router_config()
        route = find_route(raw, name)
        if route is None:
            abort(404)
        return render_template("route_edit.html", route=route, error=None)

    @app.post("/router/routes/<name>")
    def route_save(name: str):
        if not _NAME_RE.fullmatch(name):
            abort(404)
        raw = router_config()
        existing = find_route(raw, name) or {}
        try:
            route = _route_from_form(request.form, name, existing)
            save_config(settings.router_config, upsert_route(raw, route))
            audit("router.save", name)
        except (ValueError, ConfigError, OSError) as exc:
            return (
                render_template(
                    "route_edit.html",
                    route=existing or {"name": name},
                    error=str(exc),
                ),
                400,
            )
        return redirect(url_for("router_page"))

    @app.post("/router/routes/<name>/delete")
    def route_delete(name: str):
        raw = router_config()
        try:
            save_config(settings.router_config, delete_route(raw, name))
            audit("router.delete", name)
        except KeyError:
            abort(404)
        except (ConfigError, OSError) as exc:
            return str(exc), 400
        return redirect(url_for("router_page"))

    @app.post("/router/restart")
    def router_restart():
        return submit_host("router-restart")

    @app.post("/router/actions/<action>")
    def router_action(action: str):
        return submit_host(action)

    def route_names() -> list[str]:
        return [
            route["name"]
            for route in router_config().get("routes", [])
            if route.get("name")
        ]

    @app.get("/keys")
    def keys_page():
        names = route_names()
        return render_template(
            "keys.html",
            items=key_inventory(settings.secrets_dir, names),
            new_token=session.pop("new_token", None),
        )

    @app.post("/keys/router/<route>/rotate")
    def keys_rotate(route: str):
        if route not in route_names():
            abort(404)
        session["new_token"] = rotate_router_token(settings.secrets_dir, route)
        audit("keys.rotate", route)
        return redirect(url_for("keys_page"))

    @app.post("/keys/upstream/<route>/<provider>")
    def keys_upstream(route: str, provider: str):
        if route not in route_names() or provider not in ("flai", "orca"):
            abort(404)
        try:
            set_upstream_key(
                settings.secrets_dir,
                route,
                provider,
                request.form.get("value", ""),
            )
        except ValueError as exc:
            return str(exc), 400
        audit(f"keys.upstream.{provider}", route)
        return redirect(url_for("keys_page"))

    @app.get("/audit")
    def audit_page():
        path = settings.state_dir / "audit.jsonl"
        entries = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[-200:]:
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
        except OSError:
            entries = []
        return render_template("audit.html", entries=list(reversed(entries)))

    return app
