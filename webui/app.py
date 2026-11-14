from __future__ import annotations

import json
import math
import os
import re
import threading
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
from markupsafe import Markup, escape

from router.llm_router import ConfigError

from . import APP_TITLE, __version__
from .actions import CommandBuilder, HOST_ACTIONS, SPEAKER_ACTIONS
from .appearance import (
    COLOR_CHOICES,
    COLOR_MAP,
    canonical_color,
    load_overrides,
    remove_override,
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
from .discovery import merge_known_profiles, scan
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
from .profile_writer import archive_profile, merge_profile_env, validate_profile, write_profile
from .providers import (
    Provider,
    delete_provider,
    fetch_models,
    load_providers,
    slugify,
    upsert_provider,
)
from .router_config import delete_route, read_config, save_config, upsert_route
from .settings import Settings, load_settings
from .status import sync_from_jobs
from .subnets import fallback_prefixes, load_subnets, subnet_prefixes
from .wizard import HOST_STEP, STEPS, Progress, advance, load_progress, save_progress, set_last_job, step_by_number

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,50}$")
_ROUTER_ACTIONS = {"router-start", "router-stop", "router-restart"}
_FIRMWARE_ACTIONS = {"firmware", "stand-start", "stand-stop", "stand-status"}
MAX_FALLBACKS = 9
SETUP_ACTIONS = {4: "adb", 5: "root", 7: "bridge", 8: "check"}
JOB_STATUS_LABELS = {
    "queued": "в очереди",
    "running": "выполняется",
    "succeeded": "выполнено",
    "failed": "ошибка",
    "cancelled": "отменено",
    "interrupted": "прервано",
}
JOB_ACTION_LABELS = {
    **{key: spec.label for key, spec in SPEAKER_ACTIONS.items()},
    **{key: spec.label for key, spec in HOST_ACTIONS.items()},
    "say": "Произнести",
}


def render_breadcrumbs(items) -> Markup:
    """Цепочка разделов: последний элемент — текущая страница без ссылки."""
    chunks = []
    total = len(items)
    for index, (label, href) in enumerate(items):
        text = escape(str(label))
        if href and index < total - 1:
            chunks.append(f'<a href="{escape(href)}">{text}</a>')
        else:
            chunks.append(f'<span class="breadcrumb-current">{text}</span>')
    separator = '<span class="breadcrumb-sep">←</span>'
    return Markup(
        '<nav class="breadcrumbs" aria-label="Навигация">'
        + separator.join(chunks)
        + "</nav>"
    )


def format_size(value: int) -> str:
    """Размер в байтах с пробелами между разрядами."""
    return f"{value:,}".replace(",", " ") + " байт"


def json_for_pre(value, secrets_dir=None) -> str:
    """JSON для <pre>: секреты редактируются, кавычки остаются как есть,
    HTML-спецсимволы экранируются."""
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if secrets_dir is not None:
        text = redact(text, secrets_dir)
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


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
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds должен быть положительным числом")

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


def _upstream_from_provider(
    form, providers: list[Provider], *, default_history: str = "server"
) -> dict:
    provider_id = form.get("provider_id", "").strip()
    provider = next((p for p in providers if p.id == provider_id), None)
    if provider is None:
        raise ValueError("выберите провайдера")
    model = form.get("model", "").strip()
    if not model or model not in provider.models:
        raise ValueError("выберите модель из списка провайдера")
    api_key_file = form.get("api_key_file", "").strip()
    if api_key_file and Path(api_key_file).name != api_key_file:
        raise ValueError("api_key_file должен быть именем файла без каталогов")
    history = form.get("history", default_history).strip()
    if history not in ("server", "client"):
        raise ValueError("history должен быть server или client")
    try:
        timeout_seconds = float(form.get("timeout_seconds") or form.get("timeout") or "180")
    except ValueError as exc:
        raise ValueError("timeout_seconds должен быть числом") from exc
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds должен быть положительным числом")
    return {
        "base_url": provider.base_url,
        "api_key_file": api_key_file,
        "model": model,
        "history": history,
        "timeout_seconds": timeout_seconds,
    }


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or load_settings()
    app = Flask(
        __name__,
        template_folder=str(settings.templates_dir),
        static_folder=str(settings.static_dir),
    )
    app.config["WEBUI_SETTINGS"] = settings
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.config["WEBUI_TITLE"] = APP_TITLE
    app.config["WEBUI_VERSION"] = __version__
    app.config["WEBUI_STAND_IP"] = settings.stand_ip
    app.config["WEBUI_ROUTER_DISPLAY_URL"] = settings.router_display_url
    app.config["WEBUI_ROUTER_HEALTH_DISPLAY_URL"] = settings.router_health_display_url
    assets = [
        settings.static_dir / "app.css",
        settings.static_dir / "app.js",
    ]
    mtimes = [path.stat().st_mtime for path in assets if path.exists()]
    app.config["WEBUI_ASSET_VERSION"] = (
        str(int(max(mtimes))) if mtimes else "1"
    )
    init_auth(app, settings)
    app.jinja_env.globals["job_status_label"] = (
        lambda status: JOB_STATUS_LABELS.get(status, status)
    )
    app.jinja_env.globals["job_action_label"] = (
        lambda action: JOB_ACTION_LABELS.get(action, action)
    )
    app.jinja_env.globals["breadcrumbs"] = render_breadcrumbs
    app.jinja_env.globals["format_size"] = format_size

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
    status_path = settings.state_dir / "speaker-status.json"

    def speaker_statuses(jobs: list | None = None) -> dict:
        runner = app.extensions["jobs"]
        jobs_list = jobs if jobs is not None else (
            runner.list(limit=200) if hasattr(runner, "list") else []
        )
        return sync_from_jobs(status_path, jobs_list)

    profiles_lock = threading.RLock()

    def reload_profiles() -> None:
        nonlocal profiles
        loaded = {
            profile.name: profile
            for profile in load_profiles(settings.speakers_dir)
        }
        with profiles_lock:
            profiles = loaded
            app.extensions["profiles"] = loaded

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
        with profiles_lock:
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
                    "size_text": format_size(stat.st_size),
                    "modified": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(timespec="seconds"),
                }
            )
        return result

    def router_config() -> dict:
        if not settings.router_config.exists():
            return {"routes": []}
        try:
            return read_config(settings.router_config)
        except (OSError, ValueError) as exc:
            raise ConfigError(
                f"Файл маршрутов повреждён или недоступен: {exc}"
            ) from exc

    def progress_path(name: str) -> Path:
        return settings.state_dir / "setup" / f"{name}.json"

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

    providers_path = settings.state_dir / "providers.json"

    def providers() -> list[Provider]:
        return load_providers(providers_path, normalized_routes())

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

    def audit_entries() -> list[dict]:
        path = settings.state_dir / "audit.jsonl"
        entries: list[dict] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[-100:]:
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
        except OSError:
            entries = []
        return list(reversed(entries))

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

    @app.get("/start")
    def start_page():
        return render_template(
            "start.html",
            host_step=HOST_STEP,
            has_profiles=bool(profiles),
        )

    @app.get("/")
    def speakers_page():
        query = request.args.get("q", "").strip()
        cards = speaker_cards()
        if query:
            needle = query.casefold()
            cards = [
                card for card in cards
                if needle in " ".join(
                    (card["profile"].name, card["profile"].room,
                     card["profile"].mac, card["profile"].device_id,
                     card["model"])
                ).casefold()
            ]
        runner = app.extensions["jobs"]
        jobs_list = runner.list(limit=200) if hasattr(runner, "list") else []
        jobs_running = any(
            getattr(job, "status", None) in ("queued", "running")
            for job in jobs_list
            if getattr(job, "action", None) == "status"
        )
        return render_template(
            "speakers.html",
            cards=cards,
            query=query,
            statuses=speaker_statuses(),
            probe=request.args.get("probe"),
            jobs_running=jobs_running,
        )

    @app.get("/speakers")
    def legacy_speakers():
        return redirect(url_for("speakers_page"), code=301)

    @app.get("/speakers/new")
    def speaker_new():
        error = None
        devices = None
        subnet = request.args.get("subnet", "192.168.1").strip() or "192.168.1"
        if request.args.get("scan") == "1":
            try:
                devices = scan(subnet)
                refresh_profiles()
                devices = merge_known_profiles(devices, profiles.values())
            except ValueError as exc:
                error = str(exc)
        subnets = subnet_prefixes(
            load_subnets(settings.state_dir / "host-subnets.json")
        ) or fallback_prefixes(profiles.values())
        return render_template(
            "speaker_new.html",
            error=error,
            devices=devices,
            subnet=subnet,
            subnets=subnets,
            color_choices=COLOR_CHOICES,
        )

    @app.post("/speakers/new")
    def speaker_create():
        form = request.form
        name = form.get("name", "").strip()
        values = {
            "SPEAKER_NAME": name,
            "SPEAKER_IP": form.get("ip", "").strip(),
            "SPEAKER_SUBNET": form.get("subnet", "").strip(),
            "SPEAKER_DEVICE_ID": form.get("device_id", "").strip(),
            "SPEAKER_MAC": form.get("mac", "").strip().lower(),
            "SPEAKER_ROOM": form.get("room", "").strip(),
            "SPEAKER_COLOR": form.get("color", "").strip().lower(),
            "SPEAKER_MODEL": form.get("model", "").strip(),
        }

        def form_error(message: str):
            return render_template(
                "speaker_new.html",
                error=message,
                devices=None,
                subnet=values["SPEAKER_SUBNET"] or "192.168.1",
                subnets=subnet_prefixes(
                    load_subnets(settings.state_dir / "host-subnets.json")
                ) or fallback_prefixes(profiles.values()),
                color_choices=COLOR_CHOICES,
            ), 400

        if name and (settings.speakers_dir / f"{name}.env").exists():
            return form_error("Колонка с таким именем уже существует")
        try:
            validate_profile(
                name,
                values["SPEAKER_IP"],
                values["SPEAKER_SUBNET"],
                values["SPEAKER_MAC"],
                values["SPEAKER_DEVICE_ID"],
            )
            color = values["SPEAKER_COLOR"]
            if color and color not in COLOR_MAP and not re.fullmatch(
                r"#[0-9a-fA-F]{6}", color
            ):
                raise ValueError("недопустимый цвет")
            write_profile(settings.speakers_dir, values)
        except ValueError as exc:
            return form_error(str(exc))
        reload_profiles()
        save_progress(progress_path(name), Progress(step=4))
        audit("speaker.create", name)
        return redirect(url_for("speaker_setup", name=name, step=4), code=303)

    @app.get("/speakers/<name>")
    def speaker_page(name: str):
        profile = get_profile(name)
        card = next(
            item for item in speaker_cards() if item["profile"].name == name
        )
        runner = app.extensions["jobs"]
        if hasattr(runner, "list"):
            all_jobs = runner.list(limit=200)
        else:
            all_jobs = []
        jobs = [
            job
            for job in all_jobs
            if job.target == profile.name
        ][:10]
        return render_template(
            "speaker.html",
            profile=profile,
            card=card,
            color_choices=COLOR_CHOICES,
            actions=SPEAKER_ACTIONS.values(),
            jobs=jobs,
            statuses=speaker_statuses(all_jobs),
        )

    @app.get("/speakers/<name>/setup")
    def speaker_setup(name: str):
        refresh_profiles()
        profile = profiles.get(name)
        if profile is None:
            return redirect(url_for("speaker_new"), code=303)
        progress = load_progress(progress_path(name))
        step_number = progress.step
        try:
            query_step = int(request.args.get("step", progress.step))
        except (TypeError, ValueError):
            query_step = progress.step
        if query_step in {s.number for s in STEPS}:
            step_number = query_step
        current = step_by_number(step_number)
        if current is None:
            current = step_by_number(progress.step) or STEPS[-1]
        card = next(
            item for item in speaker_cards() if item["profile"].name == name
        )
        return render_template(
            "setup.html",
            profile=profile,
            card=card,
            steps=STEPS,
            host_step=HOST_STEP,
            current=current,
            progress=progress,
            providers=providers(),
            upstream_keys=upstream_keys(),
            firmware_files=firmware_files(),
        )

    @app.post("/speakers/<name>/setup/<int:step>")
    def speaker_setup_step(name: str, step: int):
        refresh_profiles()
        profile = profiles.get(name)
        if profile is None:
            return redirect(url_for("speaker_new"), code=303)
        current = step_by_number(step)
        if current is None:
            abort(400)
        progress = load_progress(progress_path(name))
        op = request.form.get("op", "").strip()
        if op in ("done", "skip"):
            progress = advance(
                progress, current.key, skipped=(op == "skip")
            )
            save_progress(progress_path(name), progress)
            audit(f"setup.{op}", name)
            return redirect(url_for("speaker_setup", name=name), code=303)
        if op != "run":
            abort(400)
        if step == 6:
            return _setup_route_step(name, profile, progress)
        action = SETUP_ACTIONS.get(step)
        if action is None:
            abort(400)
        job = app.extensions["jobs"].submit(action, profile)
        progress = set_last_job(progress, job.id)
        save_progress(progress_path(name), progress)
        audit("setup.run", name, detail=f"step={current.key} job={job.id}")
        return redirect(url_for("job_page", job_id=job.id), code=303)

    def _setup_route_step(name: str, profile, progress):
        raw = router_config()
        route = find_route(raw, name)
        if route is None:
            provider_id = request.form.get("provider_id", "").strip()
            provider = next(
                (p for p in providers() if p.id == provider_id), None
            )
            if provider is None:
                flash("Сначала добавьте провайдера")
                return redirect(url_for("access_page", _anchor="providers"))
            model = request.form.get("model", "").strip()
            if not model or model not in provider.models:
                flash("Выберите модель из списка провайдера")
                return redirect(url_for("speaker_setup", name=name, step=6))
            api_key_file = request.form.get("api_key_file", "").strip()
            if api_key_file and Path(api_key_file).name != api_key_file:
                flash("Ключ должен быть именем файла без каталогов")
                return redirect(url_for("speaker_setup", name=name, step=6))
            token_file = f"router-token-{name}"
            token_path = settings.secrets_dir / token_file
            if not token_path.exists():
                rotate_router_token(settings.secrets_dir, token_file)
            route = {
                "name": name,
                "token_file": token_file,
                "session": {
                    "mode": "server",
                    "user": "voice",
                    "idle_minutes": 30,
                    "cleanup_keep": 3,
                },
                "primary": {
                    "base_url": provider.base_url,
                    "api_key_file": api_key_file,
                    "model": model,
                    "history": "server",
                    "timeout_seconds": 180,
                },
                "fallbacks": [],
            }
            save_config(settings.router_config, upsert_route(raw, route))
        token_file = route.get("token_file", f"router-token-{name}")
        token_path = settings.secrets_dir / token_file
        if not token_path.exists():
            rotate_router_token(settings.secrets_dir, token_file)
        try:
            model = route["primary"]["model"]
        except KeyError:
            return "Маршрут повреждён: отсутствует основной upstream", 400
        merge_profile_env(
            profile.path,
            {
                "LLM_BASE_URL": settings.router_display_url,
                "LLM_MODEL": model,
                "LLM_TOKEN_FILE": f"secrets/{token_file}",
            },
        )
        job = app.extensions["jobs"].submit("key", profile)
        progress = set_last_job(progress, job.id)
        save_progress(progress_path(name), progress)
        audit("setup.route", name, detail=f"job={job.id}")
        return redirect(url_for("job_page", job_id=job.id), code=303)

    @app.post("/speakers/<name>/delete")
    def speaker_delete(name: str):
        profile = get_profile(name)
        if request.form.get("confirm", "").strip() != name:
            return "Введите имя колонки для подтверждения", 400
        raw = router_config()
        route = find_route(raw, name)
        appearance = load_overrides(appearance_path).get(profile.device_id)
        if route is not None:
            try:
                new_raw = delete_route(raw, name)
                if not new_raw.get("routes"):
                    return (
                        "Нельзя удалить последнюю колонку: в роутере должен "
                        "остаться хотя бы один маршрут.",
                        400,
                    )
                save_config(settings.router_config, new_raw)
            except (ConfigError, OSError) as exc:
                return str(exc), 400
        try:
            dest = archive_profile(
                settings, name, route=route,
                appearance=appearance,
            )
        except ValueError as exc:
            if route is not None:
                try:
                    save_config(settings.router_config, raw)
                except (ConfigError, OSError):
                    pass
            return str(exc), 400
        remove_override(appearance_path, profile.device_id)
        reload_profiles()
        audit("speaker.delete", name, detail=str(dest))
        return redirect(url_for("speakers_page"), code=303)

    @app.post("/speakers/probe")
    def speakers_probe():
        profiles = app.extensions["profiles"]
        runner = app.extensions["jobs"]
        for profile in profiles.values():
            runner.submit("status", profile)
        audit("speaker.probe", "all", detail=f"{len(profiles)}")
        return redirect(url_for("speakers_page", probe=1), code=303)

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

    @app.post("/speakers/<name>/tts")
    def speaker_tts(name: str):
        profile = get_profile(name)
        mode = (request.form.get("tts") or "").strip().lower()
        if mode not in {"cloud", "piper"}:
            flash("Неизвестный тип TTS")
            return redirect(url_for("speaker_page", name=name))
        merge_profile_env(profile.path, {"SPEAKER_TTS": mode})
        refresh_profiles()
        job = app.extensions["jobs"].submit("tts", profile)
        audit("speaker.tts", profile.name, detail=f"mode={mode} job={job.id}")
        target = (request.form.get("next") or "").strip()
        if target != url_for("speaker_page", name=name) and not target.startswith(
            url_for("speaker_page", name=name) + "/"
        ):
            target = url_for("speaker_page", name=name)
        return redirect(target, code=303)

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
        refresh_profiles()
        return render_template(
            "job.html",
            job=job,
            text=text,
            offset=offset,
            job_profile=profiles.get(job.target),
        )

    @app.get("/jobs/<job_id>/log")
    def job_log(job_id: str):
        job = app.extensions["jobs"].get(job_id)
        if job is None:
            abort(404)
        text, offset = app.extensions["jobs"].tail(job_id, 0)
        text = redact(text, settings.secrets_dir)
        return render_template("_job_log.html", job=job, text=text, offset=offset)

    @app.get("/test")
    def test_page():
        job = None
        text = ""
        offset = 0
        job_id = request.args.get("job", "").strip()
        if job_id:
            job = app.extensions["jobs"].get(job_id)
            if job is None:
                abort(404)
            text, offset = app.extensions["jobs"].tail(job_id, 0)
            text = redact(text, settings.secrets_dir)
        return render_template(
            "test.html",
            cards=speaker_cards(),
            job=job,
            text=text,
            offset=offset,
        )

    @app.post("/test/say")
    def test_say():
        profile = get_profile(request.form.get("speaker", "").strip())
        text = (request.form.get("text") or "").strip()
        if not text:
            flash("Введите текст для озвучки")
            return redirect(url_for("test_page", _anchor="voice"))
        if len(text) > max_say_chars:
            flash(f"Слишком длинный текст: до {max_say_chars} символов")
            return redirect(url_for("test_page", _anchor="voice"))
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
        audit("test.say", profile.name, detail=f"job={job.id}")
        return redirect(url_for("test_page", job=job.id, _anchor="voice"), code=303)

    @app.post("/test/check")
    def test_check():
        profile = get_profile(request.form.get("speaker", "").strip())
        job = app.extensions["jobs"].submit("check", profile)
        audit("test.check", profile.name, detail=f"job={job.id}")
        return redirect(url_for("test_page", job=job.id, _anchor="llm"), code=303)

    @app.post("/test/bridge")
    def test_bridge():
        profile = get_profile(request.form.get("speaker", "").strip())
        job = app.extensions["jobs"].submit("status", profile)
        audit("test.bridge", profile.name, detail=f"job={job.id}")
        return redirect(url_for("test_page", job=job.id, _anchor="bridge"), code=303)

    @app.get("/firmware")
    def firmware_page():
        return redirect(url_for("setup_prepare"), code=301)

    @app.get("/setup/prepare")
    def setup_prepare():
        return render_template(
            "prepare.html",
            host_step=HOST_STEP,
            firmware_files=firmware_files(),
            host_actions={
                key: value
                for key, value in HOST_ACTIONS.items()
                if key in _FIRMWARE_ACTIONS
            },
        )

    @app.post("/setup/prepare/actions/<action>")
    def setup_prepare_action(action: str):
        if action not in _FIRMWARE_ACTIONS:
            abort(404)
        job = app.extensions["jobs"].submit(action, None)
        audit(f"setup.prepare.{action}", "host", detail=f"job={job.id}")
        return redirect(url_for("job_page", job_id=job.id), code=303)

    @app.post("/firmware/actions/<action>")
    def firmware_action(action: str):
        if action not in _FIRMWARE_ACTIONS:
            abort(404)
        job = app.extensions["jobs"].submit(action, None)
        audit(f"firmware.{action}", "host", detail=f"job={job.id}")
        return redirect(url_for("job_page", job_id=job.id), code=303)

    @app.get("/access")
    def access_page():
        probe = request.args.get("probe", "").lower() in ("1", "true", "yes")
        payload, status = health(probe=probe)
        probe_results = (
            {item["name"]: item for item in payload.get("routes", [])}
            if probe
            else {}
        )
        return render_template(
            "access.html",
            providers=providers(),
            upstream_keys=upstream_keys(),
            items=key_inventory(settings.secrets_dir, normalized_routes()),
            routes=normalized_routes(),
            probe_requested=probe,
            probe_results=probe_results,
            max_fallbacks=MAX_FALLBACKS,
            fallback_count=sum(
                len(route["fallbacks"]) for route in normalized_routes()
            ),
            health=payload,
            health_status=status,
            actions={
                key: value
                for key, value in HOST_ACTIONS.items()
                if key in allowed_router_actions()
            },
        )

    @app.get("/router")
    def legacy_router():
        return redirect(url_for("access_page") + "#routes", code=301)

    @app.get("/keys")
    def legacy_keys():
        return redirect(url_for("access_page") + "#keys", code=301)

    @app.get("/router/health")
    def router_health():
        payload, status = health()
        return jsonify(payload), status

    @app.get("/router/routes/new")
    @app.get("/access/routes/new")
    def route_new():
        return render_template(
            "route_new.html",
            error=None,
            upstream_keys=upstream_keys(),
            providers=providers(),
        )

    def _render_secret(token: str, route_name: str, token_file: str):
        profile = speaker_for_token_file(token_file)
        if profile is None:
            return render_template(
                "secret.html",
                token=token,
                route_name=route_name,
                profile=None,
                note="Колонка с этим токеном не найдена — запишите токен вручную.",
                job_id=None,
            )
        return render_template(
            "secret.html",
            token=token,
            route_name=route_name,
            profile=profile,
            note=None,
            job_id=None,
        )

    @app.post("/router/routes/new")
    def route_create():
        name = request.form.get("name", "").strip()
        if not _NAME_RE.fullmatch(name):
            return render_template(
                "route_new.html",
                error="Имя: латиница, цифры и дефис",
                upstream_keys=upstream_keys(),
                providers=providers(),
            ), 400
        raw = router_config()
        if find_route(raw, name) is not None:
            return render_template(
                "route_new.html",
                error="Маршрут уже существует",
                upstream_keys=upstream_keys(),
                providers=providers(),
            ), 400
        try:
            if request.form.get("provider_id", "").strip():
                primary = _upstream_from_provider(
                    request.form, providers(), default_history="server"
                )
                route = {
                    "name": name,
                    "token_file": f"router-token-{name}",
                    "session": {
                        "mode": "server",
                        "user": "voice",
                        "idle_minutes": 30,
                        "cleanup_keep": 3,
                    },
                    "primary": primary,
                    "fallbacks": [],
                }
            else:
                route = _route_from_form(
                    request.form,
                    name,
                    {"primary": {}, "fallbacks": []},
                    token_file=f"router-token-{name}",
                )
            token = rotate_router_token(settings.secrets_dir, f"router-token-{name}")
            save_config(settings.router_config, upsert_route(raw, route))
        except (ValueError, ConfigError, OSError) as exc:
            return render_template(
                "route_new.html",
                error=str(exc),
                upstream_keys=upstream_keys(),
                providers=providers(),
            ), 400
        audit("router.create", name)
        return _render_secret(token, name, f"router-token-{name}")

    @app.get("/router/routes/<name>")
    @app.get("/access/routes/<name>")
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
            providers=providers(),
        )

    @app.post("/router/routes/<name>")
    def route_save(name: str):
        if not _NAME_RE.fullmatch(name):
            abort(404)
        raw = router_config()
        existing = find_route(raw, name) or {}
        try:
            if request.form.get("provider_id", "").strip():
                token_file = (existing.get("token_file") or "").strip()
                if not token_file or Path(token_file).name != token_file:
                    raise ValueError("token_file должен быть именем файла без каталогов")
                primary = _upstream_from_provider(
                    request.form, providers(), default_history="server"
                )
                session = dict(existing.get("session") or {})
                session.setdefault("mode", "server")
                session.setdefault("user", "voice")
                session.setdefault("idle_minutes", 30)
                session.setdefault("cleanup_keep", 3)
                route = {
                    "name": name,
                    "token_file": token_file,
                    "session": session,
                    "primary": primary,
                    "fallbacks": route_fallbacks(existing),
                }
            else:
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
                    providers=providers(),
                ),
                400,
            )
        return redirect(url_for("access_page", _anchor="routes"))

    def _fallback_from_form(form, providers: list[Provider]) -> dict:
        if form.get("provider_id", "").strip():
            return _upstream_from_provider(form, providers, default_history="client")
        return _upstream_from_form(form, default_history="client")

    @app.get("/router/routes/<name>/fallback/new")
    def fallback_new(name: str):
        raw = router_config()
        route = find_route(raw, name)
        if route is None:
            abort(404)
        if len(route_fallbacks(route)) >= MAX_FALLBACKS:
            flash(f"Достигнут лимит {MAX_FALLBACKS} запасных маршрутов")
            return redirect(url_for("access_page", _anchor="routes"))
        return render_template(
            "route_fallback.html",
            route=route,
            fallback={},
            index=None,
            error=None,
            upstream_keys=upstream_keys(),
            providers=providers(),
        )

    @app.post("/router/routes/<name>/fallback/new")
    def fallback_create(name: str):
        raw = router_config()
        route = find_route(raw, name)
        if route is None:
            abort(404)
        if len(route_fallbacks(route)) >= MAX_FALLBACKS:
            flash(f"Достигнут лимит {MAX_FALLBACKS} запасных маршрутов")
            return redirect(url_for("access_page", _anchor="routes"))
        try:
            fallback = _fallback_from_form(request.form, providers())
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
                providers=providers(),
            ), 400
        return redirect(url_for("access_page", _anchor="routes"))

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
            providers=providers(),
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
            fallbacks[index] = _fallback_from_form(request.form, providers())
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
                providers=providers(),
            ), 400
        return redirect(url_for("access_page", _anchor="routes"))

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
            return redirect(url_for("access_page", _anchor=anchor))
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
        return redirect(url_for("access_page", _anchor=anchor))

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
                return redirect(url_for("access_page", _anchor=anchor))
            fallbacks[index], fallbacks[target] = fallbacks[target], fallbacks[index]
            anchor = f"route-{name}-fallback-{target}"
        updated["fallbacks"] = fallbacks
        updated.pop("fallback", None)
        try:
            save_config(settings.router_config, upsert_route(raw, updated))
        except (ConfigError, OSError) as exc:
            return str(exc), 400
        audit("router.fallback.move", name, detail=f"{index} {direction}")
        return redirect(url_for("access_page", _anchor=anchor))

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
        return redirect(url_for("access_page", _anchor="routes"))

    @app.post("/router/routes/<name>/delete")
    def route_delete(name: str):
        raw = router_config()
        if len(raw.get("routes") or []) <= 1:
            flash("Нельзя удалить последний маршрут: в роутере должен остаться хотя бы один")
            return redirect(url_for("access_page", _anchor="routes"))
        try:
            save_config(settings.router_config, delete_route(raw, name))
            audit("router.delete", name)
        except KeyError:
            abort(404)
        except (ConfigError, OSError) as exc:
            return str(exc), 400
        return redirect(url_for("access_page", _anchor="routes"))

    @app.post("/router/restart")
    def router_restart():
        return submit_host("router-restart")

    @app.post("/router/actions/<action>")
    def router_action(action: str):
        return submit_host(action)

    @app.get("/access/providers/new")
    def provider_new():
        return render_template(
            "provider_form.html",
            title="Новый провайдер",
            action="/access/providers/new",
            provider=None,
            error=None,
        )

    @app.post("/access/providers/new")
    def provider_create():
        name = request.form.get("name", "").strip()
        base_url = request.form.get("base_url", "").strip()
        models_text = request.form.get("models", "").strip()
        models = [
            m.strip()
            for part in models_text.replace(",", "\n").splitlines()
            for m in [part.strip()]
            if m
        ]
        provider_id = slugify(name)
        error = None
        if not name:
            error = "Введите название провайдера"
        elif any(p.id == provider_id for p in providers()):
            error = "Провайдер с таким идентификатором уже существует"
        elif not base_url.startswith(("http://", "https://")):
            error = "base_url должен начинаться с http:// или https://"
        elif not models:
            error = "Укажите хотя бы одну модель"
        if error:
            return render_template(
                "provider_form.html",
                title="Новый провайдер",
                action="/access/providers/new",
                provider=None,
                error=error,
            ), 400
        provider = Provider(
            id=provider_id,
            name=name,
            base_url=base_url,
            models=tuple(models),
        )
        upsert_provider(providers_path, provider)
        audit("provider.create", provider.id)
        flash(f"Провайдер {provider.name} сохранён")
        return redirect(url_for("access_page", _anchor="providers"))

    @app.get("/access/providers/<pid>/edit")
    def provider_edit(pid: str):
        provider = next((p for p in providers() if p.id == pid), None)
        if provider is None:
            abort(404)
        return render_template(
            "provider_form.html",
            title="Изменить провайдера",
            action=f"/access/providers/{pid}/edit",
            provider=provider,
            error=None,
        )

    @app.post("/access/providers/<pid>/edit")
    def provider_save(pid: str):
        provider = next((p for p in providers() if p.id == pid), None)
        if provider is None:
            abort(404)
        name = request.form.get("name", "").strip()
        base_url = request.form.get("base_url", "").strip()
        models_text = request.form.get("models", "").strip()
        models = [
            m.strip()
            for part in models_text.replace(",", "\n").splitlines()
            for m in [part.strip()]
            if m
        ]
        error = None
        if not name:
            error = "Введите название провайдера"
        elif not base_url.startswith(("http://", "https://")):
            error = "base_url должен начинаться с http:// или https://"
        elif not models:
            error = "Укажите хотя бы одну модель"
        if error:
            return render_template(
                "provider_form.html",
                title="Изменить провайдера",
                action=f"/access/providers/{pid}/edit",
                provider=provider,
                error=error,
            ), 400
        upsert_provider(
            providers_path,
            Provider(
                id=pid,
                name=name,
                base_url=base_url,
                models=tuple(models),
            ),
        )
        audit("provider.save", pid)
        flash(f"Провайдер {name} сохранён")
        return redirect(url_for("access_page", _anchor="providers"))

    @app.post("/access/providers/<pid>/delete")
    def provider_delete(pid: str):
        provider = next((p for p in providers() if p.id == pid), None)
        if provider is None:
            abort(404)
        for route in normalized_routes():
            for upstream in [route.get("primary"), *(route.get("fallbacks") or [])]:
                if isinstance(upstream, dict) and upstream.get("base_url") == provider.base_url:
                    flash("Нельзя удалить провайдера, пока его base_url используется в маршруте")
                    return redirect(url_for("access_page", _anchor="providers"))
        delete_provider(providers_path, pid)
        audit("provider.delete", pid)
        flash("Провайдер удалён")
        return redirect(url_for("access_page", _anchor="providers"))

    @app.post("/access/providers/<pid>/probe")
    def provider_probe(pid: str):
        provider = next((p for p in providers() if p.id == pid), None)
        if provider is None:
            abort(404)
        key_file = request.form.get("api_key_file", "").strip()
        api_key = None
        if key_file:
            allowed = {item.file for item in upstream_keys()}
            if key_file not in allowed:
                flash("Выберите upstream-ключ из реестра")
                return redirect(url_for("access_page", _anchor="providers"))
            if Path(key_file).name != key_file:
                flash("Некорректное имя файла ключа")
                return redirect(url_for("access_page", _anchor="providers"))
            key_path = settings.secrets_dir / key_file
            try:
                if key_path.resolve().parent != settings.secrets_dir.resolve():
                    raise OSError
                api_key = key_path.read_text(encoding="utf-8").strip()
            except OSError:
                flash("Не удалось прочитать ключ")
                return redirect(url_for("access_page", _anchor="providers"))
        try:
            models = fetch_models(provider.base_url, api_key)
            flash(f"Найдены модели: {', '.join(models) if models else 'список пуст'}")
        except ValueError as exc:
            flash(str(exc))
        except Exception as exc:
            flash(f"Ошибка проверки связи: {exc}")
        return redirect(url_for("access_page", _anchor="providers"))

    @app.post("/access/routes/<name>/write-key")
    def route_write_key(name: str):
        raw = router_config()
        route = find_route(raw, name)
        if route is None:
            abort(404)
        token_file = route.get("token_file", "")
        profile = speaker_for_token_file(token_file) if token_file else None
        if profile is None:
            flash("Колонка для записи ключа не найдена")
            return redirect(url_for("access_page", _anchor="routes"))
        job = app.extensions["jobs"].submit("key", profile)
        audit("route.write-key", name, detail=f"job={job.id}")
        return redirect(url_for("job_page", job_id=job.id), code=303)

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
        token = rotate_router_token(settings.secrets_dir, token_file)
        profile = speaker_for_token_file(token_file)
        if profile is None:
            audit("keys.rotate", route)
            return render_template(
                "secret.html",
                token=token,
                route_name=route,
                profile=None,
                note="Колонка с этим token_file не найдена — запишите токен вручную.",
                job_id=None,
            )
        job = app.extensions["jobs"].submit("key", profile)
        audit("keys.rotate", route, detail=f"job={job.id}")
        return render_template(
            "secret.html",
            token=token,
            route_name=route,
            profile=profile,
            note=f"Запись в колонку {profile.name} запущена.",
            job_id=job.id,
        )

    @app.post("/keys/upstream")
    def keys_upstream_add():
        try:
            key_file = add_upstream_key(
                registry_path,
                settings.secrets_dir,
                "",
                request.form.get("file", ""),
                request.form.get("value", ""),
            )
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("access_page", _anchor="keys"))
        audit("keys.upstream.add", key_file)
        flash(f"Ключ {key_file} добавлен")
        return redirect(url_for("access_page", _anchor="keys"))

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
        return redirect(url_for("access_page", _anchor="keys"))

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
            return redirect(url_for("access_page", _anchor="keys"))
        audit("keys.upstream.delete", key_file)
        flash(f"Ключ {key_file} удалён")
        return redirect(url_for("access_page", _anchor="keys"))

    @app.get("/backup")
    def backup_page():
        return redirect("/more#backup", code=301)

    @app.post("/backup/create")
    def backup_create():
        scope = request.form.get("scope", "all")
        try:
            path = create_backup(settings, scope)
        except (BackupError, ConfigError, ValueError, OSError) as exc:
            flash(str(exc))
            return redirect("/more#backup")
        audit("backup.create", scope, detail=path.name)
        flash(f"Архив создан: {path.name}")
        return redirect("/more#backup")

    @app.post("/backup/inspect")
    def backup_inspect():
        name = request.form.get("backup", "")
        try:
            manifest = inspect_backup(settings, name)
        except (BackupError, ConfigError, ValueError, OSError) as exc:
            flash(str(exc))
            return redirect("/more#backup")
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
        uploaded = request.files.get("archive")
        temp_path: Path | None = None
        try:
            if uploaded is not None and uploaded.filename:
                if not uploaded.filename.endswith(".tar.gz"):
                    raise BackupError("ожидается файл .tar.gz")
                descriptor, name = tempfile.mkstemp(
                    dir=str(settings.state_dir), suffix=".tar.gz"
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
            summary = restore_backup(settings, source)
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
        except (BackupError, ConfigError, ValueError, OSError) as exc:
            flash(str(exc))
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        return redirect("/more#backup")

    @app.get("/password")
    def password_page():
        return redirect("/more#password", code=301)

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
        return redirect("/more#audit", code=301)

    @app.get("/more")
    def more_page():
        return render_template(
            "more.html",
            backups=list_backups(settings),
            profiles=sorted(profiles.values(), key=lambda item: item.name),
            inspection=None,
            entries=audit_entries(),
        )

    @app.get("/advanced")
    def advanced_page():
        return render_template(
            "advanced.html",
            view="index",
            title="Дополнительно",
            subtitle="Технические экраны и обслуживание панели",
        )

    @app.get("/advanced/jobs")
    def advanced_jobs():
        runner = app.extensions["jobs"]
        jobs = runner.list(limit=200) if hasattr(runner, "list") else []
        return render_template(
            "advanced.html",
            view="jobs",
            title="Журнал заданий",
            subtitle="Задания панели: действие, цель, статус и время",
            jobs=jobs,
        )

    @app.get("/advanced/routes")
    def advanced_routes():
        return render_template(
            "advanced.html",
            view="routes",
            title="Сырой JSON маршрутов",
            subtitle="Полный файл маршрутов без правок",
            route_json=json_for_pre(router_config(), settings.secrets_dir),
        )

    @app.get("/advanced/bridge")
    def advanced_bridge():
        policy_path = settings.root / "config" / "quasar-bridge-policy.json"
        policy_json = None
        try:
            policy_json = json_for_pre(
                json.loads(policy_path.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError):
            policy_json = None
        return render_template(
            "advanced.html",
            view="bridge",
            title="Политика Bridge",
            subtitle="Файл config/quasar-bridge-policy.json только для чтения",
            policy_json=policy_json,
            profiles=sorted(profiles.values(), key=lambda item: item.name),
        )

    @app.errorhandler(ConfigError)
    def handle_config_error(exc: ConfigError):
        return render_template("config_error.html", error=str(exc)), 500

    return app
