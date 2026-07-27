"""
MCP server (Module 5): exposes Samuel's portfolio tools over the Model Context Protocol, so
any MCP client — Claude Desktop, an IDE, another agent — can search his documents and list his
skills, projects, and services. These are the same read-only tools the /agent endpoint uses:
the agent proved them internally; the MCP server publishes them to any client.

Run it over stdio (what an MCP client launches):

    python mcp_server.py

Configure Claude Desktop (claude_desktop_config.json):

    { "mcpServers": {
        "samuel-portfolio": { "command": "python", "args": ["/absolute/path/to/mcp_server.py"] }
    } }

It runs over stdio, the transport MCP clients launch locally — the same tools the /agent
endpoint uses, now available to any client, from one shared implementation in agent.py.
"""

from mcp.server.fastmcp import FastMCP

# Reuse the exact tool implementations the agent uses — one source of truth for both surfaces.
from agent import _search_portfolio, _list_skills, _list_projects, _list_services

mcp = FastMCP("samuel-portfolio")


@mcp.tool()
def search_portfolio(query: str) -> dict:
    """Semantic search over Samuel Hill's real documents (background, projects, skills).
    Returns the most relevant snippets with their source, to ground any claim about him."""
    return _search_portfolio(query)


@mcp.tool()
def list_skills(status: str = "all") -> dict:
    """List Samuel's skills, split into shipped (built and deployed) and currently building
    (in progress, not yet shipped). Never present building work as shipped.
    status: 'shipped', 'building', or 'all' (default)."""
    return _list_skills(status)


@mcp.tool()
def list_projects() -> dict:
    """List Samuel's projects, each with a one-line summary."""
    return _list_projects()


@mcp.tool()
def list_services() -> dict:
    """List the freelance packages Samuel offers, with real starting prices, for questions
    about hiring him or scoping a build."""
    return _list_services()


if __name__ == "__main__":
    mcp.run()   # stdio transport — what an MCP client launches
