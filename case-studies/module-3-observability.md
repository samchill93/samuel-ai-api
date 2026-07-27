# Case Study — Observability: Every Request Explains Itself

*Living Portfolio, Module 3. Status: live in production — `X-Request-ID` on every response,
per-request tracing on `/chat`, structured JSON logs, and a public `/metrics` endpoint at
samuel-ai-api.onrender.com, verified end to end.*

## Problem

The assistant worked, but it was opaque. When an answer felt slow, there was no way to say
*why* — was it retrieval, the model, the database? When something failed, the logs were
unstructured prints with no way to tie a user's report ("it broke at 2pm") to the exact
request. And the system could not answer the most basic operational question about itself:
how many requests has it served, how fast, at what cost? For a portfolio whose thesis is
*this system is real and I understand it*, "I can't tell you why it was slow" is a failing
answer.

The goal: make every request **traceable** (a correlatable id, timed by phase), make the
logs **structured** (machine-parseable, greppable by id), and let the system **report its
own health** — all without an external APM service, and without ever logging a message body
or a secret.

## Constraints

- **No external APM** — no Datadog/Sentry account to stand up or pay for. Self-hosted
  instrumentation only, using what's already in the stack (Python logging, an in-process
  registry, Render's log capture).
- **Honest windows** — a single process with no persistent metrics store. Aggregates reset
  on every deploy, so the numbers must be *labelled* with the window they cover, never
  dressed up as lifetime totals.
- **Leak nothing** — logs and metrics carry operational data only (timings, token counts,
  status codes). No request text, no PII, no secrets — the same discipline the error
  handlers already follow when they refuse to echo a driver message to the caller.
- **Bounded memory** — an in-memory registry can't grow without limit; latency samples are
  capped so a long-running process can't leak memory through its own metrics.

## Architecture

```
Every HTTP request
   │
   ▼
observe() middleware  ── assigns request_id (uuid, 12 hex)  ── times the whole request
   │
   │   ┌─────────────────── /chat handler ───────────────────┐
   │   │  t0 → retrieve()          → retrieval_ms            │
   │   │  t1 → Claude Haiku 4.5    → model_ms (0 on refusal) │
   │   │  Trace{ request_id, grounded, sources,             │
   │   │         top_similarity, retrieval_ms, model_ms,    │
   │   │         total_ms }  ── returned to the caller       │
   │   └─────────────────────────────────────────────────────┘
   ▼
metrics.record_request(path, status, latency_ms)     logger.info(one JSON line → stdout → Render)
metrics.record_chat(answered, tokens, cost_usd)      X-Request-ID header set on the response
   │
   ▼
GET /metrics  →  { since, uptime_seconds, total_requests, status_counts,
                   requests_by_path, latency_ms{p50,p95,samples},
                   chat{answers, refusals, input_tokens, output_tokens, total_cost_usd} }
```

Two decisions carry the design. **The middleware records in a `finally` block**, so a
request is counted and given its `X-Request-ID` header even if the handler raises — a failed
request is exactly the one you most need traced. And **the trace is returned to the caller,
not just logged.** The timings and retrieval facts are operational, not sensitive, so handing
them back turns the API itself into a glass box: the same data a future on-site panel will
render to show a request explaining how it was produced.

## Trade-offs (options considered, why the choice won)

- **In-process registry** over a metrics backend (Prometheus/StatsD). Zero new
  infrastructure, and honest for a single-instance service. The trade is that aggregates are
  process-local and reset on deploy — accepted, and made honest with the `since` label.
- **JSON logs to stdout** over a log-shipping agent. Render already captures stdout; one JSON
  object per line is greppable and parseable with nothing extra to run. Only the app's own
  logger namespace is reconfigured, so it doesn't fight uvicorn's logging.
- **Trace returned in the response** over logs-only. Slightly larger payloads, but it makes
  the tracing demonstrable and directly feeds the planned glass-box panel — and it exposes no
  message text, only shapes and timings.
- **Bounded latency deque (last 500)** over unbounded history. Percentiles stay meaningful,
  memory stays flat, at the cost of true long-range history — which a single free-tier
  instance shouldn't be the system of record for anyway.
- **Middleware assumes failure (`status = 500`) until proven otherwise** over assuming
  success. If a handler raises before returning a status, the metric records the 5xx rather
  than silently mislabelling a crash as a success.

## Metrics (honestly labeled — live production, fresh process window)

Measured live on the deployed API, minutes after a deploy (so the window is small and real):

- **A grounded `/chat` trace:** `retrieval_ms 6194.8`, `model_ms 1773.9`, `total_ms 7968.7`,
  `sources 5`, `top_similarity 0.531`, `cost_usd 0.001877`.
- **A refused `/chat` trace:** `grounded false`, `model_ms 0.0`, `cost_usd 0.0`,
  `top_similarity 0.161` — the trace proves the refusal cost nothing, because no model call
  was made.
- **`/metrics` after those calls:** `total_requests 5`, `status_counts {2xx: 4, 4xx: 1}`,
  `latency_ms {p50: 1.5, p95: 7971}`, `chat {answers: 1, refusals: 1, total_cost_usd: 0.001877}`.
- **`X-Request-ID`** present on every response (e.g. `99f03e3416e1`), matching the `request_id`
  inside the same request's trace and logs.

## What broke, and what the instrumentation found

1. **Retrieval, not the model, dominates latency — and the trace proved it.** The very first
   grounded request showed `retrieval_ms 6195` against `model_ms 1774`. Retrieval is doing two
   things the trace currently bundles: an OpenAI embedding call for the query, and a **fresh
   Neon connection** opened per `search()` on a serverless Postgres that cold-starts. So the
   slow first answer isn't the LLM at all — it's the embedding round-trip plus a cold database
   connection. This is the whole point of the module: you cannot optimise what you cannot see,
   and the instrumentation put the target on the board.
2. **A phantom `4xx` in the path counts.** `/metrics` showed one `4xx` against path `/` — a
   request to the root, which has no route, so FastAPI correctly returns 404. Harmless, but it
   is the metrics doing their job: surfacing traffic (a health pinger or a bare browser hit)
   that the code never explicitly handles.
3. **Logging had to not fight the server.** Reconfiguring the root logger would have doubled or
   swallowed uvicorn's own lines. Fixed by configuring only the app's logger namespace with
   `propagate=False` and a single marked handler, so repeated imports (tests, reload) don't
   stack handlers.

## What's next

- **Split `retrieval_ms` into `embed_ms` + `db_ms` — done, and it's pointed.** The trace now
  carries both. Measured live: warm, the Neon/pgvector step dominates (~1.3s) over embedding
  (~0.2s); cold, both are slow (OpenAI ~4s, Neon ~2s). A 1.3s warm database step on a 12-chunk
  table isn't the query — it's the per-request connection to Neon. The instrument found its own
  next target.
- **Reuse the database connection** (a pooled/persistent connection instead of connect-per-
  `search`) to kill the warm-connection tax the split just localized, then re-measure.
- **The glass-box panel (public after Module 6):** render a request's own trace on the site —
  retrieval vs model time, sources, similarity, cost — so a visitor watches the answer account
  for itself. The backend already returns everything it needs.
- **A live metrics page (Module 4):** surface the `/metrics` snapshot on the site with the
  honest `since` window, turning the operational numbers into a public, self-updating panel.
- **Persist aggregates** only if it's ever worth it — a single free instance shouldn't pretend
  to be a metrics system of record; the `since`-labelled window is the honest scope for now.
