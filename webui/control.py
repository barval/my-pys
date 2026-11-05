from __future__ import annotations

import http.client
import json
import os
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
CONTAINER = os.environ.get("CONTROL_CONTAINER", "llm-router")
SOCKET_PATH = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")
PORT = int(os.environ.get("CONTROL_PORT", "8081"))


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str):
        super().__init__("localhost")
        self.socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect(self.socket_path)


def restart_container(name: str = CONTAINER, socket_path: str = SOCKET_PATH) -> int:
    if not _CONTAINER_RE.fullmatch(name):
        raise ValueError(f"invalid container name: {name}")
    connection = UnixHTTPConnection(socket_path)
    try:
        connection.request("POST", f"/containers/{name}/restart?t=10")
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


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
        if self.path != "/restart":
            self._json(404, {"error": "not found"})
            return
        try:
            status = restart_container()
        except (OSError, ValueError) as exc:
            self._json(502, {"error": str(exc)})
            return
        if 200 <= status < 300:
            self._json(200, {"status": "restarted"})
        else:
            self._json(502, {"error": f"docker returned {status}"})

    def log_message(self, fmt: str, *args) -> None:
        print(fmt % args, flush=True)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"router-control listening on :{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
