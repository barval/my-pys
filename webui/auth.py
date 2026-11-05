from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path

from flask import (
    Flask,
    abort,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .audit import record
from .settings import Settings

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LEN = 32
_MAX_ATTEMPTS = 5
_ATTEMPT_WINDOW = 300.0


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_LEN,
    )
    return (
        f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}"
        f"${_b64encode(salt)}${_b64encode(digest)}"
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, digest = encoded.split("$")
        if algorithm != "scrypt":
            return False
        expected = _b64decode(digest)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(actual, expected)


def save_password_hash(path: Path, password: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    with open(temp, "w", encoding="utf-8") as stream:
        stream.write(hash_password(password) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def load_or_create_session_key(path: Path) -> bytes:
    path = Path(path)
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    temp = path.with_name(f"{path.name}.tmp")
    temp.write_bytes(key)
    os.chmod(temp, 0o600)
    os.replace(temp, path)
    return key


def init_auth(app: Flask, settings: Settings) -> None:
    app.secret_key = load_or_create_session_key(settings.session_key_file)
    app.config.update(
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_HTTPONLY=True,
    )
    attempts: dict[str, deque[float]] = defaultdict(deque)

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

    def is_public(path: str) -> bool:
        return path == "/login" or path == "/healthz" or path.startswith("/static/")

    @app.before_request
    def guard():
        if request.method == "POST":
            expected = session.get("csrf")
            provided = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not expected or not provided or not hmac.compare_digest(expected, provided):
                abort(400)
        if is_public(request.path):
            return None
        if session.get("user") != "admin":
            return redirect(url_for("login"))
        return None

    app.jinja_env.globals["csrf_token"] = lambda: session.get("csrf", "")

    @app.get("/login")
    def login():
        if not session.get("csrf"):
            session["csrf"] = secrets.token_urlsafe(32)
        return render_template("login.html", notice=session.pop("notice", None))

    @app.post("/login")
    def login_post():
        now = time.monotonic()
        remote = request.remote_addr or "unknown"
        bucket = attempts[remote]
        while bucket and now - bucket[0] > _ATTEMPT_WINDOW:
            bucket.popleft()
        if len(bucket) >= _MAX_ATTEMPTS:
            return (
                render_template(
                    "login.html",
                    error="Слишком много попыток. Подождите 5 минут.",
                ),
                429,
            )
        password = request.form.get("password", "")
        try:
            encoded = settings.admin_hash_file.read_text(encoding="utf-8").strip()
        except OSError:
            return (
                render_template(
                    "login.html",
                    error="Пароль администратора не настроен.",
                ),
                503,
            )
        if not verify_password(password, encoded):
            bucket.append(now)
            audit("auth.login", remote, "denied", "wrong password")
            return render_template("login.html", error="Неверный пароль."), 401
        attempts.pop(remote, None)
        session.clear()
        session["user"] = "admin"
        session["csrf"] = secrets.token_urlsafe(32)
        audit("auth.login", remote)
        return redirect(url_for("index"))

    @app.post("/logout")
    def logout():
        audit("auth.logout", "session")
        session.clear()
        return redirect(url_for("login"))
