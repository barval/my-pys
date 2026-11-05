"""Local OpenAI-compatible router for the Quasar Bridge speakers.

The router keeps the speaker-side configuration stable: every speaker talks to
one address with a router token.  Per-route config decides which upstream gets
the request, whether the upstream keeps conversation history itself, and where
to fail over when the primary is unavailable.

Only the Python standard library is used so the container needs no pip
dependencies and the tests run on the host.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlsplit

LOG = logging.getLogger("llm-router")

DEFAULT_FALLBACK_STATUSES = frozenset({429, 500, 502, 503, 504})
HISTORY_MODES = frozenset({"client", "server"})


class ConfigError(Exception):
    """Raised when router-routes.json cannot be used."""


@dataclass(frozen=True)
class Upstream:
    base_url: str
    api_key: str = ""
    model: str | None = None
    history: str = "client"
    timeout_seconds: float = 120.0
    fallback_on: frozenset[int] = DEFAULT_FALLBACK_STATUSES

    @property
    def available(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class SessionConfig:
    mode: str = "client"
    user: str = "voice"
    idle_minutes: int = 30
    cleanup_keep: int = 3


@dataclass(frozen=True)
class ResponsePolicy:
    """Voice-output limits applied to non-stream chat completions."""

    max_sentences: int = 3
    max_chars: int = 400
    strip_markdown: bool = True


@dataclass(frozen=True)
class Route:
    name: str
    token: str
    session: SessionConfig
    primary: Upstream
    fallbacks: tuple[Upstream, ...] = ()

    @property
    def fallback(self) -> Upstream | None:
        return self.fallbacks[0] if self.fallbacks else None


@dataclass(frozen=True)
class Config:
    routes: tuple[Route, ...]
    mtime_ns: int
    watched_mtimes: Mapping[str, int]
    response: ResponsePolicy
    response_chunked: ResponsePolicy
    by_token_map: Mapping[str, Route]

    def by_token(self, token: str) -> Route | None:
        return self.by_token_map.get(token)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _resolve(base_dir: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


def _read_secret(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _parse_upstream(
    raw: Any,
    base_dir: Path,
    default_history: str,
    watched: dict[str, int] | None = None,
) -> Upstream:
    if not isinstance(raw, dict):
        raise ConfigError("upstream must be an object")
    base_url = raw.get("base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        raise ConfigError("upstream.base_url is required")

    api_key = raw.get("api_key") or ""
    if not isinstance(api_key, str):
        raise ConfigError("upstream.api_key must be a string")
    key_file = raw.get("api_key_file")
    if key_file:
        if not isinstance(key_file, str):
            raise ConfigError("upstream.api_key_file must be a string")
        key_path = _resolve(base_dir, key_file)
        api_key = _read_secret(key_path)
        if watched is not None:
            watched[str(key_path.resolve())] = _mtime_ns(key_path)
        if not api_key:
            LOG.warning("upstream key file is missing or empty: %s", key_path)

    history = raw.get("history", default_history)
    if history not in HISTORY_MODES:
        raise ConfigError("upstream.history must be 'client' or 'server'")

    model = raw.get("model")
    if model is not None and not isinstance(model, str):
        raise ConfigError("upstream.model must be a string")

    try:
        timeout_seconds = float(raw.get("timeout_seconds", 120))
        fallback_on = frozenset(int(code) for code in raw.get("fallback_on", DEFAULT_FALLBACK_STATUSES))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid upstream timeout/status list: {exc}") from exc

    return Upstream(
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        model=model,
        history=history,
        timeout_seconds=timeout_seconds,
        fallback_on=fallback_on,
    )


def _parse_session(raw: Any, default_history: str) -> SessionConfig:
    if not isinstance(raw, dict):
        raw = {}
    mode = raw.get("mode", default_history)
    if mode not in HISTORY_MODES:
        raise ConfigError("session.mode must be 'client' or 'server'")
    user = raw.get("user", "voice")
    if not isinstance(user, str) or not user.strip():
        raise ConfigError("session.user must be a non-empty string")
    try:
        idle_minutes = int(raw.get("idle_minutes", 30))
        cleanup_keep = int(raw.get("cleanup_keep", 3))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid session limits: {exc}") from exc
    if idle_minutes < 1 or cleanup_keep < 1:
        raise ConfigError("session.idle_minutes and cleanup_keep must be positive")
    return SessionConfig(mode=mode, user=user.strip(), idle_minutes=idle_minutes, cleanup_keep=cleanup_keep)


def _parse_response_policy(raw: Any, default_sentences: int = 3, default_chars: int = 400) -> ResponsePolicy:
    if not isinstance(raw, dict):
        raw = {}
    try:
        max_sentences = int(raw.get("max_sentences", default_sentences))
        max_chars = int(raw.get("max_chars", default_chars))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid response limits: {exc}") from exc
    if max_sentences < 1 or max_chars < 1:
        raise ConfigError("response.max_sentences and response.max_chars must be positive")
    return ResponsePolicy(
        max_sentences=max_sentences,
        max_chars=max_chars,
        strip_markdown=bool(raw.get("strip_markdown", True)),
    )


def probe_upstream(upstream: Upstream, timeout: float = 3.0) -> dict[str, Any]:
    """Return a short live status for an upstream without exposing its key."""
    if not upstream.available:
        return {"state": "no_key"}
    url = upstream.base_url.rstrip("/") + "/models"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {upstream.api_key}",
            "Accept": "application/json",
            "User-Agent": "llm-router/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            response.read(64)
            return {
                "state": "ok" if 200 <= status < 300 else "error",
                "http": status,
            }
    except urllib.error.HTTPError as exc:
        return {"state": "error", "http": exc.code}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"state": "unreachable", "error": str(exc)[:200]}


def load_config(path: Path) -> Config:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("routes"), list):
        raise ConfigError("config must contain a 'routes' array")

    base_dir = path.parent
    watched = {str(path.resolve()): _mtime_ns(path)}
    routes: list[Route] = []
    by_token: dict[str, Route] = {}
    for item in raw["routes"]:
        if not isinstance(item, dict):
            raise ConfigError("each route must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError("route.name is required")
        token_file = item.get("token_file")
        if not isinstance(token_file, str) or not token_file:
            raise ConfigError(f"route {name}: token_file is required")
        token_path = _resolve(base_dir, token_file)
        token = _read_secret(token_path)
        watched[str(token_path.resolve())] = _mtime_ns(token_path)
        if not token:
            raise ConfigError(f"route {name}: token file is missing or empty: {token_file}")
        if token in by_token:
            raise ConfigError(f"duplicate router token for route {name}")

        session = _parse_session(item.get("session"), "server")
        primary = _parse_upstream(item.get("primary"), base_dir, session.mode, watched)
        fallbacks_raw = item.get("fallbacks")
        if isinstance(fallbacks_raw, list):
            fallbacks = tuple(
                _parse_upstream(entry, base_dir, session.mode, watched)
                for entry in fallbacks_raw
            )
        elif fallbacks_raw is not None:
            raise ConfigError(f"route {name}: fallbacks must be an array")
        else:
            fallback_raw = item.get("fallback")
            fallbacks = (
                (_parse_upstream(fallback_raw, base_dir, session.mode, watched),)
                if fallback_raw
                else ()
            )

        route = Route(
            name=name.strip(),
            token=token,
            session=session,
            primary=primary,
            fallbacks=fallbacks,
        )
        routes.append(route)
        by_token[token] = route

    if not routes:
        raise ConfigError("config has no routes")
    mtime_ns = _mtime_ns(path)
    response_raw = raw.get("response")
    chunked_raw = response_raw.get("chunked") if isinstance(response_raw, dict) else None
    return Config(
        routes=tuple(routes),
        mtime_ns=mtime_ns,
        watched_mtimes=watched,
        response=_parse_response_policy(response_raw),
        response_chunked=_parse_response_policy(chunked_raw, 100, 3000),
        by_token_map=by_token,
    )


class ConfigStore:
    """Reloads the config when its mtime changes, keeping the last good copy."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._config = load_config(self.path)

    @staticmethod
    def _changed(config: Config) -> bool:
        return any(_mtime_ns(Path(path)) != mtime for path, mtime in config.watched_mtimes.items())

    def get(self) -> Config:
        if not self._changed(self._config):
            return self._config
        with self._lock:
            if not self._changed(self._config):
                return self._config
            try:
                self._config = load_config(self.path)
                LOG.info("config reloaded")
            except Exception as exc:  # noqa: BLE001 - keep the last good config
                LOG.error("config reload failed, keeping previous config: %s", exc)
        return self._config


# ---------------------------------------------------------------------------
# Request shaping
# ---------------------------------------------------------------------------


def build_payload(upstream: Upstream, body: dict[str, Any], session_user: str) -> dict[str, Any]:
    """Return the upstream body for one route.

    ``server`` history sends only the last user message.  FLAI concatenates
    every role into one text and stores it as a user turn, so sending the
    Bridge's system prompt or history would both duplicate context and make
    the model quote service instructions back to the user.  The upstream's
    own system prompt supplies the identity and style.  ``client`` history
    passes every message through.
    """
    payload = copy.deepcopy(body)
    if upstream.model:
        payload["model"] = upstream.model

    if upstream.history != "server":
        return payload

    messages = payload.get("messages")
    if not isinstance(messages, list):
        return payload

    last_user = next(
        (message for message in reversed(messages) if isinstance(message, dict) and message.get("role") == "user"),
        None,
    )
    if last_user is None:
        return payload

    payload["messages"] = [last_user]
    payload["user"] = session_user
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        metadata = dict(metadata)
        metadata.pop("session_id", None)
        if metadata:
            payload["metadata"] = metadata
        else:
            payload.pop("metadata", None)
    return payload


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            part["text"]
            for part in content
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)
        ]
        return " ".join(parts)
    return ""


def is_health_probe(body: dict[str, Any]) -> bool:
    """True for the Bridge's single-message ``check-backends`` probe."""
    messages = body.get("messages")
    if not isinstance(messages, list) or len(messages) != 1:
        return False
    message = messages[0]
    if not isinstance(message, dict) or message.get("role") != "user":
        return False
    return _message_text(message).strip().lower() == "ответь одним словом: связь"


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_FENCED_CODE = re.compile(r"```.*?```", re.S)
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_INLINE_CODE = re.compile(r"`([^`]*)`")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_BULLET = re.compile(r"^\s*[-*+]\s+", re.M)
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+", re.M)
_EMPHASIS = re.compile(r"(\*\*|__)(.*?)\1")
_URL = re.compile(r"https?://\S+")
_WHITESPACE = re.compile(r"\s+")


def shorten_text(text: str, policy: ResponsePolicy) -> str:
    """Trim an LLM answer to the voice budget, preferring sentence boundaries."""
    original = text.strip()
    if not original:
        return original

    if policy.strip_markdown:
        text = _FENCED_CODE.sub(" ", text)
        text = _MARKDOWN_LINK.sub(r"\1", text)
        text = _INLINE_CODE.sub(r"\1", text)
        text = _HEADING.sub("", text)
        text = _BULLET.sub("", text)
        text = _NUMBERED.sub("", text)
        text = _EMPHASIS.sub(r"\2", text)
        text = _URL.sub("", text)

    text = _WHITESPACE.sub(" ", text).strip()
    if not text:
        text = original

    sentences = [sentence.strip() for sentence in _SENTENCE_SPLIT.split(text) if sentence.strip()]
    if sentences:
        text = " ".join(sentences[: policy.max_sentences])

    if len(text) <= policy.max_chars:
        return text

    limit = max(1, policy.max_chars - 1)
    head = text[:limit]
    cut = head.rsplit(" ", 1)[0].rstrip(" ,;:—-.")
    if not cut:
        cut = head.rstrip()
    return cut + "…"


def apply_response_policy(data: bytes, policy: ResponsePolicy) -> bytes:
    """Shorten assistant text in an OpenAI chat-completion JSON response."""
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return data
    if not isinstance(payload, dict):
        return data

    changed = False
    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    shortened = shorten_text(content, policy)
                    if shortened != content:
                        message["content"] = shortened
                        changed = True
            text = choice.get("text")
            if isinstance(text, str) and text.strip():
                shortened = shorten_text(text, policy)
                if shortened != text:
                    choice["text"] = shortened
                    changed = True
    return json.dumps(payload, ensure_ascii=False).encode("utf-8") if changed else data


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


class SessionManager:
    """Tracks one logical FLAI conversation per route and its idle epochs."""

    def __init__(self, state_path: Path, clock: Callable[[], float] = time.time):
        self.state_path = Path(state_path)
        self.clock = clock
        self._lock = threading.Lock()
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_name(self.state_path.name + ".tmp")
        tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.state_path)

    def lease(self, route: Route) -> tuple[str, bool]:
        """Return (session user, rotated) and update the idle timer."""
        with self._lock:
            entry = self._state.get(route.name)
            base = route.session.user
            if not isinstance(entry, dict) or entry.get("base") != base:
                entry = {"base": base, "epoch": 0, "last_used": 0.0, "users": [base]}
                self._state[route.name] = entry

            now = self.clock()
            idle_seconds = max(1, route.session.idle_minutes) * 60
            rotated = False
            last_used = float(entry.get("last_used") or 0.0)
            if last_used and now - last_used > idle_seconds:
                entry["epoch"] = int(entry.get("epoch") or 0) + 1
                entry.setdefault("users", [base]).append(f"{base}-{entry['epoch']}")
                rotated = True
            entry["last_used"] = now
            try:
                self._save()
            except OSError as exc:
                LOG.warning("cannot save session state: %s", exc)
            return entry["users"][-1], rotated

    def user_for(self, route: Route) -> str:
        return self.lease(route)[0]

    def users_for(self, route: Route) -> list[str]:
        with self._lock:
            entry = self._state.get(route.name)
            if not isinstance(entry, dict):
                return [route.session.user]
            users = entry.get("users")
            return list(users) if isinstance(users, list) and users else [route.session.user]

    def trim_users(self, route: Route, keep: int) -> None:
        """Keep the state file from growing with every epoch."""
        with self._lock:
            entry = self._state.get(route.name)
            if not isinstance(entry, dict):
                return
            users = entry.get("users")
            if isinstance(users, list) and len(users) > max(1, keep):
                entry["users"] = users[-max(1, keep) :]
                try:
                    self._save()
                except OSError as exc:
                    LOG.warning("cannot save session state: %s", exc)


# ---------------------------------------------------------------------------
# FLAI session cleanup
# ---------------------------------------------------------------------------


def _session_title(user: str) -> str:
    fingerprint = hashlib.sha1(user.encode("utf-8")).hexdigest()  # noqa: S324 - FLAI's session key, not security
    return "flai:conv:" + fingerprint[:32]


def select_stale_sessions(
    sessions: list[dict[str, Any]],
    titles: set[str],
    keep: int,
    must_keep: str | None = None,
) -> list[str]:
    """Return ids of matching sessions except the newest ``keep`` (and must_keep)."""
    matching = [
        session
        for session in sessions
        if isinstance(session, dict) and session.get("id") and session.get("title") in titles
    ]
    matching.sort(key=lambda session: str(session.get("created_at") or ""), reverse=True)
    keep_ids = {session["id"] for session in matching[:keep]}
    if must_keep:
        keep_ids.add(must_keep)
    return [session["id"] for session in matching if session["id"] not in keep_ids]


def _http_json(
    method: str,
    url: str,
    api_key: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 15,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw else {}


def cleanup_sessions(route: Route, sessions: SessionManager) -> int:
    """Keep the current FLAI session and two previous ones for this route."""
    upstream = route.primary
    if upstream.history != "server" or not upstream.available:
        return 0

    users = sessions.users_for(route)
    titles = {_session_title(user) for user in users}
    current_title = _session_title(users[-1])
    base = upstream.base_url.rstrip("/")
    try:
        listing = _http_json("GET", base + "/flai/sessions", upstream.api_key)
        data = listing.get("data") if isinstance(listing, dict) else None
        if not isinstance(data, list):
            return 0
        current_ids = [item.get("id") for item in data if item.get("title") == current_title and item.get("id")]
        stale = select_stale_sessions(
            data,
            titles,
            keep=route.session.cleanup_keep,
            must_keep=current_ids[0] if current_ids else None,
        )
        for session_id in stale:
            _http_json("DELETE", base + f"/flai/sessions/{session_id}", upstream.api_key)
        if stale:
            LOG.info("route=%s cleanup removed %d old FLAI sessions", route.name, len(stale))
        sessions.trim_users(route, route.session.cleanup_keep)
        return len(stale)
    except Exception as exc:  # noqa: BLE001 - cleanup must never break a request
        LOG.warning("route=%s session cleanup failed: %s", route.name, exc)
        return 0


_cleanup_lock = threading.Lock()
_cleanup_active: set[str] = set()


def schedule_cleanup(route: Route, sessions: SessionManager) -> None:
    with _cleanup_lock:
        if route.name in _cleanup_active:
            return
        _cleanup_active.add(route.name)

    def run() -> None:
        try:
            cleanup_sessions(route, sessions)
        finally:
            with _cleanup_lock:
                _cleanup_active.discard(route.name)

    threading.Thread(target=run, daemon=True, name=f"cleanup-{route.name}").start()


# ---------------------------------------------------------------------------
# HTTP proxy
# ---------------------------------------------------------------------------


def _error_payload(message: str, code: str) -> dict[str, Any]:
    return {"error": {"message": message, "type": "router_error", "code": code}}


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _bearer(value: str | None) -> str | None:
    if not value:
        return None
    parts = value.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


class RouterServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], config_store: ConfigStore, sessions: SessionManager):
        super().__init__(address, ProxyHandler)
        self.config_store = config_store
        self.sessions = sessions


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: RouterServer

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        self._handle("POST")

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.info("%s - %s", self.address_string(), fmt % args)

    # -- request handling -------------------------------------------------

    def _handle(self, method: str) -> None:
        path = urlsplit(self.path).path
        if path == "/health":
            config = self.server.config_store.get()
            query = parse_qs(urlsplit(self.path).query)
            probe = query.get("probe", ["0"])[0].lower() in ("1", "true", "yes")
            if not probe:
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "routes": [
                            {
                                "name": route.name,
                                "available": bool(
                                    route.primary.available
                                    or any(item.available for item in route.fallbacks)
                                ),
                            }
                            for route in config.routes
                        ],
                    },
                )
                return
            entries: list[tuple[Route, str, Upstream]] = []
            for route in config.routes:
                entries.append((route, "primary", route.primary))
                for index, fallback in enumerate(route.fallbacks):
                    entries.append((route, f"fallback:{index}", fallback))
            with ThreadPoolExecutor(max_workers=min(8, max(1, len(entries)))) as pool:
                results = list(pool.map(lambda item: probe_upstream(item[2]), entries))
            by_route: dict[str, dict[str, Any]] = {}
            for (route, slot, _), result in zip(entries, results):
                item = by_route.setdefault(
                    route.name,
                    {"name": route.name, "primary": {}, "fallbacks": []},
                )
                if slot == "primary":
                    item["primary"] = result
                else:
                    item["fallbacks"].append(result)
            for item in by_route.values():
                item["available"] = item["primary"].get("state") == "ok" or any(
                    fallback.get("state") == "ok"
                    for fallback in item["fallbacks"]
                )
            self._send_json(200, {"status": "ok", "routes": list(by_route.values())})
            return

        if not path.startswith("/v1/"):
            self._send_json(404, _error_payload("not found", "not_found"))
            return

        token = _bearer(self.headers.get("Authorization"))
        if not token:
            self._send_json(401, _error_payload("missing bearer token", "invalid_token"))
            return

        config = self.server.config_store.get()
        route = config.by_token(token)
        if route is None:
            self._send_json(401, _error_payload("unknown bearer token", "invalid_token"))
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw_body = self.rfile.read(length) if length else b""

        body: dict[str, Any] | None = None
        stream = False
        if path == "/v1/chat/completions" and method == "POST":
            try:
                parsed = json.loads(raw_body.decode("utf-8")) if raw_body else None
            except (UnicodeDecodeError, ValueError):
                self._send_json(400, _error_payload("request body must be valid JSON", "invalid_body"))
                return
            if not isinstance(parsed, dict):
                self._send_json(400, _error_payload("request body must be a JSON object", "invalid_body"))
                return
            body = parsed
            stream = body.get("stream") is True

        session_user = route.session.user
        rotated = False
        if body is not None and route.session.mode == "server":
            if is_health_probe(body):
                session_user = f"{route.session.user}-health"
            else:
                session_user, rotated = self.server.sessions.lease(route)

        status, headers, payload, label = self._forward(
            route=route,
            method=method,
            path=path,
            body=body,
            raw_body=raw_body,
            stream=stream,
            session_user=session_user,
        )

        if body is not None and not stream and status == 200 and isinstance(payload, bytes):
            chunked = self.headers.get("X-Quasar-Voice-Chunking", "").strip().lower() in ("1", "true", "yes")
            payload = apply_response_policy(payload, config.response_chunked if chunked else config.response)

        if stream and isinstance(payload, tuple):
            self._send_stream(status, headers, payload)
        else:
            self._send_bytes(status, headers, payload if isinstance(payload, bytes) else _json_bytes(payload))

        if rotated:
            schedule_cleanup(route, self.server.sessions)

        LOG.info(
            "route=%s attempt=%s status=%s stream=%s fallback=%s",
            route.name,
            label,
            status,
            stream,
            label != "primary",
        )

    # -- upstream ---------------------------------------------------------

    def _forward(
        self,
        route: Route,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        raw_body: bytes,
        stream: bool,
        session_user: str,
    ) -> tuple[int, Mapping[str, str], bytes | tuple[bytes, Any], str]:
        attempts: list[tuple[Upstream, str]] = [(route.primary, "primary")]
        for index, upstream in enumerate(route.fallbacks):
            label = "fallback" if index == 0 else f"fallback{index + 1}"
            attempts.append((upstream, label))

        for index, (upstream, label) in enumerate(attempts):
            has_next = index + 1 < len(attempts)
            if not upstream.available:
                LOG.warning("route=%s attempt=%s has no upstream key", route.name, label)
                continue

            payload = build_payload(upstream, body, session_user) if body is not None else None
            data = _json_bytes(payload) if payload is not None else (raw_body or None)
            url = upstream.base_url.rstrip("/") + path[len("/v1") :]
            request = urllib.request.Request(
                url,
                data=data,
                method=method,
                headers={
                    "Authorization": f"Bearer {upstream.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream" if stream else "application/json",
                    "User-Agent": "llm-router/1.0",
                },
            )
            started = time.monotonic()

            try:
                response = urllib.request.urlopen(request, timeout=upstream.timeout_seconds)
                status = int(response.status)
                if status in upstream.fallback_on and has_next:
                    response.read()
                    response.close()
                    LOG.warning("route=%s attempt=%s status=%s, trying fallback", route.name, label, status)
                    continue

                if stream:
                    try:
                        first = response.read(1)
                    except OSError as exc:
                        response.close()
                        if has_next:
                            LOG.warning("route=%s attempt=%s stream failed before first byte: %s", route.name, label, exc)
                            continue
                        return 504, {}, _json_bytes(_error_payload("upstream timed out", "upstream_timeout")), "none"
                    LOG.info(
                        "route=%s attempt=%s status=%s ms=%d stream=true",
                        route.name,
                        label,
                        status,
                        int((time.monotonic() - started) * 1000),
                    )
                    return status, response.headers, (first, response), label

                try:
                    result = response.read()
                except OSError as exc:
                    response.close()
                    if has_next:
                        LOG.warning("route=%s attempt=%s read failed: %s", route.name, label, exc)
                        continue
                    return 504, {}, _json_bytes(_error_payload("upstream timed out", "upstream_timeout")), "none"
                headers = response.headers
                response.close()
                LOG.info(
                    "route=%s attempt=%s status=%s ms=%d stream=false",
                    route.name,
                    label,
                    status,
                    int((time.monotonic() - started) * 1000),
                )
                return status, headers, result, label

            except urllib.error.HTTPError as exc:
                error_body = exc.read()
                error_headers = exc.headers
                exc.close()
                if exc.code in upstream.fallback_on and has_next:
                    LOG.warning("route=%s attempt=%s status=%s, trying fallback", route.name, label, exc.code)
                    continue
                LOG.warning("route=%s attempt=%s status=%s error", route.name, label, exc.code)
                return exc.code, error_headers, error_body, label
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                LOG.warning("route=%s attempt=%s unavailable: %s", route.name, label, exc)
                if has_next:
                    continue
                return 502, {}, _json_bytes(_error_payload("all upstreams are unavailable", "upstream_unavailable")), "none"

        return 503, {}, _json_bytes(_error_payload("route has no configured upstream", "route_unavailable")), "none"

    # -- responses --------------------------------------------------------

    def _copy_headers(self, headers: Mapping[str, str] | None) -> None:
        if not headers:
            return
        for name in ("Content-Type", "Cache-Control", "X-Accel-Buffering", "OpenAI-Processing-Ms"):
            value = headers.get(name)
            if value:
                self.send_header(name, value)

    def _send_json(self, status: int, payload: Any) -> None:
        self._send_bytes(status, {"Content-Type": "application/json; charset=utf-8"}, _json_bytes(payload))

    def _send_bytes(self, status: int, headers: Mapping[str, str] | None, data: bytes) -> None:
        self.send_response(status)
        self._copy_headers(headers)
        if not headers or not headers.get("Content-Type"):
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _send_stream(self, status: int, headers: Mapping[str, str] | None, payload: tuple[bytes, Any]) -> None:
        first, response = payload
        self.send_response(status)
        self._copy_headers(headers)
        if not headers or not headers.get("Content-Type"):
            self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            if first:
                self._write_chunk(first)
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                self._write_chunk(chunk)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError as exc:
            LOG.warning("stream interrupted: %s", exc)
        finally:
            response.close()

    def _write_chunk(self, data: bytes) -> None:
        self.wfile.write(f"{len(data):X}\r\n".encode("ascii") + data + b"\r\n")
        self.wfile.flush()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("ROUTER_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config_path = Path(os.environ.get("ROUTER_CONFIG", "secrets/router-routes.json"))
    state_path = Path(os.environ.get("ROUTER_STATE", "router-state/router-state.json"))
    host = os.environ.get("ROUTER_HOST", "0.0.0.0")
    port = int(os.environ.get("ROUTER_PORT", "5002"))

    store = ConfigStore(config_path)
    sessions = SessionManager(state_path)
    server = RouterServer((host, port), store, sessions)
    LOG.info("listening on %s:%d with routes: %s", host, port, ", ".join(route.name for route in store.get().routes))
    server.serve_forever()


if __name__ == "__main__":
    main()
