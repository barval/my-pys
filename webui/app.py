from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path

import tempfile
from datetime import datetime, timezone

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from router.llm_router import ConfigError

from . import APP_TITLE, __version__
from .actions import CommandBuilder, HOST_ACTIONS, SPEAKER_ACTIONS
from .appearance import (
    COLOR_CHOICES,
    COLOR_MAP,
    canonical_color,
    load_overrides,
    resolve_color,
    resolve_color_name,
    resolve_model,
    save_override,
)
from .audit import record, redact
from .auth import init_auth, save_password_hash, verify_password
from .backup import (
    BackupError,
    create_backup,
    inspect_backup,
    list_backups,
    resolve_backup,
    restore_backup,
)
from .jobs import JobRunner
from .keys import (
    add_upstream_key,
    delete_upstream_key,
    key_inventory,
    rotate_router_token,
    set_upstream_key,
    upstream_key_list,
)
from .profiles import load_profiles, parse_env
from .router_config import delete_route, read_config, save_config, upsert_route
from .settings import Settings, load_settings

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_ROUTER_ACTIONS = {"router-start", "router-stop", "router-restart"}
_FIRMWARE_ACTIONS = {"firmware", "stand-start", "stand-stop", "stand-status"}
MAX_FALLBACKS = 9


def route_fallbacks(route: dict) -> list[dict]:
    raw = route.get("fallbacks")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    legacy = route.get("fallback")
    return [legacy] if isinstance(legacy, dict) else []


def _upstream_from_form(form, *, prefix: str = "", default_history: str = "server") -> dict:
    base_url = form.get(f"{prefix}base_url", "").strip()
    model = form.get(f"{prefix}model", "").strip()
    api_key_file = form.get(f"{prefix}api_key_file", "").strip()
    history = form.get(f"{prefix}history", default_history).strip()
    try:
        timeout_seconds = float(
            form.get(f"{prefix}timeout_seconds", "180") or "180"
        )
    except ValueError as exc:
        raise ValueError("timeout_seconds должен быть числом") from exc

    errors: list[str] = []
    if not model:
        errors.append("model обязателен")
    if not base_url.startswith(("http://", "https://")):
        errors.append("base_url должен начинаться с http:// или https://")
    if api_key_file and Path(api_key_file).name != api_key_file:
        errors.append("api_key_file должен быть именем файла без каталогов")
    if history not in ("server", "client"):
        errors.append("history должен быть server или client")
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "base_url": base_url,
        "api_key_file": api_key_file,
        "model": model,
        "history": history,
        "timeout_seconds": timeout_seconds,
    }


def _route_from_form(
    form, name: str, existing: dict, token_file: str | None = None
) -> dict:
    token_file = (token_file or form.get("token_file", "")).strip()
    if not token_file or Path(token_file).name != token_file:
        raise ValueError("token_file должен быть именем файла без каталогов")
    primary = _upstream_from_form(form, default_history="server")
    fallbacks = route_fallbacks(existing)
    if form.get("fallback_base_url", "").strip():
        fallbacks = [
            _upstream_from_form(form, prefix="fallback_", default_history="client")
        ]
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
        "fallbacks": fallbacks,
    }


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or load_settings()
    app = Flask(
        __name__,
        template_folder=str(settings.templates_dir),
        static_folder=str(settings.static_dir),
    )
    app.config["WEBUI_SETTINGS"] = settings
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.config["WEBUI_TITLE"] = APP_TITLE
    app.config["WEBUI_VERSION"] = __version__
    app.config["WEBUI_STAND_IP"] = settings.stand_ip
    app.config["WEBUI_ROUTER_DISPLAY_URL"] = settings.router_display_url
    app.config["WEBUI_ROUTER_HEALTH_DISPLAY_URL"] = settings.router_health_display_url
    asset = settings.static_dir / "app.css"
    app.config["WEBUI_ASSET_VERSION"] = (
        str(int(asset.stat().st_mtime)) if asset.exists() else "1"
    )
    init_auth(app, settings)

    profiles = {profile.name: profile for profile in load_profiles(settings.speakers_dir)}
    runner = JobRunner(
        settings.state_dir,
        CommandBuilder(
            settings.root,
            router_control=settings.router_control,
            sidecar_url=settings.sidecar_url,
            stand_control=settings.stand_control,
            stand_url=settings.stand_url,
        ),
        max_workers=settings.max_workers,
        timeout=settings.job_timeout,
    )
    app.extensions["profiles"] = profiles
    app.extensions["jobs"] = runner
    appearance_path = settings.state_dir / "speaker-appearance.json"

    def reload_profiles() -> None:
        profiles.clear()
        profiles.update(
            {profile.name: profile for profile in load_profiles(settings.speakers_dir)}
        )

    def profiles_mtime() -> float:
        try:
            return max(
                path.stat().st_mtime
                for path in settings.speakers_dir.glob("*.env")
            )
        except ValueError:
            return 0.0

    profile_state = {"mtime": profiles_mtime()}

    def refresh_profiles() -> None:
        mtime = profiles_mtime()
        if mtime != profile_state["mtime"]:
            reload_profiles()
            profile_state["mtime"] = mtime

    def speaker_cards() -> list[dict]:
        refresh_profiles()
        overrides = load_overrides(appearance_path)
        return [
            {
                "profile": profile,
                "override": overrides.get(profile.device_id, {}),
                "model": resolve_model(
                    profile, overrides.get(profile.device_id, {})
                ),
                "color": resolve_color(
                    profile, overrides.get(profile.device_id, {})
                ),
                "color_name": resolve_color_name(
                    profile, overrides.get(profile.device_id, {})
                ),
                "color_key": canonical_color(
                    overrides.get(profile.device_id, {}).get("color")
                    or profile.color
                ),
            }
            for profile in sorted(profiles.values(), key=lambda item: item.name)
        ]

    def get_profile(name: str):
        refresh_profiles()
        profile = profiles.get(name)
        if profile is None:
            abort(404)
        return profile

    def firmware_files() -> list[dict]:
        directory = (
            settings.root / "vendor" / "lite-kit" / "firmware" / "yandexmicro"
        )
        result = []
        try:
            paths = sorted(directory.glob("*.zip"))
        except OSError:
            return result
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                continue
            result.append(
                {
                    "name": path.name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(timespec="seconds"),
                }
            )
        return result

    def router_config() -> dict:
        try:
            return read_config(settings.router_config)
        except (OSError, ValueError):
            return {"routes": []}

    def health(probe: bool = False) -> tuple[dict, int]:
        url = settings.router_health_url
        if probe:
            url += ("&" if "?" in url else "?") + "probe=1"
        try:
            with urllib.request.urlopen(
                url, timeout=12 if probe else 2
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
        return jsonify({"status": "ok", "version": __version__})

    @app.after_request
    def no_html_cache(response):
        if response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return redirect(url_for("speakers_page"))

    @app.get("/speakers")
    def speakers_page():
        return render_template("speakers.html", cards=speaker_cards())

    @app.get("/speakers/<name>")
    def speaker_page(name: str):
        profile = get_profile(name)
        card = next(
            item for item in speaker_cards() if item["profile"].name == name
        )
        jobs = [
            job
            for job in app.extensions["jobs"].list(limit=100)
            if job.target == profile.name
        ][:10]
        return render_template(
            "speaker.html",
            profile=profile,
            card=card,
            color_choices=COLOR_CHOICES,
            actions=SPEAKER_ACTIONS.values(),
            jobs=jobs,
        )

    @app.post("/speakers/<name>/appearance")
    def speaker_appearance(name: str):
        profile = get_profile(name)
        color = request.form.get("color", "").strip()
        model = request.form.get("model", "").strip()
        if color and color not in COLOR_MAP and not re.fullmatch(
            r"#[0-9a-fA-F]{6}", color
        ):
            return "недопустимый цвет", 400
        save_override(appearance_path, profile.device_id, color, model)
        audit("speaker.appearance", name)
        return redirect(url_for("speaker_page", name=name))

    @app.post("/speakers/<name>/actions/<action>")
    def speaker_action(name: str, action: str):
        profile = get_profile(name)
        if action not in SPEAKER_ACTIONS:
            abort(404)
        job = app.extensions["jobs"].submit(action, profile)
        audit(f"speaker.{action}", profile.name, detail=f"job={job.id}")
        return redirect(url_for("job_page", job_id=job.id), code=303)

    max_say_chars = 500

    @app.post("/speakers/<name>/say")
    def speaker_say(name: str):
        profile = get_profile(name)
        text = (request.form.get("text") or "").strip()
        if not text:
            flash("Введите текст для озвучки")
            return redirect(url_for("speaker_page", name=name))
        if len(text) > max_say_chars:
            flash(f"Слишком длинный текст: до {max_say_chars} символов")
            return redirect(url_for("speaker_page", name=name))
        job = app.extensions["jobs"].submit_command(
            "say",
            profile.name,
            ["bash", "scripts/say-text.sh"],
            {
                "SPEAKER_ENV": str(profile.path),
                "SPEAKER_TRUST_IP": "1",
                "SAY_TEXT": text,
            },
        )
        audit("speaker.say", profile.name, detail=f"job={job.id}")
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

    def normalized_routes() -> list[dict]:
        result = []
        for route in router_config().get("routes", []):
            item = dict(route)
            item["fallbacks"] = route_fallbacks(route)
            item.pop("fallback", None)
            result.append(item)
        return result

    registry_path = settings.state_dir / "upstream-keys.json"

    def upstream_keys():
        return upstream_key_list(
            registry_path, settings.secrets_dir, normalized_routes()
        )

    @app.get("/firmware")
    def firmware_page():
        return render_template(
            "firmware.html",
            cards=speaker_cards(),
            firmware_files=firmware_files(),
            speaker_actions=SPEAKER_ACTIONS.values(),
            host_actions={
                key: value
                for key, value in HOST_ACTIONS.items()
                if key in _FIRMWARE_ACTIONS
            },
        )

    @app.post("/firmware/actions/<action>")
    def firmware_action(action: str):
        if action not in _FIRMWARE_ACTIONS:
            abort(404)
        job = app.extensions["jobs"].submit(action, None)
        audit(f"firmware.{action}", "host", detail=f"job={job.id}")
        return redirect(url_for("job_page", job_id=job.id), code=303)

    @app.get("/router")
    def router_page():
        probe = request.args.get("probe", "").lower() in ("1", "true", "yes")
        payload, status = health(probe=probe)
        probe_results = (
            {item["name"]: item for item in payload.get("routes", [])}
            if probe
            else {}
        )
        return render_template(
            "router.html",
            routes=normalized_routes(),
            probe_requested=probe,
            probe_results=probe_results,
            max_fallbacks=MAX_FALLBACKS,
            fallback_count=sum(
                len(route["fallbacks"]) for route in normalized_routes()
            ),
            new_token=session.pop("new_route_token", None),
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

    @app.get("/router/routes/new")
    def route_new():
        return render_template(
            "route_new.html", error=None, upstream_keys=upstream_keys()
        )

    @app.post("/router/routes/new")
    def route_create():
        name = request.form.get("name", "").strip()
        if not _NAME_RE.fullmatch(name):
            return render_template(
                "route_new.html",
                error="Имя: латиница, цифры и дефис",
                upstream_keys=upstream_keys(),
            ), 400
        raw = router_config()
        if find_route(raw, name) is not None:
            return render_template(
                "route_new.html",
                error="Маршрут уже существует",
                upstream_keys=upstream_keys(),
            ), 400
        try:
            token = rotate_router_token(settings.secrets_dir, f"router-token-{name}")
            route = _route_from_form(
                request.form,
                name,
                {"primary": {}, "fallbacks": []},
                token_file=f"router-token-{name}",
            )
            save_config(settings.router_config, upsert_route(raw, route))
        except (ValueError, ConfigError, OSError) as exc:
            return render_template(
                "route_new.html", error=str(exc), upstream_keys=upstream_keys()
            ), 400
        session["new_route_token"] = token
        audit("router.create", name)
        flash(f"Маршрут {name} создан")
        return redirect(url_for("router_page"))

    @app.get("/router/routes/<name>")
    def route_edit(name: str):
        raw = router_config()
        route = find_route(raw, name)
        if route is None:
            abort(404)
        route = dict(route)
        route["fallbacks"] = route_fallbacks(route)
        route.pop("fallback", None)
        return render_template(
            "route_edit.html",
            route=route,
            error=None,
            upstream_keys=upstream_keys(),
        )

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
                    upstream_keys=upstream_keys(),
                ),
                400,
            )
        return redirect(url_for("router_page"))

    @app.get("/router/routes/<name>/fallback/new")
    def fallback_new(name: str):
        raw = router_config()
        route = find_route(raw, name)
        if route is None:
            abort(404)
        if len(route_fallbacks(route)) >= MAX_FALLBACKS:
            flash(f"Достигнут лимит {MAX_FALLBACKS} запасных маршрутов")
            return redirect(url_for("router_page"))
        return render_template(
            "route_fallback.html",
            route=route,
            fallback={},
            index=None,
            error=None,
            upstream_keys=upstream_keys(),
        )

    @app.post("/router/routes/<name>/fallback/new")
    def fallback_create(name: str):
        raw = router_config()
        route = find_route(raw, name)
        if route is None:
            abort(404)
        if len(route_fallbacks(route)) >= MAX_FALLBACKS:
            flash(f"Достигнут лимит {MAX_FALLBACKS} запасных маршрутов")
            return redirect(url_for("router_page"))
        try:
            fallback = _upstream_from_form(
                request.form, default_history="client"
            )
            fallbacks = route_fallbacks(route) + [fallback]
            updated = dict(route)
            updated["fallbacks"] = fallbacks
            updated.pop("fallback", None)
            save_config(settings.router_config, upsert_route(raw, updated))
            audit("router.fallback.create", name)
        except (ValueError, ConfigError, OSError) as exc:
            return render_template(
                "route_fallback.html",
                route=route,
                fallback=request.form,
                index=None,
                error=str(exc),
                upstream_keys=upstream_keys(),
            ), 400
        return redirect(url_for("router_page"))

    @app.get("/router/routes/<name>/fallback/<int:index>")
    def fallback_edit(name: str, index: int):
        raw = router_config()
        route = find_route(raw, name)
        if route is None:
            abort(404)
        fallbacks = route_fallbacks(route)
        if index < 0 or index >= len(fallbacks):
            abort(404)
        return render_template(
            "route_fallback.html",
            route=route,
            fallback=fallbacks[index],
            index=index,
            error=None,
            upstream_keys=upstream_keys(),
        )

    @app.post("/router/routes/<name>/fallback/<int:index>")
    def fallback_save(name: str, index: int):
        raw = router_config()
        route = find_route(raw, name)
        if route is None:
            abort(404)
        fallbacks = route_fallbacks(route)
        if index < 0 or index >= len(fallbacks):
            abort(404)
        try:
            fallbacks[index] = _upstream_from_form(
                request.form, default_history="client"
            )
            updated = dict(route)
            updated["fallbacks"] = fallbacks
            updated.pop("fallback", None)
            save_config(settings.router_config, upsert_route(raw, updated))
            audit("router.fallback.save", name)
        except (ValueError, ConfigError, OSError) as exc:
            return render_template(
                "route_fallback.html",
                route=route,
                fallback=request.form,
                index=index,
                error=str(exc),
                upstream_keys=upstream_keys(),
            ), 400
        return redirect(url_for("router_page"))

    @app.post("/router/routes/<name>/primary/move")
    def primary_move(name: str):
        raw = router_config()
        route = find_route(raw, name)
        if route is None:
            abort(404)
        if request.form.get("direction") != "down":
            abort(400)
        fallbacks = route_fallbacks(route)
        anchor = f"route-{name}"
        if not fallbacks:
            return redirect(url_for("router_page", _anchor=anchor))
        primary = route.get("primary")
        fallbacks[0], primary = primary, fallbacks[0]
        updated = dict(route)
        updated["primary"] = primary
        updated["fallbacks"] = fallbacks
        updated.pop("fallback", None)
        try:
            save_config(settings.router_config, upsert_route(raw, updated))
        except (ConfigError, OSError) as exc:
            return str(exc), 400
        audit("router.primary.move", name, detail="primary<->fallback1")
        return redirect(url_for("router_page", _anchor=anchor))

    @app.post("/router/routes/<name>/fallback/<int:index>/move")
    def fallback_move(name: str, index: int):
        raw = router_config()
        route = find_route(raw, name)
        if route is None:
            abort(404)
        fallbacks = route_fallbacks(route)
        direction = request.form.get("direction", "")
        if direction not in ("up", "down"):
            abort(400)
        if index < 0 or index >= len(fallbacks):
            abort(404)
        anchor = f"route-{name}"
        updated = dict(route)
        if direction == "up" and index == 0:
            primary = route.get("primary")
            fallbacks[0], primary = primary, fallbacks[0]
            updated["primary"] = primary
        else:
            target = index - 1 if direction == "up" else index + 1
            if target < 0 or target >= len(fallbacks):
                return redirect(url_for("router_page", _anchor=anchor))
            fallbacks[index], fallbacks[target] = fallbacks[target], fallbacks[index]
            anchor = f"route-{name}-fallback-{target}"
        updated["fallbacks"] = fallbacks
        updated.pop("fallback", None)
        try:
            save_config(settings.router_config, upsert_route(raw, updated))
        except (ConfigError, OSError) as exc:
            return str(exc), 400
        audit("router.fallback.move", name, detail=f"{index} {direction}")
        return redirect(url_for("router_page", _anchor=anchor))

    @app.post("/router/routes/<name>/fallback/<int:index>/delete")
    def fallback_delete(name: str, index: int):
        raw = router_config()
        route = find_route(raw, name)
        if route is None:
            abort(404)
        fallbacks = route_fallbacks(route)
        if index < 0 or index >= len(fallbacks):
            abort(404)
        del fallbacks[index]
        updated = dict(route)
        updated["fallbacks"] = fallbacks
        updated.pop("fallback", None)
        try:
            save_config(settings.router_config, upsert_route(raw, updated))
            audit("router.fallback.delete", name)
        except (ConfigError, OSError) as exc:
            return str(exc), 400
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

    @app.get("/keys")
    def keys_page():
        return render_template(
            "keys.html",
            items=key_inventory(settings.secrets_dir, normalized_routes()),
            upstream_keys=upstream_keys(),
            new_token=session.pop("new_token", None),
            new_token_note=session.pop("new_token_note", None),
            new_token_job=session.pop("new_token_job", None),
        )

    def speaker_for_token_file(token_file: str):
        """Колонка, у которой LLM_TOKEN_FILE указывает на этот файл."""
        refresh_profiles()
        target = (settings.secrets_dir / Path(token_file).name).resolve()
        for profile in profiles.values():
            value = parse_env(profile.path).get("LLM_TOKEN_FILE", "").strip()
            if not value:
                continue
            candidate = Path(value)
            if not candidate.is_absolute():
                candidate = settings.root / candidate
            if candidate.resolve() == target:
                return profile
        return None

    @app.post("/keys/router/<route>/rotate")
    def keys_rotate(route: str):
        raw = router_config()
        item = find_route(raw, route)
        if item is None:
            abort(404)
        token_file = item.get("token_file", "")
        if not token_file:
            abort(404)
        session["new_token"] = rotate_router_token(
            settings.secrets_dir, token_file
        )
        profile = speaker_for_token_file(token_file)
        if profile is None:
            session["new_token_note"] = (
                "Колонка с этим token_file не найдена — запишите токен вручную."
            )
            audit("keys.rotate", route)
        else:
            job = app.extensions["jobs"].submit("key", profile)
            session["new_token_note"] = (
                f"Запись в колонку {profile.name} запущена."
            )
            session["new_token_job"] = job.id
            audit("keys.rotate", route, detail=f"job={job.id}")
        return redirect(url_for("keys_page"))

    @app.post("/keys/upstream")
    def keys_upstream_add():
        try:
            key_file = add_upstream_key(
                registry_path,
                settings.secrets_dir,
                request.form.get("label", ""),
                request.form.get("file", ""),
                request.form.get("value", ""),
            )
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("keys_page"))
        audit("keys.upstream.add", key_file)
        flash(f"Ключ {key_file} добавлен")
        return redirect(url_for("keys_page"))

    @app.post("/keys/upstream/<key_file>")
    def keys_upstream_save(key_file: str):
        if key_file not in {item.file for item in upstream_keys()}:
            abort(404)
        try:
            set_upstream_key(
                settings.secrets_dir,
                key_file,
                request.form.get("value", ""),
            )
        except ValueError as exc:
            return str(exc), 400
        audit("keys.upstream", key_file)
        return redirect(url_for("keys_page"))

    @app.post("/keys/upstream/<key_file>/delete")
    def keys_upstream_delete(key_file: str):
        try:
            delete_upstream_key(
                registry_path,
                settings.secrets_dir,
                key_file,
                normalized_routes(),
            )
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("keys_page"))
        audit("keys.upstream.delete", key_file)
        flash(f"Ключ {key_file} удалён")
        return redirect(url_for("keys_page"))

    @app.get("/backup")
    def backup_page():
        return render_template(
            "backup.html",
            backups=list_backups(settings),
            profiles=sorted(profiles.values(), key=lambda item: item.name),
            inspection=None,
        )

    @app.post("/backup/create")
    def backup_create():
        scope = request.form.get("scope", "all")
        passphrase = request.form.get("passphrase", "")
        confirm = request.form.get("confirm", "")
        if passphrase != confirm:
            flash("Пароли архива не совпадают")
            return redirect(url_for("backup_page"))
        try:
            path = create_backup(settings, scope, passphrase)
        except BackupError as exc:
            flash(str(exc))
            return redirect(url_for("backup_page"))
        audit("backup.create", scope, detail=path.name)
        flash(f"Архив создан: {path.name}")
        return redirect(url_for("backup_page"))

    @app.post("/backup/inspect")
    def backup_inspect():
        name = request.form.get("backup", "")
        passphrase = request.form.get("passphrase", "")
        try:
            manifest = inspect_backup(settings, name, passphrase)
        except BackupError as exc:
            flash(str(exc))
            return redirect(url_for("backup_page"))
        return render_template(
            "backup.html",
            backups=list_backups(settings),
            profiles=sorted(profiles.values(), key=lambda item: item.name),
            inspection=manifest,
        )

    @app.get("/backup/download/<name>")
    def backup_download(name: str):
        try:
            path = resolve_backup(settings, name)
        except BackupError:
            abort(404)
        response = send_file(
            path,
            as_attachment=True,
            download_name=path.name,
            mimetype="application/octet-stream",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/backup/restore")
    def backup_restore():
        passphrase = request.form.get("passphrase", "")
        confirm = request.form.get("confirm", "")
        uploaded = request.files.get("archive")
        temp_path: Path | None = None
        try:
            if uploaded is not None and uploaded.filename:
                if not uploaded.filename.endswith(".tar.gz.enc"):
                    raise BackupError("ожидается файл .tar.gz.enc")
                descriptor, name = tempfile.mkstemp(
                    dir=str(settings.state_dir), suffix=".tar.gz.enc"
                )
                os.close(descriptor)
                temp_path = Path(name)
                os.chmod(temp_path, 0o600)
                uploaded.save(temp_path)
                source = temp_path
            else:
                source = resolve_backup(
                    settings, request.form.get("backup", "")
                )
            summary = restore_backup(
                settings, source, passphrase, confirm
            )
            reload_profiles()
            audit(
                "backup.restore",
                summary.get("speaker") or "all",
                detail=f"files={summary['restored']}",
            )
            flash(
                "Конфигурация восстановлена. "
                f"Файлов: {summary['restored']}. "
                f"Снапшот: {summary['snapshot']}"
            )
        except BackupError as exc:
            flash(str(exc))
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        return redirect(url_for("backup_page"))

    @app.get("/password")
    def password_page():
        return render_template("password.html", error=None)

    @app.post("/password")
    def password_change():
        current = request.form.get("current", "")
        new = request.form.get("new", "")
        confirm = request.form.get("confirm", "")
        if new != confirm:
            return render_template(
                "password.html", error="Новые пароли не совпадают"
            ), 400
        if len(new) < 8:
            return render_template(
                "password.html", error="Пароль должен быть не короче 8 символов"
            ), 400
        try:
            encoded = settings.admin_hash_file.read_text(encoding="utf-8").strip()
        except OSError:
            return render_template(
                "password.html", error="Пароль администратора не настроен"
            ), 503
        if not verify_password(current, encoded):
            return render_template(
                "password.html", error="Текущий пароль неверен"
            ), 400
        save_password_hash(settings.admin_hash_file, new)
        audit("auth.password", "admin")
        session.clear()
        session["notice"] = "Пароль изменён. Войдите заново."
        return redirect(url_for("login"))

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
