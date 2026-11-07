from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

_TOKEN_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"flai-[A-Za-z0-9]{16,}"),
)


def redact(text: str, secrets_dir: Path | None = None) -> str:
    result = text
    for pattern in _TOKEN_PATTERNS:
        result = pattern.sub("***", result)
    if secrets_dir is not None:
        directory = Path(secrets_dir)
        try:
            for path in directory.iterdir():
                if not path.is_file():
                    continue
                try:
                    value = path.read_text(encoding="utf-8").strip()
                except (OSError, UnicodeDecodeError):
                    continue
                if len(value) >= 8:
                    result = result.replace(value, "***")
        except OSError:
            pass
    return result


def record(
    path: Path,
    actor: str,
    action: str,
    target: str,
    result: str,
    detail: str = "",
    secrets_dir: Path | None = None,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "actor": actor,
        "action": action,
        "target": target,
        "result": result,
        "detail": redact(detail, secrets_dir),
    }
    line = json.dumps(entry, ensure_ascii=False)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o600,
    )
    with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
        stream.write(line + "\n")
    os.chmod(path, 0o600)
