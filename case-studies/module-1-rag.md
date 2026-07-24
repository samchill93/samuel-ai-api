# Case Study — RAG with Visible, Touchable Citations

*Living Portfolio, Module 1. Status: built and verified locally; production deploy
pending two Render environment variables (see "What's next").*

## Problem

The portfolio assistant answered from a single hand-written system prompt. Every fact
about Samuel lived in a Python string, which meant three things: the claims were
unverifiable (no sources), the bot could drift into saying whatever sounded plausible,
and the "knowledge" was a maintenance burden tangled into code. For a portfolio whose
entire thesis is *everything here is true and defensible*, an unsourced bot was the
weakest link — the exact "AI slop" a senior reviewer discounts.

The goal: the assistant answers **only** from Samuel's real documents, shows **where each
claim came from**, and **refuses honestly** when the documents don't cover a question.

## Constraints

- **8GB Windows laptop** — no local models or local embedding training; hosted services only.
- **Cost control** — Claude Haiku 4.5 for runtime; every LLM-looping process is costed first.
- **Free / low-cost tiers** — Neon Postgres free tier; a second embedding provider on minimal credit.
- **Secrets in environment only** — never in code or commits.
- **The corpus is a claims surface** — anything the bot can say must be true and defensible, so
  the documents were audited before ingestion (an "OpenAI API — shipped" overclaim was caught
  and moved to "in progress" during that audit).

## Architecture

```
Browser chat widget
   │  POST /chat { messages: [...] }
   ▼
FastAPI  /chat
   │  question = latest user turn
   ▼
retrieve(question)
   ├─ embed query  → OpenAI text-embedding-3-small (1536-dim)
   └─ top-5 cosine search → pgvector HNSW index on Neon → chunks + their source docs
   │
   ├─ is_grounded?  (top cosine similarity ≥ 0.35)
   │     no  → deterministic REFUSAL      (no LLM call — 0 tokens, $0)
   │     yes ↓
   ▼
build_system_prompt(persona shell + numbered sources + grounding rules)
   ▼
Claude Haiku 4.5  →  answer containing [n] markers
   ▼
finalize_citations  →  renumber [n] to 1..N, dedupe sources, attach a snippet each
   ▼
ChatResponse { reply, usage(tokens, cost), citations[] }
   ▼
Widget renders the reply; each [n] is a hover/tap popover previewing its source,
and a deduped source list sits under the answer.
```

Two design choices carry most of the weight. **Retrieval is split from embedding**
(`search(vector)` vs `retrieve(query)`) so the SQL and the pgvector operator could be
tested against the real database before an embedding key existed. And **`about_me.py`
shrank from facts to a persona shell** so the corpus is the single claims surface — the
bot cannot answer from a second, uncited source.

## Trade-offs (options considered, why the choice won)

- **Postgres host — Neon** over Supabase / Render Postgres. Free serverless tier, a clean
  dashboard, and it lives separately from the app host, which the topology diagram makes a
  virtue of. At 12 chunks, cold starts are irrelevant.
- **Embedding provider — OpenAI `text-embedding-3-small`** over Voyage. Its 1536 dims match
  the schema as written, and it's the default a reviewer expects. Voyage is free and
  Anthropic-recommended but 1024-dim (a schema change). Cost was not the deciding factor —
  embedding the whole corpus costs **$0.00004**.
- **Chunking — fixed 1000-char windows, 150 overlap, cut on whitespace** over heading-aware.
  Simple and defensible for a tiny corpus; the overlap keeps a sentence that straddles a cut
  from being lost. Revisit if the corpus grows.
- **Refusal — deterministic threshold, skip the LLM** over always calling the model with a
  "refuse if unsupported" instruction. Zero cost and zero hallucination risk on out-of-corpus
  questions; the trade is that greetings score low and get the redirect message.
- **Citations — renumbered + deduped + snippet popover** over raw markers. A raw `[n]` refers
  to the n-th retrieved chunk, not the deduped source list, so the numbers wouldn't line up;
  renumbering makes them a real reference list, and the popover (Perplexity/Claude pattern)
  solves the small-panel problem where a marker and the source list can't be seen together.

## Metrics (honestly labeled — local, not yet production traffic)

- **Corpus:** 6 documents → 12 chunks, ~2,132 tokens total.
- **Retrieval separation** (measured on real queries, top-1 cosine similarity):
  - "What did Samuel do before engineering?" → **0.530**
  - "Tell me about Cadence" → **0.504**
  - "Has Samuel built RAG systems?" → **0.498**
  - "Favorite pizza topping?" (out of corpus) → **0.326** → refused
  - Refusal threshold **0.35** cleanly splits the in-corpus cluster (0.46–0.53) from the
    out-of-corpus question (0.33).
- **Cost per answer** (Haiku 4.5 at $1/$5 per Mtok, computed from real token counts):
  grounded answers **~$0.0017–0.0029**; refusals **$0.00** (no model call).
- **Tests:** 26 passing — chunking, the grounding decision, citation renumber/dedup/snippet,
  and the honesty guards (now asserting against the corpus).

## What broke, and how it was fixed

1. **Vectors bound as `float[]`, not `vector`.** A plain Python list made `embedding <=> $1`
   fail with "operator does not exist". Fixed by wrapping values in `pgvector.Vector`. It was
   caught *before* the embedding key existed, because `search()` was written to be testable
   against the database on its own — and the same latent bug was lurking in the ingestion
   script, which had never run.
2. **The server served stale code.** `main.py` runs without `--reload`, so a rewritten `/chat`
   kept returning old responses until a manual `uvicorn` restart. Lesson written down: restart
   the backend after backend edits.
3. **`insufficient_quota` on first embed.** The OpenAI key authenticated but the account had a
   $0 balance; OpenAI requires prepaid credit. A billing step, not a code bug — but a good
   reminder that "key works" and "API works" are different checks.
4. **Citation numbers didn't line up.** Markers referenced retrieved-chunk order while the chips
   were deduped, so `[1]` and `[4]` could be the same file. `finalize_citations` renumbers to a
   clean 1..N aligned with the chips.
5. **A marker and its source couldn't be seen together** in the small chat panel. Researched how
   Perplexity/Claude/ChatGPT handle it; the answer is a preview popover anchored to the marker,
   bringing the source to the reader instead of scrolling to it.

## What's next

- **Deploy:** add `OPENAI_API_KEY` and `DATABASE_URL` to Render, then verify production `/chat`
  returns cited answers. Until then the feature is local-only, and the site says so.
- **Evals (Module 2):** calibrate the 0.35 threshold against labeled should-answer / should-refuse
  cases; measure groundedness, citation correctness, and retrieval recall@k with published numbers.
- **Instruction adherence:** the model occasionally emits Markdown despite a plain-text
  instruction — a concrete thing for the eval harness to catch and the prompt to fix.
- **Chunking:** move to heading-aware splitting if the corpus grows past a handful of documents.
