"""A fake Bitrix24 REST endpoint running on localhost for tests."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from bitrix24_mcp.client import Bitrix24Client

TOKEN = "s3cr3ttok3n"

Handler = Callable[[dict[str, Any]], "tuple[int, dict[str, Any]] | dict[str, Any]"]


class FakeBitrix:
    def __init__(self) -> None:
        self.routes: dict[str, Handler] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.port = 0

    @property
    def webhook(self) -> str:
        return f"http://127.0.0.1:{self.port}/rest/1/{TOKEN}/"

    def route(self, method: str, handler: Handler | dict[str, Any]) -> None:
        self.routes[method] = handler if callable(handler) else (lambda _p, h=handler: h)

    def methods_called(self) -> list[str]:
        return [m for m, _ in self.calls]


@pytest.fixture
def fake() -> Iterator[FakeBitrix]:
    state = FakeBitrix()

    class RequestHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            prefix = f"/rest/1/{TOKEN}/"
            if not self.path.startswith(prefix) or not self.path.endswith(".json"):
                self._send(401, {"error": "INVALID_CREDENTIALS", "error_description": "bad url"})
                return
            method = self.path[len(prefix) : -len(".json")]
            length = int(self.headers.get("Content-Length") or 0)
            params = json.loads(self.rfile.read(length) or b"{}")
            state.calls.append((method, params))
            handler = state.routes.get(method)
            if handler is None:
                self._send(404, {"error": "ERROR_METHOD_NOT_FOUND", "error_description": method})
                return
            out = handler(params)
            status, body = out if isinstance(out, tuple) else (200, out)
            self._send(status, body)

        def _send(self, status: int, body: dict[str, Any]) -> None:
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_args: Any) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
    state.port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def client(fake: FakeBitrix) -> Bitrix24Client:
    return Bitrix24Client(fake.webhook, allow_insecure=True, backoff=0.01, timeout=5)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
