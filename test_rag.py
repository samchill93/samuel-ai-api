"""
Unit tests for grounded-answer assembly — the rules that make the RAG answers honest,
tested without a key or database.
"""

from rag import build_context, build_system_prompt, finalize_citations, to_plain_text, REFUSAL

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
    assert "not yet shipped" in prompt                     # the shipped-vs-building honesty rule
    assert "Cadence is a support chatbot." in prompt       # sources embedded


# --- Citations + renumbering (the honest, touchable part) -------------------
def _paths_titles(cites):
    return [{"source_path": c["source_path"], "title": c["title"]} for c in cites]


def test_finalize_returns_only_what_the_reply_cites():
    reply, cites = finalize_citations("Samuel is a Full-Stack AI Engineer [1].", HITS)
    assert reply == "Samuel is a Full-Stack AI Engineer [1]."
    assert _paths_titles(cites) == [{"source_path": "profile.md", "title": "Profile"}]


def test_finalize_renumbers_and_dedupes_in_citation_order():
    # [2] then [1]; [3] is also profile.md. After renumbering, cadence=1 and profile=2,
    # and the two profile markers collapse to the same number so text matches the chips.
    reply, cites = finalize_citations(
        "Cadence is a chatbot [2]. Samuel builds them [1], as a former PM [3].", HITS
    )
    assert reply == "Cadence is a chatbot [1]. Samuel builds them [2], as a former PM [2]."
    assert _paths_titles(cites) == [
        {"source_path": "projects/cadence.md", "title": "Cadence"},
        {"source_path": "profile.md", "title": "Profile"},
    ]


def test_finalize_includes_a_snippet_of_the_cited_text():
    """Each citation carries a preview of its source, for the marker popover."""
    _, cites = finalize_citations("Cadence is a chatbot [2].", HITS)
    assert cites[0]["snippet"] == "Cadence is a support chatbot."


def test_finalize_drops_out_of_range_markers():
    """A marker with no matching chunk must not become a fabricated citation."""
    reply, cites = finalize_citations("According to the docs [99], something is true.", HITS)
    assert cites == []
    assert "[99]" not in reply


def test_finalize_leaves_plain_text_unchanged():
    reply, cites = finalize_citations("A plain answer with no citations.", HITS)
    assert reply == "A plain answer with no citations."
    assert cites == []


def test_refusal_message_is_honest():
    assert "don't have that" in REFUSAL and "confidently" in REFUSAL


# --- Plain-text enforcement --------------------------------------------------
def test_to_plain_text_strips_markdown_headings_and_bold():
    assert to_plain_text("## What's shipped\nHe deployed X.") == "What's shipped\nHe deployed X."
    assert to_plain_text("He is a **Full-Stack** engineer.") == "He is a Full-Stack engineer."


def test_to_plain_text_leaves_prose_and_citations_untouched():
    text = "Samuel led teams [1], then shipped products [2]."
    assert to_plain_text(text) == text
