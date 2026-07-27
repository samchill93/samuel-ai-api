# Case Study — Publishing the Portfolio Tools as an MCP Server

*Living Portfolio, Module 5 (second half). Status: shipped — an open-source Model Context
Protocol server exposing the portfolio tools over stdio, verified end to end with a real MCP
client. Completes the "Agentic AI Engineer" milestone alongside the live agent.*

## Problem

The agent's four tools — search the corpus, list skills, list projects, list services — were
useful, but locked inside one HTTP endpoint. Any *other* AI client a person already uses
(Claude Desktop, an IDE assistant, another agent) couldn't reach them. The open answer to
that is the Model Context Protocol: a standard way to expose tools so any MCP-speaking client
can discover and call them. The goal was to publish the same tools over MCP — without
duplicating their logic, and verified against a real client rather than assumed to work.

## Constraints

- **One source of truth for the tools** — the MCP server must reuse the exact implementations
  the agent uses, not a parallel copy that can drift.
- **Verified, not "should work"** — the site's rule is that everything is real and checked, so
  the server had to be exercised over the actual protocol (initialize, list, call), not just
  imported.
- **Read-only, same as the agent** — the tools look things up; nothing takes an action, so the
  server is safe to hand to any client.
- **Don't destabilise the live API** — the running FastAPI service serves the public chat and
  agent; the MCP server ships as its own stdio process rather than being mounted into that app,
  so it can't affect the API's stability.

## Architecture

```
MCP client (Claude Desktop, an IDE, another agent)
   │  stdio (JSON-RPC): initialize → tools/list → tools/call
   ▼
mcp_server.py  (FastMCP "samuel-portfolio")
   │  @mcp.tool() search_portfolio / list_skills / list_projects / list_services
   ▼
agent.py tool implementations  ── the SAME functions the /agent endpoint calls
   │
   ├─ search_portfolio → OpenAI embedding → pgvector search (Neon)
   └─ list_* → the corpus files and the published service list
```

The one decision that carries it: **the MCP tools are thin wrappers over `agent.py`'s
implementations.** The agent and the MCP server are two surfaces onto one set of tools, so a
change to a tool is a change everywhere at once — no drift between "what the agent does" and
"what the MCP server exposes."

## Trade-offs (options considered, why the choice won)

- **stdio transport** over a hosted HTTP endpoint. stdio is what desktop MCP clients launch,
  and it ships without adding a fragile mount to the production API or a second service to
  operate. A hosted URL is a nice future addition; it wasn't worth risking the live API's
  stability for this step. The trade is that a user runs the server locally rather than hitting
  a URL — the normal shape for MCP servers today.
- **FastMCP** over the low-level `Server`. The decorator API generates each tool's JSON schema
  from the function signature and docstring, so the schema can't fall out of sync with the code.
- **Reuse the agent's tools** over reimplementing for MCP. One implementation, two surfaces —
  the whole point.

## Verification (honestly labeled — real protocol, local)

Exercised two ways, both over the actual MCP protocol:

- **In-memory client↔server session** (in the test suite): initialize, `tools/list` returns the
  four tools with their schemas, and `tools/call` runs `list_services` and `list_skills` and gets
  the real data back. 4 tests, part of the 55-test suite.
- **A real stdio subprocess** (the exact thing Claude Desktop launches): a client spawned
  `python mcp_server.py`, initialized (server `samuel-portfolio`, protocol `2025-11-25`), listed
  the four tools, and called `search_portfolio` — which ran the full embedding + pgvector search
  through the protocol and returned five sourced results. End to end, not stubbed.

## What this completes

Shipping the MCP server met the condition the corpus had set for Samuel's title: the
"Full-Stack Agentic AI Engineer" title is earned once *both* agentic tool use and an MCP server
ship. Both now have — the live agent and this server — so `profile.md` and the site title update
to reflect shipped work, not aspiration. The honesty discipline carries through the tools
themselves: `list_skills` still separates shipped from in-progress, so an MCP client gets the
same truthful split the website does.

## What's next

- **A hosted HTTP transport** — expose the server at a URL (FastMCP's streamable-HTTP app) so a
  client can add it without running anything locally, once it can be done without risking the
  live API.
- **Rate-limiting** — the same hardening owed to the public agent and chat endpoints applies if
  the MCP server is ever hosted openly.
- **More tools** — the case-study and build-log corpus could become their own retrieval tool, so
  a client can ask the server directly about how each module was built.
