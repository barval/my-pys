from __future__ import annotations

import os
import sys
import urllib.request


def request(
    action: str, base_url: str, timeout: float = 600.0
) -> tuple[int, str]:
    req = urllib.request.Request(
        base_url.rstrip("/") + "/" + action,
        data=b"",
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m webui.stand_client start|stop|status", file=sys.stderr)
        return 2
    action = sys.argv[1]
    if action not in ("start", "stop", "status"):
        print(f"unknown action: {action}", file=sys.stderr)
        return 2
    url = os.environ.get("WEBUI_STAND_URL", "http://127.0.0.1:8082")
    try:
        status, body = request(action, url)
    except Exception as exc:  # noqa: BLE001 - report to the job log
        print(f"stand-control error: {exc}", file=sys.stderr)
        return 1
    print(body)
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
