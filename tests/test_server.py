from __future__ import annotations

import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from bitrix24_mcp.server import build_server

pytestmark = pytest.mark.anyio

READ_TOOLS = {
    "whoami",
    "list_deal_stages",
    "list_deals",
    "get_deal",
    "search_contacts",
    "get_contact",
    "list_leads",
    "list_tasks",
}
WRITE_TOOLS = {"create_lead", "create_deal", "move_deal_stage", "add_deal_comment", "create_task"}


async def tool_names(server) -> set[str]:
    return {t.name for t in await server.list_tools()}


def payload(result):
    """Extract the tool's return value from a CallToolResult."""
    if getattr(result, "structured_content", None) is not None:
        data = result.structured_content
        return data.get("result", data) if isinstance(data, dict) and len(data) == 1 else data
    text = result.content[0].text
    return json.loads(text)


async def test_read_only_by_default_exposes_no_write_tools(client):
    names = await tool_names(build_server(client))
    assert names == READ_TOOLS


async def test_write_tools_when_enabled(client):
    names = await tool_names(build_server(client, read_only=False))
    assert names == READ_TOOLS | WRITE_TOOLS


async def test_raw_calls_only_when_enabled(client):
    assert "call_method" not in await tool_names(build_server(client, read_only=False))
    assert "call_method" in await tool_names(build_server(client, allow_raw_calls=True))


async def test_read_tools_are_annotated_read_only(client):
    for tool in await build_server(client).list_tools():
        assert tool.annotations is not None and tool.annotations.read_only_hint is True


async def test_search_contacts_by_phone_normalizes_number(fake, client):
    fake.route(
        "crm.contact.list",
        {"result": [{"ID": "5", "NAME": "Aigerim", "PHONE": [{"VALUE": "+77011234567"}]}]},
    )
    server = build_server(client)
    result = await server.call_tool("search_contacts", {"query": "+7 (701) 123-45-67"})
    method, params = fake.calls[0]
    assert method == "crm.contact.list"
    assert params["filter"] == {"PHONE": "+77011234567"}
    contacts = payload(result)
    assert contacts[0]["PHONE"] == ["+77011234567"]


async def test_search_contacts_by_email(fake, client):
    fake.route("crm.contact.list", {"result": []})
    await build_server(client).call_tool("search_contacts", {"query": "a@b.kz"})
    assert fake.calls[0][1]["filter"] == {"EMAIL": "a@b.kz"}


async def test_search_contacts_by_name_merges_and_dedupes(fake, client):
    fake.route(
        "crm.contact.list",
        lambda p: {"result": [{"ID": "1", "NAME": "Asel"}, {"ID": "2", "LAST_NAME": "Aselova"}]},
    )
    result = await build_server(client).call_tool("search_contacts", {"query": "Асель"})
    filters = [p["filter"] for _, p in fake.calls]
    assert filters == [{"%NAME": "Асель"}, {"%LAST_NAME": "Асель"}]
    assert [c["ID"] for c in payload(result)] == ["1", "2"]


async def test_list_deals_builds_filter(fake, client):
    fake.route("crm.deal.list", {"result": [{"ID": "10", "TITLE": "Kaspi"}]})
    await build_server(client).call_tool(
        "list_deals", {"stage_id": "C1:NEW", "title_contains": "Kaspi", "limit": 5}
    )
    params = fake.calls[0][1]
    assert params["filter"] == {"STAGE_ID": "C1:NEW", "%TITLE": "Kaspi"}
    assert params["order"] == {"ID": "DESC"}


async def test_list_deal_stages_uses_category_entity(fake, client):
    fake.route("crm.status.list", {"result": [{"STATUS_ID": "C3:NEW", "NAME": "New", "SORT": 10}]})
    server = build_server(client)
    await server.call_tool("list_deal_stages", {})
    await server.call_tool("list_deal_stages", {"category_id": 3})
    entities = [p["filter"]["ENTITY_ID"] for _, p in fake.calls]
    assert entities == ["DEAL_STAGE", "DEAL_STAGE_3"]


async def test_list_tasks_unwraps_tasks_key(fake, client):
    fake.route("tasks.task.list", {"result": {"tasks": [{"id": "42", "title": "Call"}]}})
    result = await build_server(client).call_tool("list_tasks", {"status": 3})
    assert fake.calls[0][1]["filter"] == {"REAL_STATUS": 3}
    assert payload(result)[0]["id"] == "42"


async def test_create_lead_sends_multifields(fake, client):
    fake.route("crm.lead.add", {"result": 77})
    server = build_server(client, read_only=False)
    result = await server.call_tool(
        "create_lead", {"title": "Site form", "phone": "+77010000000", "email": "x@y.kz"}
    )
    fields = fake.calls[0][1]["fields"]
    assert fields["PHONE"] == [{"VALUE": "+77010000000", "VALUE_TYPE": "WORK"}]
    assert fields["EMAIL"] == [{"VALUE": "x@y.kz", "VALUE_TYPE": "WORK"}]
    assert "NAME" not in fields
    assert payload(result) == {"id": 77}


async def test_create_task_returns_id(fake, client):
    fake.route("tasks.task.add", {"result": {"task": {"id": "501"}}})
    server = build_server(client, read_only=False)
    result = await server.call_tool("create_task", {"title": "Call back", "responsible_id": 1})
    assert payload(result) == {"id": "501"}


async def test_bitrix_errors_become_tool_errors(fake, client):
    fake.route("crm.deal.get", (400, {"error": "NOT_FOUND", "error_description": "Not found"}))
    with pytest.raises(ToolError, match="NOT_FOUND"):
        await build_server(client).call_tool("get_deal", {"deal_id": 1})


async def test_empty_query_is_rejected(client):
    with pytest.raises(ToolError):
        await build_server(client).call_tool("search_contacts", {"query": "  "})
