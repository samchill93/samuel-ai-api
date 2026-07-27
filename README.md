# Ask Me About Samuel — AI Portfolio Assistant (API)

A Python backend that powers an AI assistant you can **interview about my experience**.
Ask it about my skills, my projects, or whether I'm a fit for a role, and it answers
**only from my real documents** — retrieving the relevant passages, citing its sources,
and refusing honestly when the documents don't cover the question. Built with FastAPI.

This is the Living Portfolio backend — a portfolio that demonstrates my skills by being
built with them.

> **Status.** Live in production on Render (always-on, continuous deployment from `main`),
> with interactive docs at [`/docs`](https://samuel-ai-api.onrender.com/docs). The RAG
> pipeline described below is deployed and verified: `/chat` returns grounded, cited
> answers, and `/inquiry` validates then stores to Neon.

---

## What it does

- **Answers only from a real corpus (RAG)** — the visitor's question is embedded, the most
  similar chunks of my documents are retrieved from a vector store, and the model answers
  grounded in exactly those chunks.
- **Cites its sources** — every answer carries `[n]` markers that map to the documents used,
  returned as a `citations` array (source path, title, and a snippet of the cited text).
- **Refuses honestly** — when the best match is too weak (below a cosine-similarity
  threshold), it says the answer isn't in the documents instead of guessing. No LLM call is
  made, so a refusal costs nothing.
- **Honest by design** — the corpus is the single claims surface; shipped work and
  in-progress work are kept explicitly separate, and tests fail if an overclaim is introduced.
- **Typed, validated API** — every request and response is checked against a Pydantic schema.
- **Cost-metered** — each answer reports real input/output token counts and the computed cost.
- **Observable** — every request gets an id (`X-Request-ID`), is timed and logged as one
  structured JSON line, and `/chat` returns a per-request trace (retrieval vs model time,
  sources, similarity); `GET /metrics` reports request counts, latency p50/p95, and the
  running token/cost tally, honestly scoped to the current process.
- **Agentic** — `POST /agent` runs a tool-using loop: Claude decides which read-only tools to
  call over Samuel's real data (search the corpus, list skills / projects / services), iterates,
  and returns the answer plus every step it took, so the run is transparent.

## Architecture

The frontend never touches any API key. The browser sends the conversation to this backend,
which retrieves grounding chunks, calls Claude with them, and returns a cited answer.

```
Portfolio site (frontend)
        │ POST /chat { messages }
        ▼
   FastAPI /chat
        │  embed the question ──► OpenAI text-embedding-3-small (1536-dim)
        │  top-k cosine search ─► Neon Postgres + pgvector (HNSW index)
        │
        ├─ weak match?  ─► honest refusal (no model call, $0)
        │
        └─ ground Claude on the retrieved, numbered sources ──► Claude API
                 │  holds the API keys; the browser never sees them
                 ▼
           reply + usage(tokens, cost) + citations[]
```

## Key files

- **`main.py`** — the FastAPI app: `/health`, `/version`, `/metrics`, `/inquiry`, the RAG `/chat`, and the `/agent` loop.
- **`obs.py`** — observability (Module 3): a JSON log formatter, a request-id generator, and a
  thread-safe, bounded in-memory metrics registry read by `/metrics`.
- **`agent.py`** — the tool-using agent (Module 5): four read-only tools over Samuel's data and a
  hand-written loop that lets Claude call them, iterate, and return every step.
- **`mcp_server.py`** — an MCP server (Module 5) exposing those same four tools over the Model
  Context Protocol (stdio), so any MCP client like Claude Desktop can use them.
- **`retrieve.py`** — `search(vector, k)` (pure database cosine search, testable on its own) and
  `retrieve(query, k)` (embeds the question, then searches).
- **`rag.py`** — assembles the grounded system prompt and, after the model answers, renumbers
  the `[n]` markers to a clean `1..N` matched to a deduped source list with snippets.
- **`about_me.py`** — the assistant's persona/voice only. The facts live in the corpus.
- **`ingest.py`** — chunk → embed → upsert the `/corpus` markdown into the vector store.
- **`schema.sql` / `apply_schema.py`** — `documents`, `chunks` (with the HNSW vector index),
  and `inquiries`; idempotent to apply.
- **`corpus/`** — the markdown documents the bot answers from (its claims surface).
- **`test_main.py` / `test_retrieve.py` / `test_rag.py` / `test_obs.py` / `test_agent.py` / `test_mcp.py`** —
  pytest suite (55 tests): chunking, the grounding/refusal decision, citation renumbering/dedup/snippets,
  honesty guards, the observability registry + middleware, the agent tools + loop (fake client, no
  network), and the MCP server (tools listed and called over a real in-memory client↔server session).

## Built with

Python · FastAPI · Pydantic · Anthropic Claude API · OpenAI Embeddings · PostgreSQL +
pgvector (Neon) · Uvicorn · pytest

## Run it locally

```bash
git clone https://github.com/samchill93/samuel-ai-api.git
cd samuel-ai-api

py -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` with three values (all git-ignored, never committed):

```
ANTHROPIC_API_KEY=sk-ant-...      # console.anthropic.com  — the chat model
OPENAI_API_KEY=sk-...             # platform.openai.com    — query + corpus embeddings
DATABASE_URL=postgresql://...     # a Neon (or any pgvector) Postgres connection string
```

Then set up the vector store and start the server:

```bash
python apply_schema.py     # create the tables + pgvector index (idempotent)
python ingest.py           # chunk, embed, and load the /corpus documents
uvicorn main:app --reload
```

Open **http://localhost:8000/docs** for interactive API docs, or
**http://localhost:8000/health** for a quick check. To exercise the chat from the portfolio
site running locally, add your local origin to `CORS_ORIGINS` in `.env` — production stays
locked because that variable isn't set on Render.

Editing the corpus is the normal way to change what the bot knows: change a file in
`corpus/`, re-run `python ingest.py`, and the new content is retrievable immediately.

## Use it as an MCP server

The same portfolio tools are exposed over the Model Context Protocol, so an MCP client can search
Samuel's documents and list his skills, projects, and services. To use it in Claude Desktop, add
to `claude_desktop_config.json` and restart:

```json
{
  "mcpServers": {
    "samuel-portfolio": {
      "command": "python",
      "args": ["/absolute/path/to/samuel-ai-api/mcp_server.py"]
    }
  }
}
```

It runs over stdio and reuses the same tool implementations as the `/agent` endpoint. Tools:
`search_portfolio`, `list_skills`, `list_projects`, `list_services`. (`search_portfolio` needs
`DATABASE_URL` and `OPENAI_API_KEY` in the environment; the list tools work from the corpus files
alone.)

## Roadmap (the Living Portfolio)

- **Evals** ✓ shipped — a 108-case golden dataset and an LLM-as-judge (recall@5 0.992,
  citations 92/92); the eval loop caught a real honesty bug in the live bot, fixed and
  deployed. Judge-vs-human calibration is the one pending step.
- **Observability** ✓ shipped — per-request ids, structured JSON logs, `/chat` tracing, and a
  `/metrics` endpoint (latency p50/p95, request counts, running token/cost). Next: split
  retrieval into embed-vs-db time, and pool the database connection.
- **Agents** ✓ shipped — `POST /agent` runs a tool-use loop over Samuel's data (search, skills,
  projects, services) and returns every step; try it live on the site.
- **MCP server** ✓ shipped — the same tools over the Model Context Protocol (stdio), verified with
  a real MCP client; add it to Claude Desktop (see below). Next: streaming, Docker, Terraform.
