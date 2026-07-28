"""
Retrieval for the RAG assistant: turn a visitor's question into the most relevant
corpus chunks, each carrying the source it came from so the answer can cite it.

Two layers, split on purpose:
  - search(vector, k)   — pure database work: cosine-nearest chunks for a given vector.
                          Testable without any embedding key (see test_retrieve.py).
  - retrieve(query, k)  — embeds the question, then calls search(). Needs the embedding key.

The split matters: it lets the SQL, the pgvector operator, and the join to `documents`
be verified against the real database before an embedding provider is ever wired up.
"""

import atexit
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from pgvector import Vector                     # wraps a list so it adapts as VECTOR, not float[]
from pgvector.psycopg import register_vector

from ingest import embed  # one embedding implementation, shared with ingestion

load_dotenv(Path(__file__).with_name(".env"))

# How many chunks to retrieve for a question. Small corpus, short answers — a handful is plenty.
RETRIEVAL_K = 5

# Below this cosine similarity, the top hit is treated as "not in the docs" and the
# assistant refuses rather than answering from weakly-related text. This is a starting
# value; Module 2's evals will calibrate it against real should-answer/should-refuse cases.
MIN_SIMILARITY = 0.35


# --- Connection pool ---------------------------------------------------------
# Reuse database connections across requests instead of reconnecting every time. The Module 3
# trace showed the per-request Neon connection — not the query — dominates retrieval latency
# (~1.4s warm), so closely-spaced requests (the messages of one chat conversation) should share
# a warm connection and skip that. Serverless-safe: `check` validates each connection on
# checkout, so a connection Neon dropped while idle is replaced rather than handed out dead —
# reliability is preserved, which is why this is safe on the live path.
_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    """Lazily create the shared connection pool — not at import, so tests (and any code path)
    that never touch the database never open a connection."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                from psycopg_pool import ConnectionPool
                pool = ConnectionPool(
                    conninfo=os.environ["DATABASE_URL"],
                    min_size=0, max_size=4,                  # hold nothing when idle; a few under load
                    max_idle=60,                             # recycle idle conns (Neon scales to zero)
                    configure=register_vector,               # teach each connection the VECTOR type once
                    check=ConnectionPool.check_connection,   # validate on checkout; replace dead ones
                    timeout=15,
                    open=True,
                )
                atexit.register(pool.close)                  # stop the pool's worker cleanly on exit
                _pool = pool
    return _pool


def search(query_vector, k: int = RETRIEVAL_K) -> list[dict]:
    """Return the k chunks most cosine-similar to query_vector, best first.

    Each result carries its source (path + title + chunk index) so the caller can cite
    it, and the similarity score so the caller can decide whether it is strong enough.
    """
    sql = """
        SELECT c.content, c.chunk_index, d.source_path, d.title,
               1 - (c.embedding <=> %(q)s) AS similarity
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        ORDER BY c.embedding <=> %(q)s          -- raw operator keeps the HNSW index usable
        LIMIT %(k)s
    """
    with _get_pool().connection() as conn:   # pooled + validated on checkout; VECTOR type pre-registered
        with conn.cursor() as cur:
            # Vector(...) so the value adapts as a vector; a bare list goes as float[].
            cur.execute(sql, {"q": Vector(query_vector), "k": k})
            rows = cur.fetchall()

    return [
        {
            "content": content,
            "chunk_index": chunk_index,
            "source_path": source_path,
            "title": title,
            "similarity": float(similarity),
        }
        for (content, chunk_index, source_path, title, similarity) in rows
    ]


def conversation_query(messages: list[dict], max_user_turns: int = 2, max_chars: int = 500) -> str:
    """Build the retrieval query from the recent conversation, not just the last line.

    A follow-up like "what's it built with?" retrieves almost nothing on its own — the
    topic lives in the previous turn ("tell me about Cadence"). Joining the last couple of
    user turns restores that context. It's a lightweight alternative to an LLM query-rewrite
    (which would add a call); the trade-off is mild topic bleed when the user hard-switches
    subjects, which Module 2's evals can measure. Kept to user turns so the model's own
    words don't dominate the query.
    """
    user_turns = [m["content"] for m in messages if m.get("role") == "user" and m.get("content")]
    if not user_turns:
        return ""
    query = " ".join(user_turns[-max_user_turns:])
    return query[-max_chars:] if len(query) > max_chars else query   # keep the current turn intact


def embed_query(text: str) -> list[float]:
    """Embed a single question. For OpenAI, query and document embeddings are symmetric;
    a Voyage switch would pass input_type='query' here instead of 'document'."""
    return embed([text])[0]


def retrieve(query: str, k: int = RETRIEVAL_K) -> list[dict]:
    """Embed the question and return its k nearest corpus chunks (needs the embedding key)."""
    return search(embed_query(query), k)


def retrieve_timed(query: str, k: int = RETRIEVAL_K) -> tuple[list[dict], float, float]:
    """Like retrieve(), but split the timing into (hits, embed_ms, db_ms) so a trace can show
    whether embedding the query or the vector search dominates retrieval latency — the two
    halves have very different causes (an OpenAI round-trip vs. a Neon/pgvector query)."""
    t0 = time.perf_counter()
    vector = embed_query(query)
    t1 = time.perf_counter()
    hits = search(vector, k)
    t2 = time.perf_counter()
    return hits, (t1 - t0) * 1000, (t2 - t1) * 1000


def is_grounded(results: list[dict], threshold: float = MIN_SIMILARITY) -> bool:
    """True when the best hit clears the threshold — i.e. the corpus actually covers this."""
    return bool(results) and results[0]["similarity"] >= threshold


if __name__ == "__main__":
    # Manual smoke test once the corpus is ingested:  python retrieve.py "your question"
    import sys

    question = " ".join(sys.argv[1:]) or "Has Samuel built RAG systems?"
    hits = retrieve(question)
    print(f"Q: {question}")
    print(f"grounded: {is_grounded(hits)}")
    for h in hits:
        print(f"  [{h['similarity']:.3f}] {h['source_path']}#chunk{h['chunk_index']}: {h['content'][:80]}...")
