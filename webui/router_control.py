from __future__ import annotations

import os
import sys
import urllib.request


def restart(base_url: str, timeout: float = 30.0) -> tuple[int, str]:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/restart",
        data=b"",
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def main() -> int:
    url = os.environ.get("WEBUI_SIDECAR_URL", "http://127.0.0.1:8081")
    try:
        status, body = restart(url)
    except Exception as exc:  # noqa: BLE001 - report to the job log
        print(f"sidecar error: {exc}", file=sys.stderr)
        return 1
    print(body)
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
