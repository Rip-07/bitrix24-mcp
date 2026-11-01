from __future__ import annotations

import pytest

from bitrix24_mcp.client import Bitrix24Client, Bitrix24Error, mask_webhook

from .conftest import TOKEN

pytestmark = pytest.mark.anyio


def paged(total: int):
    """Handler emulating Bitrix24 pagination (50 per page, `next` offset)."""

    def handler(params):
        start = int(params.get("start", 0))
        page = [{"ID": str(i)} for i in range(start, min(start + 50, total))]
        body = {"result": page, "total": total}
        if start + 50 < total:
            body["next"] = start + 50
        return body

    return handler


async def test_result_returns_result_field(fake, client):
    fake.route("user.current", {"result": {"ID": "1", "NAME": "Askhat"}})
    assert await client.result("user.current") == {"ID": "1", "NAME": "Askhat"}


async def test_list_follows_pagination_and_respects_limit(fake, client):
    fake.route("crm.deal.list", paged(120))
    items = await client.list("crm.deal.list", {"select": ["ID"]}, limit=70)
    assert len(items) == 70
    assert [p["start"] for _, p in fake.calls] == [0, 50]


async def test_list_stops_when_no_next(fake, client):
    fake.route("crm.deal.list", paged(30))
    items = await client.list("crm.deal.list", limit=200)
    assert len(items) == 30
    assert len(fake.calls) == 1


async def test_list_with_result_key(fake, client):
    fake.route("tasks.task.list", {"result": {"tasks": [{"id": "7"}]}, "total": 1})
    assert await client.list("tasks.task.list", result_key="tasks") == [{"id": "7"}]


async def test_retries_on_rate_limit(fake, client):
    attempts = {"n": 0}

    def flaky(_params):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return 503, {"error": "QUERY_LIMIT_EXCEEDED", "error_description": "Too many requests"}
        return {"result": True}

    fake.route("crm.deal.update", flaky)
    assert await client.result("crm.deal.update", {"id": 1}) is True
    assert attempts["n"] == 3


async def test_gives_up_after_max_retries(fake, client):
    fake.route("crm.deal.list", lambda _p: (503, {"error": "QUERY_LIMIT_EXCEEDED"}))
    with pytest.raises(Bitrix24Error) as exc:
        await client.call("crm.deal.list")
    assert exc.value.code == "QUERY_LIMIT_EXCEEDED"
    assert len(fake.calls) == client.max_retries + 1


async def test_bitrix_error_is_raised_with_code(fake, client):
    fake.route("crm.deal.get", (400, {"error": "NOT_FOUND", "error_description": "Not found"}))
    with pytest.raises(Bitrix24Error, match="NOT_FOUND: Not found"):
        await client.call("crm.deal.get", {"id": 999})


async def test_network_error_does_not_leak_token():
    dead = Bitrix24Client(f"http://127.0.0.1:1/rest/1/{TOKEN}/", allow_insecure=True, timeout=1)
    with pytest.raises(Bitrix24Error) as exc:
        await dead.call("user.current")
    assert exc.value.code == "NETWORK_ERROR"
    assert TOKEN not in str(exc.value)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://portal.bitrix24.kz/",
        "https://portal.bitrix24.kz/rest/abc/token/",
        "ftp://portal.bitrix24.kz/rest/1/token/",
    ],
)
def test_rejects_invalid_webhook(url):
    with pytest.raises(ValueError):
        Bitrix24Client(url)


def test_requires_https_by_default():
    with pytest.raises(ValueError, match="https"):
        Bitrix24Client("http://portal.bitrix24.kz/rest/1/token/")


@pytest.mark.parametrize("method", ["../admin", "crm.deal.list?x=1", "CRM", "user", "crm deal"])
async def test_rejects_bad_method_names(client, method):
    with pytest.raises(ValueError):
        await client.call(method)


def test_mask_webhook():
    assert mask_webhook("https://a.bitrix24.kz/rest/12/abcDEF123/") == (
        "https://a.bitrix24.kz/rest/12/***/"
    )
    assert "abc" not in mask_webhook("garbage abc")
