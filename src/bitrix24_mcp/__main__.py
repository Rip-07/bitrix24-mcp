"""Command-line entry point: ``bitrix24-mcp`` or ``python -m bitrix24_mcp``."""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from . import __version__
from .client import Bitrix24Client
from .server import build_server

log = logging.getLogger("bitrix24_mcp")

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _bool(env: dict[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"{name} must be true or false, got {raw!r}")


@dataclass
class Settings:
    webhook_url: str
    read_only: bool = True
    allow_raw_calls: bool = False
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    auth_token: str | None = None
    allow_no_auth: bool = False
    allowed_hosts: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if env is None else env)
        url = env.get("BITRIX24_WEBHOOK_URL", "").strip()
        if not url:
            raise ValueError("BITRIX24_WEBHOOK_URL is not set")
        hosts = [h.strip() for h in env.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
        return cls(
            webhook_url=url,
            read_only=_bool(env, "BITRIX24_READ_ONLY", True),
            allow_raw_calls=_bool(env, "BITRIX24_ALLOW_RAW_CALLS", False),
            transport=env.get("MCP_TRANSPORT", "stdio").strip() or "stdio",
            host=env.get("MCP_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=int(env.get("MCP_PORT", "8000")),
            auth_token=(env.get("MCP_AUTH_TOKEN") or "").strip() or None,
            allow_no_auth=_bool(env, "MCP_ALLOW_NO_AUTH", False),
            allowed_hosts=hosts,
        )


class BearerAuthMiddleware:
    """Pure-ASGI middleware requiring ``Authorization: Bearer <token>``.

    Streaming-safe (does not buffer responses). ``/health`` stays public.
    """

    def __init__(self, app: Any, token: str, public_paths: frozenset[str] = frozenset({"/health"})):
        self.app = app
        self._expected = f"Bearer {token}".encode()
        self.public_paths = public_paths

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("path") in self.public_paths:
            await self.app(scope, receive, send)
            return
        provided = b""
        for name, value in scope.get("headers") or []:
            if name.lower() == b"authorization":
                provided = value
                break
        if hmac.compare_digest(provided, self._expected):
            await self.app(scope, receive, send)
            return
        body = json.dumps({"error": "unauthorized"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def build_http_app(settings: Settings, server: Any) -> Any:
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.responses import JSONResponse

    @server.custom_route("/health", methods=["GET"])
    async def health(_request: Any) -> JSONResponse:
        return JSONResponse({"status": "ok", "version": __version__})

    security = None
    if settings.allowed_hosts:
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.allowed_hosts,
            allowed_origins=[f"https://{h.split(':')[0]}" for h in settings.allowed_hosts],
        )
    app = server.streamable_http_app(transport_security=security, host=settings.host)
    if settings.auth_token:
        app = BearerAuthMiddleware(app, settings.auth_token)
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bitrix24-mcp", description="MCP server for Bitrix24")
    parser.add_argument("--transport", choices=["stdio", "http"], help="overrides MCP_TRANSPORT")
    parser.add_argument("--host", help="overrides MCP_HOST (http only)")
    parser.add_argument("--port", type=int, help="overrides MCP_PORT (http only)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    # stdout belongs to the MCP protocol in stdio mode: log to stderr only.
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        settings = Settings.from_env()
    except ValueError as exc:
        log.error("%s", exc)
        return 2
    if args.transport:
        settings.transport = args.transport
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    if settings.transport == "streamable-http":
        settings.transport = "http"
    if settings.transport not in ("stdio", "http"):
        log.error("MCP_TRANSPORT must be stdio or http")
        return 2

    try:
        client = Bitrix24Client(settings.webhook_url)
    except ValueError as exc:
        log.error("%s", exc)
        return 2

    server = build_server(
        client, read_only=settings.read_only, allow_raw_calls=settings.allow_raw_calls
    )
    log.info(
        "bitrix24-mcp %s: portal %s, read_only=%s, transport=%s",
        __version__,
        client.masked_url,
        settings.read_only,
        settings.transport,
    )

    if settings.transport == "stdio":
        server.run("stdio")
        return 0

    if not settings.auth_token and not settings.allow_no_auth:
        log.error(
            "HTTP transport needs MCP_AUTH_TOKEN (or MCP_ALLOW_NO_AUTH=true for a trusted network)"
        )
        return 2
    import uvicorn

    app = build_http_app(settings, server)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
