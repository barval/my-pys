from __future__ import annotations

import argparse
import getpass
import os

from .auth import hash_password, load_or_create_session_key
from .settings import load_settings


def _write_private(path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp")
    temp.write_text(data, encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Администрирование web UI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("set-password", help="задать пароль администратора")
    sub.add_parser("generate-session-key", help="создать ключ сессий")
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.command == "set-password":
        first = getpass.getpass("Новый пароль: ")
        second = getpass.getpass("Повторите пароль: ")
        if first != second:
            raise SystemExit("Пароли не совпадают")
        if len(first) < 8:
            raise SystemExit("Пароль должен быть не короче 8 символов")
        _write_private(settings.admin_hash_file, hash_password(first) + "\n")
        print(f"Сохранено: {settings.admin_hash_file}")
    elif args.command == "generate-session-key":
        load_or_create_session_key(settings.session_key_file)
        print(f"Сохранено: {settings.session_key_file}")


if __name__ == "__main__":
    main()
