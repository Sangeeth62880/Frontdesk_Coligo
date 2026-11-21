"""Real PostgreSQL checks, isolated in a rolled-back temporary schema.

Run with TEST_DATABASE_URL set to a local PostgreSQL database with CREATE rights.
"""
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL verification")
    import psycopg
    from psycopg import sql
    with psycopg.connect(url) as conn:
        try:
            schema = "test_" + uuid4().hex
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
            root = Path(__file__).resolve().parents[1]
            for migration in sorted((root / "migrations").glob("*.sql")):
                conn.execute(migration.read_text())
            yield conn
        finally:
            conn.rollback()


def test_seed_configuration(db):
    assert db.execute("SELECT count(*) FROM agents").fetchone()[0] == 9
    assert db.execute("SELECT count(*) FROM sla_policies").fetchone()[0] == 3
    assert db.execute("SELECT name FROM holidays WHERE day = '2026-04-15'").fetchone()[0] == "Vishu"


def create_event(db):
    ticket = db.execute("INSERT INTO tickets(subject, customer_email, priority, start_at) VALUES ('Test', 'test@example.com', 'urgent', now()) RETURNING id").fetchone()[0]
    return db.execute("INSERT INTO events(ticket_id, actor, event_type, created_at) VALUES (%s, 'system', 'created', '2000-01-01') RETURNING id, created_at", (ticket,)).fetchone()


@pytest.mark.parametrize("statement", [
    "UPDATE events SET actor = 'customer' WHERE id = %s",
    "DELETE FROM events WHERE id = %s",
    "TRUNCATE events",
])
def test_events_reject_mutations(db, statement):
    import psycopg
    event_id, _ = create_event(db)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        with db.transaction():
            db.execute(statement, (event_id,) if "%s" in statement else None)
    assert db.execute("SELECT actor FROM events WHERE id = %s", (event_id,)).fetchone()[0] == "system"


def test_event_timestamp_is_server_generated(db):
    before = datetime.now(timezone.utc)
    _, stamped = create_event(db)
    assert stamped >= before
    assert stamped <= datetime.now(timezone.utc)


def test_holidays_extended_to_2027(db):
    rows = dict(db.execute("SELECT day::text, name FROM holidays"))
    assert "company holiday" in rows["2027-01-01"]
    assert rows["2027-01-26"] == "Republic Day"
    assert rows["2027-12-25"] == "Christmas"
    assert db.execute("SELECT count(*) FROM holidays WHERE day BETWEEN '2026-01-01' AND '2026-12-31'").fetchone()[0] == 22
