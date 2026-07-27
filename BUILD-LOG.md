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
