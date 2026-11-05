from __future__ import annotations

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get("CONTROL_PORT", "8082"))
REPO = Path(os.environ.get("STAND_REPO", "/app"))

_COMMANDS = {
    "start": (["bash", "scripts/start-lite-kit.sh"], 900),
    "stop": (["bash", "scripts/stop-lite-kit.sh"], 120),
    "status": (
        [
            "docker",
            "ps",
            "--filter",
            "name=ysl-lite-kit",
            "--format",
            "{{.Status}}",
        ],
        30,
    ),
}


def run_action(action: str, repo: Path | str | None = None) -> tuple[int, dict]:
    if action not in _COMMANDS:
        raise ValueError(f"unknown action: {action}")
    argv, timeout = _COMMANDS[action]
    if action in ("start", "stop") and not os.environ.get("HOST_REPO_PATH"):
        return 500, {
            "status": "error",
            "error": "HOST_REPO_PATH is not set; run via make webui",
        }
    cwd = Path(repo or REPO)
    result = subprocess.run(
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if action == "status":
        payload = {
            "running": bool(output) and result.returncode == 0,
            "status": output,
        }
        if error:
            payload["error"] = error
        return (200 if result.returncode == 0 else 500), payload
    payload = {
        "status": "ok" if result.returncode == 0 else "error",
        "output": output[-4000:],
    }
    if error:
        payload["error"] = error[-2000:]
    return (200 if result.returncode == 0 else 500), payload


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        action = self.path.lstrip("/")
        if action not in _COMMANDS:
            self._json(404, {"error": "not found"})
            return
        try:
            status, payload = run_action(action)
        except subprocess.TimeoutExpired:
            self._json(504, {"status": "error", "error": "timeout"})
            return
        except OSError as exc:
            self._json(502, {"status": "error", "error": str(exc)})
            return
        self._json(status, payload)

    def log_message(self, fmt: str, *args) -> None:
        print(fmt % args, flush=True)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"stand-control listening on :{PORT} (repo {REPO})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
