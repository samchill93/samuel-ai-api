"""
Tests for the MCP server (Module 5): the four tools are registered with correct schemas, and
a real MCP client<->server session (in-memory, over the actual protocol — no subprocess) can
list and call them. Tools that hit the database aren't exercised here; the pure ones prove the
end-to-end wiring.
"""

import asyncio
import json

from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_server import mcp


def _run(coro):
    return asyncio.run(coro)


# --- Registration ------------------------------------------------------------
def test_server_registers_the_four_tools():
    tools = _run(mcp.list_tools())
    assert {t.name for t in tools} == {
        "search_portfolio", "list_skills", "list_projects", "list_services"}
    for t in tools:
        assert t.description and t.inputSchema["type"] == "object"


def test_search_portfolio_declares_a_required_query():
    tools = {t.name: t for t in _run(mcp.list_tools())}
    assert "query" in tools["search_portfolio"].inputSchema.get("required", [])


# --- Real protocol round-trip (in-memory client + server) --------------------
def test_client_lists_and_calls_a_tool_over_the_protocol():
    async def go():
        async with connect(mcp) as client:
            listed = await client.list_tools()
            assert {t.name for t in listed.tools} == {
                "search_portfolio", "list_skills", "list_projects", "list_services"}
            # Call a tool that needs no database, through the real MCP round-trip.
            result = await client.call_tool("list_services", {})
            data = json.loads(result.content[0].text)
            assert len(data["services"]) == 5
            assert any(s["name"] == "Starter Support Bot" for s in data["services"])
    _run(go())


def test_client_calls_list_skills_with_an_argument():
    async def go():
        async with connect(mcp) as client:
            result = await client.call_tool("list_skills", {"status": "shipped"})
            data = json.loads(result.content[0].text)
            assert data["shipped"], "shipped skills should come back through the protocol"
    _run(go())
