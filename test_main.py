"""
A first taste of testing in Python with pytest.

Run it with:   pytest
(pytest automatically finds files named test_*.py and functions named test_*.)

This tests the /health endpoint, which needs no API key — so it passes immediately.
Testing the /chat endpoint properly means "mocking" the Claude call so tests don't cost
money or need the network; we'll add that when we build the evaluations node.

It also guards the bot's honesty: the tests below fail if the knowledge base ever
re-introduces an overclaim (listing in-progress work as a shipped skill). These are
plain string assertions on ABOUT_SAMUEL — no API key, no network, no cost.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from main import app

# TestClient lets us call the app in-process, without starting a real server.
client = TestClient(app)

# The corpus is the bot's claims surface now (Module 1 / RAG), so the honesty guards
# below assert against it rather than the old hand-written system prompt.
SKILLS_MD = (Path(__file__).parent / "corpus" / "skills.md").read_text(encoding="utf-8")


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version_returns_build_info():
    response = client.get("/version")
    assert response.status_code == 200
    data = response.json()
    assert data["sha"]            # non-empty commit id (or "dev" when run locally)
    assert data["deployed_at"]    # ISO timestamp of when this process started


def test_inquiry_rejects_invalid_email():
    """Pydantic rejects a bad email with a 422 before the handler runs — no DB needed."""
    r = client.post("/inquiry", json={"name": "A", "email": "not-an-email", "message": "hi"})
    assert r.status_code == 422


def test_inquiry_requires_name_and_message():
    r = client.post("/inquiry", json={"email": "a@b.com"})
    assert r.status_code == 422


def test_inquiry_honeypot_is_silently_accepted():
    """A filled honeypot returns 'received' without storing — the bot can't tell it was caught."""
    r = client.post("/inquiry", json={
        "name": "Bot", "email": "bot@spam.com", "message": "spam", "website": "http://spam"
    })
    assert r.status_code == 201
    assert r.json() == {"status": "received"}


def test_inquiry_without_database_url_fails_honestly(monkeypatch):
    """No DATABASE_URL means the message cannot be stored, so it must not report success.

    Also guards the leak: a psycopg connection error carries the database host and user,
    and that must never reach the caller.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    r = client.post("/inquiry", json={
        "name": "Real Person", "email": "person@example.com", "message": "Hello",
    })
    assert r.status_code == 503
    assert "received" not in r.text            # never claim a message was stored
    assert "DATABASE_URL" not in r.text        # no config names
    assert "postgres" not in r.text.lower()    # no driver or host detail


def test_answer_cost_uses_haiku_pricing():
    """Cost comes from real token counts and the Haiku price constants — no fabricated numbers."""
    from main import _answer_cost_usd, HAIKU_INPUT_USD_PER_MTOK, HAIKU_OUTPUT_USD_PER_MTOK
    assert _answer_cost_usd(1_000_000, 0) == HAIKU_INPUT_USD_PER_MTOK
    assert _answer_cost_usd(0, 1_000_000) == HAIKU_OUTPUT_USD_PER_MTOK
    assert 0 < _answer_cost_usd(1500, 200) < 0.01   # a real answer is a fraction of a cent


# ----------------------------------------------------------------------------
# Honesty guards — now against the corpus (corpus/skills.md), the bot's claims
# surface. skills.md is organized into "## " sections; _section() grabs one
# section's text (header up to the next "## ") so we can assert on that slice in
# isolation — e.g. "RAG must not appear in the *shipped* section, even though it
# legitimately appears in the *currently building* section."
# ----------------------------------------------------------------------------

def _section(header_prefix: str) -> str:
    """Return the text of the '## ' section in skills.md whose header starts with header_prefix."""
    start = SKILLS_MD.index(header_prefix)
    body = SKILLS_MD[start:]
    next_header = body.find("\n## ", len(header_prefix))
    return body if next_header == -1 else body[:next_header]


def test_shipped_skills_do_not_claim_in_progress_work():
    """The 'shipped' section must not list anything Samuel hasn't shipped.
    (RAG moved to shipped once Module 1 deployed; evals/agents/etc. are still building.)"""
    shipped = _section("## Shipped").lower()
    for overclaim in ["agents", "mcp", "docker", "terraform", "streaming", "observability", "evaluation"]:
        assert overclaim not in shipped, f"'{overclaim}' must not appear as a shipped skill"


def test_in_progress_work_is_present_and_labeled_not_shipped():
    """The in-progress work must exist and be clearly labeled as not-yet-shipped."""
    building = _section("## Currently building")
    assert "agents" in building.lower()          # agents/MCP is still in progress
    assert "not yet shipped" in building.lower()


def test_honesty_rule_is_present():
    """The assembled system prompt must instruct the bot never to present in-progress work as done."""
    from rag import build_system_prompt
    hits = [{"source_path": "profile.md", "title": "Profile", "content": "text", "similarity": 0.9}]
    prompt = build_system_prompt("persona", hits).lower()
    assert "never say samuel has shipped" in prompt       # the shipped-vs-building rule
    assert "only using the numbered sources" in prompt    # and it must be grounded
