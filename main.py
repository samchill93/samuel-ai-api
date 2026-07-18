"""
Ask Me About Samuel — a small FastAPI backend that answers questions about
Samuel using the Claude API. It's the Python twin of the Cadence support bot:
same idea, new language.

Coming from JavaScript/TypeScript? The comments point out the Python equivalents
of things you already know.
"""

import os                                            # read environment variables (e.g. allowed CORS origins)

from anthropic import Anthropic                     # official Claude SDK for Python
from dotenv import load_dotenv                       # loads the .env file into environment variables
from fastapi import FastAPI, HTTPException           # the web framework (like Express, but typed)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel                       # typed, self-validating data models

from about_me import ABOUT_SAMUEL                    # the knowledge the bot answers from

# Read ANTHROPIC_API_KEY (and anything else) from the .env file so it lands in the environment.
load_dotenv()

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


class ChatResponse(BaseModel):
    reply: str


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


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Send the conversation to Claude with a system prompt about Samuel, and return the reply."""

    # Turn our pydantic Message objects into the plain dicts the SDK expects.
    # This is a "list comprehension" — Python's compact map:
    #   [f(item) for item in items]   is like   items.map(item => f(item))
    claude_messages = [{"role": m.role, "content": m.content} for m in request.messages]

    try:
        # Anthropic() reads your ANTHROPIC_API_KEY from the environment — the key stays out of the code.
        client = Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",   # fast + inexpensive; great for a portfolio bot
            max_tokens=1024,
            system=ABOUT_SAMUEL,
            messages=claude_messages,
        )
    except Exception as error:
        # If the key is missing or the API call fails, return a clear error instead of crashing.
        raise HTTPException(status_code=500, detail=f"Could not reach Claude: {error}")

    # response.content is a LIST of content blocks; for a normal text answer we want the first block's text.
    reply_text = response.content[0].text
    return ChatResponse(reply=reply_text)


# Note: these handlers are plain `def` (not `async def`). FastAPI runs sync handlers in a
# threadpool, so the blocking Claude call here is fine. We can switch to the async client later.
