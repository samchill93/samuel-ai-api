"""
Apply schema.sql to the database pointed to by DATABASE_URL.

Run it with:  python apply_schema.py

It is idempotent (everything uses IF NOT EXISTS), so re-running is safe.
The connection string is read from the environment (.env locally) and never printed.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
import psycopg

# Load .env sitting next to this file, so the script works from any working directory.
load_dotenv(Path(__file__).with_name(".env"))


def _statements(sql: str):
    """Yield individual SQL statements, skipping blank/comment-only fragments.

    psycopg sends one command per execute(), so we split the file on ';'.
    Our schema has no semicolons inside statements, so a simple split is safe.
    """
    for fragment in sql.split(";"):
        has_sql = any(
            line.strip() and not line.strip().startswith("--")
            for line in fragment.splitlines()
        )
        if has_sql:
            yield fragment.strip()


def main() -> None:
    url = os.environ["DATABASE_URL"]
    sql = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")

    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            for statement in _statements(sql):
                cur.execute(statement)
            conn.commit()

            # Print a short summary so we can see it worked.
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            has_vector = cur.fetchone() is not None
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
            tables = [row[0] for row in cur.fetchall()]
            cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'chunks'")
            indexes = [row[0] for row in cur.fetchall()]

    print("Schema applied.")
    print("  vector extension enabled:", has_vector)
    print("  tables:", ", ".join(tables) or "(none)")
    print("  chunks indexes:", ", ".join(indexes) or "(none)")


if __name__ == "__main__":
    main()
