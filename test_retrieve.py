"""
Unit tests for the retrieval and chunking logic that need neither an embedding key nor
a database — the pure decisions that govern grounding and chunk quality.

The database path (search()) and the embedding path (retrieve()) are exercised
separately once the corpus is ingested; here we pin the logic that decides whether an
answer is grounded and how documents are split.
"""

from ingest import chunk_text, CHUNK_SIZE, CHUNK_OVERLAP
from retrieve import is_grounded, MIN_SIMILARITY


# --- Grounding / refusal decision -------------------------------------------
def test_no_results_is_not_grounded():
    """Nothing retrieved must mean refusal, never a confident answer from thin air."""
    assert is_grounded([]) is False


def test_strong_top_hit_is_grounded():
    hits = [{"similarity": MIN_SIMILARITY + 0.2}, {"similarity": 0.1}]
    assert is_grounded(hits) is True


def test_weak_top_hit_is_not_grounded():
    """A top hit below threshold is 'not in the docs' — the anti-hallucination guard."""
    hits = [{"similarity": MIN_SIMILARITY - 0.05}]
    assert is_grounded(hits) is False


def test_threshold_is_inclusive():
    hits = [{"similarity": MIN_SIMILARITY}]
    assert is_grounded(hits) is True


# --- Chunking ----------------------------------------------------------------
def test_short_text_is_one_chunk():
    assert chunk_text("A short profile line.") == ["A short profile line."]


def test_empty_text_yields_no_chunks():
    assert chunk_text("   ") == []


def test_long_text_splits_and_respects_size():
    text = "word " * 800  # ~4000 chars, comfortably over CHUNK_SIZE
    chunks = chunk_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= CHUNK_SIZE for c in chunks)


def test_consecutive_chunks_overlap():
    """Overlap is what stops a sentence on a chunk boundary from being lost to both sides."""
    text = "".join(f"sentence number {i} here. " for i in range(300))
    chunks = chunk_text(text)
    assert len(chunks) >= 2
    # the end of one chunk should reappear at the start of the next
    tail = chunks[0][-CHUNK_OVERLAP:]
    assert any(word in chunks[1] for word in tail.split())
