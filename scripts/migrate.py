"""Apply ordered SQL migrations exactly once, in a transaction with a DB lock."""
import os
from pathlib import Path

import psycopg


def apply(conn):
    conn.execute("SELECT pg_advisory_xact_lock(7220261121)")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT clock_timestamp())")
    for path in sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql")):
        if conn.execute("SELECT 1 FROM schema_migrations WHERE name = %s", (path.name,)).fetchone():
            continue
        conn.execute(path.read_text())
        conn.execute("INSERT INTO schema_migrations(name) VALUES (%s)", (path.name,))
        print(f"Applied {path.name}")


def main():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        apply(conn)


if __name__ == "__main__":
    main()
