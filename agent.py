"""
Agentic tool use (Module 5): a real agent loop where Claude decides which tools to call,
calls them against Samuel's actual data, observes the results, and iterates until it can
answer — the core draw of agents (autonomous, multi-step tool use), not a single prompted
reply. Every step is captured and returned, so the agent shows its work.

The loop is hand-written rather than a framework for two reasons: the control flow is
explicit and unit-testable (inject a fake client, no network), and it lets us record each
tool call for the transparent trace the site renders. The tools are read-only over the
corpus and the published service list — the agent can look things up, never take an action,
so there is nothing unsafe for it to run.
"""

import json
import re
from pathlib import Path

from retrieve import retrieve   # semantic search over the corpus (the RAG retriever)

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus"

AGENT_MODEL = "claude-haiku-4-5-20251001"   # same fast, inexpensive model as the chat bot
MAX_ITERATIONS = 6                          # hard stop so the loop can never run away
MAX_TOKENS = 2048                           # room for a multi-requirement fit analysis

AGENT_SYSTEM = (
    "You are Samuel Hill's portfolio agent. You answer questions and complete tasks about "
    "Samuel — his background, skills, projects, and freelance services — by USING TOOLS to "
    "look up real information. Do not answer from memory; ground every claim in tool results, "
    "and if the tools do not support a claim, say so plainly.\n"
    "Honesty rule (critical): some skills are labelled 'currently building — in progress, not "
    "yet shipped'. Never present in-progress work as shipped, built, or past experience. Only "
    "call something done when a tool says it is shipped.\n"
    "For a fit question (a pasted job description or a description of work someone needs), break "
    "it into concrete requirements, look up evidence for each with the tools, then report each "
    "requirement as covered / partial / gap with the evidence, and finish with an honest overall "
    "verdict — including what he can't yet do. When cost or hiring comes up, use the services "
    "tool for real starting prices.\n"
    "Be concise and specific. Plain text only — no markdown, no headings, no asterisks."
)


# ---------------------------------------------------------------------------
# Corpus helpers
# ---------------------------------------------------------------------------
def _section(text: str, header_prefix: str) -> str:
    """Return the body of the '## ' section whose header starts with header_prefix."""
    start = text.find(header_prefix)
    if start == -1:
        return ""
    body = text[start:]
    nxt = body.find("\n## ", len(header_prefix))
    return body if nxt == -1 else body[:nxt]


def _bullets(section_text: str) -> list[str]:
    """Bullet lines ('- ...') with markdown bold stripped, as plain strings."""
    out = []
    for line in section_text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            out.append(re.sub(r"\*\*(.+?)\*\*", r"\1", line[2:]).strip())
    return out


def _title_and_summary(text: str) -> tuple[str, str]:
    """First '# ' heading as the title, first prose paragraph as the summary."""
    title, summary = "", ""
    for line in text.splitlines():
        s = line.strip()
        if not title and s.startswith("# "):
            title = s[2:].strip()
        elif title and s and not s.startswith("#"):
            summary = s
            break
    return title, summary


# ---------------------------------------------------------------------------
# Tool implementations — each returns a JSON-serialisable dict
# ---------------------------------------------------------------------------
def _search_portfolio(query: str) -> dict:
    """Semantic search over Samuel's real documents; returns grounded snippets + sources."""
    hits = retrieve(query)
    return {
        "results": [
            {
                "source": h["source_path"],
                "title": h["title"],
                "similarity": round(float(h["similarity"]), 3),
                "text": " ".join(h["content"].split())[:400],
            }
            for h in hits
        ]
    }


def _list_skills(status: str = "all") -> dict:
    """Samuel's skills split into shipped vs currently-building (in progress, not shipped)."""
    text = (CORPUS / "skills.md").read_text(encoding="utf-8")
    out = {}
    if status in ("shipped", "all"):
        out["shipped"] = _bullets(_section(text, "## Shipped"))
    if status in ("building", "all"):
        out["currently_building_not_shipped"] = _bullets(_section(text, "## Currently building"))
    return out


def _list_projects() -> dict:
    """Samuel's projects, each with a one-line summary."""
    projects = []
    for p in sorted((CORPUS / "projects").glob("*.md")):
        title, summary = _title_and_summary(p.read_text(encoding="utf-8"))
        projects.append({"file": f"projects/{p.name}", "title": title, "summary": summary})
    return {"projects": projects}


# The freelance packages, mirrored from the site's Services section — real, published starting
# prices (the final quote is given on inquiry, which the agent should say).
SERVICES = [
    {"name": "Starter Support Bot", "starting_usd": 1500,
     "summary": "A grounded customer-support chatbot on Claude or OpenAI — honest refusal and a clean human handoff."},
    {"name": "Business Bot + Integration", "starting_usd": 3500,
     "summary": "Starter plus real integration into an existing app: auth and one external integration (CRM / email / Stripe)."},
    {"name": "Full-Stack AI Feature / App", "starting_usd": 7500,
     "summary": "A production feature or app end to end — typed FastAPI, React/Next or Expo, payments, i18n, deploy."},
    {"name": "Landing Page / Marketing Site", "starting_usd": 1200,
     "summary": "A fast, framework-free responsive site built for conversion."},
    {"name": "Care & Improve retainer", "starting_usd": 300,
     "summary": "Ongoing care after a build ships: monitoring, prompt tuning, minor updates ($300-$1,200/mo)."},
]


def _list_services() -> dict:
    return {"services": SERVICES, "note": "Starting prices; the final quote is given on inquiry."}


# ---------------------------------------------------------------------------
# Tool registry — schema (sent to Claude) + implementation (run locally)
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "search_portfolio",
        "description": "Semantic search over Samuel's real documents (background, projects, skills). "
                       "Use this to find concrete evidence for any factual claim about his experience.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "What to look up"}},
            "required": ["query"],
        },
        "fn": lambda a: _search_portfolio(a["query"]),
    },
    {
        "name": "list_skills",
        "description": "List Samuel's skills, split into shipped (built and deployed) and currently "
                       "building (in progress, not yet shipped). Never present building work as shipped.",
        "input_schema": {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["shipped", "building", "all"],
                                       "description": "Which set to return (default all)"}},
            "required": [],
        },
        "fn": lambda a: _list_skills(a.get("status", "all")),
    },
    {
        "name": "list_projects",
        "description": "List Samuel's projects, each with a one-line summary.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "fn": lambda a: _list_projects(),
    },
    {
        "name": "list_services",
        "description": "List the freelance packages Samuel offers with real starting prices. Use this "
                       "for any question about hiring him, engagement scope, or cost.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "fn": lambda a: _list_services(),
    },
]

_TOOL_BY_NAME = {t["name"]: t for t in TOOLS}
TOOL_SCHEMAS = [{k: t[k] for k in ("name", "description", "input_schema")} for t in TOOLS]


def _run_tool(name: str, args: dict) -> dict:
    tool = _TOOL_BY_NAME.get(name)
    if not tool:
        return {"error": f"unknown tool: {name}"}
    try:
        return tool["fn"](args or {})
    except Exception:
        # Tool failures are reported to the model as data, not raised — the agent can recover
        # (e.g. try a different query) instead of the whole run crashing.
        return {"error": f"tool '{name}' failed"}


# ---------------------------------------------------------------------------
# The agent loop
# ---------------------------------------------------------------------------
def run_agent(task: str, client, model: str = AGENT_MODEL, max_iterations: int = MAX_ITERATIONS) -> dict:
    """Run the tool-use loop until Claude gives a final answer or the iteration cap is hit.

    `client` is an Anthropic() instance, injected so the loop is testable with a fake that
    returns canned responses. Returns the answer plus the full ordered list of steps
    (thoughts and tool calls) so the caller can show the agent's work.
    """
    messages = [{"role": "user", "content": task}]
    steps: list[dict] = []
    input_tokens = output_tokens = 0
    iterations = 0

    while iterations < max_iterations:
        iterations += 1
        resp = client.messages.create(
            model=model, max_tokens=MAX_TOKENS, system=AGENT_SYSTEM,
            tools=TOOL_SCHEMAS, messages=messages,
        )
        input_tokens += resp.usage.input_tokens
        output_tokens += resp.usage.output_tokens
        messages.append({"role": "assistant", "content": resp.content})

        # Record any reasoning text the model emitted alongside its tool calls.
        for block in resp.content:
            if getattr(block, "type", None) == "text" and block.text.strip():
                steps.append({"type": "thought", "text": block.text.strip()})

        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if resp.stop_reason != "tool_use" or not tool_uses:
            answer = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
            return {"answer": answer, "steps": steps, "iterations": iterations,
                    "input_tokens": input_tokens, "output_tokens": output_tokens, "stopped": "complete"}

        # Execute every requested tool and feed the results back for the next turn.
        tool_results = []
        for tu in tool_uses:
            output = _run_tool(tu.name, tu.input)
            steps.append({"type": "tool_call", "tool": tu.name, "input": tu.input or {}, "output": output})
            tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(output)})
        messages.append({"role": "user", "content": tool_results})

    return {"answer": "I couldn't finish this within the step limit — try narrowing the task.",
            "steps": steps, "iterations": iterations,
            "input_tokens": input_tokens, "output_tokens": output_tokens, "stopped": "max_iterations"}
