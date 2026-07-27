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

- **`main.py`** — the FastAPI app: `/health`, `/version`, `/inquiry`, and the RAG `/chat`.
- **`retrieve.py`** — `search(vector, k)` (pure database cosine search, testable on its own) and
  `retrieve(query, k)` (embeds the question, then searches).
- **`rag.py`** — assembles the grounded system prompt and, after the model answers, renumbers
  the `[n]` markers to a clean `1..N` matched to a deduped source list with snippets.
- **`about_me.py`** — the assistant's persona/voice only. The facts live in the corpus.
- **`ingest.py`** — chunk → embed → upsert the `/corpus` markdown into the vector store.
- **`schema.sql` / `apply_schema.py`** — `documents`, `chunks` (with the HNSW vector index),
  and `inquiries`; idempotent to apply.
- **`corpus/`** — the markdown documents the bot answers from (its claims surface).
- **`test_main.py` / `test_retrieve.py` / `test_rag.py`** — pytest suite (26 tests): chunking,
  the grounding/refusal decision, citation renumbering/dedup/snippets, and honesty guards.

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

## Roadmap (the Living Portfolio)

- **Evals** — a golden dataset and an LLM-as-judge calibrated to hand labels; calibrate the
  refusal threshold and publish groundedness, citation-correctness, and recall@k numbers.
- **Observability** — per-request token cost, latency, and retrieval tracing.
- **Agentic mode** — tool use, and an MCP server exposing the portfolio tools.
