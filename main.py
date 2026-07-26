"""
Ask Me About Samuel — a small FastAPI backend that answers questions about
Samuel using the Claude API. It's the Python twin of the Cadence support bot:
same idea, new language.

Coming from JavaScript/TypeScript? The comments point out the Python equivalents
of things you already know.
"""

import logging                                       # server-side error detail, never sent to the client
import os                                            # read environment variables (e.g. allowed CORS origins)
import subprocess                                    # local git SHA as a dev fallback for /version
from datetime import datetime, timezone              # timestamps for /version

import psycopg                                       # PostgreSQL driver — stores contact inquiries

from anthropic import Anthropic                     # official Claude SDK for Python
from dotenv import load_dotenv                       # loads the .env file into environment variables
from fastapi import FastAPI, HTTPException           # the web framework (like Express, but typed)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field      # typed, self-validating data models

from about_me import ABOUT_SAMUEL                    # the assistant's persona/voice shell
from retrieve import retrieve, is_grounded           # RAG: find relevant corpus chunks
from rag import build_system_prompt, finalize_citations, to_plain_text, REFUSAL  # ground, cite, enforce plain text

# Read ANTHROPIC_API_KEY (and anything else) from the .env file so it lands in the environment.
load_dotenv()

logger = logging.getLogger("samuel-ai-api")   # goes to Render's logs, not to the caller

# The app object is what the server (uvicorn) runs. In Express you'd write: const app = express()
app = FastAPI(title="Ask Me About Samuel")

# CORS controls which websites may call this API from a browser. Production is locked to the
# live portfolio site. Local development adds localhost origins through the CORS_ORIGINS
# environment variable (set in .env, which is git-ignored). The default below is exactly the
# production lock, so nothing changes in prod unless CORS_ORIGINS is set there deliberately.
DEFAULT_ORIGINS = "https://living-portfolio-chi.vercel.app"
allowed_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


class ChatResponse(BaseModel):
    reply: str
    usage: Usage                        # token counts + computed cost for the honest cost footer
    citations: list[Citation] = []      # the sources the answer actually cited (RAG, Module 1)


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


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Answer only from Samuel's corpus (RAG): retrieve the chunks relevant to the latest
    question, ground the prompt on them, and cite the sources the reply actually used.
    When the corpus doesn't cover the question, refuse honestly instead of guessing."""

    claude_messages = [{"role": m.role, "content": m.content} for m in request.messages]

    # Retrieve on the latest user turn — that's the question being asked right now.
    question = next((m.content for m in reversed(request.messages) if m.role == "user"), None)
    if not question:
        raise HTTPException(status_code=422, detail="No user message to answer.")

    # Find grounding chunks. If the knowledge base is unreachable, do NOT fall back to
    # answering from thin air — say it's unavailable.
    try:
        hits = retrieve(question)
    except Exception:
        logger.exception("retrieval failed")
        raise HTTPException(status_code=503, detail="The knowledge base is unavailable right now.")

    # Not covered by the corpus → refuse honestly, and skip the LLM call entirely (no cost).
    if not is_grounded(hits):
        return ChatResponse(
            reply=REFUSAL,
            usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
            citations=[],
        )

    # Ground the persona prompt on the retrieved sources, then answer.
    grounded_system = build_system_prompt(ABOUT_SAMUEL, hits)
    try:
        client = Anthropic()   # reads ANTHROPIC_API_KEY from the environment
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",   # fast + inexpensive; great for a portfolio bot
            max_tokens=1024,
            system=grounded_system,
            messages=claude_messages,
        )
    except Exception:
        logger.exception("claude call failed")   # never echo the SDK error to the caller
        raise HTTPException(status_code=502, detail="Could not reach the language model.")

    # Renumber the [n] markers to match the deduped source list, and get that list back.
    reply_text, citations = finalize_citations(response.content[0].text, hits)
    reply_text = to_plain_text(reply_text)   # enforce the plain-text contract the widget relies on
    usage = Usage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cost_usd=_answer_cost_usd(response.usage.input_tokens, response.usage.output_tokens),
    )
    return ChatResponse(reply=reply_text, usage=usage, citations=citations)


# Note: these handlers are plain `def` (not `async def`). FastAPI runs sync handlers in a
# threadpool, so the blocking Claude call here is fine. We can switch to the async client later.
