#!/usr/bin/env python3
"""Small OpenAI-compatible proxy that strips voice invocation phrases.

Quasar Bridge sends the recognised phrase as-is ("Спроси у ФЛАЙ: ...").
FLAI should receive only the actual question ("..."). This proxy sits in
front of FLAI and rewrites the last user message before forwarding.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("FLAI_UPSTREAM", "http://127.0.0.1:5000").rstrip("/")
PORT = int(os.environ.get("PROXY_PORT", "5001"))
TIMEOUT = float(os.environ.get("PROXY_TIMEOUT", "600"))

INVOCATION = re.compile(
    r"^\s*(?:алиса[,\s]+)?(?:пожалуйста[,\s]+)?"
    r"(?:спроси\s+(?:у\s+)?(?:флай|нейросет(?:ь|и)|свою\s+модель|у\s+своей\s+модели)"
    r"|используй\s+нейросеть)"
    r"[\s,:;.!?-]+",
    re.IGNORECASE,
)


def clean_text(text: str) -> str:
    if not isinstance(text, str):
        return text
    cleaned = INVOCATION.sub("", text).strip()
    return cleaned or text.strip()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _read_body(self) -> bytes | None:
        length = self.headers.get("Content-Length")
        if not length:
            return None
        try:
            return self.rfile.read(int(length))
        except (TypeError, ValueError):
            return None

    def _rewrite_chat(self, body: bytes) -> bytes:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return body
        messages = payload.get("messages")
        if isinstance(messages, list):
            for message in messages:
                if not isinstance(message, dict):
                    continue
                if message.get("role") != "user":
                    continue
                content = message.get("content")
                if isinstance(content, str):
                    message["content"] = clean_text(content)
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def _proxy(self) -> None:
        body = self._read_body()
        path = self.path
        if path.startswith("/v1/chat/completions") and body:
            body = self._rewrite_chat(body)

        request = urllib.request.Request(
            UPSTREAM + path,
            data=body,
            method=self.command,
        )
        for header in ("Authorization", "Content-Type", "Accept"):
            value = self.headers.get(header)
            if value:
                request.add_header(header, value)

        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                data = response.read()
                self.send_response(response.status)
                content_type = response.headers.get("Content-Type")
                if content_type:
                    self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as exc:
            data = exc.read()
            self.send_response(exc.code)
            content_type = exc.headers.get("Content-Type", "application/json")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:  # noqa: BLE001 - return a clear proxy error
            message = json.dumps(
                {"error": {"message": f"proxy: {exc}", "type": "proxy_error"}},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        self._proxy()

    def do_GET(self) -> None:  # noqa: N802
        self._proxy()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.address_string(), self.log_date_time_string(), fmt % args)
        )


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"flai invocation proxy on :{PORT} -> {UPSTREAM}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
