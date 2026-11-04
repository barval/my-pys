#!/usr/bin/env python3
"""Drive the official Quasar Bridge installer through a PTY.

The installer runs the remote setup with `ssh -tt`. A plain pipe closes
before setup.sh can read its answers; pexpect keeps a real terminal open
and sends each answer when the corresponding prompt appears.
"""
import os
import re
import sys

try:
    import pexpect
except ImportError:  # pragma: no cover - checked by the shell wrapper
    print("Нужен python3-pexpect", file=sys.stderr)
    sys.exit(2)


def main() -> int:
    if len(sys.argv) != 7:
        print(
            "usage: bridge_install_pexpect.py INSTALLER TARGET PORT BASE MODEL TOKEN",
            file=sys.stderr,
        )
        return 2

    installer, target, port, base, model, token = sys.argv[1:7]
    reboot = os.environ.get("REBOOT", "y")
    env = os.environ.copy()

    child = pexpect.spawn(
        "sh", [installer, target, "-p", port],
        env=env, encoding="utf-8", timeout=600,
    )
    child.logfile = None

    def send(pattern: str, answer: str, timeout: int = 600) -> None:
        child.expect(pattern, timeout=timeout)
        child.sendline(answer)

    def redact(text: str) -> str:
        if not text:
            return ""
        return text.replace(token, "***")

    try:
        child.expect(
            ["Изменить подключение к нейросети\\?", "Адрес API нейросети"],
            timeout=180,
        )
        if "Изменить" in child.after:
            child.sendline("y")
            child.expect("Адрес API нейросети", timeout=60)
        child.sendline(base)

        send("Название модели:", model)
        send("Ключ API", token)
        send("Chat Completions", "1")
        send("Home Assistant MCP", "")

        index = child.expect(
            [
                "Проверка не прошла",
                "Подключить Алису к Quasar Bridge",
                "Обновление завершено",
                pexpect.EOF,
            ],
            timeout=600,
        )
        if index == 0:
            child.sendline("n")
            print("Проверка подключения к FLAI не прошла.", file=sys.stderr)
            print(redact((child.before or ""))[-4000:], file=sys.stderr)
            return 1
        if index == 1:
            child.sendline("y")
            send("Перезагрузить сейчас", reboot)
            child.expect(pexpect.EOF, timeout=180)
        elif index == 2:
            # Already connected: installer skips the connect/reboot prompts.
            child.expect(pexpect.EOF, timeout=60)
        else:
            pass
    except pexpect.TIMEOUT:
        print("Таймаут ожидания мастера установки.", file=sys.stderr)
        print(redact((child.before or ""))[-4000:], file=sys.stderr)
        return 1
    except pexpect.EOF:
        print("Установщик закрыл соединение до завершения.", file=sys.stderr)
        print(redact((child.before or ""))[-4000:], file=sys.stderr)
        return 1
    finally:
        child.close(force=True)

    print("Установка завершена.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
