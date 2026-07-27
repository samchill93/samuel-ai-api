# Build Log — Ask Me About Samuel (Living Portfolio backend)

A dated record of what shipped, one entry per logical milestone.
Format: `date · what shipped · capabilities demonstrated`.
(Samuel merges these into his master timeline document.)

---

**2026-07-18 · Module 0 — about_me.py honesty fix shipped to production ·**
Corrected the portfolio bot's knowledge base to distinguish shipped skills from
in-progress work: removed RAG, agents/tool-use, vector search, evaluations, and
Docker from the "shipped" claims; added a "Currently building" section for that
in-progress work; added the Living Portfolio itself and Render as real entries;
fixed the title to "Full-Stack AI Engineer"; and added a system-prompt rule so the
bot never presents in-progress work as completed. Added pytest honesty-guard tests
that fail if an overclaim is ever re-introduced. Verified live on the deployed API
(the bot now answers "Has Samuel built RAG systems?" honestly — not yet, in
progress). Capabilities demonstrated: honest AI-portfolio scoping, prompt-as-claims-
surface discipline, regression-guarding a content invariant with tests, and a full
CI/CD deploy loop (commit → push → Render auto-deploy → live verification).

**2026-07-19 · Site restructured into portfolio + storefront; typed contact API shipped ·**
Replaced the "Selected Work" section with "This site is the portfolio" — capabilities
split into Live and Planned, each labelled honestly and never blurred. Added a Services
storefront from the pricing menu (rate quoted on inquiry, not displayed). Backend gained
`POST /inquiry` (Pydantic model with EmailStr, clean 422s, invisible honeypot that returns
success without storing so a bot cannot detect it), `GET /version` (build SHA from
RENDER_GIT_COMMIT), and per-answer `usage` on `/chat` carrying real input/output token
counts and a cost computed from published Haiku pricing. Added an `inquiries` table.
Capabilities demonstrated: typed request/response modelling, server-side validation as a
product feature, anti-spam without a CAPTCHA, honest unit-economics reporting from
measured tokens rather than estimates.

**2026-07-20 · Architecture X-Ray and Deployment Topology shipped; backend hardened ·**
Rebuilt the site in a dark design system and added two interactive explainers. The
Architecture X-Ray follows one request through seven real layers (browser → DNS/TLS →
uvicorn → CORS → Pydantic → Claude → typed response), each with the actual code that runs
it. The Deployment Topology shows the same system in space — GitHub, Vercel, Render, the
browser, Anthropic and Neon — including a single push rebuilding two independent clouds in
parallel, which a request trace cannot express. Both work fully without WebGL; optional 3D
layers exist behind flags (`xray3d`, `topology3d`, both shipping false) with lazy loading,
capability gates, a measured-fps quality governor, keyboard navigation, and screen-space
label collision resolution. Backend: `/inquiry` no longer echoes driver errors to the
caller (a psycopg connection error carries the database host and user), and a missing
DATABASE_URL now returns 503 instead of claiming receipt for a message it cannot store.
Verified live: SHA cbfac27 deployed; `/health` ok; `/inquiry` returns 422 on a malformed
email and 503 while DATABASE_URL is unset; CORS returns the allow-origin header to the
portfolio domain and none to an unapproved origin. Capabilities demonstrated: explaining
one's own architecture to a non-specialist, progressive enhancement, performance budgeting
with adaptive degradation, not leaking infrastructure detail through error messages, and
labelling a half-finished path as half-finished on a public page.

**Open at this entry:** DATABASE_URL is not set in Render, so the inquiry write to Neon
is not running; the site says so rather than implying otherwise. Both 3D layers remain
flagged off in production pending a performance check on lower-end hardware.

**2026-07-24 · Module 1 — RAG with visible, touchable citations (built + verified locally) ·**
The assistant stopped answering from a hand-written prompt and now answers only from
Samuel's real documents. A `/corpus` of markdown is chunked (fixed 1000-char windows, 150
overlap), embedded with OpenAI `text-embedding-3-small` (1536-dim), and stored in Neon
Postgres with a pgvector HNSW cosine index. `/chat` retrieves the top-5 chunks for the
question, refuses deterministically at $0 when the best cosine similarity is below 0.35
(the out-of-corpus "pizza" question scores 0.33 vs 0.46–0.53 for real questions), and
otherwise grounds Claude on numbered sources. Replies carry `[n]` markers renumbered to
match a deduped source list; the widget renders each marker as a hover/tap popover
previewing the source title and a snippet — the Perplexity/Claude citation pattern.
`about_me.py` shrank from a facts-laden prompt to a persona shell, so the corpus is the
single claims surface. Measured: grounded answers ~$0.0017–0.0029 (Haiku 4.5), refusals
$0; 26 tests pass. Capabilities demonstrated: retrieval-augmented generation, embeddings +
vector search, grounding-vs-hallucination with a calibrated refusal, honest chunk-level
citations, and testing database plumbing independently of a paid API — a separation that
caught a real bug (a Python list binds as `float[]`, not `vector`, which would have broken
ingestion on first run).

**2026-07-27 · Module 1 deployed to production ·** `OPENAI_API_KEY` and `DATABASE_URL`
added to Render; the 10 RAG commits pushed and deployed (SHA a43ef7c). Verified live at
`samuel-ai-api.onrender.com`: `/chat` returns grounded, multi-source cited answers
(~$0.0029), an out-of-corpus question refuses at $0, and `/inquiry` validates then stores
to Neon (201). The frontend's touchable citation UI shipped to Vercel, and the site copy
was corrected to match (RAG marked shipped; the topology's inquiry flow no longer says
"not deployed"). Case study: `case-studies/module-1-rag.md`.

**Open at this entry:** threshold calibration, published eval numbers, and the
Markdown-in-plain-text slip are Module 2 work. Teach-back for Module 1 still to pass.

**2026-07-27 · Module 2 (in progress) — LLM evals: golden dataset, judge, and an eval-driven honesty fix ·**
Built the evaluation engine for the RAG assistant. A 108-example golden dataset
(`data/golden_dataset.json`, 66 answer / 42 refuse across six categories) was generated
by a 12-agent workflow — six category generators plus six adversarial verifiers that
checked every label against the corpus. `evals/harness.py` runs each example through the
real pipeline and scores the objective dimensions: retrieval recall@5 = 0.992, citation
validity 92/92 (zero fabricated citations). `evals/judge.py` adds an LLM-as-judge (Claude
Sonnet 5 — stronger than the Haiku that writes the answers), scoring groundedness,
behaviour correctness, and completeness on the actual replies, with the corpus sent as a
cached prefix (~$0.20 per full run, ~354k tokens from cache): overall pass 0.917, grounded
0.944, behaviour-correct 0.981 (numbers from the run in `evals/judged.json`; both
generation and judging are non-deterministic, so they move ~0.02 run-to-run). The judge caught a live honesty bug — asked "can he do
streaming and Terraform?", the bot answered "yes, he's shipped them", when the corpus lists
both as in progress. The grounding rule was strengthened, the fix re-measured and deployed,
and verified on production (the bot now frames that work as in progress). `evals/calibrate.py`
builds a blind hand-labeling slice and computes judge-vs-human agreement (raw + Cohen's
kappa). Capabilities demonstrated: dataset construction with adversarial verification,
objective retrieval/citation metrics, LLM-as-judge with prompt caching, and closing the
full eval loop — measure, find a real bug, fix, re-measure, deploy, verify.

**Open at this entry:** the calibration slice (`data/calibration_slice.json`, 24 items)
awaits Samuel's hand labels — the senior signal ("judge agreement vs hand labels"). The
Module 2 case study is drafted (`case-studies/module-2-evals.md`) with every judge number
labeled uncalibrated until that check runs. Still open after calibration: a public Evals
page rendering the calibrated numbers. Judge scores show run-to-run variance (both
generation and judging are non-deterministic), which is exactly why calibration and
recurring-failure analysis matter more than a single run.

**2026-07-27 · Module 2 — public Evals page shipped to the site ·** The site gained an
"Evals · Module 2" section (`#evals`, in the nav and roadmap, behind the now-on `evalsDash`
flag): objective scores as the headline (retrieval recall@5 0.992, citation validity 92/92),
the eval-driven honesty fix as the story, judge scores shown but badged "Calibration pending"
so no unvalidated number is presented as fact, and the 0.611-vs-0.981 finding anchored on a
code fact rather than an uncalibrated score. Every figure renders from `evals/summary.json` —
a committed artifact that `evals/summarize.py` derives from the run files — so the published
numbers are provably from one real run, not typed. The section passed a three-lens adversarial
review (honesty, design, hostile-skeptic) before going public; the review caught a real cost
understatement (answer-generation cost was labelled "per full run" — corrected to the true
end-to-end $0.41 = answers $0.21 + judge $0.20) plus three responsive/consistency fixes.
Verified live at `living-portfolio-chi.vercel.app`. Capabilities demonstrated: publishing
measured quality with honest provenance and labelling, deliberately holding a public number
back until it is validated, and adversarially reviewing one's own public-facing work before
shipping it.

**Open at this entry:** judge calibration still awaits Samuel's hand labels
(`data/calibration_slice.json`, 24 items); when scored, the page's "Calibration pending"
badge becomes the agreement number. Teach-back for Modules 1–2 remains the open gate.

**2026-07-27 · Module 3 — Observability: request tracing, structured logs, and /metrics ·**
The assistant can now account for itself. An HTTP middleware gives every request a
correlatable id (`X-Request-ID` on the response), times it, and logs it as one structured
JSON line to stdout (Render captures it); `/chat` times retrieval and the model separately and
returns a `Trace` (id, grounded, sources, top similarity, retrieval_ms, model_ms, total_ms);
and `GET /metrics` reports request counts, status families, latency p50/p95, and the running
chat token/cost tally — process-local and labelled with a `since` window so the numbers never
pretend to be lifetime totals. No request bodies, PII, or secrets are recorded (`obs.py` holds
the JSON formatter and a thread-safe, bounded metrics registry). The instrumentation
immediately found something: on a grounded answer, retrieval (~6.2s cold) dominated the model
(~1.8s) — the slow first response is a fresh Neon serverless connection plus the embedding
call, not the LLM. 11 new tests (42 total). Verified live: X-Request-ID present, a grounded
/chat trace and a $0 refusal trace both correct, and /metrics returning real counts.
Capabilities demonstrated: self-hosted observability without an external APM, request
correlation, honest operational reporting scoped to a known window, and using a trace to
locate a real bottleneck instead of guessing. Case study: `case-studies/module-3-observability.md`.

**Open at this entry:** the retrieval bottleneck the trace exposed is not yet fixed — the next
cuts are splitting retrieval into embed-vs-db timing and pooling the database connection. The
public glass-box panel stays flagged off (public after Module 6); the site's roadmap
Observability row now points to the live `/metrics` as proof of the shipped capability.

**2026-07-27 · Module 4 — Live Metrics Page ·** The site now surfaces the Module 3
observability data as a public, self-updating panel ("Live metrics", `#metrics`, behind the
`metricsPage` flag). It reads `/metrics` on load and every 15s and renders the system reporting
on itself — requests served, latency p50/p95, chat answers/refusals, running cost, and request
breakdowns by status and path — with an honest "since this deploy" window (no lifetime-total
pretence) and a graceful "waking up" state for the free-tier backend. Path keys from the
endpoint are HTML-escaped before they touch the DOM, since any caller can request any path. No
new backend — it consumes the endpoint shipped in Module 3. Verified live at
`living-portfolio-chi.vercel.app`. Capabilities demonstrated: turning an operational endpoint
into an honest public dashboard, live polling with a sensible degraded state, and treating
server-provided strings as untrusted in the browser.

**2026-07-27 · Module 5 — a tool-using agent that shows its work ·** `POST /agent` runs a
hand-written tool-use loop: Claude decides which of four read-only tools to call over Samuel's
real data (search_portfolio, list_skills, list_projects, list_services), iterates to a bounded
cap, and returns the final answer plus every step it took — reasoning and tool calls — so the
autonomy is visible, not a black box. `agent.py` holds the tools and the loop (client injected,
so it is unit-tested with a fake — no key, no network); `main.py` wires the endpoint with
request-id, timing, and structured logging. The site's new Agent section lets anyone give it a
task (a job description, a build request, a fit question) and watch the steps; all model/tool
output is rendered with createElement + textContent so nothing from the API can inject HTML. A
live fit-analysis run made 4 tool calls across 2 model turns for well under a cent, producing a
per-requirement covered/partial/gap verdict grounded in real shipped work. 9 new tests (51 total).
Building the tools surfaced and fixed a real honesty drift — the corpus still listed evals and
observability as "currently building" after both shipped — so skills.md and the title condition in
profile.md were corrected, re-ingested, and the honesty guards updated. Verified live: /agent
returns grounded multi-tool answers and /chat reflects the corrected shipped/building split. Case
study: `case-studies/module-5-agents.md`. Capabilities demonstrated: a real agentic loop (not a
scripted pipeline), grounded read-only tool use, transparent step traces, testing an agent without
the network, and handling untrusted model output safely in the DOM.

**Open at this entry:** the MCP server (the second half of the agents module) is not built — the
roadmap now lists Agents (shipped) and MCP server (planned) separately. The public agent and chat
endpoints have no rate limiting yet; that is the honest Module 6 hardening item. Judge calibration
(Module 2) and teach-back remain the standing open gates.

**2026-07-27 · Module 5 (second half) — MCP server, and the Agentic title earned ·** `mcp_server.py`
is a FastMCP server that publishes the agent's four read-only tools over the Model Context Protocol,
so any MCP client (Claude Desktop, an IDE, another agent) can search Samuel's documents and list his
skills, projects, and services. The tools are thin wrappers over the same `agent.py` implementations
— two surfaces, one source of truth. Verified end to end over the real protocol two ways: an
in-memory client<->server session in the test suite, and a real stdio subprocess (server
"samuel-portfolio", protocol 2025-11-25) that initialised, listed the four tools, and ran
search_portfolio through the full embedding + pgvector path. 4 new tests (55 total); the README
documents the Claude Desktop config. Shipping this met the corpus's title condition — both agentic
halves (the live agent and the MCP server) are done — so profile.md and the site title update to
"Full-Stack Agentic AI Engineer", reflecting shipped work, not aspiration. Case study:
`case-studies/module-5-mcp.md`. Capabilities demonstrated: exposing tools over an open protocol, one
implementation behind two surfaces, and verifying an MCP server against a real client rather than
assuming it works.

**Open at this entry:** the MCP server ships over stdio (run locally by the client); a hosted HTTP
transport is a future add, gated on doing it without risking the live API. Rate-limiting the public
agent/chat endpoints remains the Module 6 hardening item. Judge calibration (Module 2) and teach-back
remain the standing open gates.

**2026-07-27 · Module 6 — token-by-token streaming ·** `POST /chat/stream` sends the answer as
Server-Sent Events as the model writes it, then a final `done` event carries the finalized reply,
citations, usage, and trace — so the streaming path keeps every honest extra the non-streaming `/chat`
has (renumbered citations, touchable chips, real cost), all computed once the full text is in.
Retrieval and grounding are shared with `/chat` through one `_retrieve_for_chat` helper, so the two
can't drift on grounding, the $0 refusal, or errors. The chat widget reads the stream with
`fetch` + `ReadableStream`, types the raw tokens live (following the scroll only when the reader is at
the bottom), and on `done` swaps in the finalized reply and citations. Two buffering risks were
checked, not assumed: the observability middleware forwards the stream (and still logs the request),
and `Cache-Control: no-cache` + `X-Accel-Buffering: no` stop Render's proxy from holding it — verified
live, where a real answer arrived as ~15 token events spread over ~2.9s rather than one blob. 56 tests
(added an SSE-format guard). Corpus and honesty guards updated: streaming moves to shipped, leaving
only Docker and Terraform in progress. Case study: `case-studies/module-6-streaming.md`. Capabilities
demonstrated: SSE streaming from FastAPI, preserving a finalize-then-render contract under streaming,
sharing logic between two endpoints, and proving a stream isn't buffered end to end.

**Open at this entry:** the agent's steps aren't streamed yet (same SSE pattern, applied to `/agent`,
is the next natural step). Rate-limiting the public streaming/agent/chat endpoints is still the owed
hardening. Docker and Terraform remain on the roadmap; judge calibration and teach-back remain the
standing gates.

