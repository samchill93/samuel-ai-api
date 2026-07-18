# The Living Portfolio

A portfolio that demonstrates Samuel's skills by being built with them — an AI you can
interview about his experience, extended in public one engineering capability at a time.

## What's shipped
- A typed Python (FastAPI) backend on the Claude API, deployed on Render (always-on).
- An "Ask my AI" chat widget embedded in the portfolio site (hosted on Vercel), wired to the backend.
- Grounded, honest answers from a curated knowledge base. The backend holds the API key and the
  system prompt, so the browser never touches secrets.

## In progress — not yet shipped
- **RAG with visible source citations** over Samuel's real documents (being built now).
- Public evals, observability/tracing, an agentic mode with a published MCP server, and a
  Terraform-defined cloud deploy.

## Why it matters
It is purpose-built around what applied-AI roles actually screen for — RAG, evals, observability,
agents/MCP — and proves those skills by being built with them, in public, phase by phase, rather
than just listing them.

**Stack:** FastAPI, Pydantic, Claude API, PostgreSQL + pgvector (RAG, in progress), vanilla
HTML/CSS/JS frontend, Render, Vercel.
**Repo:** github.com/samchill93/samuel-ai-api
