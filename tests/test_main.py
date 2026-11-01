from __future__ import annotations

import pytest

from bitrix24_mcp.__main__ import BearerAuthMiddleware, Settings, main

pytestmark = pytest.mark.anyio

WEBHOOK = "https://portal.bitrix24.kz/rest/1/abc123/"


def test_settings_defaults_are_safe():
    s = Settings.from_env({"BITRIX24_WEBHOOK_URL": WEBHOOK})
    assert s.read_only is True
    assert s.allow_raw_calls is False
    assert s.transport == "stdio"
    assert s.host == "127.0.0.1"


def test_settings_parses_env():
    s = Settings.from_env(
        {
            "BITRIX24_WEBHOOK_URL": WEBHOOK,
            "BITRIX24_READ_ONLY": "false",
            "MCP_TRANSPORT": "http",
            "MCP_PORT": "9000",
            "MCP_AUTH_TOKEN": "t",
            "MCP_ALLOWED_HOSTS": "mcp.example.kz, localhost:9000",
        }
    )
    assert s.read_only is False
    assert s.port == 9000
    assert s.allowed_hosts == ["mcp.example.kz", "localhost:9000"]


def test_settings_rejects_ambiguous_bool():
    with pytest.raises(ValueError):
        Settings.from_env({"BITRIX24_WEBHOOK_URL": WEBHOOK, "BITRIX24_READ_ONLY": "maybe"})


def test_main_requires_webhook(monkeypatch):
    monkeypatch.delenv("BITRIX24_WEBHOOK_URL", raising=False)
    assert main([]) == 2


def test_http_without_token_refuses_to_start(monkeypatch):
    monkeypatch.setenv("BITRIX24_WEBHOOK_URL", WEBHOOK)
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_ALLOW_NO_AUTH", raising=False)
    assert main(["--transport", "http"]) == 2


async def _run(app, path: str, headers: list[tuple[bytes, bytes]]):
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await app({"type": "http", "path": path, "headers": headers}, receive, send)
    return sent


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


@pytest.mark.parametrize(
    ("path", "headers", "status"),
    [
        ("/mcp", [], 401),
        ("/mcp", [(b"authorization", b"Bearer wrong")], 401),
        ("/mcp", [(b"authorization", b"Bearer good")], 200),
        ("/mcp", [(b"Authorization", b"Bearer good")], 200),
        ("/health", [], 200),
    ],
)
async def test_bearer_middleware(path, headers, status):
    app = BearerAuthMiddleware(_ok_app, "good")
    sent = await _run(app, path, headers)
    assert sent[0]["status"] == status
