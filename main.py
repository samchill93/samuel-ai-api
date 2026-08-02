"""
Ask Me About Samuel — a small FastAPI backend that answers questions about
Samuel using the Claude API. It's the Python twin of the Cadence support bot:
same idea, new language.

Coming from JavaScript/TypeScript? The comments point out the Python equivalents
of things you already know.
"""

import json                                          # SSE event serialization (streaming, Module 6)
import logging                                       # server-side error detail, never sent to the client
import os                                            # read environment variables (e.g. allowed CORS origins)
import subprocess                                    # local git SHA as a dev fallback for /version
import time                                          # per-request and per-phase timing (Module 3)
from datetime import datetime, timezone              # timestamps for /version

import psycopg                                       # PostgreSQL driver — stores contact inquiries

from anthropic import Anthropic                     # official Claude SDK for Python
from dotenv import load_dotenv                       # loads the .env file into environment variables
from fastapi import Depends, FastAPI, HTTPException, Request  # the web framework (like Express, but typed)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse       # token-by-token SSE (Module 6)
from pydantic import BaseModel, EmailStr, Field      # typed, self-validating data models

from about_me import ABOUT_SAMUEL                    # the assistant's persona/voice shell
from retrieve import retrieve, retrieve_timed, is_grounded, conversation_query   # RAG: find relevant corpus chunks
from rag import build_system_prompt, finalize_citations, to_plain_text, REFUSAL  # ground, cite, enforce plain text
from obs import metrics, new_request_id, configure_logging       # observability (Module 3)
from agent import run_agent, run_agent_stream                     # tool-using agent (Module 5)
from ratelimit import RateLimiter                                 # per-IP rate limiting (hardening)

# Read ANTHROPIC_API_KEY (and anything else) from the .env file so it lands in the environment.
load_dotenv()

logger = configure_logging("samuel-ai-api")   # structured JSON logs to stdout (Render captures them)

# The app object is what the server (uvicorn) runs. In Express you'd write: const app = express()
#
# Opt-in hosted MCP: when ENABLE_MCP_HTTP is set, the portfolio MCP server is also served over
# streamable HTTP at /mcp on this same app — the same four tools as the stdio server. It is OFF
# by default, so production is unchanged unless the env var is deliberately set; the mount cannot
# destabilize the live API unless someone turns it on.
_ENABLE_MCP_HTTP = os.getenv("ENABLE_MCP_HTTP", "").lower() in ("1", "true", "yes")
if _ENABLE_MCP_HTTP:
    from contextlib import asynccontextmanager
    from mcp_server import mcp as _portfolio_mcp

    _portfolio_mcp.settings.streamable_http_path = "/"     # so mounting at /mcp serves exactly /mcp
    _mcp_http_app = _portfolio_mcp.streamable_http_app()

    @asynccontextmanager
    async def _lifespan(_app):
        # Run the MCP session manager's lifespan alongside the API's.
        async with _mcp_http_app.router.lifespan_context(_app):
            yield

    app = FastAPI(title="Ask Me About Samuel", lifespan=_lifespan)
else:
    app = FastAPI(title="Ask Me About Samuel")

# CORS controls which websites may call this API from a browser. Production is locked to the
# live portfolio site — the custom domain (apex + www) and the original vercel.app URL. Local
# development adds localhost origins through the CORS_ORIGINS environment variable (set in .env,
# which is git-ignored). The default below is exactly the production lock, so nothing changes in
# prod unless CORS_ORIGINS is set there deliberately.
DEFAULT_ORIGINS = "https://samuelhill.online,https://www.samuelhill.online,https://living-portfolio-chi.vercel.app"
allowed_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------------------
# Observability middleware (Module 3): give every request an id, time it, log it as one
# structured JSON line, record it in the in-memory metrics registry, and return the id in
# an X-Request-ID header so a caller can correlate what they saw with the server logs.
# ----------------------------------------------------------------------------
@app.middleware("http")
async def observe(request: Request, call_next):
    rid = new_request_id()
    request.state.request_id = rid
    started = time.perf_counter()
    status = 500                # assume failure until proven otherwise (covers an unhandled raise)
    response = None
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        latency_ms = (time.perf_counter() - started) * 1000
        metrics.record_request(request.url.path, status, latency_ms)
        if response is not None:
            response.headers["X-Request-ID"] = rid
        logger.info("request", extra={"fields": {
            "request_id": rid,
            "method": request.method,
            "path": request.url.path,
            "status": status,
            "latency_ms": round(latency_ms, 1),
        }})


# ----------------------------------------------------------------------------
# Build/version info — powers the site's live telemetry strip (GET /version).
# The commit SHA comes from Render's injected RENDER_GIT_COMMIT in production; locally
# we fall back to the git SHA, then to "dev". deployed_at is this process's start time —
# each Render deploy restarts the process, so it is an honest "live since" timestamp.
# ----------------------------------------------------------------------------
_STARTED_AT = datetime.now(timezone.utc).isoformat()


def _commit_sha() -> str:
    sha = os.getenv("RENDER_GIT_COMMIT")  # Render injects this at deploy time
    if sha:
        return sha[:7]
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            text=True,
            timeout=3,
        ).strip()
    except Exception:
        return "dev"


_SHA = _commit_sha()  # computed once at startup, not per request


# ----------------------------------------------------------------------------
# Cost accounting — powers the chat widget's honest cost footer.
# Prices are US dollars per 1,000,000 tokens, from Anthropic's published pricing for
# Claude Haiku 4.5 (input $1.00 / output $5.00 per 1M tokens), as of July 2026.
# These two numbers are the single source of truth; update them if the model or price changes.
# ----------------------------------------------------------------------------
HAIKU_INPUT_USD_PER_MTOK = 1.00
HAIKU_OUTPUT_USD_PER_MTOK = 5.00


def _answer_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Cost of one answer from the real token counts the API reports."""
    return (
        input_tokens / 1_000_000 * HAIKU_INPUT_USD_PER_MTOK
        + output_tokens / 1_000_000 * HAIKU_OUTPUT_USD_PER_MTOK
    )


# ----------------------------------------------------------------------------
# Rate limiting (hardening) — the LLM endpoints cost money and are public, so cap requests
# per client IP. In-memory and process-local (resets on deploy); tune via env without a code
# change. A normal visitor sends a few messages a minute — well under the cap; a script hits it.
# ----------------------------------------------------------------------------
RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "20"))          # requests per window, per IP
RATE_LIMIT_WINDOW = float(os.getenv("RATE_LIMIT_WINDOW", "60"))  # seconds
_llm_limiter = RateLimiter(RATE_LIMIT_MAX, RATE_LIMIT_WINDOW)


def _rate_limit(http_request: Request) -> None:
    """Dependency for the paid LLM endpoints: 429 with Retry-After when a client IP is over."""
    ip = http_request.client.host if http_request.client else "unknown"
    allowed, retry = _llm_limiter.check(ip, time.monotonic())
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests — please slow down.",
                            headers={"Retry-After": str(int(retry) + 1)})


# ----------------------------------------------------------------------------
# Data models
# Pydantic models describe the shape of the JSON going in and out — and validate it
# automatically. Think TypeScript interfaces that actually enforce themselves at runtime:
# if a request doesn't match, FastAPI returns a clear 422 error for you, for free.
# ----------------------------------------------------------------------------

class Message(BaseModel):
    role: str            # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]     # the conversation so far. list[Message] is Python's Array<Message>.


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float


class Citation(BaseModel):
    source_path: str          # e.g. 'projects/cadence.md' — which corpus file the claim came from
    title: str | None = None
    snippet: str | None = None   # a short preview of the cited text, shown next to the marker


class Trace(BaseModel):
    """Per-request trace (Module 3): the real timings and retrieval facts behind one answer.
    Operational data only — no message text, no secrets — so it's safe to hand to the caller
    and is what a future 'glass-box' panel reads to show a request explaining itself."""
    request_id: str
    grounded: bool                       # did retrieval clear the threshold (answer) or not (refuse)?
    sources: int                         # how many chunks retrieval returned
    top_similarity: float | None = None  # best cosine similarity for the query
    retrieval_ms: float
    embed_ms: float | None = None        # part of retrieval_ms: the OpenAI embedding round-trip
    db_ms: float | None = None           # part of retrieval_ms: the Neon/pgvector search
    model_ms: float                      # 0.0 on a refusal — no model call is made
    total_ms: float


class ChatResponse(BaseModel):
    reply: str
    usage: Usage                        # token counts + computed cost for the honest cost footer
    citations: list[Citation] = []      # the sources the answer actually cited (RAG, Module 1)
    trace: Trace | None = None          # per-request timing + retrieval trace (Module 3)


# --- Agent (Module 5): a task in, an answer plus the steps the agent took ---------------
class AgentRequest(BaseModel):
    task: str = Field(min_length=1, max_length=4000)   # a question or a job description to assess


class AgentStep(BaseModel):
    """One step in the agent's run — either a 'thought' (reasoning text) or a 'tool_call'
    (which tool it invoked, with what input, and what came back). This is what makes the
    agent transparent: the caller sees every move, not just the final answer."""
    type: str
    text: str | None = None
    tool: str | None = None
    input: dict | None = None
    output: dict | None = None


class AgentResponse(BaseModel):
    answer: str
    steps: list[AgentStep]              # the ordered trace of thoughts and tool calls
    iterations: int                     # how many model turns the loop took
    tool_calls: int                     # how many tools were actually run
    usage: Usage                        # summed tokens + cost across the whole loop
    request_id: str
    elapsed_ms: float
    stopped: str                        # 'complete' or 'max_iterations'


class VersionResponse(BaseModel):
    sha: str
    deployed_at: str


class InquiryRequest(BaseModel):
    """A message from the site's contact form. Pydantic validates every field for us."""
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    message: str = Field(min_length=1, max_length=4000)
    company: str | None = Field(default=None, max_length=160)
    package_interest: str | None = Field(default=None, max_length=120)
    # Honeypot: this field is hidden from real users in the browser. If it arrives filled,
    # the sender is almost certainly a bot — the handler silently accepts and drops it.
    website: str | None = Field(default=None, max_length=200)


class InquiryResponse(BaseModel):
    status: str


# ----------------------------------------------------------------------------
# Routes
# The @app.get / @app.post lines are "decorators" — they attach the function below
# as the handler for that route (same job as app.get('/health', handler) in Express,
# just written above the function instead of beside it).
# ----------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    """Quick 'is the server alive?' check. Open http://localhost:8000/health in a browser."""
    return {"status": "ok"}


@app.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    """Build info for the site's telemetry strip: the deployed commit and when it went live."""
    return VersionResponse(sha=_SHA, deployed_at=_STARTED_AT)


@app.get("/metrics")
def get_metrics() -> dict:
    """Operational metrics since this process started (Module 3): request counts, latency
    percentiles, and the running chat token/cost tally. Process-local and honest about its
    window — the `since` field is this deploy's start time, so the numbers never pretend to
    be lifetime totals. No request contents are recorded, only shapes, statuses, and timings."""
    return metrics.snapshot()


@app.post("/inquiry", response_model=InquiryResponse, status_code=201)
def inquiry(request: InquiryRequest) -> InquiryResponse:
    """Accept a contact-form message: validated by Pydantic, then stored in Postgres.

    Invalid input never reaches this function — FastAPI returns a 422 with the field
    errors first. That is the "typed API" the form shows off.
    """
    # Honeypot: real users can't see the 'website' field, so a filled one means a bot.
    # Return success WITHOUT storing, so the bot can't tell it was caught.
    if request.website:
        return InquiryResponse(status="received")

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        # Missing configuration is not the caller's mistake, and pretending the message
        # was received would silently lose it. Fail honestly instead.
        raise HTTPException(status_code=503, detail="The inquiry store is not configured yet.")

    try:
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO inquiries (name, email, company, package_interest, message) "
                "VALUES (%s, %s, %s, %s, %s)",
                (request.name, request.email, request.company, request.package_interest, request.message),
            )
    except Exception:
        # Never echo the driver's message to the client: a psycopg connection error can
        # carry the database host and user from DATABASE_URL. Log it, return nothing.
        logger.exception("inquiry insert failed")
        raise HTTPException(status_code=500, detail="Could not store the inquiry.")

    return InquiryResponse(status="received")


def _retrieve_for_chat(request: ChatRequest, rid: str):
    """Shared prep for /chat and /chat/stream: build the messages, form the retrieval query
    from the recent conversation, and fetch grounding chunks. Raises the same 422/503 both
    endpoints return, so their behaviour can't drift apart."""
    claude_messages = [{"role": m.role, "content": m.content} for m in request.messages]
    query = conversation_query(claude_messages)   # recent turns, so a follow-up keeps its topic
    if not query:
        raise HTTPException(status_code=422, detail="No user message to answer.")
    try:
        hits, embed_ms, db_ms = retrieve_timed(query)
    except Exception:
        logger.exception("retrieval failed", extra={"fields": {"request_id": rid}})
        raise HTTPException(status_code=503, detail="The knowledge base is unavailable right now.")
    return claude_messages, hits, embed_ms, db_ms


def _sse(event: dict) -> str:
    """Format one Server-Sent Events message (data-only)."""
    return f"data: {json.dumps(event)}\n\n"


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(_rate_limit)])
def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
    """Answer only from Samuel's corpus (RAG): retrieve the chunks relevant to the latest
    question, ground the prompt on them, and cite the sources the reply actually used.
    When the corpus doesn't cover the question, refuse honestly instead of guessing.

    Module 3: each phase is timed and the request's trace (id, timings, retrieval facts) is
    logged and returned, so the answer can account for exactly how it was produced."""

    rid = getattr(http_request.state, "request_id", "")
    claude_messages, hits, embed_ms, db_ms = _retrieve_for_chat(request, rid)
    retrieval_ms = embed_ms + db_ms
    top_similarity = hits[0]["similarity"] if hits else None

    # Not covered by the corpus → refuse honestly, and skip the LLM call entirely (no cost).
    if not is_grounded(hits):
        metrics.record_chat(answered=False, input_tokens=0, output_tokens=0, cost_usd=0.0)
        trace = Trace(request_id=rid, grounded=False, sources=len(hits), top_similarity=top_similarity,
                      retrieval_ms=round(retrieval_ms, 1), embed_ms=round(embed_ms, 1), db_ms=round(db_ms, 1), model_ms=0.0, total_ms=round(retrieval_ms, 1))
        logger.info("chat", extra={"fields": {
            "request_id": rid, "grounded": False, "sources": len(hits),
            "top_similarity": top_similarity, "retrieval_ms": round(retrieval_ms, 1), "cost_usd": 0.0}})
        return ChatResponse(
            reply=REFUSAL,
            usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
            citations=[],
            trace=trace,
        )

    # Ground the persona prompt on the retrieved sources, then answer.
    grounded_system = build_system_prompt(ABOUT_SAMUEL, hits)
    t_model = time.perf_counter()
    try:
        client = Anthropic()   # reads ANTHROPIC_API_KEY from the environment
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",   # fast + inexpensive; great for a portfolio bot
            max_tokens=1024,
            system=grounded_system,
            messages=claude_messages,
        )
    except Exception:
        logger.exception("claude call failed", extra={"fields": {"request_id": rid}})   # never echo the SDK error
        raise HTTPException(status_code=502, detail="Could not reach the language model.")
    model_ms = (time.perf_counter() - t_model) * 1000

    # Renumber the [n] markers to match the deduped source list, and get that list back.
    reply_text, citations = finalize_citations(response.content[0].text, hits)
    reply_text = to_plain_text(reply_text)   # enforce the plain-text contract the widget relies on
    usage = Usage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cost_usd=_answer_cost_usd(response.usage.input_tokens, response.usage.output_tokens),
    )
    metrics.record_chat(answered=True, input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens, cost_usd=usage.cost_usd)
    trace = Trace(request_id=rid, grounded=True, sources=len(hits), top_similarity=top_similarity,
                  retrieval_ms=round(retrieval_ms, 1), embed_ms=round(embed_ms, 1), db_ms=round(db_ms, 1),
                  model_ms=round(model_ms, 1), total_ms=round(retrieval_ms + model_ms, 1))
    logger.info("chat", extra={"fields": {
        "request_id": rid, "grounded": True, "sources": len(hits), "top_similarity": top_similarity,
        "retrieval_ms": round(retrieval_ms, 1), "model_ms": round(model_ms, 1),
        "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
        "cost_usd": round(usage.cost_usd, 6)}})
    return ChatResponse(reply=reply_text, usage=usage, citations=citations, trace=trace)


@app.post("/chat/stream", dependencies=[Depends(_rate_limit)])
def chat_stream(request: ChatRequest, http_request: Request):
    """Streaming version of /chat (Module 6): the answer's tokens arrive as Server-Sent Events
    as the model writes them, then a final 'done' event carries the finalized reply, citations,
    usage, and trace. Retrieval and grounding are identical to /chat — only delivery differs, so
    the refusal, cost, and citation behaviour all match its non-streaming twin."""
    rid = getattr(http_request.state, "request_id", "")
    claude_messages, hits, embed_ms, db_ms = _retrieve_for_chat(request, rid)
    retrieval_ms = embed_ms + db_ms
    top_similarity = hits[0]["similarity"] if hits else None

    def event_stream():
        # Out of corpus → one refusal event, no model call and no cost (same rule as /chat).
        if not is_grounded(hits):
            metrics.record_chat(answered=False, input_tokens=0, output_tokens=0, cost_usd=0.0)
            trace = Trace(request_id=rid, grounded=False, sources=len(hits), top_similarity=top_similarity,
                          retrieval_ms=round(retrieval_ms, 1), embed_ms=round(embed_ms, 1), db_ms=round(db_ms, 1), model_ms=0.0, total_ms=round(retrieval_ms, 1))
            logger.info("chat_stream", extra={"fields": {"request_id": rid, "grounded": False,
                        "sources": len(hits), "retrieval_ms": round(retrieval_ms, 1), "cost_usd": 0.0}})
            yield _sse({"type": "done", "reply": REFUSAL, "citations": [],
                        "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                        "trace": trace.model_dump()})
            return

        grounded_system = build_system_prompt(ABOUT_SAMUEL, hits)
        t_model = time.perf_counter()
        try:
            client = Anthropic()
            with client.messages.stream(model="claude-haiku-4-5-20251001", max_tokens=1024,
                                        system=grounded_system, messages=claude_messages) as stream:
                for delta in stream.text_stream:
                    yield _sse({"type": "token", "text": delta})   # raw text as it arrives
                final = stream.get_final_message()
        except Exception:
            logger.exception("claude stream failed", extra={"fields": {"request_id": rid}})
            yield _sse({"type": "error", "detail": "Could not reach the language model."})
            return
        model_ms = (time.perf_counter() - t_model) * 1000

        # Finalize once the full text is in: renumber [n] markers, strip markdown, price it.
        reply_text, citations = finalize_citations(final.content[0].text, hits)
        reply_text = to_plain_text(reply_text)
        cost = _answer_cost_usd(final.usage.input_tokens, final.usage.output_tokens)
        metrics.record_chat(answered=True, input_tokens=final.usage.input_tokens,
                            output_tokens=final.usage.output_tokens, cost_usd=cost)
        trace = Trace(request_id=rid, grounded=True, sources=len(hits), top_similarity=top_similarity,
                      retrieval_ms=round(retrieval_ms, 1), embed_ms=round(embed_ms, 1), db_ms=round(db_ms, 1),
                      model_ms=round(model_ms, 1), total_ms=round(retrieval_ms + model_ms, 1))
        logger.info("chat_stream", extra={"fields": {"request_id": rid, "grounded": True,
                    "sources": len(hits), "retrieval_ms": round(retrieval_ms, 1), "model_ms": round(model_ms, 1),
                    "input_tokens": final.usage.input_tokens, "output_tokens": final.usage.output_tokens,
                    "cost_usd": round(cost, 6)}})
        yield _sse({"type": "done", "reply": reply_text, "citations": citations,
                    "usage": {"input_tokens": final.usage.input_tokens,
                              "output_tokens": final.usage.output_tokens, "cost_usd": cost},
                    "trace": trace.model_dump()})

    # no-cache / no-buffering headers so proxies (and Render) don't hold the stream back.
    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/agent", response_model=AgentResponse, dependencies=[Depends(_rate_limit)])
def agent_endpoint(request: AgentRequest, http_request: Request) -> AgentResponse:
    """Run the tool-using agent on a task (Module 5). Claude decides which tools to call over
    Samuel's real data (search his documents, list skills / projects / services), loops until it
    can answer, and every step is returned so the caller can see the agent's work. The tools are
    read-only — the agent looks things up, it never takes an action."""
    rid = getattr(http_request.state, "request_id", "")
    started = time.perf_counter()
    try:
        result = run_agent(request.task, Anthropic())   # Anthropic() reads the key from the env
    except Exception:
        logger.exception("agent run failed", extra={"fields": {"request_id": rid}})
        raise HTTPException(status_code=502, detail="The agent could not complete the task.")

    elapsed_ms = (time.perf_counter() - started) * 1000
    cost = _answer_cost_usd(result["input_tokens"], result["output_tokens"])
    tool_calls = sum(1 for s in result["steps"] if s["type"] == "tool_call")
    logger.info("agent", extra={"fields": {
        "request_id": rid, "iterations": result["iterations"], "tool_calls": tool_calls,
        "input_tokens": result["input_tokens"], "output_tokens": result["output_tokens"],
        "cost_usd": round(cost, 6), "elapsed_ms": round(elapsed_ms, 1), "stopped": result["stopped"]}})
    return AgentResponse(
        answer=to_plain_text(result["answer"]),
        steps=[AgentStep(**s) for s in result["steps"]],
        iterations=result["iterations"],
        tool_calls=tool_calls,
        usage=Usage(input_tokens=result["input_tokens"], output_tokens=result["output_tokens"], cost_usd=cost),
        request_id=rid,
        elapsed_ms=round(elapsed_ms, 1),
        stopped=result["stopped"],
    )


@app.post("/agent/stream", dependencies=[Depends(_rate_limit)])
def agent_stream(request: AgentRequest, http_request: Request):
    """Streaming version of /agent: each step (a thought or a tool call) is sent as a Server-Sent
    Event the moment it happens, then a final 'done' event carries the answer, run counts, and
    usage — so the caller watches the agent work rather than waiting for the whole run."""
    rid = getattr(http_request.state, "request_id", "")
    started = time.perf_counter()

    def event_stream():
        tool_calls = 0
        final = None
        try:
            client = Anthropic()
            for kind, payload in run_agent_stream(request.task, client):
                if kind == "step":
                    if payload["type"] == "tool_call":
                        tool_calls += 1
                    yield _sse({"type": "step", "step": payload})
                else:
                    final = payload
        except Exception:
            logger.exception("agent stream failed", extra={"fields": {"request_id": rid}})
            yield _sse({"type": "error", "detail": "The agent could not complete the task."})
            return

        elapsed_ms = (time.perf_counter() - started) * 1000
        cost = _answer_cost_usd(final["input_tokens"], final["output_tokens"])
        logger.info("agent_stream", extra={"fields": {
            "request_id": rid, "iterations": final["iterations"], "tool_calls": tool_calls,
            "input_tokens": final["input_tokens"], "output_tokens": final["output_tokens"],
            "cost_usd": round(cost, 6), "elapsed_ms": round(elapsed_ms, 1), "stopped": final["stopped"]}})
        yield _sse({"type": "done", "answer": to_plain_text(final["answer"]),
                    "iterations": final["iterations"], "tool_calls": tool_calls,
                    "usage": {"input_tokens": final["input_tokens"], "output_tokens": final["output_tokens"], "cost_usd": cost},
                    "request_id": rid, "elapsed_ms": round(elapsed_ms, 1), "stopped": final["stopped"]})

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if _ENABLE_MCP_HTTP:
    # Hosted MCP over streamable HTTP at /mcp (opt-in). Mounted last, after every native route.
    app.mount("/mcp", _mcp_http_app)


# Note: these handlers are plain `def` (not `async def`). FastAPI runs sync handlers in a
# threadpool, so the blocking Claude call here is fine. We can switch to the async client later.
