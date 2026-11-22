"""Real PostgreSQL checks, isolated in a rolled-back temporary schema.

Run with TEST_DATABASE_URL set to a local PostgreSQL database with CREATE rights.
"""
import os
from datetime import UTC, datetime
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
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"), db.transaction():
        db.execute(statement, (event_id,) if "%s" in statement else None)
    assert db.execute("SELECT actor FROM events WHERE id = %s", (event_id,)).fetchone()[0] == "system"


def test_event_timestamp_is_server_generated(db):
    before = datetime.now(UTC)
    _, stamped = create_event(db)
    assert stamped >= before
    assert stamped <= datetime.now(UTC)


def test_holidays_extended_to_2027(db):
    rows = dict(db.execute("SELECT day::text, name FROM holidays"))
    assert "company holiday" in rows["2027-01-01"]
    assert rows["2027-01-26"] == "Republic Day"
    assert rows["2027-12-25"] == "Christmas"
    assert db.execute("SELECT count(*) FROM holidays WHERE day BETWEEN '2026-01-01' AND '2026-12-31'").fetchone()[0] == 22


def test_upgrade_preserves_creation_source_and_recorded_breach(db):
    # Exercise migration 006 on genuinely pre-hardening records.
    from psycopg import sql
    schema='upgrade_'+uuid4().hex
    db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    db.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
    migrations=Path(__file__).resolve().parents[1]/'migrations'
    for path in sorted(migrations.glob('*.sql')):
        if path.name>='006':continue
        db.execute(path.read_text())
    ids=[]
    for actor in ['agent:1','customer']:
        tid=db.execute("INSERT INTO tickets(subject,customer_email,priority,start_at) VALUES ('Legacy','a@example.com','urgent','2026-11-20 10:00+05:30') RETURNING id").fetchone()[0]
        db.execute("INSERT INTO events(ticket_id,actor,event_type) VALUES (%s,%s,'created')",(tid,actor))
        db.execute("INSERT INTO resolution_cycles(ticket_id,cycle_number,opened_at,start_at,ended_at,resolution_due_at,breached) VALUES (%s,1,'2026-11-20 10:00+05:30','2026-11-20 10:00+05:30','2026-11-23 10:00+05:30','2026-11-20 18:30+05:30',true)",(tid,))
        ids.append(tid)
    db.execute((migrations/'006_hardening.sql').read_text())
    assert db.execute('SELECT first_reply_required,first_reply_due_at,resolution_breached FROM tickets ORDER BY id').fetchall()==[(False,None,True),(True,None,True)]
    assert db.execute('SELECT count(*) FROM events').fetchone()[0]==2
