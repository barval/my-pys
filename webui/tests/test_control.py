from __future__ import annotations

import socketserver
import threading

from webui.control import restart_container


def test_restart_container_calls_docker_socket(tmp_path):
    socket_path = tmp_path / "docker.sock"
    requests: list[bytes] = []

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            requests.append(self.request.recv(4096))
            self.request.sendall(
                b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n"
            )

    server = socketserver.UnixStreamServer(str(socket_path), Handler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    try:
        status = restart_container("llm-router", str(socket_path))
    finally:
        thread.join(timeout=5)
        server.server_close()

    assert status == 204
    assert requests
    assert b"POST /containers/llm-router/restart" in requests[0]
