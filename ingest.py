"""
Ingest the /corpus markdown files into the vector store.

Per file:  read -> chunk (fixed size, with overlap) -> embed each chunk -> upsert into Postgres.

Run it with:  python ingest.py

Needs DATABASE_URL and an embedding API key in the environment (.env). It is idempotent:
re-running re-embeds each document and replaces its chunks, so editing the corpus and
re-running is the normal update loop.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
import psycopg
from pgvector import Vector                     # wraps a list so it adapts as VECTOR, not float[]
from pgvector.psycopg import register_vector

load_dotenv(Path(__file__).with_name(".env"))

CORPUS_DIR = Path(__file__).with_name("corpus")


# --- Chunking -------------------------------------------------------------
# Fixed-size character windows with overlap. Simple and defensible (see ADR); the overlap
# keeps a sentence that straddles a cut from being lost to both chunks.
CHUNK_SIZE = 1000       # characters
CHUNK_OVERLAP = 150     # characters shared between neighbouring chunks


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Prefer to cut at a newline or space near the target, for cleaner chunks.
            window_start = max(start + size - overlap, start)
            brk = max(text.rfind("\n", window_start, end), text.rfind(" ", window_start, end))
            if brk > start:
                end = brk
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


# --- Embedding (provider-swappable) --------------------------------------
# Choose the provider with EMBED_PROVIDER in .env: "openai" (default) or "voyage".
# NOTE: the schema column is VECTOR(1536). text-embedding-3-small is 1536 dims. If you switch
# to a Voyage model with a different dimensionality, update schema.sql to match.
EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "openai")


def embed(texts: list[str]) -> list[list[float]]:
    if EMBED_PROVIDER == "openai":
        from openai import OpenAI

        client = OpenAI()  # reads OPENAI_API_KEY from the environment
        model = os.getenv("EMBED_MODEL", "text-embedding-3-small")
        resp = client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in resp.data]
    if EMBED_PROVIDER == "voyage":
        import voyageai

        client = voyageai.Client()  # reads VOYAGE_API_KEY from the environment
        model = os.getenv("EMBED_MODEL", "voyage-3")
        return client.embed(texts, model=model, input_type="document").embeddings
    raise ValueError(f"Unknown EMBED_PROVIDER: {EMBED_PROVIDER!r} (use 'openai' or 'voyage')")


# --- Ingestion ------------------------------------------------------------
def title_from(path: Path, text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def upsert_document(cur, source_path: str, title: str, content: str,
                    chunks: list[str], embeddings: list[list[float]]) -> None:
    cur.execute(
        """
        INSERT INTO documents (source_path, title, content, updated_at)
        VALUES (%s, %s, %s, now())
        ON CONFLICT (source_path)
        DO UPDATE SET title = EXCLUDED.title, content = EXCLUDED.content, updated_at = now()
        RETURNING id
        """,
        (source_path, title, content),
    )
    document_id = cur.fetchone()[0]
    # Replace the document's chunks wholesale so re-ingesting is a clean update.
    cur.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
    for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        cur.execute(
            """
            INSERT INTO chunks (document_id, chunk_index, content, token_count, embedding)
            VALUES (%s, %s, %s, %s, %s)
            """,
            # Vector(...) so the embedding adapts as a vector; a bare list goes as float[].
            (document_id, index, chunk, len(chunk.split()), Vector(embedding)),  # token_count ~ word count
        )


def main() -> None:
    files = sorted(p for p in CORPUS_DIR.rglob("*.md") if p.name != "README.md")
    if not files:
        print("No corpus files found in", CORPUS_DIR)
        return

    total_chunks = 0
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        register_vector(conn)  # lets us pass Python lists straight into VECTOR columns
        with conn.cursor() as cur:
            for path in files:
                text = path.read_text(encoding="utf-8")
                relative = path.relative_to(CORPUS_DIR).as_posix()
                chunks = chunk_text(text)
                if not chunks:
                    continue
                embeddings = embed(chunks)
                upsert_document(cur, relative, title_from(path, text), text, chunks, embeddings)
                total_chunks += len(chunks)
                print(f"  {relative}: {len(chunks)} chunks")
        conn.commit()

    print(f"Ingested {len(files)} documents, {total_chunks} chunks.")


if __name__ == "__main__":
    main()
