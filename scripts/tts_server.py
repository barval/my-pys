#!/usr/bin/env python3
"""Локальный HTTP-сервис Piper для действия «Сказать».

POST /say с {"text": "..."} возвращает моно WAV 16 бит. Модель голоса
загружается один раз и остаётся в памяти; запросы выполняются последовательно,
потому что PiperVoice не безопасен при одновременном синтезе.
"""
from __future__ import annotations

import io
import json
import logging
import os
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

VOICE_PATH = os.environ.get("TTS_VOICE_PATH", "/voices/model.onnx")
PORT = int(os.environ.get("TTS_PORT", "8083"))
MAX_TEXT = int(os.environ.get("TTS_MAX_CHARS", "1000"))

_voice = None
_voice_lock = threading.Lock()
_speak_lock = threading.Lock()


def _load_voice():
    global _voice
    with _voice_lock:
        if _voice is None:
            from piper import PiperVoice

            _voice = PiperVoice.load(VOICE_PATH, use_cuda=False)
        return _voice


def _synthesize(text: str) -> bytes:
    voice = _load_voice()
    buffer = io.BytesIO()
    with _speak_lock:
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(voice.config.sample_rate)
            voice.synthesize(text, wav_file)
    return buffer.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = "my-pys-tts/2.2"

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        parts = urlsplit(self.path)
        if parts.path == "/healthz":
            self._json(200, {"status": "ok"})
            return
        if parts.path == "/say.wav":
            text = (parse_qs(parts.query).get("text") or [""])[0].strip()
            self._say(text)
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        if self.path != "/say":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json(400, {"error": "request body must be valid JSON"})
            return
        text = str(payload.get("text", "")).strip() if isinstance(payload, dict) else ""
        self._say(text)

    def _say(self, text: str) -> None:
        if not text:
            self._json(400, {"error": "text is required"})
            return
        if len(text) > MAX_TEXT:
            self._json(413, {"error": "text is too long"})
            return
        try:
            audio = _synthesize(text)
        except Exception as exc:  # noqa: BLE001 - surface any TTS failure
            logging.exception("synthesis failed")
            self._json(500, {"error": str(exc)})
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(audio)))
        self.end_headers()
        self.wfile.write(audio)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - stdlib naming
        logging.info("%s - %s", self.address_string(), fmt % args)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("TTS_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _load_voice()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    logging.info("tts listening on :%s with %s", PORT, VOICE_PATH)
    server.serve_forever()


if __name__ == "__main__":
    main()
