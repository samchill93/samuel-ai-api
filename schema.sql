-- Schema for the RAG corpus store (PostgreSQL + pgvector, hosted on Neon).
-- Apply it with:  python apply_schema.py
-- It is idempotent — safe to run repeatedly.

-- pgvector adds a VECTOR type and similarity operators to Postgres.
CREATE EXTENSION IF NOT EXISTS vector;

-- One row per source document in /corpus.
CREATE TABLE IF NOT EXISTS documents (
    id          BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_path TEXT        NOT NULL UNIQUE,   -- e.g. 'profile.md', 'projects/cadence.md'
    title       TEXT,
    content     TEXT        NOT NULL,          -- the full original markdown
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per chunk. Each chunk stores its own embedding and a pointer back to its
-- document — that back-pointer is what makes chunk-level source citations possible.
CREATE TABLE IF NOT EXISTS chunks (
    id           BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id  BIGINT       NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  INT          NOT NULL,        -- order of this chunk within its document
    content      TEXT         NOT NULL,        -- the chunk text the bot may quote
    token_count  INT,
    embedding    VECTOR(1536) NOT NULL,        -- OpenAI text-embedding-3-small = 1536 dims
    UNIQUE (document_id, chunk_index)
);

-- Approximate-nearest-neighbour index for fast cosine-similarity search.
-- HNSW builds incrementally (no training data needed) and is the modern default.
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);

-- Inquiries submitted through the site's contact form (POST /inquiry).
CREATE TABLE IF NOT EXISTS inquiries (
    id               BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name             TEXT        NOT NULL,
    email            TEXT        NOT NULL,
    company          TEXT,
    package_interest TEXT,
    message          TEXT        NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
