"""Minimal async client for the Bitrix24 REST API (inbound webhooks).

Uses only the standard library for HTTP so the package has a single runtime
dependency (the MCP SDK). Requests run in a worker thread to keep the event
loop free.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any

from . import __version__

log = logging.getLogger(__name__)

PAGE_SIZE = 50  # Bitrix24 returns at most 50 records per list call
_RETRYABLE_ERRORS = {"QUERY_LIMIT_EXCEEDED"}
_METHOD_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
_WEBHOOK_RE = re.compile(r"^(https?)://([^/\s]+)/rest/(\d+)/([A-Za-z0-9]+)/?$")


class Bitrix24Error(Exception):
    """Error returned by Bitrix24 or raised while talking to it."""

    def __init__(self, code: str, description: str = "", status: int | None = None) -> None:
        self.code = code
        self.description = description
        self.status = status
        message = code if not description else f"{code}: {description}"
        super().__init__(message)


def mask_webhook(url: str) -> str:
    """Hide the secret token of a webhook URL, e.g. for logs and error messages."""
    match = _WEBHOOK_RE.match(url.strip())
    if not match:
        return "<invalid webhook url>"
    scheme, host, user_id, _token = match.groups()
    return f"{scheme}://{host}/rest/{user_id}/***/"


class Bitrix24Client:
    """Calls Bitrix24 REST methods through an inbound webhook URL.

    The webhook URL looks like ``https://example.bitrix24.kz/rest/1/abcdef123456/``
    and is a secret: anyone who has it can act with the webhook's permissions.
    """

    def __init__(
        self,
        webhook_url: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff: float = 0.5,
        allow_insecure: bool = False,
    ) -> None:
        url = webhook_url.strip()
        match = _WEBHOOK_RE.match(url)
        if not match:
            raise ValueError(
                "BITRIX24_WEBHOOK_URL must look like https://<portal>/rest/<user_id>/<token>/"
            )
        if match.group(1) != "https" and not allow_insecure:
            raise ValueError("BITRIX24_WEBHOOK_URL must use https")
        self._base = url.rstrip("/") + "/"
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff

    @property
    def masked_url(self) -> str:
        return mask_webhook(self._base)

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a REST method and return the full JSON response (result, total, next...)."""
        if not _METHOD_RE.match(method):
            raise ValueError(f"Invalid Bitrix24 method name: {method!r}")
        attempt = 0
        while True:
            try:
                return await asyncio.to_thread(self._post, method, params or {})
            except Bitrix24Error as exc:
                if exc.code in _RETRYABLE_ERRORS and attempt < self.max_retries:
                    delay = self.backoff * (2**attempt)
                    log.warning("Bitrix24 rate limit on %s, retrying in %.1fs", method, delay)
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                raise

    async def result(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Call a REST method and return only its ``result`` field."""
        return (await self.call(method, params)).get("result")

    async def list(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        limit: int = 50,
        result_key: str | None = None,
    ) -> list[Any]:
        """Call a ``*.list`` method, following pagination until ``limit`` items are collected.

        ``result_key`` is for methods that wrap the list, e.g. ``tasks.task.list``
        returns ``{"result": {"tasks": [...]}}``.
        """
        items: list[Any] = []
        start: int | None = 0
        base = dict(params or {})
        while start is not None and len(items) < limit:
            response = await self.call(method, {**base, "start": start})
            page = response.get("result") or []
            if result_key is not None and isinstance(page, dict):
                page = page.get(result_key) or []
            if not isinstance(page, list):
                raise Bitrix24Error("UNEXPECTED_RESPONSE", f"{method} did not return a list")
            items.extend(page)
            nxt = response.get("next")
            start = int(nxt) if nxt is not None and page else None
        return items[:limit]

    # -- internals ---------------------------------------------------------

    def _post(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self._base + method + ".json",
            data=json.dumps(params, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": f"bitrix24-mcp/{__version__}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = response.status
                body = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = exc.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise Bitrix24Error(
                "NETWORK_ERROR", f"cannot reach {self.masked_url}: {reason}"
            ) from None

        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise Bitrix24Error(
                "INVALID_RESPONSE", f"HTTP {status}, response is not JSON", status
            ) from None

        if isinstance(data, dict) and "error" in data:
            raise Bitrix24Error(
                str(data.get("error")), str(data.get("error_description") or ""), status
            )
        if status >= 400:
            raise Bitrix24Error("HTTP_ERROR", f"HTTP {status}", status)
        if not isinstance(data, dict):
            raise Bitrix24Error("INVALID_RESPONSE", "response is not a JSON object", status)
        return data
