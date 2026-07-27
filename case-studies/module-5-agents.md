# Case Study — A Tool-Using Agent That Shows Its Work

*Living Portfolio, Module 5. Status: live in production — `POST /agent` runs a real tool-use
loop over Samuel's data, and the site's Agent section lets anyone give it a task and watch
every step. Verified end to end.*

## Problem

The RAG assistant answers one question at a time from a single retrieval. That is the wrong
shape for a whole class of real questions — "here's a job description, is Samuel a fit, and
where are the gaps?" or "I need X built, can he do it and what would it cost?" Those require
*several* lookups (skills, evidence per requirement, projects, pricing) and reasoning across
the results. A single grounded call can't do it.

That gap is exactly the thing agents exist for, and it's the module's whole point: the draw
of an agent isn't a chat personality, it's **autonomous, multi-step tool use** — the model
deciding which tools to call, in what order, looping on the results until it can actually
answer. The goal was to build that for real (not a scripted pipeline dressed up as an agent),
ground every tool in Samuel's actual data, and make the agent **show its work** so the
autonomy is visible rather than a black box.

## Constraints

- **Bounded cost** — a loop makes several model calls, so it needs a hard iteration cap and a
  cheap model; every run reports its real summed cost.
- **Read-only tools** — the agent can look things up, never take an action. There is nothing
  destructive for it to run, so exposing it publicly carries only the same cost posture as the
  already-public chat.
- **Honesty carries into tools** — the tools distinguish shipped from in-progress work, and
  the system prompt forbids presenting building work as done. An agent that confidently
  overclaims would be worse than no agent.
- **Testable without the network** — the loop takes an injected client, so its control flow is
  driven by a fake in unit tests; no key, no cost, no flakiness in CI.
- **Transparent** — every step (reasoning and tool call) is captured and returned, so the run
  can be rendered, not just its final answer.

## Architecture

```
POST /agent { task }
   │
   ▼
run_agent(task, client)                         ── hand-written loop, capped at 6 iterations
   │
   ├─►  Claude (Haiku 4.5) + tool schemas + conversation so far
   │        │
   │        ├─ stop_reason "tool_use"  → run each requested tool locally, append results, loop
   │        └─ stop_reason "end_turn"  → final answer, exit
   │
   │   Tools (read-only, over real data):
   │     search_portfolio(query) → pgvector semantic search of the corpus (the RAG retriever)
   │     list_skills(status)     → shipped vs currently-building, from skills.md
   │     list_projects()         → titles + summaries from corpus/projects
   │     list_services()         → the published freelance packages + starting prices
   ▼
{ answer, steps:[ thought | tool_call{tool,input,output} ], iterations, tool_calls,
  usage(tokens,cost), request_id, elapsed_ms, stopped }
```

Two decisions carry the design. **The loop is hand-written, not a framework.** The control
flow — call the model, execute the tools it asked for, feed the results back, repeat until it
stops — is explicit, which makes it both unit-testable with a fake client and easy to
instrument for the step trace. And **every step is returned, not just the answer.** The trace
of thoughts and tool calls is what turns the agent from a black box into a glass one — the
same transparency theme as the observability module, applied to the agent's own decisions.

## Trade-offs (options considered, why the choice won)

- **Hand-written loop** over the SDK's tool runner. The runner would have hidden the loop; the
  point of the module is to show the loop is understood and to own the step-capture. The trade
  is a few more lines, which is the right trade for a portfolio.
- **Read-only tools** over action tools (send email, write to a DB). Actions would be a bigger
  "wow" but carry real risk on a public endpoint. Lookup tools make the agent genuinely useful
  (fit analysis, quoting) with nothing unsafe to run — the honest scope for a public demo.
- **Haiku 4.5** over a larger model. The agent's job is orchestration and grounded synthesis,
  which Haiku does well and cheaply — a full fit analysis with four tool calls costs well under
  a cent. A stronger model is a one-line change if a task ever needs it.
- **Bounded at 6 iterations** over an open loop. A hard cap means a confused run degrades to
  "I couldn't finish" instead of burning tokens forever; the response says which way it stopped.
- **Tool failures returned as data** over raised. A failed tool is handed back to the model as
  `{"error": ...}` so it can recover (try a different query) instead of crashing the whole run.

## Metrics (honestly labeled — live production)

A live fit-analysis run — *"build an LLM eval harness and add observability to a FastAPI
service; is Samuel a fit, call out gaps?"*:

- **2 model turns, 4 tool calls** — `list_skills` → `search_portfolio` (twice, different
  queries) → `list_projects`, chosen by the model, not scripted.
- **Cost $0.0062**, a few seconds end to end, summed across the whole loop from real token counts.
- **Grounded output** — a per-requirement verdict (covered / partial / gap) citing the actual
  shipped evals and observability work, not generic claims.
- **9 unit tests** drive the four tools and the loop (tool execution, feeding results back, the
  iteration cap) with a fake client — no key or network. 51 tests total, all passing.

## What broke, and what the agent found

1. **The agent surfaced a real honesty drift in the corpus.** Building the tools meant reading
   `skills.md`, which still listed LLM evaluations and observability under "currently building —
   not yet shipped" — even though both had shipped in Modules 2 and 3, and the site's own
   roadmap already said "Shipped." The bot would have told a visitor those weren't done while
   the site said they were. Fixed: moved evals, observability, and agent tool use to the shipped
   section, and corrected `profile.md`'s title condition (the "Agentic AI Engineer" title now
   waits only on the MCP server, since the agent shipped). Re-ingested so retrieval matches, and
   updated the honesty-guard tests to the new truth. The module cleaned up after the two before it.
2. **Markdown leaking into a plain-text contract.** The agent, like the chat model, sometimes
   emits `**bold**` despite a plain-text instruction. The same deterministic `to_plain_text`
   backstop the chat path uses strips it before the answer is returned.
3. **Public exposure of a paid endpoint.** The agent costs more per call than chat (multiple
   model turns), and the endpoint is public. It's the same class of exposure as the already-
   public chat, so it ships now — but rate-limiting is the honest follow-up, and it's slotted
   as Module 6 hardening rather than pretended away.

## What's next

- **The MCP server (Module 5's second half):** expose these same four tools as a Model Context
  Protocol server, so any MCP client (Claude Desktop, etc.) can use them — the tools are already
  factored to make that a thin wrapper. This is why the roadmap now lists Agents (shipped) and
  MCP server (planned) separately rather than bundled.
- **Rate-limiting** the public agent and chat endpoints — the responsible hardening before these
  paid loops stay open to the internet, slotted into the Module 6 work.
- **Streaming the steps** — render each tool call as it happens rather than after the run, once
  streaming (a later module) lands; the backend already produces the steps in order.
