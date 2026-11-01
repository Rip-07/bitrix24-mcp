"""MCP server exposing Bitrix24 CRM and tasks as tools."""

from __future__ import annotations

import re
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__
from .client import Bitrix24Client, Bitrix24Error

MAX_LIMIT = 200

DEAL_FIELDS = [
    "ID",
    "TITLE",
    "STAGE_ID",
    "CATEGORY_ID",
    "OPPORTUNITY",
    "CURRENCY_ID",
    "CONTACT_ID",
    "COMPANY_ID",
    "ASSIGNED_BY_ID",
    "DATE_CREATE",
    "DATE_MODIFY",
    "CLOSEDATE",
]
CONTACT_FIELDS = [
    "ID",
    "NAME",
    "SECOND_NAME",
    "LAST_NAME",
    "PHONE",
    "EMAIL",
    "COMPANY_ID",
    "ASSIGNED_BY_ID",
    "DATE_MODIFY",
]
LEAD_FIELDS = [
    "ID",
    "TITLE",
    "STATUS_ID",
    "NAME",
    "LAST_NAME",
    "PHONE",
    "EMAIL",
    "SOURCE_ID",
    "ASSIGNED_BY_ID",
    "DATE_CREATE",
]
TASK_FIELDS = ["ID", "TITLE", "STATUS", "RESPONSIBLE_ID", "CREATED_BY", "DEADLINE", "CREATED_DATE"]

INSTRUCTIONS = """\
Tools for a Bitrix24 portal: CRM deals, contacts, leads and tasks.
IDs are Bitrix24 numeric IDs. Deal stages are portal-specific: call
list_deal_stages before filtering or moving deals by stage. Amounts default
to KZT. Write tools exist only if the server was started with
BITRIX24_READ_ONLY=false; confirm with the user before creating or changing
records."""

_READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
)


def _clamp(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


def _multi(values: Any) -> list[str]:
    """Flatten Bitrix24 multi-fields ([{"VALUE": ...}, ...]) into a list of strings."""
    if not isinstance(values, list):
        return []
    return [str(v.get("VALUE")) for v in values if isinstance(v, dict) and v.get("VALUE")]


def _simplify(record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    for key in ("PHONE", "EMAIL"):
        if key in out:
            out[key] = _multi(out[key])
    return out


def _comm(value: str | None) -> list[dict[str, str]] | None:
    return [{"VALUE": value, "VALUE_TYPE": "WORK"}] if value else None


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def build_server(
    client: Bitrix24Client, *, read_only: bool = True, allow_raw_calls: bool = False
) -> MCPServer:
    """Create the MCP server. Write tools are registered only when ``read_only`` is False."""
    mcp = MCPServer(
        name="bitrix24",
        title="Bitrix24",
        instructions=INSTRUCTIONS,
        version=__version__,
        website_url="https://github.com/Rip-07/bitrix24-mcp",
    )

    async def call(method: str, params: dict[str, Any] | None = None) -> Any:
        try:
            return await client.result(method, params)
        except Bitrix24Error as exc:
            raise ToolError(f"Bitrix24 {method} failed: {exc}") from None

    async def listing(method: str, params: dict[str, Any], limit: int, key: str | None = None):
        try:
            return await client.list(method, params, limit=_clamp(limit), result_key=key)
        except Bitrix24Error as exc:
            raise ToolError(f"Bitrix24 {method} failed: {exc}") from None

    # -- read tools --------------------------------------------------------

    @mcp.tool(annotations=_READ)
    async def whoami() -> dict[str, Any]:
        """Return the Bitrix24 user the webhook acts as (ID, name, email)."""
        user = await call("user.current")
        keys = ("ID", "NAME", "LAST_NAME", "EMAIL", "WORK_POSITION")
        return {k: user.get(k) for k in keys} if isinstance(user, dict) else {"result": user}

    @mcp.tool(annotations=_READ)
    async def list_deal_stages(category_id: int = 0) -> list[dict[str, Any]]:
        """List deal stages of a pipeline (category 0 is the default pipeline)."""
        entity = "DEAL_STAGE" if category_id == 0 else f"DEAL_STAGE_{category_id}"
        stages = await call(
            "crm.status.list", {"filter": {"ENTITY_ID": entity}, "order": {"SORT": "ASC"}}
        )
        return [
            {"STATUS_ID": s.get("STATUS_ID"), "NAME": s.get("NAME"), "SORT": s.get("SORT")}
            for s in stages or []
        ]

    @mcp.tool(annotations=_READ)
    async def list_deals(
        stage_id: str | None = None,
        category_id: int | None = None,
        assigned_by_id: int | None = None,
        title_contains: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List deals, newest first. Filters are optional and combined with AND."""
        flt = _drop_none(
            {
                "STAGE_ID": stage_id,
                "CATEGORY_ID": category_id,
                "ASSIGNED_BY_ID": assigned_by_id,
                "%TITLE": title_contains,
            }
        )
        params = {"filter": flt, "select": DEAL_FIELDS, "order": {"ID": "DESC"}}
        return await listing("crm.deal.list", params, limit)

    @mcp.tool(annotations=_READ)
    async def get_deal(deal_id: int) -> dict[str, Any]:
        """Get all fields of one deal."""
        return await call("crm.deal.get", {"id": deal_id})

    @mcp.tool(annotations=_READ)
    async def search_contacts(query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Find contacts by phone, email or name.

        A query with '@' searches email, a query with 6+ digits searches phone,
        anything else searches first and last name.
        """
        q = query.strip()
        if not q:
            raise ToolError("query must not be empty")
        base = {"select": CONTACT_FIELDS, "order": {"ID": "DESC"}}
        digits = re.sub(r"\D", "", q)
        if "@" in q:
            filters = [{"EMAIL": q}]
        elif len(digits) >= 6 and not re.search(r"[A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]", q):
            phone = ("+" if q.startswith("+") else "") + digits
            filters = [{"PHONE": phone}]
        else:
            filters = [{"%NAME": q}, {"%LAST_NAME": q}]
        found: dict[str, dict[str, Any]] = {}
        for flt in filters:
            for row in await listing("crm.contact.list", {**base, "filter": flt}, limit):
                found.setdefault(str(row.get("ID")), _simplify(row))
        return list(found.values())[: _clamp(limit)]

    @mcp.tool(annotations=_READ)
    async def get_contact(contact_id: int) -> dict[str, Any]:
        """Get one contact; phones and emails are returned as plain lists."""
        return _simplify(await call("crm.contact.get", {"id": contact_id}))

    @mcp.tool(annotations=_READ)
    async def list_leads(status_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """List leads, newest first, optionally by status (e.g. NEW, IN_PROCESS)."""
        params = {
            "filter": _drop_none({"STATUS_ID": status_id}),
            "select": LEAD_FIELDS,
            "order": {"ID": "DESC"},
        }
        return [_simplify(r) for r in await listing("crm.lead.list", params, limit)]

    @mcp.tool(annotations=_READ)
    async def list_tasks(
        responsible_id: int | None = None, status: int | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """List tasks, newest first.

        status: 2 pending, 3 in progress, 4 awaiting control, 5 completed, 6 deferred.
        """
        params = {
            "filter": _drop_none({"RESPONSIBLE_ID": responsible_id, "REAL_STATUS": status}),
            "select": TASK_FIELDS,
            "order": {"ID": "desc"},
        }
        return await listing("tasks.task.list", params, limit, key="tasks")

    # -- write tools -------------------------------------------------------

    if not read_only:

        @mcp.tool(annotations=_WRITE)
        async def create_lead(
            title: str,
            name: str | None = None,
            phone: str | None = None,
            email: str | None = None,
            comment: str | None = None,
        ) -> dict[str, Any]:
            """Create a CRM lead. Returns the new lead ID."""
            fields = _drop_none(
                {
                    "TITLE": title,
                    "NAME": name,
                    "PHONE": _comm(phone),
                    "EMAIL": _comm(email),
                    "COMMENTS": comment,
                }
            )
            return {"id": await call("crm.lead.add", {"fields": fields})}

        @mcp.tool(annotations=_WRITE)
        async def create_deal(
            title: str,
            stage_id: str | None = None,
            category_id: int | None = None,
            contact_id: int | None = None,
            amount: float | None = None,
            currency_id: str = "KZT",
            assigned_by_id: int | None = None,
        ) -> dict[str, Any]:
            """Create a deal. Returns the new deal ID."""
            fields = _drop_none(
                {
                    "TITLE": title,
                    "STAGE_ID": stage_id,
                    "CATEGORY_ID": category_id,
                    "CONTACT_ID": contact_id,
                    "OPPORTUNITY": amount,
                    "CURRENCY_ID": currency_id if amount is not None else None,
                    "ASSIGNED_BY_ID": assigned_by_id,
                }
            )
            return {"id": await call("crm.deal.add", {"fields": fields})}

        @mcp.tool(annotations=_WRITE)
        async def move_deal_stage(deal_id: int, stage_id: str) -> dict[str, Any]:
            """Move a deal to another stage (see list_deal_stages for valid IDs)."""
            ok = await call("crm.deal.update", {"id": deal_id, "fields": {"STAGE_ID": stage_id}})
            return {"updated": bool(ok)}

        @mcp.tool(annotations=_WRITE)
        async def add_deal_comment(deal_id: int, comment: str) -> dict[str, Any]:
            """Add a comment to a deal's timeline."""
            fields = {"ENTITY_ID": deal_id, "ENTITY_TYPE": "deal", "COMMENT": comment}
            return {"id": await call("crm.timeline.comment.add", {"fields": fields})}

        @mcp.tool(annotations=_WRITE)
        async def create_task(
            title: str,
            responsible_id: int,
            description: str | None = None,
            deadline: str | None = None,
        ) -> dict[str, Any]:
            """Create a task. deadline is ISO 8601, e.g. 2026-11-15T18:00:00+05:00."""
            fields = _drop_none(
                {
                    "TITLE": title,
                    "RESPONSIBLE_ID": responsible_id,
                    "DESCRIPTION": description,
                    "DEADLINE": deadline,
                }
            )
            result = await call("tasks.task.add", {"fields": fields})
            task = result.get("task", {}) if isinstance(result, dict) else {}
            return {"id": task.get("id")}

    if allow_raw_calls:

        @mcp.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=True))
        async def call_method(method: str, params: dict[str, Any] | None = None) -> Any:
            """Call any Bitrix24 REST method directly (advanced; can change or delete data)."""
            try:
                return await client.result(method, params or {})
            except (Bitrix24Error, ValueError) as exc:
                raise ToolError(f"Bitrix24 {method} failed: {exc}") from None

    return mcp
