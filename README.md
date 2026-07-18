# Ask Me About Samuel — AI Portfolio Assistant (API)

A Python backend that powers an AI assistant you can **interview about my experience**. Ask it about my skills, my projects, or whether I'm a fit for a role, and it answers from a curated knowledge base using the Claude API. Built with FastAPI and designed to plug straight into my portfolio website.

This is Phase 1 of my "Living Portfolio" — a portfolio that demonstrates my skills by being built with them.

**Live:** the API runs on Render (always-on) with continuous deployment from `main`. Interactive docs at [`/docs`](https://samuel-ai-api.onrender.com/docs).

---

## What it does

- **Answers questions about me** — grounded in a real knowledge base, not made up. Ask "What's Samuel's experience with AI?" or "Is he a fit for a React role?" and get an accurate, on-brand answer.
- **Honest by design** — the knowledge base separates shipped skills from work that's still in progress, and the assistant never presents in-progress work as finished.
- **Won't invent details** — if something isn't in its knowledge, it says so and points you to reach out directly, instead of hallucinating.
- **Typed, validated API** — every request and response is checked against a schema, so bad input gets a clear error automatically.
- **Ready for the web** — CORS-enabled and structured so a frontend (my portfolio site) can call it directly.

## Architecture

The frontend never touches the API key. The browser sends the conversation to this backend, which holds the key and calls Claude with a system prompt that defines who the assistant answers about.

```
Portfolio site (frontend)  ──fetch──►  FastAPI  /chat  ──►  Claude API
                                          │
                              holds the API key + system prompt
```

- **`main.py`** — the FastAPI app: a `/health` check and a `/chat` endpoint, with typed Pydantic request/response models. Allowed CORS origins are configurable via the `CORS_ORIGINS` env var (defaults to the production site).
- **`about_me.py`** — the assistant's knowledge, kept separate from the logic (so the content can change without touching the code). Roadmap: replace this with RAG over a document set.
- **`test_main.py`** — automated tests (pytest): the `/health` endpoint plus honesty guards that fail if the knowledge base ever re-introduces an overclaim.

## Built with

Python · FastAPI · Pydantic · Anthropic Claude API · Uvicorn · pytest

## Run it locally

```bash
git clone https://github.com/samchill93/samuel-ai-api.git
cd samuel-ai-api

# create and activate a virtual environment (Windows)
py -m venv venv
.\venv\Scripts\activate

pip install -r requirements.txt

# add your key: copy .env.example to .env and paste your key
# get one at https://console.anthropic.com

uvicorn main:app --reload
```

Then open **http://localhost:8000/docs** for interactive API docs, or **http://localhost:8000/health** for a quick check. The `.env` file is git-ignored, so the API key stays private.

To exercise the chat from the portfolio site running on your machine, set `CORS_ORIGINS` in `.env` to include your local origin (see `.env.example`) — production stays locked because that variable isn't set on Render.

## Roadmap (the Living Portfolio)

- **RAG** — retrieve answers from a real document set with source citations, instead of a static system prompt.
- **Agentic mode** — let the assistant take actions via tool use, and expose it as an MCP server.
- **Evals + observability** — measure answer accuracy and trace token cost and latency.
