from __future__ import annotations

import io
import json
import os
import shutil
import tarfile
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .keys import validate_secret_name
from .router_config import read_config, save_config, upsert_route, validate_config
from .settings import Settings

MAGIC = b"MY-PYS-BACKUP\x01"
FORMAT_VERSION = 1
ITERATIONS = 600_000
MAX_RESTORE_BYTES = 64 * 1024 * 1024
_LOCK = threading.Lock()


class BackupError(Exception):
    """Ошибка создания, чтения или восстановления резервной копии."""


@dataclass(frozen=True)
class BackupInfo:
    name: str
    size: int
    modified: str


def _backup_dir(settings: Settings) -> Path:
    return settings.root / "backups" / "config"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=ITERATIONS,
    ).derive(passphrase.encode("utf-8"))


def _encrypt(data: bytes, passphrase: str) -> bytes:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    ciphertext = AESGCM(_derive_key(passphrase, salt)).encrypt(
        nonce, data, MAGIC
    )
    return MAGIC + salt + nonce + ciphertext


def _decrypt(blob: bytes, passphrase: str) -> bytes:
    header = len(MAGIC)
    if len(blob) < header + 28 or not blob.startswith(MAGIC):
        raise BackupError("это не архив резервной копии")
    salt = blob[header : header + 16]
    nonce = blob[header + 16 : header + 28]
    try:
        return AESGCM(_derive_key(passphrase, salt)).decrypt(
            nonce, blob[header + 28 :], MAGIC
        )
    except InvalidTag as exc:
        raise BackupError("неверный пароль или повреждённый архив") from exc


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _collect(settings: Settings, scope: str) -> tuple[list[tuple[str, Path]], str | None]:
    root = settings.root
    speakers_dir = settings.speakers_dir
    secrets_dir = settings.secrets_dir
    files: list[tuple[str, Path]] = []
    if scope == "all":
        env_file = root / "local" / ".env"
        if env_file.is_file():
            files.append(("local/.env", env_file))
        for path in sorted(speakers_dir.glob("*.env")):
            if path.name != "example.env":
                files.append((f"local/speakers/{path.name}", path))
        if settings.router_config.is_file():
            files.append(("secrets/router-routes.json", settings.router_config))
        for path in sorted(secrets_dir.glob("*-token-*")):
            if path.is_file():
                files.append((f"secrets/{path.name}", path))
        # Ключи с произвольными именами берём из маршрутов: панель разрешает
        # называть файлы как угодно, а не только *-token-*.
        seen = {archive_name for archive_name, _ in files}
        try:
            raw = read_config(settings.router_config)
        except (OSError, ValueError):
            raw = {}
        for route in raw.get("routes", []):
            if not isinstance(route, dict):
                continue
            candidates = [route.get("token_file")]
            for upstream in [route.get("primary"), *(route.get("fallbacks") or [])]:
                if isinstance(upstream, dict):
                    candidates.append(upstream.get("api_key_file"))
            for candidate in candidates:
                if not isinstance(candidate, str):
                    continue
                candidate = candidate.strip()
                if not candidate or Path(candidate).name != candidate:
                    continue
                try:
                    validate_secret_name(candidate)
                except ValueError:
                    continue
                path = secrets_dir / candidate
                archive_name = f"secrets/{candidate}"
                if path.is_file() and archive_name not in seen:
                    files.append((archive_name, path))
                    seen.add(archive_name)
        for extra in ("upstream-keys.json", "speaker-appearance.json"):
            path = settings.state_dir / extra
            if path.is_file():
                files.append((f"webui-state/{extra}", path))
        for name in ("speaker_ed25519", "speaker_ed25519.pub", "webui-admin.hash"):
            path = secrets_dir / name
            if path.is_file():
                files.append((f"secrets/{name}", path))
        providers_path = settings.state_dir / "providers.json"
        if providers_path.is_file():
            files.append(("webui-state/providers.json", providers_path))
        for path in sorted((settings.state_dir / "setup").glob("*.json")):
            if path.is_file():
                files.append((f"webui-state/setup/{path.name}", path))
        return files, None

    if not scope.startswith("speaker:"):
        raise BackupError("неизвестный режим архива")
    name = scope.split(":", 1)[1]
    validate_secret_name(name)
    profile = speakers_dir / f"{name}.env"
    if not profile.is_file():
        raise BackupError(f"профиль не найден: {profile.name}")
    files.append((f"local/speakers/{profile.name}", profile))
    setup_progress = settings.state_dir / "setup" / f"{name}.json"
    if setup_progress.is_file():
        files.append(
            (f"webui-state/setup/{setup_progress.name}", setup_progress)
        )
    for prefix in (
        "router-token-",
        "flai-token-",
        "orca-token-",
        "fallback-token-",
    ):
        path = secrets_dir / f"{prefix}{name}"
        if path.is_file():
            files.append((f"secrets/{path.name}", path))

    # Ключи с произвольными именами (например, openrouter-token-*) берём из
    # самого маршрута, иначе бэкап одной колонки терял бы их.
    seen = {archive_name for archive_name, _ in files}
    fragment = _route_fragment(settings, name)
    if fragment:
        route = fragment["routes"][0]
        candidates = [route.get("token_file")]
        for upstream in [route.get("primary"), *(route.get("fallbacks") or [])]:
            if isinstance(upstream, dict):
                candidates.append(upstream.get("api_key_file"))
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            candidate = candidate.strip()
            if not candidate or Path(candidate).name != candidate:
                continue
            try:
                validate_secret_name(candidate)
            except ValueError:
                continue
            path = secrets_dir / candidate
            archive_name = f"secrets/{candidate}"
            if path.is_file() and archive_name not in seen:
                files.append((archive_name, path))
                seen.add(archive_name)
    return files, name


def _route_fragment(settings: Settings, name: str) -> dict | None:
    try:
        raw = read_config(settings.router_config)
    except (OSError, ValueError):
        return None
    for route in raw.get("routes", []):
        if route.get("name") == name:
            return {"routes": [route]}
    return None


def _build_tar(settings: Settings, files: list[tuple[str, Path]], manifest: dict) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, path in files:
            data = path.read_bytes()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o600 if name.startswith("secrets/") else 0o644
            archive.addfile(info, io.BytesIO(data))
        manifest_data = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_data)
        info.mode = 0o600
        archive.addfile(info, io.BytesIO(manifest_data))
    return buffer.getvalue()


def create_backup(settings: Settings, scope: str, passphrase: str) -> Path:
    if len(passphrase) < 8:
        raise BackupError("пароль архива должен быть не короче 8 символов")
    with _LOCK:
        files, speaker = _collect(settings, scope)
        if not files:
            raise BackupError("нечего сохранять")
        manifest = {
            "format": FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scope": "speaker" if speaker else "all",
            "speaker": speaker,
            "files": [name for name, _ in files],
        }
        routes = _route_fragment(settings, speaker) if speaker else None
        if routes is not None:
            manifest["files"].append("router/routes.json")
            route_data = json.dumps(routes, ensure_ascii=False, indent=2).encode()
            info = tarfile.TarInfo("router/routes.json")
            info.size = len(route_data)
            info.mode = 0o600
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                for name, path in files:
                    data = path.read_bytes()
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    member.mode = 0o600 if name.startswith("secrets/") else 0o644
                    archive.addfile(member, io.BytesIO(data))
                archive.addfile(info, io.BytesIO(route_data))
                manifest_data = json.dumps(
                    manifest, ensure_ascii=False, indent=2
                ).encode()
                manifest_member = tarfile.TarInfo("manifest.json")
                manifest_member.size = len(manifest_data)
                manifest_member.mode = 0o600
                archive.addfile(manifest_member, io.BytesIO(manifest_data))
            plain = buffer.getvalue()
        else:
            plain = _build_tar(settings, files, manifest)
        encrypted = _encrypt(plain, passphrase)
        suffix = speaker or "all"
        path = _backup_dir(settings) / f"config-{_timestamp()}-{suffix}.tar.gz.enc"
        _atomic_write(path, encrypted, 0o600)
        return path


def list_backups(settings: Settings) -> list[BackupInfo]:
    directory = _backup_dir(settings)
    result: list[BackupInfo] = []
    try:
        paths = list(directory.glob("*.tar.gz.enc"))
    except OSError:
        return result
    for path in sorted(paths, key=lambda item: item.stat().st_mtime, reverse=True):
        stat = path.stat()
        result.append(
            BackupInfo(
                name=path.name,
                size=stat.st_size,
                modified=datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(timespec="seconds"),
            )
        )
    return result


def resolve_backup(settings: Settings, name: str) -> Path:
    if not name or Path(name).name != name or not name.endswith(".tar.gz.enc"):
        raise BackupError("недопустимое имя архива")
    directory = _backup_dir(settings).resolve()
    path = (directory / name).resolve()
    if path.parent != directory or not path.is_file():
        raise BackupError("архив не найден")
    return path


def _safe_extract(blob: bytes, destination: Path) -> None:
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
            members = archive.getmembers()
            for member in members:
                if not (member.isfile() or member.isdir()):
                    raise BackupError("в архиве есть недопустимые элементы")
                name = PurePosixPath(member.name)
                if name.is_absolute() or ".." in name.parts:
                    raise BackupError("в архиве есть недопустимый путь")
                total += member.size
                if total > MAX_RESTORE_BYTES:
                    raise BackupError("архив слишком большой")
            archive.extractall(destination, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise BackupError(f"не удалось прочитать архив: {exc}") from exc


def _load_archive(path: Path, passphrase: str, destination: Path) -> dict:
    try:
        blob = path.read_bytes()
    except OSError as exc:
        raise BackupError(f"не удалось открыть архив: {exc}") from exc
    _safe_extract(_decrypt(blob, passphrase), destination)
    manifest_path = destination / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError("в архиве нет корректного манифеста") from exc
    if manifest.get("format") != FORMAT_VERSION:
        raise BackupError("неподдерживаемая версия архива")
    if manifest.get("scope") not in ("all", "speaker"):
        raise BackupError("неизвестный режим архива")
    return manifest


def inspect_backup(settings: Settings, name: str, passphrase: str) -> dict:
    path = resolve_backup(settings, name)
    with tempfile.TemporaryDirectory(prefix="webui-backup-") as directory:
        return _load_archive(path, passphrase, Path(directory))


def _snapshot(settings: Settings, manifest: dict, extracted: Path) -> Path:
    stamp = _timestamp()
    directory = settings.state_dir / "restore-backups" / f"{stamp}-{uuid.uuid4().hex[:6]}"
    directory.mkdir(parents=True, exist_ok=False)
    for name in manifest.get("files", []):
        relative = PurePosixPath(name)
        if relative.parts[:1] == ("router",):
            continue
        source = settings.root / Path(*relative.parts)
        if source.is_file():
            target = directory / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            os.chmod(target, 0o600)
    return directory


def _target(settings: Settings, name: str) -> Path:
    relative = PurePosixPath(name)
    if relative.parts[:1] == ("local",):
        return settings.root / Path(*relative.parts)
    if relative.parts[:1] == ("secrets",):
        return settings.secrets_dir / Path(*relative.parts[1:])
    if relative.parts[:1] == ("webui-state",):
        return settings.state_dir / Path(*relative.parts[1:])
    raise BackupError(f"недопустимый путь в архиве: {name}")


def restore_backup(
    settings: Settings,
    source: Path,
    passphrase: str,
    confirm: str,
) -> dict:
    if confirm != "REPLACE":
        raise BackupError("для восстановления введите REPLACE")
    with _LOCK:
        path = Path(source)
        with tempfile.TemporaryDirectory(prefix="webui-restore-") as directory:
            extracted = Path(directory)
            manifest = _load_archive(path, passphrase, extracted)
            snapshot = _snapshot(settings, manifest, extracted)
            restored = 0
            router_done = False

            def rollback() -> None:
                for name in manifest.get("files", []):
                    if name == "router/routes.json":
                        continue
                    target = _target(settings, name)
                    snap = snapshot / Path(*PurePosixPath(name).parts)
                    if snap.is_file():
                        _atomic_write(
                            target,
                            snap.read_bytes(),
                            snap.stat().st_mode & 0o777,
                        )
                    else:
                        target.unlink(missing_ok=True)

            try:
                for name in manifest.get("files", []):
                    if name == "router/routes.json":
                        continue
                    source_file = extracted / Path(*PurePosixPath(name).parts)
                    if not source_file.is_file():
                        raise BackupError(f"в архиве нет файла: {name}")
                    if name == "secrets/router-routes.json":
                        validate_config(source_file)
                        router_done = True
                        continue
                    target = _target(settings, name)
                    mode = 0o600 if name.startswith("secrets/") else 0o644
                    _atomic_write(target, source_file.read_bytes(), mode)
                    restored += 1

                if manifest["scope"] == "all" and router_done:
                    target = settings.router_config
                    _atomic_write(
                        target,
                        (extracted / "secrets" / "router-routes.json").read_bytes(),
                        0o600,
                    )
                if manifest["scope"] == "speaker":
                    fragment_path = extracted / "router" / "routes.json"
                    if fragment_path.is_file():
                        fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
                        routes = fragment.get("routes", [])
                        if len(routes) == 1:
                            try:
                                raw = read_config(settings.router_config)
                            except (OSError, ValueError):
                                raw = {"routes": []}
                            save_config(
                                settings.router_config,
                                upsert_route(raw, routes[0]),
                            )
                if settings.router_config.is_file():
                    validate_config(settings.router_config)
            except Exception:
                try:
                    rollback()
                except OSError:
                    pass
                raise

            return {
                "scope": manifest["scope"],
                "speaker": manifest.get("speaker"),
                "restored": restored,
                "snapshot": str(snapshot),
            }
