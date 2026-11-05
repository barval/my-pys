from __future__ import annotations

import argparse

from .app import create_app
from .settings import load_settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Локальная веб-панель проекта")
    parser.add_argument("--host", help="адрес прослушивания")
    parser.add_argument("--port", type=int, help="порт")
    args = parser.parse_args(argv)

    settings = load_settings()
    app = create_app(settings)
    app.run(
        host=args.host or settings.host,
        port=args.port or settings.port,
    )


if __name__ == "__main__":
    main()
