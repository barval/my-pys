#!/usr/bin/env python3
"""Проверка маркеров открытой релизной линии my-pys.

Только чтение. Запускать из корня репозитория после поднятия версии.

Обязательные проверки описывают, как выглядит открытая линия: ветка
нарезана, версия продукта обновлена во всех местах, где её видит
пользователь, API, тесты или агент, предыдущий раздел CHANGELOG датирован,
новый открыт как Unreleased.

Все оставшиеся вхождения прошлой версии печатаются как REVIEW. Это не
ошибка: версия законно живёт в истории CHANGELOG, в размерах CSS
(2.1rem), в адресах и в комментариях ключей. Каждую строку нужно
прочитать и классифицировать; переписывать вслепую нельзя.

Коды возврата:
    0  обязательные маркеры верны (REVIEW может быть)
    1  хотя бы один обязательный маркер отсутствует или устарел
    2  ошибка использования или чтения файла
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git",
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "backups",
    "graphify-out",
    "local",
    "node_modules",
    "router-state",
    "secrets",
    "webui-state",
}

SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".pdf", ".mo", ".log",
    ".zip", ".gz", ".tar", ".pyc", ".whl", ".img",
}

VERSION_RE = re.compile(r"^\d+\.\d+$")

# (файл, описание, регулярное выражение, ожидаемое число совпадений)
MANDATORY: list[tuple[str, str, str, int]] = [
    ("VERSION", "файл версии", r"^v{ver}$", 1),
    ("webui/__init__.py", "версия пакета", r'__version__\s*=\s*"{ver}"', 1),
    ("router/llm_router.py", "User-Agent роутера", r'"User-Agent":\s*"llm-router/{ver}"', 2),
    ("scripts/tts_server.py", "версия TTS-сервиса", r'server_version\s*=\s*"my-pys-tts/{ver}"', 1),
    ("README.md", "строка версии", r"\*\*Версия:\*\*\s*v{ver}", 1),
    ("AGENTS.md", "текущая версия", r"Текущая версия — \*\*`v{ver}`\*\*", 1),
    ("AGENTS.md", "тег версии", r"git-тег — `{ver}`", 1),
    ("AGENTS.md", "версия в интерфейсе", r"`/healthz` — `{ver}`", 1),
    ("CONTRIBUTING.md", "рабочая ветка", r"`v{ver}` — текущая рабочая ветка", 1),
    ("docs/README.md", "актуальное состояние", r"Актуальное состояние v{ver}", 1),
    ("docs/04-risks.md", "ограничения линии", r"## Ограничения v{ver}", 1),
    ("docs/03-runbook.md", "шаг тега", r"тег `v{ver}`", 1),
    ("webui/tests/test_app.py", "версия в /healthz", r'payload\["version"\]\s*==\s*"{ver}"', 1),
    ("webui/tests/test_app.py", "версия в шапке", r"<small>v{ver}</small>", 1),
]

CHANGELOG = Path("CHANGELOG.md")


def iter_text_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        if rel.parts[:2] == ("vendor", "lite-kit"):
            continue
        try:
            yield rel, path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"ERROR  {rel}: {exc}", file=sys.stderr)


def check_mandatory(version: str) -> list[str]:
    failures: list[str] = []
    for filename, label, pattern, expected in MANDATORY:
        path = Path(filename)
        if not path.is_file():
            failures.append(f"{filename}: файл не найден ({label})")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found = len(re.findall(pattern.format(ver=re.escape(version)), text, re.MULTILINE))
        if found != expected:
            failures.append(f"{filename}: {label} — найдено {found}, ожидалось {expected}")
        else:
            print(f"OK     {filename}: {label}")
    return failures


def check_changelog(version: str, previous: str) -> list[str]:
    if not CHANGELOG.is_file():
        return ["CHANGELOG.md: файл не найден"]
    text = CHANGELOG.read_text(encoding="utf-8", errors="replace")
    failures: list[str] = []
    if not re.search(rf"^## \[{re.escape(version)}\] — (Unreleased|\d{{4}}-\d{{2}}-\d{{2}})$", text, re.MULTILINE):
        failures.append(f"CHANGELOG.md: нет раздела «## [{version}] — Unreleased» или даты")
    else:
        print(f"OK     CHANGELOG.md: раздел {version} открыт (Unreleased или дата)")
    if not re.search(rf"^## \[{re.escape(previous)}\] — \d{{4}}-\d{{2}}-\d{{2}}$", text, re.MULTILINE):
        failures.append(f"CHANGELOG.md: раздел {previous} не датирован")
    else:
        print(f"OK     CHANGELOG.md: раздел {previous} датирован")
    return failures


def review_rows(previous: str) -> list[tuple[str, int, str]]:
    pattern = re.compile(rf"(?<![\d.]){re.escape(previous)}(?![\d])")
    rows: list[tuple[str, int, str]] = []
    for rel, text in iter_text_files(Path(".")):
        for number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                rows.append((str(rel), number, line.strip()[:120]))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="новая версия, например 2.2")
    parser.add_argument("--previous", required=True, help="прошлая версия, например 2.1")
    args = parser.parse_args()

    if not VERSION_RE.match(args.version) or not VERSION_RE.match(args.previous):
        print("Версия должна быть в формате X.Y", file=sys.stderr)
        return 2
    if args.version == args.previous:
        print("Новая и прошлая версии совпадают", file=sys.stderr)
        return 2
    if not Path("VERSION").is_file():
        print("Запускать из корня репозитория", file=sys.stderr)
        return 2

    failures = check_mandatory(args.version)
    failures += check_changelog(args.version, args.previous)

    rows = review_rows(args.previous)
    print(f"\nREVIEW — вхождений {args.previous}: {len(rows)}")
    for filename, number, line in rows:
        print(f"REVIEW {filename}:{number}: {line}")

    if failures:
        print("\nПРОВЕРКА НЕ ПРОЙДЕНА:")
        for failure in failures:
            print(f"FAIL   {failure}")
        return 1
    print(f"\nМаркеры версии {args.version} корректны.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
