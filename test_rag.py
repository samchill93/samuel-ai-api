"""
Unit tests for grounded-answer assembly — the rules that make the RAG answers honest,
tested without a key or database.
"""

from rag import build_context, build_system_prompt, cited_sources, REFUSAL

HITS = [
    {"source_path": "profile.md", "title": "Profile", "content": "Samuel is a Full-Stack AI Engineer.", "similarity": 0.8},
    {"source_path": "projects/cadence.md", "title": "Cadence", "content": "Cadence is a support chatbot.", "similarity": 0.6},
    {"source_path": "profile.md", "title": "Profile", "content": "He was a technical project manager.", "similarity": 0.5},
]


# --- Context -----------------------------------------------------------------
def test_context_numbers_chunks_and_tags_sources():
    ctx = build_context(HITS)
    assert "[1]" in ctx and "[2]" in ctx and "[3]" in ctx
    assert "source: profile.md" in ctx
    assert "Samuel is a Full-Stack AI Engineer." in ctx


# --- System prompt -----------------------------------------------------------
def test_system_prompt_grounds_and_keeps_the_persona():
    prompt = build_system_prompt("You are Samuel's assistant.", HITS)
    assert "You are Samuel's assistant." in prompt        # persona preserved
    assert "ONLY using the numbered sources" in prompt     # grounding rule present
    assert "do not guess" in prompt                        # anti-hallucination
    assert "in-progress work as finished" in prompt        # the standing honesty rule
    assert "Cadence is a support chatbot." in prompt       # sources embedded


# --- Citations (the honest part) --------------------------------------------
def test_cited_sources_returns_only_what_the_reply_cites():
    reply = "Samuel is a Full-Stack AI Engineer [1]."
    cites = cited_sources(reply, HITS)
    assert cites == [{"source_path": "profile.md", "title": "Profile"}]


def test_cited_sources_dedupes_by_path_in_citation_order():
    # [2] then [1]; [3] is also profile.md so it must not appear twice.
    reply = "Cadence is a chatbot [2]. Samuel builds them [1], as a former PM [3]."
    cites = cited_sources(reply, HITS)
    assert cites == [
        {"source_path": "projects/cadence.md", "title": "Cadence"},
        {"source_path": "profile.md", "title": "Profile"},
    ]


def test_cited_sources_ignores_out_of_range_markers():
    """A marker with no matching chunk must not become a fabricated citation."""
    reply = "According to the docs [99], something is true."
    assert cited_sources(reply, HITS) == []


def test_cited_sources_empty_when_no_markers():
    assert cited_sources("A plain answer with no citations.", HITS) == []


def test_refusal_message_is_honest():
    assert "don't have that" in REFUSAL and "confidently" in REFUSAL
